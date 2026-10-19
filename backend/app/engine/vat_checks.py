"""VAT return review checks (engine 1.2.0).

The return's boxes are recomputed from the sales and purchase registers using
the entity's tax code treatments (client configuration) and the rule pack's box
layout (which treatments and measures make up each box). Differences beyond the
pack's tolerance, GL VAT account differences, reverse-charge items, zero-rated
exports without evidence and input VAT on blocked categories become findings.
Every box result records its formula, inputs and the rows that make it up.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

import polars as pl
from pydantic import Field

from app.engine.data_checks import (
    DataCheckError,
    DataContext,
    DataEvaluation,
    InputMissing,
    LoadedDataset,
    RuleKey,
    _need,
    _need_column,
    _rows_evidence,
    _sum,
)
from app.engine.einvoice_checks import _M, _evaluation, _Groups, _rule, _typed_rule
from app.models import DatasetKind

_REGISTERS = (DatasetKind.SALES_REGISTER, DatasetKind.PURCHASE_REGISTER)


def _entity(ctx: DataContext) -> Any:
    if ctx.entity is None:
        raise InputMissing("Not run: this review has no entity (its VAT setup is needed).")
    return ctx.entity


def treated(ds: LoadedDataset, entity: Any) -> pl.DataFrame:
    """Register rows with the entity's treatment and recoverability for their tax code."""
    reg = ds.kind.value
    mapping = [
        (code, t, rec) for (r, code), (t, rec) in sorted(entity.tax_codes.items()) if r == reg
    ]
    lookup = pl.DataFrame(
        {
            "tax_code": [m[0] for m in mapping],
            "_treatment": [m[1] for m in mapping],
            "_recoverable": [m[2] for m in mapping],
        },
        schema={"tax_code": pl.String, "_treatment": pl.String, "_recoverable": pl.Boolean},
    )
    df = ds.frame
    if "tax_code" not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias("tax_code"))
    return (
        df.with_columns(pl.col("tax_code").str.strip_chars())
        .join(lookup, on="tax_code", how="left")
        .sort("row_id")
    )


def _unmapped(ds: LoadedDataset, df: pl.DataFrame, g: _Groups) -> None:
    rows = df.filter(pl.col("_treatment").is_null())
    if rows.height:
        key = f"unmapped_tax_code:{ds.kind.value}"
        g.add(
            key,
            f"Tax code without a VAT treatment ({ds.kind.value.replace('_', ' ')})",
            _rows_evidence(
                ds,
                rows,
                ["tax_code", "net_amount", "tax_amount"],
                f"{rows.height} row(s); codes: "
                + ", ".join(sorted({str(c) for c in rows["tax_code"].to_list()}))[:300],
            ),
        )
        g.counts[key] = rows.height


def _return_values(ret: LoadedDataset) -> dict[str, tuple[Decimal | None, Decimal | None, int]]:
    out: dict[str, tuple[Decimal | None, Decimal | None, int]] = {}
    df = ret.frame
    for row in df.iter_rows(named=True):
        code = str(row["box_code"]).strip()
        amount = row.get("amount")
        tax = row.get("tax_amount")
        prev = out.get(code)
        if prev is not None:
            raise DataCheckError(f"Box {code} appears more than once in the VAT return.")
        out[code] = (
            Decimal(amount) if amount is not None else None,
            Decimal(tax) if tax is not None else None,
            int(row["row_id"]),
        )
    return out


class VatBoxReconcileCheck(_M):
    """Recompute each return box from the registers and compare with the return."""

    type: Literal["vat_box_reconcile"]
    layout_rule: RuleKey
    tolerance_rule: RuleKey

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.VAT_RETURN}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        entity = _entity(ctx)
        ret = _need(ctx, DatasetKind.VAT_RETURN)
        _need_column(ret, "box_code")
        layout = _typed_rule(ctx, self.layout_rule, meta)
        tol = Decimal(_rule(ctx, self.tolerance_rule, meta))
        returned = _return_values(ret)
        g = _Groups()
        frames: dict[str, tuple[LoadedDataset, pl.DataFrame]] = {}
        for kind in _REGISTERS:
            ds = ctx.datasets.get(kind)
            if ds is not None:
                df = treated(ds, entity)
                frames[kind.value] = (ds, df)
                _unmapped(ds, df, g)
        table: list[dict[str, Any]] = []
        for box in layout.boxes:
            pair = frames.get(box.register)
            if pair is None:
                raise InputMissing(
                    f"Not run: box {box.code} needs a {box.register.replace('_', ' ')}."
                )
            ds, df = pair
            rows = df.filter(pl.col("_treatment").is_in(list(box.treatments)))
            if box.filter_field:
                if box.filter_field not in rows.columns:
                    raise DataCheckError(
                        f"Box {box.code} splits by {box.filter_field}, which is not mapped."
                    )
                rows = rows.filter(
                    pl.col(box.filter_field).str.strip_chars().str.to_uppercase()
                    == (box.filter_value or "").upper()
                )
            if box.measure == "recoverable_tax":
                rows = rows.filter(pl.col("_recoverable").fill_null(False))
                column = "tax_amount"
            else:
                column = box.measure
            _need_column(ds, column)
            expected = _sum(rows, column) * box.sign
            r_amount, r_tax, r_row = returned.get(box.code, (None, None, None))
            stated = r_amount if box.measure == "net_amount" else r_tax
            diff = (stated if stated is not None else Decimal(0)) - expected
            entry = {
                "code": box.code,
                "label": box.label,
                "register": box.register,
                "treatments": list(box.treatments),
                "measure": box.measure,
                "filter": f"{box.filter_field}={box.filter_value}" if box.filter_field else None,
                "expected": str(expected),
                "returned": str(stated) if stated is not None else None,
                "difference": str(diff),
                "row_count": rows.height,
                "formula": f"Σ {column} of {box.register} rows with treatment in "
                f"{', '.join(box.treatments)}"
                + (f" and {box.filter_field} = {box.filter_value}" if box.filter_field else "")
                + (" (recoverable only)" if box.measure == "recoverable_tax" else "")
                + (" × −1" if box.sign == -1 else ""),
            }
            table.append(entry)
            if stated is None and expected == 0:
                continue
            if abs(diff) > tol:
                ev = [
                    {"type": "computation", "label": f"Box {box.code} {box.label}", "detail": entry}
                ]
                if r_row is not None:
                    ev.append(
                        _rows_evidence(
                            ret,
                            ret.frame.filter(pl.col("row_id") == r_row),
                            ["box_code", "amount", "tax_amount"],
                            f"Return box {box.code}",
                        )
                    )
                ev.append(
                    _rows_evidence(
                        ds,
                        rows,
                        ["invoice_number", "tax_code", "net_amount", "tax_amount"],
                        f"{rows.height} register row(s) in box {box.code}",
                        limit=20,
                    )
                )
                g.add(f"box:{box.code}", f"Return box {box.code} differs from the registers", ev[0])
                g.items[f"box:{box.code}"].evidence.extend(ev[1:])
        known = {b.code for b in layout.boxes} | {t.code for t in layout.totals}
        vals = dict(returned)

        def pick(code: str, col: int) -> Decimal:
            v = vals.get(code)
            got = v[col] if v is not None else None
            return got if isinstance(got, Decimal) else Decimal(0)

        for t in layout.totals:
            col = 1 if t.column == "tax_amount" else 0
            computed = sum((pick(c, col) for c in t.plus), Decimal(0)) - sum(
                (pick(c, col) for c in t.minus), Decimal(0)
            )
            stated_t = vals.get(t.code)
            stated_v = stated_t[col] if stated_t is not None else None
            entry = {
                "code": t.code,
                "label": t.label,
                "expected": str(computed),
                "returned": str(stated_v) if stated_v is not None else None,
                "difference": str((stated_v or Decimal(0)) - computed),
                "formula": f"{' + '.join(t.plus)}"
                + (f" − {' − '.join(t.minus)}" if t.minus else ""),
                "is_total": True,
            }
            table.append(entry)
            if stated_v is not None and abs(stated_v - computed) > tol:
                g.add(
                    f"box_total:{t.code}",
                    f"Return total {t.code} does not add up",
                    {"type": "computation", "label": f"Box {t.code} {t.label}", "detail": entry},
                )
        meta["box_table"] = table
        meta["unknown_boxes"] = sorted(set(returned) - known)
        meta["tolerance"] = str(tol)
        return _evaluation(g, len(table), meta, "return box(es)")


class VatGlReconcileCheck(_M):
    """Return output and input VAT against the movement on the entity's VAT GL accounts."""

    type: Literal["vat_gl_reconcile"]
    layout_rule: RuleKey
    tolerance_rule: RuleKey

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.VAT_RETURN, DatasetKind.GENERAL_LEDGER}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        entity = _entity(ctx)
        ret = _need(ctx, DatasetKind.VAT_RETURN)
        gl = _need(ctx, DatasetKind.GENERAL_LEDGER)
        _need_column(gl, "amount")
        layout = _typed_rule(ctx, self.layout_rule, meta)
        tol = Decimal(_rule(ctx, self.tolerance_rule, meta))
        if not layout.output_tax_boxes or not layout.input_tax_boxes:
            raise DataCheckError("The box layout does not name its output and input tax boxes.")
        returned = _return_values(ret)
        df = gl.frame
        if ctx.period is not None:
            start, end = ctx.period
            df = df.filter(pl.col("posting_date").is_between(start, end))
            meta["period"] = [start.isoformat(), end.isoformat()]
        g = _Groups()
        sides = {
            "output": (
                ["output_vat", "reverse_charge_output"],
                layout.output_tax_boxes,
                -1,  # credit balances: GL amount is debit − credit
            ),
            "input": (["input_vat", "reverse_charge_input"], layout.input_tax_boxes, 1),
        }
        table = []
        for side, (roles, boxes, sign) in sides.items():
            accounts = sorted({a for r in roles for a in entity.tax_accounts.get(r, ())})
            if not accounts:
                raise DataCheckError(f"Set the entity's {side} VAT GL accounts in its VAT setup.")
            rows = df.filter(pl.col("account_code").cast(pl.String).is_in(accounts))
            gl_total = _sum(rows, "amount") * sign
            ret_total = sum(
                ((returned.get(b, (None, None, 0))[1] or Decimal(0)) for b in boxes), Decimal(0)
            )
            diff = ret_total - gl_total
            entry = {
                "side": side,
                "accounts": accounts,
                "boxes": list(boxes),
                "gl": str(gl_total),
                "returned": str(ret_total),
                "difference": str(diff),
                "row_count": rows.height,
                "formula": f"{'−' if sign < 0 else ''}Σ GL amount on {', '.join(accounts)} "
                f"vs Σ tax of boxes {', '.join(boxes)}",
            }
            table.append(entry)
            if abs(diff) > tol:
                g.add(
                    f"gl:{side}",
                    f"Return {side} VAT differs from the GL VAT accounts",
                    {"type": "computation", "label": f"{side} VAT", "detail": entry},
                )
                g.items[f"gl:{side}"].evidence.append(
                    _rows_evidence(
                        gl,
                        rows,
                        ["entry_id", "posting_date", "account_code", "amount"],
                        f"{rows.height} GL line(s) on VAT accounts",
                        limit=20,
                    )
                )
        meta["gl_table"] = table
        meta["tolerance"] = str(tol)
        return _evaluation(g, 2, meta, "side(s)")


class ReverseChargeCheck(_M):
    """List reverse-charge purchases for review; flag those without self-assessed VAT."""

    type: Literal["reverse_charge"]

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.PURCHASE_REGISTER}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        entity = _entity(ctx)
        ds = _need(ctx, DatasetKind.PURCHASE_REGISTER)
        df = treated(ds, entity).filter(pl.col("_treatment") == "reverse_charge")
        g = _Groups()
        cols = ["invoice_number", "supplier_name", "tax_code", "net_amount", "tax_amount"]
        if df.height:
            g.add(
                "rc:items",
                "Reverse-charge purchases to review",
                _rows_evidence(ds, df, cols, f"{df.height} reverse-charge row(s)"),
            )
            g.counts["rc:items"] = df.height
        zero = df.filter(pl.col("tax_amount").fill_null(0) == 0)
        if zero.height:
            g.add(
                "rc:no_tax",
                "Reverse-charge purchases with no VAT recorded",
                _rows_evidence(ds, zero, cols, f"{zero.height} row(s) with zero VAT"),
            )
            g.counts["rc:no_tax"] = zero.height
        meta["reverse_charge_rows"] = df.height
        meta["reverse_charge_net"] = str(_sum(df, "net_amount"))
        return _evaluation(g, df.height, meta, "reverse-charge row(s)")


class ZeroRatedEvidenceCheck(_M):
    """Zero-rated exports need an export evidence reference and no VAT charged."""

    type: Literal["zero_rated_evidence"]
    include_zero_rated_foreign: bool = Field(
        default=True, description="Also treat zero-rated sales to a foreign customer as exports."
    )

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.SALES_REGISTER}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        entity = _entity(ctx)
        ds = _need(ctx, DatasetKind.SALES_REGISTER)
        df = treated(ds, entity)
        for c in ("export_evidence_ref", "customer_country"):
            if c not in df.columns:
                df = df.with_columns(pl.lit(None, dtype=pl.String).alias(c))
        export = pl.col("_treatment") == "zero_rated_export"
        if self.include_zero_rated_foreign:
            foreign = (
                pl.col("customer_country")
                .str.strip_chars()
                .str.to_uppercase()
                .fill_null(entity.country)
            )
            export = export | ((pl.col("_treatment") == "zero_rated") & (foreign != entity.country))
        rows = df.filter(export)
        g = _Groups()
        cols = [
            "invoice_number",
            "customer_name",
            "customer_country",
            "tax_code",
            "net_amount",
            "tax_amount",
            "export_evidence_ref",
        ]
        missing = rows.filter(
            pl.col("export_evidence_ref").is_null()
            | (pl.col("export_evidence_ref").str.strip_chars() == "")
        )
        if missing.height:
            g.add(
                "zero_rated:no_evidence",
                "Zero-rated export without export evidence",
                _rows_evidence(
                    ds, missing, cols, f"{missing.height} row(s) without an evidence reference"
                ),
            )
            g.counts["zero_rated:no_evidence"] = missing.height
        charged = df.filter(
            pl.col("_treatment").is_in(["zero_rated", "zero_rated_export"])
            & (pl.col("tax_amount").fill_null(0) != 0)
        )
        if charged.height:
            g.add(
                "zero_rated:tax_charged",
                "VAT charged on a zero-rated supply",
                _rows_evidence(ds, charged, cols, f"{charged.height} row(s)"),
            )
            g.counts["zero_rated:tax_charged"] = charged.height
        meta["export_rows"] = rows.height
        return _evaluation(g, rows.height, meta, "zero-rated export row(s)")


class BlockedInputCheck(_M):
    """Recoverable input VAT claimed on expense categories the rule pack lists as blocked."""

    type: Literal["blocked_input"]
    blocked_rule: RuleKey

    def datasets_needed(self) -> set[DatasetKind]:
        return {DatasetKind.PURCHASE_REGISTER}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        entity = _entity(ctx)
        ds = _need(ctx, DatasetKind.PURCHASE_REGISTER)
        _need_column(ds, "expense_category")
        blocked = [str(c).strip().casefold() for c in _typed_rule(ctx, self.blocked_rule, meta)]
        df = treated(ds, entity).with_columns(
            pl.col("expense_category").str.strip_chars().str.to_lowercase().alias("_cat")
        )
        hits = df.filter(
            pl.col("_cat").is_in(blocked)
            & pl.col("_recoverable").fill_null(False)
            & (pl.col("tax_amount").fill_null(0) != 0)
        )
        g = _Groups()
        cols = ["invoice_number", "supplier_name", "expense_category", "tax_code", "tax_amount"]
        for cat in sorted(set(hits["_cat"].to_list())):
            rows = hits.filter(pl.col("_cat") == cat)
            key = f"blocked:{cat}"
            g.add(
                key,
                f"Input VAT claimed on blocked category '{cat}'",
                _rows_evidence(
                    ds, rows, cols, f"{rows.height} row(s), VAT {_sum(rows, 'tax_amount')}"
                ),
            )
            g.counts[key] = rows.height
        meta["blocked_categories"] = blocked
        meta["checked"] = df.height
        return _evaluation(g, df.height, meta, "purchase row(s)")


VAT_CHECK_TYPES = (
    VatBoxReconcileCheck,
    VatGlReconcileCheck,
    ReverseChargeCheck,
    ZeroRatedEvidenceCheck,
    BlockedInputCheck,
)
