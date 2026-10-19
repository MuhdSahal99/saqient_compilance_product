"""Accounts payable and expense analytics (engine 1.5.0).

One configurable check, ``ap_analytics``, runs one test per requirement:

- ``duplicate_payment``  pairs of payments in the same currency to the same vendor
                         (same vendor id, or names at least the pack's similarity)
                         whose amounts differ by no more than the pack's tolerance and
                         that are within the pack's day window, or carry invoice
                         numbers at least the pack's similarity
- ``vendor_employee_bank`` vendor payments to a bank account (IBAN) that is also on
                         the employee master; IBANs are compared in memory and only
                         the last four characters appear in evidence
- ``missing_trn``        payments to vendors in the pack's countries with no TRN, at
                         or above the pack's minimum amount (or with no country)
- ``dormant_vendor``     a payment to a vendor whose previous payment is at least the
                         pack's dormancy days earlier
- ``three_way_match``    invoiced quantity above the received quantity (plus the pack's
                         tolerance), invoices with nothing received, and invoice unit
                         prices that differ from the PO price by more than the pack's
                         share
- ``expense_policy``     claims above the pack's per-category limit, claims above the
                         receipt threshold with no receipt reference, categories the
                         pack does not list, and claims in another currency than the
                         category's limit

Every parameter is a pack rule under ``rules_prefix``. A flag is a lead for review,
never a conclusion of error or fraud.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

import polars as pl
from rapidfuzz import fuzz

from app.crypto import mask
from app.engine.data_checks import (
    DataContext,
    DataEvaluation,
    LoadedDataset,
    RuleKey,
    _need,
    _need_column,
    _rows_evidence,
)
from app.engine.einvoice_checks import _M, _evaluation, _Groups, _rule, _typed_rule
from app.models import DatasetKind

ZERO = Decimal(0)
ApTest = Literal[
    "duplicate_payment",
    "vendor_employee_bank",
    "missing_trn",
    "dormant_vendor",
    "three_way_match",
    "expense_policy",
]
PAY_COLS = [
    "payment_id",
    "payment_date",
    "vendor_id",
    "vendor_name",
    "vendor_country",
    "invoice_number",
    "amount",
    "currency",
    "_iban",
    "_pair",
    "_gap_days",
]
EMP_COLS = ["employee_id", "employee_name", "_iban"]
TWM_COLS = [
    "po_number",
    "invoice_number",
    "vendor_name",
    "item",
    "po_quantity",
    "received_quantity",
    "invoiced_quantity",
    "po_unit_price",
    "invoice_unit_price",
    "_difference",
]
EXP_COLS = [
    "claim_id",
    "employee_id",
    "claim_date",
    "category",
    "amount",
    "currency",
    "receipt_ref",
    "_limit",
]


def _d(v: Any) -> Decimal:
    return ZERO if v is None else Decimal(str(v))


def _text(v: Any) -> str:
    return " ".join(str(v or "").split())


def norm_name(v: Any) -> str:
    """Casefolded letters and digits, single-spaced (no regular expressions)."""
    kept = "".join(ch if ch.isalnum() else " " for ch in str(v or "").casefold())
    return " ".join(kept.split())


def norm_iban(v: Any) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum())


def similarity(a: str, b: str) -> Decimal:
    """Token-sort similarity from 0 to 100, rounded to 2 places."""
    return Decimal(str(round(fuzz.token_sort_ratio(a, b), 2)))


def same_vendor(a: dict[str, Any], b: dict[str, Any], name_min: Decimal) -> bool:
    ida, idb = _text(a.get("vendor_id")), _text(b.get("vendor_id"))
    if ida and idb:
        return ida.casefold() == idb.casefold()
    return similarity(norm_name(a.get("vendor_name")), norm_name(b.get("vendor_name"))) >= name_min


def duplicate_pairs(
    rows: list[dict[str, Any]],
    tolerance: Decimal,
    window_days: int,
    name_min: Decimal,
    invoice_min: Decimal,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Candidate duplicate pairs; rows are compared only with others close in amount."""
    ordered = sorted(rows, key=lambda r: (_d(r.get("amount")), r["row_id"]))
    pairs = []
    for i, a in enumerate(ordered):
        amt = _d(a.get("amount"))
        for b in ordered[i + 1 :]:
            if _d(b.get("amount")) - amt > tolerance:
                break
            if _text(a.get("currency")) != _text(b.get("currency")):
                continue
            if not same_vendor(a, b, name_min):
                continue
            close = abs((a["payment_date"] - b["payment_date"]).days) <= window_days
            ia, ib = norm_name(a.get("invoice_number")), norm_name(b.get("invoice_number"))
            same_inv = bool(ia and ib) and similarity(ia, ib) >= invoice_min
            if close or same_inv:
                first, second = sorted((a, b), key=lambda r: r["row_id"])
                pairs.append((first, second))
    return sorted(pairs, key=lambda p: (p[0]["row_id"], p[1]["row_id"]))


def dormant_payments(
    rows: list[dict[str, Any]], days: int
) -> list[tuple[dict[str, Any], dict[str, Any], int]]:
    """(previous payment, reactivating payment, gap in days) per vendor."""
    by_vendor: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        key = _text(r.get("vendor_id")).casefold() or norm_name(r.get("vendor_name"))
        if key:
            by_vendor.setdefault(key, []).append(r)
    out = []
    for key in sorted(by_vendor):
        seq = sorted(by_vendor[key], key=lambda r: (r["payment_date"], r["row_id"]))
        for prev, cur in zip(seq, seq[1:], strict=False):
            gap = (cur["payment_date"] - prev["payment_date"]).days
            if gap >= days:
                out.append((prev, cur, gap))
    return out


def _frame(rows: list[dict[str, Any]], cols: list[str]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {c: (str(x.get(c)) if x.get(c) is not None else None) for c in cols}
            | {"row_id": x["row_id"]}
            for x in rows
        ],
        schema={**dict.fromkeys(cols, pl.String), "row_id": pl.Int64},
    )


class ApAnalyticsCheck(_M):
    type: Literal["ap_analytics"]
    test: ApTest
    rules_prefix: RuleKey

    def datasets_needed(self) -> set[DatasetKind]:
        if self.test == "vendor_employee_bank":
            return {DatasetKind.AP_PAYMENTS, DatasetKind.EMPLOYEE_MASTER}
        if self.test == "three_way_match":
            return {DatasetKind.THREE_WAY_MATCH}
        if self.test == "expense_policy":
            return {DatasetKind.EXPENSE_CLAIMS}
        return {DatasetKind.AP_PAYMENTS}

    def _r(self, ctx: DataContext, name: str, meta: dict[str, Any], typed: bool = False) -> Any:
        key = f"{self.rules_prefix}.{name}"
        return _typed_rule(ctx, key, meta) if typed else _rule(ctx, key, meta)

    def _dec(self, ctx: DataContext, name: str, meta: dict[str, Any]) -> Decimal:
        v = Decimal(str(self._r(ctx, name, meta)))
        meta[name] = str(v)
        return v

    def _int(self, ctx: DataContext, name: str, meta: dict[str, Any]) -> int:
        v = int(self._r(ctx, name, meta))
        meta[name] = v
        return v

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        meta["test"] = self.test
        if self.test == "three_way_match":
            return self._three_way(ctx, meta)
        if self.test == "expense_policy":
            return self._expenses(ctx, meta)
        ds = _need(ctx, DatasetKind.AP_PAYMENTS)
        df = ds.frame
        if ctx.period:
            df = df.filter(pl.col("payment_date").is_between(ctx.period[0], ctx.period[1]))
        rows = df.sort("row_id").to_dicts()
        g = _Groups()
        if self.test == "duplicate_payment":
            pairs = duplicate_pairs(
                rows,
                self._dec(ctx, "dup_amount_tolerance", meta),
                self._int(ctx, "dup_date_window_days", meta),
                self._dec(ctx, "dup_name_similarity", meta),
                self._dec(ctx, "dup_invoice_similarity", meta),
            )
            flagged: dict[int, dict[str, Any]] = {}
            for n, (a, b) in enumerate(pairs, start=1):
                for r in (a, b):
                    tag = flagged.get(r["row_id"], {}).get("_pair")
                    flagged[r["row_id"]] = {**r, "_pair": f"{tag},{n}" if tag else str(n)}
            self._add(
                g, ds, "duplicate_payment", "Possible duplicate payments", flagged, len(pairs)
            )
        elif self.test == "vendor_employee_bank":
            self._bank(ctx, ds, rows, g, meta)
        elif self.test == "missing_trn":
            countries = {c.upper() for c in self._r(ctx, "trn_countries", meta, typed=True)}
            minimum = self._dec(ctx, "trn_min_amount", meta)
            meta["trn_countries"] = sorted(countries)
            hit = {
                r["row_id"]: r
                for r in rows
                if not _text(r.get("vendor_trn"))
                and abs(_d(r.get("amount"))) >= minimum
                and (
                    not _text(r.get("vendor_country"))
                    or _text(r.get("vendor_country")).upper() in countries
                )
            }
            self._add(g, ds, "missing_trn", "Payments to vendors with no TRN", hit, len(hit))
        else:
            gaps = dormant_payments(rows, self._int(ctx, "dormant_days", meta))
            hit = {}
            for prev, cur, gap in gaps:
                hit[prev["row_id"]] = hit.get(prev["row_id"], prev)
                hit[cur["row_id"]] = {**cur, "_gap_days": gap}
            self._add(g, ds, "dormant_vendor", "Payments to dormant vendors", hit, len(gaps))
        return _evaluation(g, len(rows), meta, "payment(s)")

    def _add(
        self,
        g: _Groups,
        ds: LoadedDataset,
        key: str,
        title: str,
        rows: dict[int, dict[str, Any]],
        count: int,
        cols: list[str] = PAY_COLS,
    ) -> None:
        if not rows:
            return
        shown = [rows[k] for k in sorted(rows)]
        g.add(key, title, _rows_evidence(ds, _frame(shown, cols), cols, f"{count} item(s)"))
        g.counts[key] = count

    def _bank(
        self,
        ctx: DataContext,
        ds: LoadedDataset,
        rows: list[dict[str, Any]],
        g: _Groups,
        meta: dict[str, Any],
    ) -> None:
        emp = _need(ctx, DatasetKind.EMPLOYEE_MASTER)
        _need_column(ds, "iban")
        _need_column(emp, "iban")
        by_iban: dict[str, list[dict[str, Any]]] = {}
        for e in emp.frame.sort("row_id").to_dicts():
            iban = norm_iban(e.get("iban"))
            if iban:
                by_iban.setdefault(iban, []).append(e)
        pay_hit: dict[int, dict[str, Any]] = {}
        emp_hit: dict[int, dict[str, Any]] = {}
        for r in rows:
            iban = norm_iban(r.get("iban"))
            for e in by_iban.get(iban, []) if iban else []:
                pay_hit[r["row_id"]] = {**r, "_iban": mask(iban)}
                emp_hit[e["row_id"]] = {**e, "_iban": mask(iban)}
        meta["employees_with_iban"] = sum(len(v) for v in by_iban.values())
        if not pay_hit:
            return
        key = "vendor_employee_bank"
        title = "Vendor payments to an employee's bank account"
        pay = [pay_hit[k] for k in sorted(pay_hit)]
        emps = [emp_hit[k] for k in sorted(emp_hit)]
        g.add(key, title, _rows_evidence(ds, _frame(pay, PAY_COLS), PAY_COLS, "Payments"))
        g.add(key, title, _rows_evidence(emp, _frame(emps, EMP_COLS), EMP_COLS, "Employees"))
        g.counts[key] = len(pay)

    def _three_way(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, DatasetKind.THREE_WAY_MATCH)
        qty_tol = self._dec(ctx, "qty_tolerance", meta)
        price_tol = self._dec(ctx, "price_tolerance_pct", meta)
        rows = ds.frame.sort("row_id").to_dicts()
        found: dict[str, dict[int, dict[str, Any]]] = {}
        for r in rows:
            inv = _d(r.get("invoiced_quantity"))
            rec = r.get("received_quantity")
            if inv > 0 and (rec is None or _d(rec) == 0):
                found.setdefault("no_receipt", {})[r["row_id"]] = r
            elif inv - _d(rec) > qty_tol:
                found.setdefault("quantity", {})[r["row_id"]] = {
                    **r,
                    "_difference": inv - _d(rec),
                }
            po_p, inv_p = r.get("po_unit_price"), r.get("invoice_unit_price")
            if po_p is not None and inv_p is not None and _d(po_p) != 0:
                share = (_d(inv_p) - _d(po_p)) / abs(_d(po_p))
                if abs(share) > price_tol:
                    found.setdefault("price", {})[r["row_id"]] = {
                        **r,
                        "_difference": share.quantize(Decimal("0.0001")),
                    }
        titles = {
            "no_receipt": "Invoiced with nothing received",
            "quantity": "Invoiced quantity above the received quantity",
            "price": "Invoice price differs from the PO price",
        }
        g = _Groups()
        for key in sorted(found):
            self._add(g, ds, key, titles[key], found[key], len(found[key]), TWM_COLS)
        return _evaluation(g, len(rows), meta, "match line(s)")

    def _expenses(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, DatasetKind.EXPENSE_CLAIMS)
        limits = self._r(ctx, "expense_limits", meta, typed=True)
        df = ds.frame
        if ctx.period:
            df = df.filter(pl.col("claim_date").is_between(ctx.period[0], ctx.period[1]))
        rows = df.sort("row_id").to_dicts()
        found: dict[str, dict[int, dict[str, Any]]] = {}
        for r in rows:
            cat = norm_name(r.get("category")).replace(" ", "_")
            lim = limits.get(cat)
            if lim is None:
                found.setdefault(f"unknown_category:{cat}", {})[r["row_id"]] = r
                continue
            if _text(r.get("currency")).upper() != lim.currency:
                found.setdefault(f"other_currency:{cat}", {})[r["row_id"]] = r
                continue
            amt = _d(r.get("amount"))
            if lim.per_claim is not None and amt > lim.per_claim:
                found.setdefault(f"over_limit:{cat}", {})[r["row_id"]] = {
                    **r,
                    "_limit": lim.per_claim,
                }
            if (
                lim.receipt_over is not None
                and amt > lim.receipt_over
                and not _text(r.get("receipt_ref"))
            ):
                found.setdefault(f"no_receipt:{cat}", {})[r["row_id"]] = {
                    **r,
                    "_limit": lim.receipt_over,
                }
        titles = {
            "unknown_category": "Claims in a category the policy pack does not list: '{}'",
            "other_currency": "Claims not in the policy currency for '{}'",
            "over_limit": "Claims above the policy limit for '{}'",
            "no_receipt": "Claims without a receipt above the threshold for '{}'",
        }
        g = _Groups()
        for key in sorted(found):
            kind, _, cat = key.partition(":")
            self._add(g, ds, key, titles[kind].format(cat), found[key], len(found[key]), EXP_COLS)
        return _evaluation(g, len(rows), meta, "claim(s)")


AP_CHECK_TYPES = (ApAnalyticsCheck,)
