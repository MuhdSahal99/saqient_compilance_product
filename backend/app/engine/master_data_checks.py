"""Master data quality checks (engine 1.2.0): tax ids, completeness, register vs master.

Duplicate parties reuse the 1.1.0 ``duplicate`` check (exact on TRN, fuzzy on
name within a blocking key such as country) on the customer or supplier master.
"""

from __future__ import annotations

from typing import Any, Literal

import polars as pl
from pydantic import Field, model_validator

from app.engine.data_checks import (
    DataCheckError,
    DataContext,
    DataEvaluation,
    FieldName,
    LoadedDataset,
    RuleKey,
    Selection,
    _filter,
    _need,
    _need_column,
    _rows_evidence,
)
from app.engine.einvoice_checks import _evaluation, _Groups, _typed_rule
from app.engine.formats import describe_tax_id, normalise_tax_id, tax_id_ok
from app.models import DatasetKind

_PARTY_KINDS = (
    DatasetKind.CUSTOMER_MASTER,
    DatasetKind.SUPPLIER_MASTER,
    DatasetKind.SALES_REGISTER,
    DatasetKind.PURCHASE_REGISTER,
)


def _col(ds: LoadedDataset, name: str | None) -> pl.Expr:
    if name is None or name not in ds.frame.columns:
        return pl.lit(None, dtype=pl.String)
    return pl.col(name)


def _ev(ds: LoadedDataset, rows: pl.DataFrame, cols: list[str], label: str) -> dict[str, Any]:
    return _rows_evidence(ds, rows, cols, label)


class TaxIdFormatCheck(Selection):
    """Tax registration numbers checked against per-country shapes from the rule pack."""

    type: Literal["tax_id_format"]
    field: FieldName
    country_field: FieldName | None = None
    default_country: str = Field(pattern=r"^[A-Z]{2}$")
    formats_rule: RuleKey
    required: bool = False

    @model_validator(mode="after")
    def _tf(self) -> TaxIdFormatCheck:
        if self.dataset not in _PARTY_KINDS:
            raise ValueError("tax_id_format works on masters and sales/purchase registers")
        self._check_field(self.field, ("text",))
        self._check_field(self.country_field, ("text",))
        return self

    def datasets_needed(self) -> set[DatasetKind]:
        return {self.dataset}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, self.dataset)
        _need_column(ds, self.field)
        formats = _typed_rule(ctx, self.formats_rule, meta)
        df = _filter(ds.frame, self).with_columns(
            _col(ds, self.country_field)
            .str.strip_chars()
            .str.to_uppercase()
            .fill_null(self.default_country)
            .alias("_country")
        )
        g = _Groups()
        cols = ["row_id", self.field, *([self.country_field] if self.country_field else [])]
        missing = df.filter(
            pl.col(self.field).is_null() | (pl.col(self.field).str.strip_chars() == "")
        )
        if self.required and missing.height:
            g.add(
                "tax_id:missing",
                "Tax registration number missing",
                _ev(ds, missing, cols, f"{missing.height} row(s) without {self.field}"),
            )
            g.counts["tax_id:missing"] = missing.height
        present = df.filter(~pl.col("row_id").is_in(missing["row_id"]))
        no_format: set[str] = set()
        for country in sorted(set(present["_country"].to_list())):
            fmt = formats.get(country)
            if fmt is None:
                no_format.add(country)
                continue
            rows = present.filter(pl.col("_country") == country)
            bad_ids = [
                rid
                for rid, v in rows.select("row_id", self.field).iter_rows()
                if not tax_id_ok(v, fmt)
            ]
            if bad_ids:
                bad = rows.filter(pl.col("row_id").is_in(bad_ids))
                key = f"tax_id:invalid:{country}"
                g.add(
                    key,
                    f"{country} tax registration number has the wrong format",
                    _ev(
                        ds,
                        bad,
                        cols,
                        f"{bad.height} {country} number(s) not {describe_tax_id(fmt)}",
                    ),
                )
                g.counts[key] = bad.height
        meta["countries_without_format"] = sorted(no_format)
        meta["checked"] = df.height
        return _evaluation(g, df.height, meta, "row(s)")


class CompletenessCheck(Selection):
    """Required fields (fixed, or per country from the rule pack) must not be blank."""

    type: Literal["completeness"]
    fields: list[FieldName] = Field(default_factory=list, max_length=20)
    required_rule: RuleKey | None = None
    country_field: FieldName | None = None
    default_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")

    @model_validator(mode="after")
    def _cc(self) -> CompletenessCheck:
        if not self.fields and self.required_rule is None:
            raise ValueError("give fields, required_rule, or both")
        for f in self.fields:
            self._check_field(f)
        self._check_field(self.country_field, ("text",))
        return self

    def datasets_needed(self) -> set[DatasetKind]:
        return {self.dataset}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        ds = _need(ctx, self.dataset)
        df = _filter(ds.frame, self).with_columns(
            _col(ds, self.country_field)
            .str.strip_chars()
            .str.to_uppercase()
            .fill_null(self.default_country or "*")
            .alias("_country")
        )
        by_country: dict[str, list[str]] = {}
        if self.required_rule:
            by_country = _typed_rule(ctx, self.required_rule, meta)
        g = _Groups()
        for country in sorted(set(df["_country"].to_list())):
            needed = list(
                dict.fromkeys([*self.fields, *by_country.get(country, by_country.get("*", []))])
            )
            rows = df.filter(pl.col("_country") == country)
            for f in needed:
                if f not in ds.frame.columns:
                    if f in self.fields or by_country:
                        raise DataCheckError(
                            f"Field '{f}' was not mapped in {ds.kind.value.replace('_', ' ')} "
                            f"version {ds.version_number}."
                        )
                    continue
                blank = rows.filter(
                    pl.col(f).is_null() | (pl.col(f).cast(pl.String).str.strip_chars() == "")
                )
                if blank.height:
                    key = f"missing:{f}"
                    g.add(
                        key,
                        f"{f.replace('_', ' ').capitalize()} missing",
                        _ev(
                            ds,
                            blank,
                            ["row_id", f, *([self.country_field] if self.country_field else [])],
                            f"{blank.height} row(s) without {f}"
                            + (f" ({country})" if country != "*" else ""),
                        ),
                    )
                    g.counts[key] = g.counts.get(key, 1) - 1 + blank.height
        meta["checked"] = df.height
        return _evaluation(g, df.height, meta, "row(s)")


class PartyCrossCheck(Selection):
    """Register party TRNs must exist in the master; same-name parties must share a TRN."""

    type: Literal["party_cross_check"]
    master: Literal["customer_master", "supplier_master"]

    @model_validator(mode="after")
    def _pc(self) -> PartyCrossCheck:
        pairs = {
            DatasetKind.SALES_REGISTER: "customer_master",
            DatasetKind.PURCHASE_REGISTER: "supplier_master",
        }
        if pairs.get(self.dataset) != self.master:
            raise ValueError(
                "pair sales_register with customer_master, purchase_register with supplier_master"
            )
        return self

    def datasets_needed(self) -> set[DatasetKind]:
        return {self.dataset, DatasetKind(self.master)}

    def run(self, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
        reg = _need(ctx, self.dataset)
        mst = _need(ctx, DatasetKind(self.master))
        side = "customer" if self.master == "customer_master" else "supplier"
        trn_f, name_f = f"{side}_trn", f"{side}_name"
        _need_column(reg, trn_f)
        _need_column(mst, "trn")
        norm = pl.col("trn").map_elements(normalise_tax_id, return_dtype=pl.String)
        master_trns = set(
            mst.frame.filter(pl.col("trn").is_not_null()).select(norm)["trn"].to_list()
        )
        df = _filter(reg.frame, self).filter(pl.col(trn_f).is_not_null())
        df = df.with_columns(
            pl.col(trn_f).map_elements(normalise_tax_id, return_dtype=pl.String).alias("_trn")
        )
        g = _Groups()
        unknown = df.filter(~pl.col("_trn").is_in(list(master_trns)))
        cols = ["row_id", trn_f, *([name_f] if name_f in df.columns else [])]
        if unknown.height:
            g.add(
                "party:unknown_trn",
                f"{side.capitalize()} TRN on the register is not in the master",
                _ev(
                    reg,
                    unknown,
                    cols,
                    f"{unknown.height} row(s), {unknown['_trn'].n_unique()} TRN(s)",
                ),
            )
            g.counts["party:unknown_trn"] = unknown.height
        if name_f in df.columns and "name" in mst.frame.columns:
            names: dict[str, set[str]] = {}
            for name, trn in mst.frame.select("name", "trn").iter_rows():
                if name and trn:
                    names.setdefault(" ".join(name.casefold().split()), set()).add(
                        normalise_tax_id(trn)
                    )
            differs = [
                rid
                for rid, n, t in df.select("row_id", name_f, "_trn").iter_rows()
                if n
                and " ".join(n.casefold().split()) in names
                and t not in names[" ".join(n.casefold().split())]
            ]
            if differs:
                rows = df.filter(pl.col("row_id").is_in(differs))
                g.add(
                    "party:trn_differs",
                    f"{side.capitalize()} TRN differs from the master for the same name",
                    _ev(reg, rows, cols, f"{rows.height} row(s)"),
                )
                g.counts["party:trn_differs"] = rows.height
        meta["checked"] = df.height
        return _evaluation(g, df.height, meta, "register row(s)")


MASTER_CHECK_TYPES = (TaxIdFormatCheck, CompletenessCheck, PartyCrossCheck)
