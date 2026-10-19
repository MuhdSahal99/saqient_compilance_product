"""Journal entry tests over the general ledger (engine 1.4.0).

One configurable check, ``journal_entry_test``, runs one test per requirement:

- ``weekend``       postings on the pack's weekend days (ISO weekday numbers)
- ``holiday``       postings on the pack's holiday dates
- ``round_amount``  line amounts that are exact multiples of the pack's multiple
- ``unusual_user``  posters with fewer distinct entries than the pack's minimum,
                    and lines with no poster
- ``below_limit``   entries whose debit total sits just below the approval limit
                    (within the pack's share of it)
- ``post_close``    entries posted after the close date (the check's ``close_date``,
                    else the review's period end, else the ledger's period end)
                    whose document date, when given, is on or before it
- ``benford``       first-digit distribution of line amounts of 10 or more; the
                    mean absolute deviation (MAD) is compared with the pack's bands

Every parameter is a pack rule under ``rules_prefix``. A flagged entry is a lead for
the engagement team to follow up, not evidence of error or fraud.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import polars as pl

from app.engine.data_checks import (
    DataCheckError,
    DataContext,
    DataEvaluation,
    LoadedDataset,
    RuleKey,
    _need,
    _need_column,
    _rows_evidence,
)
from app.engine.einvoice_checks import _M, _evaluation, _Groups, _rule, _typed_rule
from app.models import CheckOutcome, DatasetKind

ZERO = Decimal(0)
COLS = [
    "entry_id",
    "posting_date",
    "account_code",
    "description",
    "debit",
    "credit",
    "amount",
    "posted_by",
    "document_date",
    "_value",
]
BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
JeTest = Literal[
    "weekend", "holiday", "round_amount", "unusual_user", "below_limit", "post_close", "benford"
]


def _d(v: Any) -> Decimal:
    return ZERO if v is None else Decimal(str(v))


def line_value(r: dict[str, Any]) -> Decimal:
    """Absolute line amount: |amount| if given, else |debit − credit|."""
    if r.get("amount") is not None:
        return abs(_d(r["amount"]))
    return abs(_d(r.get("debit")) - _d(r.get("credit")))


def entry_debits(rows: list[dict[str, Any]]) -> dict[str, Decimal]:
    """Debit total per entry: the debit column, else the positive signed amounts."""
    out: dict[str, Decimal] = {}
    for r in rows:
        eid = str(r["entry_id"])
        if r.get("debit") is not None or r.get("credit") is not None:
            v = _d(r.get("debit"))
        else:
            v = max(_d(r.get("amount")), ZERO)
        out[eid] = out.get(eid, ZERO) + v
    return out


def first_digit(v: Decimal) -> int | None:
    if v < 10:
        return None
    return int(str(int(v))[0])


def benford_mad(counts: dict[int, int]) -> tuple[float, dict[int, float]]:
    """MAD of observed first-digit shares against Benford's law, and observed shares."""
    n = sum(counts.values())
    shares = {d: (counts.get(d, 0) / n if n else 0.0) for d in range(1, 10)}
    return sum(abs(shares[d] - BENFORD[d]) for d in range(1, 10)) / 9, shares


def conformity(mad: float, bands: dict[str, Any]) -> str:
    for name in ("close", "acceptable", "marginal"):
        if Decimal(str(mad)) <= Decimal(str(bands[name])):
            return name
    return "nonconformity"


class JournalEntryCheck(_M):
    type: Literal["journal_entry_test"]
    test: JeTest
    rules_prefix: RuleKey
    close_date: date | None = None

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.GENERAL_LEDGER}

    def _r(self, ctx: DataContext, name: str, meta: dict[str, Any], typed: bool = False) -> Any:
        key = f"{self.rules_prefix}.{name}"
        return _typed_rule(ctx, key, meta) if typed else _rule(ctx, key, meta)

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, DatasetKind.GENERAL_LEDGER)
        meta["test"] = self.test
        if self.test == "post_close":
            return self._post_close(ds, ctx, meta)
        df = ds.frame
        if ctx.period:
            df = df.filter(pl.col("posting_date").is_between(ctx.period[0], ctx.period[1]))
        rows = df.sort("row_id").to_dicts()
        if self.test == "benford":
            return self._benford(ds, rows, ctx, meta)
        found: dict[str, tuple[str, list[dict[str, Any]]]] = {}
        if self.test == "weekend":
            days = set(self._r(ctx, "weekend_days", meta, typed=True))
            hit = [r for r in rows if r["posting_date"].isoweekday() in days]
            found["weekend"] = ("Postings on weekend days", hit)
            meta["weekend_days"] = sorted(days)
        elif self.test == "holiday":
            days = set(self._r(ctx, "holidays", meta, typed=True))
            hit = [r for r in rows if r["posting_date"] in days]
            found["holiday"] = ("Postings on holidays", hit)
        elif self.test == "round_amount":
            multiple = _d(self._r(ctx, "round_amount_multiple", meta))
            if multiple <= 0:
                raise DataCheckError("The round amount multiple must be above zero.")
            hit = [r for r in rows if line_value(r) > 0 and line_value(r) % multiple == 0]
            found["round_amount"] = (f"Line amounts in exact multiples of {multiple}", hit)
        elif self.test == "unusual_user":
            _need_column(ds, "posted_by")
            minimum = int(self._r(ctx, "min_user_entries", meta))
            entries: dict[str, set[str]] = {}
            for r in rows:
                user = str(r.get("posted_by") or "").strip()
                if user:
                    entries.setdefault(user, set()).add(str(r["entry_id"]))
            rare = {u for u, e in entries.items() if len(e) < minimum}
            found["unusual_user"] = (
                f"Entries by users with fewer than {minimum} entries",
                [r for r in rows if str(r.get("posted_by") or "").strip() in rare],
            )
            found["missing_user"] = (
                "Lines with no poster recorded",
                [r for r in rows if not str(r.get("posted_by") or "").strip()],
            )
            meta["rare_users"] = len(rare)
        elif self.test == "below_limit":
            limit = _d(self._r(ctx, "approval_limit", meta))
            share = _d(self._r(ctx, "below_limit_share", meta))
            floor = limit * (1 - share)
            totals = entry_debits(rows)
            near = {e for e, v in totals.items() if floor <= v < limit}
            hit = [
                {**r, "_value": str(totals[str(r["entry_id"])])}
                for r in rows
                if str(r["entry_id"]) in near
            ]
            found["below_limit"] = (f"Entries just below the approval limit of {limit}", hit)
            meta["band"] = [str(floor), str(limit)]
        return self._finish(ds, rows, found, meta)

    def _finish(
        self,
        ds: LoadedDataset,
        rows: list[dict[str, Any]],
        found: dict[str, tuple[str, list[dict[str, Any]]]],
        meta: dict[str, Any],
    ) -> DataEvaluation:
        g = _Groups()
        for key, (title, hit) in found.items():
            if not hit:
                continue
            n_entries = len({str(r["entry_id"]) for r in hit})
            g.add(
                key,
                title,
                _rows_evidence(ds, _frame(hit), COLS, f"{n_entries} entr(ies), {len(hit)} line(s)"),
            )
            g.counts[key] = n_entries
        meta["checked"] = len({str(r["entry_id"]) for r in rows})
        return _evaluation(g, meta["checked"], meta, "journal entries")

    def _post_close(
        self, ds: LoadedDataset, ctx: DataContext, meta: dict[str, Any]
    ) -> DataEvaluation:
        close = self.close_date or (ctx.period[1] if ctx.period else None) or ds.period_end
        if close is None:
            raise DataCheckError("Set a close date, a review period or the ledger's period end.")
        meta["close_date"] = close.isoformat()
        rows = ds.frame.sort("row_id").to_dicts()
        has_doc = "document_date" in ds.frame.columns

        def relates(r: dict[str, Any]) -> bool:
            doc = r.get("document_date") if has_doc else None
            return doc is None or doc <= close

        hit = [r for r in rows if r["posting_date"] > close and relates(r)]
        return self._finish(
            ds, rows, {"post_close": (f"Entries posted after the close date {close}", hit)}, meta
        )

    def _benford(
        self, ds: LoadedDataset, rows: list[dict[str, Any]], ctx: DataContext, meta: dict[str, Any]
    ) -> DataEvaluation:
        bands = self._r(ctx, "benford_mad_bands", meta, typed=True)
        minimum = int(self._r(ctx, "benford_min_population", meta))
        digits = {r["row_id"]: first_digit(line_value(r)) for r in rows}
        counts = Counter(d for d in digits.values() if d is not None)
        n = sum(counts.values())
        meta["population"] = n
        if n < minimum:
            return DataEvaluation(
                CheckOutcome.NOT_APPLICABLE,
                False,
                f"Benford analysis needs at least {minimum} amounts of 10 or more; found {n}.",
                [],
                meta,
            )
        mad, shares = benford_mad(dict(counts))
        level = conformity(mad, bands.model_dump() if hasattr(bands, "model_dump") else bands)
        table = {
            str(d): f"observed {shares[d]:.4f}, expected {BENFORD[d]:.4f}, count {counts.get(d, 0)}"
            for d in range(1, 10)
        }
        meta.update({"mad": f"{mad:.6f}", "conformity": level, "digits": table})
        if level in ("close", "acceptable"):
            return DataEvaluation(
                CheckOutcome.NO_EXCEPTIONS,
                False,
                f"First digits of {n} amounts conform to Benford's law ({level}, MAD {mad:.6f}).",
                [],
                meta,
            )
        worst = max(range(1, 10), key=lambda d: shares[d] - BENFORD[d])
        hit = [r for r in rows if digits[r["row_id"]] == worst]
        g = _Groups()
        ev = _rows_evidence(
            ds,
            _frame(hit),
            COLS,
            f"Digit {worst}: {counts[worst]} of {n} amounts "
            f"({shares[worst]:.4f} vs {BENFORD[worst]:.4f})",
            {
                "mad": f"{mad:.6f}",
                "conformity": level,
                **{f"digit_{k}": v for k, v in table.items()},
            },
        )
        g.add("benford", f"First-digit distribution: {level} (MAD {mad:.6f})", ev)
        g.counts["benford"] = len(hit)
        meta["checked"] = n
        return _evaluation(g, n, meta, "amounts")


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {c: (str(r.get(c)) if r.get(c) is not None else None) for c in COLS}
            | {"row_id": r["row_id"]}
            for r in rows
        ],
        schema={**{c: pl.String for c in COLS}, "row_id": pl.Int64},
    )


JE_CHECK_TYPES = (JournalEntryCheck,)
