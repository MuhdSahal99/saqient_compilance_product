"""Depreciation recalculation over a fixed asset register (engine 1.6.0).

For each asset the check recomputes accumulated depreciation at the period end and the
charge for the period, then compares them with the recorded amounts. Conventions,
stated so a reviewer can reproduce every figure:

- Months in use count the acquisition month as a full month and stop at the
  disposal month (if any) and at the useful life.
- ``straight_line``: (cost − residual) ÷ useful life months × months in use.
- ``reducing_balance``: the annual ``rate`` applies to the opening carrying amount of
  each full year; a part year applies rate × months ÷ 12. Never below residual.
- The charge is accumulated at the period end minus accumulated at the month before
  the period start.

Differences above the pack's tolerance (``<prefix>.dep_tolerance``) are findings.
Rounding follows ``<prefix>.amount_decimals`` and ``<prefix>.rounding_mode``. A
difference is a lead for the reviewer: the entity's policy may differ.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any, Literal

import polars as pl

from app.engine.data_checks import (
    DataCheckError,
    DataContext,
    DataEvaluation,
    RuleKey,
    _need,
    _rows_evidence,
)
from app.engine.einvoice_checks import _M, _evaluation, _Groups, _rule
from app.models import DatasetKind

ZERO = Decimal(0)
COLS = [
    "asset_id",
    "description",
    "method",
    "cost",
    "residual_value",
    "useful_life_months",
    "rate",
    "acquisition_date",
    "recorded_accumulated",
    "recorded_charge",
    "_expected",
    "_difference",
]


def _d(v: Any) -> Decimal:
    return ZERO if v is None else Decimal(str(v))


def months_in_use(start: date, end: date, disposal: date | None, life: int | None) -> int:
    """Whole months from the acquisition month to ``end`` (inclusive), capped."""
    if disposal is not None and disposal < end:
        end = disposal
    m = (end.year - start.year) * 12 + end.month - start.month + 1
    m = max(m, 0)
    return min(m, life) if life is not None else m


def accumulated(
    method: str,
    cost: Decimal,
    residual: Decimal,
    life: int | None,
    rate: Decimal | None,
    months: int,
) -> Decimal:
    base = cost - residual
    if months <= 0 or base <= 0:
        return ZERO
    if method == "straight_line":
        if not life:
            raise ValueError("missing_life")
        return min(base / life * months, base)
    if method == "reducing_balance":
        if rate is None or rate <= 0 or rate >= 1:
            raise ValueError("missing_rate")
        nbv = cost
        years, part = divmod(months, 12)
        for _ in range(years):
            nbv -= nbv * rate
        nbv -= nbv * rate * part / 12
        return min(cost - max(nbv, residual), base)
    raise ValueError("unknown_method")


def _month_before(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


class DepreciationCheck(_M):
    type: Literal["depreciation_recalc"]
    rules_prefix: RuleKey

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.FIXED_ASSETS}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, DatasetKind.FIXED_ASSETS)
        p = self.rules_prefix
        tolerance = Decimal(str(_rule(ctx, f"{p}.dep_tolerance", meta)))
        decimals = int(_rule(ctx, f"{p}.amount_decimals", meta))
        mode = str(_rule(ctx, f"{p}.rounding_mode", meta)).lower()
        if mode not in ("half_up", "half_even"):
            raise DataCheckError(f"Rule '{p}.rounding_mode' must be half_up or half_even.")
        q = Decimal(1).scaleb(-decimals)
        rnd = ROUND_HALF_UP if mode == "half_up" else ROUND_HALF_EVEN
        period = ctx.period or (
            (ds.period_start, ds.period_end) if ds.period_start and ds.period_end else None
        )
        if period is None:
            raise DataCheckError("Give the register or the review a period to recalculate for.")
        start, end = period
        meta.update(
            period=[start.isoformat(), end.isoformat()], tolerance=str(tolerance), convention="v1"
        )
        found: dict[str, list[dict[str, Any]]] = {}
        rows = ds.frame.sort("row_id").to_dicts()
        for r in rows:
            method = str(r.get("method") or "straight_line").strip().casefold().replace(" ", "_")
            try:
                life_raw = str(r.get("useful_life_months") or "").strip()
                life = int(life_raw) if life_raw else None
                cost, residual = _d(r.get("cost")), _d(r.get("residual_value"))
                rate = _d(r["rate"]) if r.get("rate") is not None else None
                acq: date = r["acquisition_date"]
                disposal = r.get("disposal_date")
                at_end = accumulated(
                    method, cost, residual, life, rate, months_in_use(acq, end, disposal, life)
                )
                at_open = accumulated(
                    method,
                    cost,
                    residual,
                    life,
                    rate,
                    months_in_use(acq, _month_before(start), disposal, life) if acq < start else 0,
                )
            except ValueError as exc:
                key = (
                    str(exc)
                    if str(exc) in ("missing_life", "missing_rate", "unknown_method")
                    else "unreadable"
                )
                found.setdefault(key, []).append(r)
                continue
            exp_acc = at_end.quantize(q, rounding=rnd)
            exp_charge = (at_end - at_open).quantize(q, rounding=rnd)
            for field, expected, key in (
                ("recorded_accumulated", exp_acc, "accumulated_difference"),
                ("recorded_charge", exp_charge, "charge_difference"),
            ):
                if r.get(field) is None:
                    continue
                diff = (_d(r[field]) - expected).quantize(q, rounding=rnd)
                if abs(diff) > tolerance:
                    found.setdefault(key, []).append(
                        {**r, "_expected": expected, "_difference": diff}
                    )
        titles = {
            "accumulated_difference": "Accumulated depreciation differs from the recalculation",
            "charge_difference": "Depreciation charge differs from the recalculation",
            "missing_life": "Straight-line assets without a useful life",
            "missing_rate": "Reducing-balance assets without a usable rate",
            "unknown_method": "Assets with a method the check does not recognise",
            "unreadable": "Assets whose useful life could not be read",
        }
        g = _Groups()
        for key in sorted(found):
            items = found[key]
            frame = pl.DataFrame(
                [
                    {c: (str(x.get(c)) if x.get(c) is not None else None) for c in COLS}
                    | {"row_id": x["row_id"]}
                    for x in items
                ],
                schema={**dict.fromkeys(COLS, pl.String), "row_id": pl.Int64},
            )
            g.add(
                key,
                titles[key],
                _rows_evidence(
                    ds, frame, COLS, f"{len(items)} asset(s)", {"convention": "see check notes"}
                ),
            )
            g.counts[key] = len(items)
        return _evaluation(g, len(rows), meta, "asset(s)")


FA_CHECK_TYPES = (DepreciationCheck,)
