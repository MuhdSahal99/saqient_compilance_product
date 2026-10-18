"""Withholding tax check over a payments dataset (engine 1.3.0).

For each payment to a payee outside the pack's resident country, the expected
withholding is gross × rate, where the rate is the pack's rate for the payment
type, or a lower treaty rate when the row carries a residency certificate
reference. Withholding short of the expected amount by more than the pack's
tolerance becomes a finding with the rows, rate and expected amount; so do
unknown payment types, missing payee residence and treaty rates claimed without
a certificate. A finding is a proposal for a reviewer, not a tax assessment.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

import polars as pl

from app.engine.data_checks import (
    DataContext,
    DataEvaluation,
    RuleKey,
    _need,
    _need_column,
    _rows_evidence,
)
from app.engine.einvoice_checks import _M, _evaluation, _Groups, _rule, _typed_rule
from app.models import DatasetKind

ZERO = Decimal(0)
_COLS = [
    "payment_id",
    "payee_name",
    "payee_country",
    "payment_type",
    "gross_amount",
    "wht_amount",
    "treaty_rate",
    "_rate",
    "_expected",
    "_shortfall",
]


def _d(v: Any) -> Decimal:
    return ZERO if v is None else Decimal(str(v))


class WhtRateCheck(_M):
    type: Literal["wht_rates"]
    rates_rule: RuleKey
    resident_country_rule: RuleKey
    tolerance_rule: RuleKey

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.WHT_PAYMENTS}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, DatasetKind.WHT_PAYMENTS)
        for c in ("payment_type", "gross_amount"):
            _need_column(ds, c)
        rates: dict[str, Decimal] = _typed_rule(ctx, self.rates_rule, meta)
        resident = str(_rule(ctx, self.resident_country_rule, meta)).strip().upper()
        tolerance = Decimal(str(_rule(ctx, self.tolerance_rule, meta)))
        df = ds.frame
        if ctx.period:
            df = df.filter(pl.col("payment_date").is_between(ctx.period[0], ctx.period[1]))
        g = _Groups()
        rows: dict[str, list[dict[str, Any]]] = {}
        checked = 0
        for r in df.sort("row_id").to_dicts():
            country = str(r.get("payee_country") or "").strip().upper()
            ptype = str(r.get("payment_type") or "").strip().casefold()
            if not country:
                rows.setdefault("missing_residency", []).append(r)
                continue
            if country == resident:
                continue
            checked += 1
            if ptype not in rates:
                rows.setdefault(f"unknown_type:{ptype}", []).append(r)
                continue
            rate = rates[ptype]
            treaty = r.get("treaty_rate")
            cert = str(r.get("treaty_certificate") or "").strip()
            if treaty is not None and _d(treaty) < rate:
                if cert:
                    rate = _d(treaty)
                else:
                    rows.setdefault("treaty_without_certificate", []).append(
                        {**r, "_rate": str(rate)}
                    )
            gross, withheld = _d(r.get("gross_amount")), _d(r.get("wht_amount"))
            expected = gross * rate
            shortfall = expected - withheld
            if shortfall > tolerance:
                rows.setdefault(f"under_withheld:{ptype}", []).append(
                    {
                        **r,
                        "_rate": str(rate),
                        "_expected": str(expected),
                        "_shortfall": str(shortfall),
                    }
                )
        titles = {
            "missing_residency": "Payments without the payee's country",
            "treaty_without_certificate": "Treaty rate used without a residency certificate",
        }
        for key in sorted(rows):
            found = rows[key]
            kind, _, ptype = key.partition(":")
            if kind == "under_withheld":
                title = f"Withholding below the pack rate for '{ptype}'"
                total = sum((_d(x["_shortfall"]) for x in found), ZERO)
                label = f"{len(found)} payment(s), shortfall {total}"
            elif kind == "unknown_type":
                title = f"Payment type '{ptype}' has no rate in the rule pack"
                label = f"{len(found)} payment(s)"
            else:
                title = titles[kind]
                label = f"{len(found)} payment(s)"
            frame = pl.DataFrame(
                [
                    {c: (str(x.get(c)) if x.get(c) is not None else None) for c in _COLS}
                    | {"row_id": x["row_id"]}
                    for x in found
                ]
            )
            g.add(
                key,
                title,
                _rows_evidence(
                    ds,
                    frame,
                    _COLS,
                    label,
                    {"formula": "expected = gross × rate; shortfall = expected − withheld"},
                ),
            )
            g.counts[key] = len(found)
        meta["resident_country"] = resident
        meta["tolerance"] = str(tolerance)
        meta["checked"] = checked
        return _evaluation(g, checked, meta, "non-resident payment(s)")


WHT_CHECK_TYPES = (WhtRateCheck,)
