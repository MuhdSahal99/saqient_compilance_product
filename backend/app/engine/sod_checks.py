"""Segregation of duties over an ERP user-role export (engine 1.5.0).

The conflict matrix is a pack rule (family ``sod_conflicts``): each conflict has an
id, two sets of role or permission codes (``a`` and ``b``) and a description. A
user who holds at least one code from each side, through any of their rows,
breaches that conflict. Codes are compared trimmed and case-insensitively against
the row's ``role`` and ``permission`` values. One finding per conflict id lists the
rows that grant each side. A breach is a lead for the control owner to review;
mitigating controls and approved exceptions are recorded by people, not here.
"""

from __future__ import annotations

from typing import Any, Literal

import polars as pl
from pydantic import Field

from app.engine.data_checks import (
    DataContext,
    DataEvaluation,
    RuleKey,
    _need,
    _need_column,
    _rows_evidence,
)
from app.engine.einvoice_checks import _M, _evaluation, _Groups, _typed_rule
from app.models import DatasetKind

COLS = ["user_id", "user_name", "role", "permission", "system", "status", "_side"]


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split()).casefold()


def user_codes(rows: list[dict[str, Any]]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Each user's normalised codes with the row that grants them."""
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for r in rows:
        uid = _norm(r.get("user_id"))
        if not uid:
            continue
        for col in ("role", "permission"):
            code = _norm(r.get(col))
            if code:
                out.setdefault(uid, []).append((code, r))
    return out


def breaches(
    codes: dict[str, list[tuple[str, dict[str, Any]]]], a: set[str], b: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """Users holding a code from both sides, with the granting rows marked by side."""
    out: dict[str, list[dict[str, Any]]] = {}
    for uid in sorted(codes):
        held = codes[uid]
        side_a = [r for c, r in held if c in a]
        side_b = [r for c, r in held if c in b]
        if not side_a or not side_b:
            continue
        seen: dict[int, dict[str, Any]] = {}
        for side, rows in (("a", side_a), ("b", side_b)):
            for r in rows:
                prev = seen.get(r["row_id"])
                seen[r["row_id"]] = {
                    **r,
                    "_side": "a+b" if prev and prev["_side"] != side else side,
                }
        out[uid] = [seen[k] for k in sorted(seen)]
    return out


class SodConflictCheck(_M):
    type: Literal["sod_conflict"]
    conflicts_rule: RuleKey
    exclude_statuses: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Rows whose status matches one of these (case-insensitive) are skipped.",
    )

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.USER_ROLES}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, DatasetKind.USER_ROLES)
        _need_column(ds, "user_id")
        matrix = _typed_rule(ctx, self.conflicts_rule, meta)
        skip = {_norm(s) for s in self.exclude_statuses}
        rows = [
            r
            for r in ds.frame.sort("row_id").to_dicts()
            if not (skip and _norm(r.get("status")) in skip)
        ]
        codes = user_codes(rows)
        g = _Groups()
        for conflict in matrix:
            a = {_norm(x) for x in conflict.a}
            b = {_norm(x) for x in conflict.b}
            hits = breaches(codes, a, b)
            if not hits:
                continue
            key = f"sod:{conflict.id}"
            found = [r for user_rows in hits.values() for r in user_rows]
            frame = pl.DataFrame(
                [
                    {c: (str(x.get(c)) if x.get(c) is not None else None) for c in COLS}
                    | {"row_id": x["row_id"]}
                    for x in found
                ]
            )
            g.add(
                key,
                f"Conflict {conflict.id}: {conflict.description}"[:300],
                _rows_evidence(
                    ds,
                    frame,
                    COLS,
                    f"{len(hits)} user(s)",
                    {"conflict": conflict.id, "users": ", ".join(sorted(hits))[:500]},
                ),
            )
            g.counts[key] = len(hits)
        meta["users"] = len(codes)
        meta["conflicts"] = len(matrix)
        meta["excluded_statuses"] = sorted(skip)
        return _evaluation(g, len(codes), meta, "user(s)")


SOD_CHECK_TYPES = (SodConflictCheck,)
