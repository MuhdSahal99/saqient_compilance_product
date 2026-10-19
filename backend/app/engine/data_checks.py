"""Deterministic data checks over canonical finance datasets (engine 1.1.0).

Each check is a validated declarative configuration; there is no user code and
no user regex. Checks read canonical Parquet rows (Decimal amounts, dates,
``row_id``), never floats, and always order by row id, so the same dataset
versions, rule values and configuration give the same result. Exceptions are
reported with the dataset version, row ids and column values. An exception is
something for a reviewer to look at, not a conclusion.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Protocol

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rapidfuzz import fuzz

from app.datasets.schemas import SCHEMAS
from app.models import CheckOutcome, DatasetKind

MAX_EVIDENCE_GROUPS = 20
MAX_EVIDENCE_ROWS = 50
MAX_ROW_IDS_PER_GROUP = 20

FieldName = Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
DecimalStr = Annotated[str, Field(pattern=r"^-?\d{1,16}(\.\d{1,10})?$")]
RuleKey = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[._][a-z0-9]+)*$", max_length=120)]

# Columns every canonical dataset may carry beyond its mapped fields.
_EXTRA = {"row_id": "integer", "currency": "currency"}
_DERIVED = {"amount": "amount", "debit": "amount", "credit": "amount", "balance": "amount"}


def field_type(kind: DatasetKind, name: str) -> str | None:
    f = SCHEMAS[kind].get(name)
    if f is not None:
        return f.type
    return _EXTRA.get(name) or _DERIVED.get(name)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(_Model):
    field: FieldName
    op: Literal[
        "eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "not_null", "starts_with"
    ]
    value: str | None = Field(default=None, max_length=200)
    values: list[Annotated[str, Field(max_length=200)]] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _shape(self) -> Condition:
        if self.op in ("in", "not_in"):
            if not self.values:
                raise ValueError(f"'{self.op}' needs values")
        elif self.op in ("is_null", "not_null"):
            pass
        elif self.value is None:
            raise ValueError(f"'{self.op}' needs a value")
        return self


class Selection(_Model):
    dataset: DatasetKind
    where: list[Condition] = Field(default_factory=list, max_length=10)

    def _check_field(self, name: str | None, allowed: tuple[str, ...] | None = None) -> None:
        if name is None:
            return
        t = field_type(self.dataset, name)
        if t is None:
            raise ValueError(f"'{name}' is not a field of {self.dataset.value}")
        if allowed and t not in allowed:
            raise ValueError(f"'{name}' must be of type {' or '.join(allowed)}")

    @model_validator(mode="after")
    def _fields(self) -> Selection:
        for c in self.where:
            self._check_field(c.field)
            t = field_type(self.dataset, c.field)
            if c.op == "starts_with" and t != "text":
                raise ValueError("'starts_with' works on text fields only")
            for raw in ([c.value] if c.value is not None else []) + (c.values or []):
                _typed_literal(t or "text", raw)
        return self


class ValueRef(_Model):
    """A fixed number, or a rule pack key resolved at run time."""

    value: DecimalStr | None = None
    rule: RuleKey | None = None

    @model_validator(mode="after")
    def _one(self) -> ValueRef:
        if (self.value is None) == (self.rule is None):
            raise ValueError("give exactly one of value or rule")
        return self


_Op = Literal["gt", "gte", "lt", "lte", "eq", "ne"]


class ReconcileSide(Selection):
    group_by: list[FieldName] = Field(default_factory=list, max_length=4)
    sum: FieldName
    sign: Literal[1, -1] = 1

    @model_validator(mode="after")
    def _side(self) -> ReconcileSide:
        self._check_field(self.sum, ("amount",))
        for g in self.group_by:
            self._check_field(g)
        return self


class ReconcileCheck(_Model):
    """Group and sum two selections; differences beyond tolerance are exceptions."""

    type: Literal["reconcile"]
    left: ReconcileSide
    right: ReconcileSide
    tolerance_absolute: DecimalStr = "0"
    tolerance_percent: DecimalStr = "0"
    missing_as_zero: bool = True

    @model_validator(mode="after")
    def _keys(self) -> ReconcileCheck:
        if len(self.left.group_by) != len(self.right.group_by):
            raise ValueError("left and right need the same number of group_by fields")
        if Decimal(self.tolerance_absolute) < 0 or Decimal(self.tolerance_percent) < 0:
            raise ValueError("tolerances cannot be negative")
        return self


class ThresholdCheck(Selection):
    """Rows (or the sum/count of rows) where `field flag_if value` holds are exceptions."""

    type: Literal["threshold"]
    field: FieldName | None = None
    aggregate: Literal["row", "sum", "count"] = "row"
    use_absolute: bool = False
    flag_if: _Op
    value: ValueRef

    @model_validator(mode="after")
    def _f(self) -> ThresholdCheck:
        if self.aggregate != "count":
            if self.field is None:
                raise ValueError("field is required unless aggregate is count")
            self._check_field(self.field, ("amount",))
        return self


class DuplicateCheck(Selection):
    """Rows sharing the same key. 'normalised' ignores case, spacing and punctuation;
    'similar' compares `similar_field` by edit-distance score within equal `keys`."""

    type: Literal["duplicate"]
    keys: list[FieldName] = Field(default_factory=list, max_length=6)
    match: Literal["exact", "normalised", "similar"] = "exact"
    similar_field: FieldName | None = None
    min_score: int = Field(default=90, ge=50, le=100)
    max_group_size: int = Field(default=500, ge=2, le=2000)

    @model_validator(mode="after")
    def _d(self) -> DuplicateCheck:
        for k in self.keys:
            self._check_field(k)
        if self.match == "similar":
            if self.similar_field is None:
                raise ValueError("similar matching needs similar_field")
            self._check_field(self.similar_field, ("text",))
        elif not self.keys:
            raise ValueError("give at least one key")
        return self


_FORMATS = {
    "digits": r"^[0-9]+$",
    "alphanumeric": r"^[A-Za-z0-9]+$",
    "currency_code": r"^[A-Z]{3}$",
    "email": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    "iban": r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$",
    "not_empty": r"\S",
}


class FieldFormatCheck(Selection):
    """Values that do not match a predefined format are exceptions."""

    type: Literal["field_format"]
    field: FieldName
    format: Literal["digits", "alphanumeric", "currency_code", "email", "iban", "not_empty"]
    length: int | None = Field(default=None, ge=1, le=64)
    required: bool = False

    @model_validator(mode="after")
    def _ff(self) -> FieldFormatCheck:
        self._check_field(self.field, ("text", "currency"))
        return self


_WEEKDAYS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}


class DateRuleCheck(Selection):
    type: Literal["date_rule"]
    field: FieldName
    rule: Literal["within_period", "not_weekend", "not_future", "max_days_from", "not_after_field"]
    weekend_days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] | None = None
    period_start: date | None = None
    period_end: date | None = None
    other_field: FieldName | None = None
    max_days: int | None = Field(default=None, ge=0, le=36600)

    @model_validator(mode="after")
    def _dr(self) -> DateRuleCheck:
        self._check_field(self.field, ("date",))
        if self.rule == "not_weekend" and not self.weekend_days:
            raise ValueError("not_weekend needs weekend_days (they differ by jurisdiction)")
        if self.rule in ("max_days_from", "not_after_field"):
            if self.other_field is None:
                raise ValueError(f"{self.rule} needs other_field")
            self._check_field(self.other_field, ("date",))
        if self.rule == "max_days_from" and self.max_days is None:
            raise ValueError("max_days_from needs max_days")
        return self


class Aggregate(Selection):
    aggregate: Literal["sum", "count"] = "sum"
    field: FieldName | None = None
    use_absolute: bool = False

    @model_validator(mode="after")
    def _a(self) -> Aggregate:
        if self.aggregate == "sum":
            if self.field is None:
                raise ValueError("sum needs a field")
            self._check_field(self.field, ("amount",))
        return self


class RatioCheck(_Model):
    """numerator / denominator outside [min, max] is an exception."""

    type: Literal["ratio"]
    numerator: Aggregate
    denominator: Aggregate
    min: ValueRef | None = None
    max: ValueRef | None = None

    @model_validator(mode="after")
    def _r(self) -> RatioCheck:
        if self.min is None and self.max is None:
            raise ValueError("give min, max or both")
        return self


DATA_CHECK_TYPES = (
    ReconcileCheck,
    ThresholdCheck,
    DuplicateCheck,
    FieldFormatCheck,
    DateRuleCheck,
    RatioCheck,
)
DataCheckConfig = (
    ReconcileCheck | ThresholdCheck | DuplicateCheck | FieldFormatCheck | DateRuleCheck | RatioCheck
)


def datasets_used(config: Any) -> set[DatasetKind]:
    from app.engine import tax_checks

    if isinstance(config, tax_checks.TAX_CHECK_TYPES):
        return tax_checks.datasets_used(config)
    if isinstance(config, ReconcileCheck):
        return {config.left.dataset, config.right.dataset}
    if isinstance(config, RatioCheck):
        return {config.numerator.dataset, config.denominator.dataset}
    return {config.dataset}


# ---------------------------------------------------------------- runtime context


@dataclass
class LoadedDataset:
    version_id: str
    version_number: int
    kind: DatasetKind
    frame: pl.DataFrame
    period_start: date | None
    period_end: date | None


class RuleLike(Protocol):
    """What a resolved rule must expose (see services/rule_packs.ResolvedRule)."""

    @property
    def value(self) -> Any: ...
    @property
    def verified(self) -> bool: ...

    def warning(self) -> str | None: ...
    def snapshot(self) -> dict[str, Any]: ...


@dataclass
class DataContext:
    datasets: dict[DatasetKind, LoadedDataset]
    resolve_rule: Callable[[str], RuleLike]
    as_of: date
    # Engine 1.2.0 inputs (all optional; a check that needs one and lacks it does not run).
    period: tuple[date, date] | None = None  # the review's tax period
    entity: Any = None  # engine.tax_checks.EntityInfo
    einvoices: Any = None  # engine.einvoice_checks.InvoiceSet
    resolve_file: Callable[[str], Any] | None = None  # services.rule_packs.ResolvedFile
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class FindingGroup:
    """One of several findings a check raises (e.g. one per failed invoice rule)."""

    key: str
    title: str
    message: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DataEvaluation:
    outcome: CheckOutcome
    needs_attention: bool
    message: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    groups: list[FindingGroup] = field(default_factory=list)


class DataCheckError(ValueError):
    """The check cannot run on these inputs (message safe to show)."""


class InputMissing(DataCheckError):
    """The review lacks an input this check needs: not run, nothing to look at."""


# ---------------------------------------------------------------- helpers


def _typed_literal(t: str, raw: str) -> Any:
    try:
        if t == "amount":
            return Decimal(raw)
        if t == "date":
            return date.fromisoformat(raw)
        if t == "integer":
            return int(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"'{raw}' is not a valid {t}") from exc
    return raw


def _lit(t: str, raw: str) -> pl.Expr:
    v = _typed_literal(t, raw)
    if t == "amount":
        return pl.lit(v, dtype=pl.Decimal(20, 4))
    return pl.lit(v)


def _filter(df: pl.DataFrame, sel: Selection) -> pl.DataFrame:
    for c in sel.where:
        t = field_type(sel.dataset, c.field) or "text"
        if c.field not in df.columns:
            df = df.with_columns(pl.lit(None).alias(c.field))
        col = pl.col(c.field)
        if c.op == "is_null":
            df = df.filter(col.is_null())
        elif c.op == "not_null":
            df = df.filter(col.is_not_null())
        elif c.op in ("in", "not_in"):
            values = [_typed_literal(t, v) for v in c.values or []]
            if t == "amount":
                expr = col.is_in(pl.Series(values, dtype=pl.Decimal(20, 4)))
            else:
                expr = col.is_in(values)
            df = df.filter(expr if c.op == "in" else ~expr)
        elif c.op == "starts_with":
            df = df.filter(col.str.starts_with(c.value or ""))
        else:
            rhs = _lit(t, c.value or "")
            expr = {
                "eq": col == rhs,
                "ne": col != rhs,
                "gt": col > rhs,
                "gte": col >= rhs,
                "lt": col < rhs,
                "lte": col <= rhs,
            }[c.op]
            df = df.filter(expr.fill_null(False))
    return df


def _need(ctx: DataContext, kind: DatasetKind) -> LoadedDataset:
    ds = ctx.datasets.get(kind)
    if ds is None:
        raise DataCheckError(f"This check needs a {kind.value.replace('_', ' ')} dataset.")
    return ds


def _need_column(ds: LoadedDataset, name: str) -> None:
    if name not in ds.frame.columns:
        raise DataCheckError(
            f"Field '{name}' was not mapped in {ds.kind.value.replace('_', ' ')} "
            f"version {ds.version_number}."
        )


def _fmt(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, bool)):
        return v
    return str(v)


def _rows_evidence(
    ds: LoadedDataset,
    rows: pl.DataFrame,
    columns: list[str],
    label: str,
    detail: dict[str, Any] | None = None,
    limit: int = MAX_EVIDENCE_ROWS,
) -> dict[str, Any]:
    cols = ["row_id", *[c for c in columns if c != "row_id" and c in rows.columns]]
    shown = rows.sort("row_id").head(limit).select(cols)
    return {
        "type": "dataset_rows",
        "dataset_version_id": ds.version_id,
        "dataset_kind": ds.kind.value,
        "version_number": ds.version_number,
        "label": label,
        "row_ids": shown["row_id"].to_list(),
        "row_count": rows.height,
        "columns": cols,
        "rows": [[_fmt(v) for v in r] for r in shown.iter_rows()],
        "detail": {k: _fmt(v) for k, v in (detail or {}).items()},
    }


def _ref(ref: ValueRef, ctx: DataContext, meta: dict[str, Any]) -> Decimal:
    if ref.value is not None:
        return Decimal(ref.value)
    assert ref.rule is not None
    try:
        rule = ctx.resolve_rule(ref.rule)
    except LookupError as exc:
        raise DataCheckError(str(exc)) from exc
    meta.setdefault("rules", []).append(rule.snapshot())
    warning = rule.warning()
    if warning:
        meta.setdefault("warnings", []).append(warning)
    if not isinstance(rule.value, (Decimal, int)) or isinstance(rule.value, bool):
        raise DataCheckError(f"Rule '{ref.rule}' is not a number.")
    return Decimal(rule.value)


def _compare(a: Decimal, op: str, b: Decimal) -> bool:
    return {
        "gt": a > b,
        "gte": a >= b,
        "lt": a < b,
        "lte": a <= b,
        "eq": a == b,
        "ne": a != b,
    }[op]


def _sum(df: pl.DataFrame, name: str, absolute: bool = False) -> Decimal:
    col = pl.col(name).abs() if absolute else pl.col(name)
    total = df.select(col.fill_null(0).sum()).item()
    return Decimal(total) if total is not None else Decimal(0)


def _done(
    exceptions: int,
    message_ok: str,
    message_bad: str,
    evidence: list[dict[str, Any]],
    meta: dict[str, Any],
) -> DataEvaluation:
    meta["exception_count"] = exceptions
    if exceptions:
        return DataEvaluation(
            CheckOutcome.EXCEPTIONS_FOUND, True, message_bad, evidence[:MAX_EVIDENCE_GROUPS], meta
        )
    return DataEvaluation(CheckOutcome.NO_EXCEPTIONS, False, message_ok, [], meta)


_OP_WORDS = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "=", "ne": "≠"}


# ---------------------------------------------------------------- checks


def _reconcile(c: ReconcileCheck, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
    sides = []
    for side in (c.left, c.right):
        ds = _need(ctx, side.dataset)
        for name in [side.sum, *side.group_by]:
            _need_column(ds, name)
        df = _filter(ds.frame, side)
        key_exprs = [pl.col(g).cast(pl.String).alias(f"k{i}") for i, g in enumerate(side.group_by)]
        if key_exprs:
            g = df.group_by(key_exprs).agg(
                pl.col(side.sum).fill_null(0).sum().alias("total"),
                pl.col("row_id").sort().alias("row_ids"),
            )
        else:
            g = df.select(
                pl.col(side.sum).fill_null(0).sum().alias("total"),
                pl.col("row_id").sort().implode().alias("row_ids"),
            )
        sides.append((ds, side, g))
    (lds, lside, lg), (rds, rside, rg) = sides
    keys = [f"k{i}" for i in range(len(lside.group_by))]
    tol_abs, tol_pct = Decimal(c.tolerance_absolute), Decimal(c.tolerance_percent)
    left = {tuple(r[k] for k in keys): r for r in lg.iter_rows(named=True)}
    right = {tuple(r[k] for k in keys): r for r in rg.iter_rows(named=True)}
    all_keys = sorted(
        set(left) | set(right), key=lambda k: tuple("" if x is None else x for x in k)
    )
    evidence: list[dict[str, Any]] = []
    exceptions = 0
    for key in all_keys:
        lrow, rrow = left.get(key), right.get(key)
        if (lrow is None or rrow is None) and not c.missing_as_zero:
            reason = "missing on the right" if rrow is None else "missing on the left"
            diff = None
        else:
            lt = Decimal(lrow["total"]) * lside.sign if lrow else Decimal(0)
            rt = Decimal(rrow["total"]) * rside.sign if rrow else Decimal(0)
            diff = lt - rt
            allowed = max(tol_abs, tol_pct / Decimal(100) * abs(rt))
            if abs(diff) <= allowed:
                continue
            reason = "difference beyond tolerance"
        exceptions += 1
        if len(evidence) >= MAX_EVIDENCE_GROUPS * 2:
            continue
        group = dict(zip(lside.group_by, key, strict=True)) if keys else {}
        detail = {
            **{f"group.{k}": v for k, v in group.items()},
            "left_total": (Decimal(lrow["total"]) * lside.sign) if lrow else None,
            "right_total": (Decimal(rrow["total"]) * rside.sign) if rrow else None,
            "difference": diff,
            "reason": reason,
        }
        for ds, side, row in ((lds, lside, lrow), (rds, rside, rrow)):
            ids = list(row["row_ids"])[:MAX_ROW_IDS_PER_GROUP] if row else []
            rows = ds.frame.filter(pl.col("row_id").is_in(ids)) if ids else ds.frame.head(0)
            ev = _rows_evidence(
                ds, rows, [*side.group_by, side.sum], f"{ds.kind.value} {group or 'total'}", detail
            )
            ev["row_count"] = len(row["row_ids"]) if row else 0
            evidence.append(ev)
    meta["groups_compared"] = len(all_keys)
    return _done(
        exceptions,
        f"All {len(all_keys)} group(s) reconcile within tolerance.",
        f"{exceptions} of {len(all_keys)} group(s) do not reconcile.",
        evidence,
        meta,
    )


def _threshold(c: ThresholdCheck, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
    ds = _need(ctx, c.dataset)
    if c.field:
        _need_column(ds, c.field)
    df = _filter(ds.frame, c)
    limit = _ref(c.value, ctx, meta)
    word = f"{_OP_WORDS[c.flag_if]} {limit}"
    if c.aggregate == "row":
        assert c.field is not None
        col = pl.col(c.field).abs() if c.use_absolute else pl.col(c.field)
        rhs = pl.lit(limit, dtype=pl.Decimal(38, 10))
        expr = {
            "gt": col > rhs,
            "gte": col >= rhs,
            "lt": col < rhs,
            "lte": col <= rhs,
            "eq": col == rhs,
            "ne": col != rhs,
        }[c.flag_if]
        hits = df.filter(expr.fill_null(False))
        evidence = (
            [_rows_evidence(ds, hits, [c.field, "currency"], f"{c.field} {word}")]
            if hits.height
            else []
        )
        return _done(
            hits.height,
            f"No rows with {c.field} {word} ({df.height} checked).",
            f"{hits.height} row(s) with {c.field} {word}.",
            evidence,
            meta,
        )
    value = (
        Decimal(df.height) if c.aggregate == "count" else _sum(df, c.field or "", c.use_absolute)
    )
    meta["aggregate_value"] = str(value)
    label = "row count" if c.aggregate == "count" else f"sum of {c.field}"
    if _compare(value, c.flag_if, limit):
        ev = _rows_evidence(
            ds,
            df,
            [c.field or "row_id", "currency"],
            f"{label} = {value}",
            {"aggregate": value, "limit": limit},
        )
        return _done(1, "", f"The {label} ({value}) is {word}.", [ev], meta)
    return _done(0, f"The {label} ({value}) is not {word}.", "", [], meta)


def _norm_expr(name: str) -> pl.Expr:
    return (
        pl.col(name)
        .cast(pl.String)
        .str.normalize("NFKC")
        .str.to_lowercase()
        .str.replace_all(r"[^\p{L}\p{N}]", "")
    )


def _duplicate(c: DuplicateCheck, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
    ds = _need(ctx, c.dataset)
    for k in [*c.keys, *([c.similar_field] if c.similar_field else [])]:
        _need_column(ds, k)
    df = _filter(ds.frame, c).drop_nulls(c.keys or None)
    shown_cols = [*c.keys, *([c.similar_field] if c.similar_field else [])]
    groups: list[list[int]] = []
    if c.match in ("exact", "normalised"):
        keys = [
            (
                _norm_expr(k)
                if c.match == "normalised" and field_type(c.dataset, k) == "text"
                else pl.col(k)
            ).alias(f"__k{i}")
            for i, k in enumerate(c.keys)
        ]
        g = (
            df.with_columns(keys)
            .group_by([f"__k{i}" for i in range(len(keys))])
            .agg(pl.col("row_id").sort().alias("ids"), pl.len().alias("n"))
            .filter(pl.col("n") > 1)
        )
        groups = sorted((list(r) for r in g["ids"].to_list()), key=lambda ids: ids[0])
    else:
        assert c.similar_field is not None
        df = df.drop_nulls([c.similar_field]).with_columns(_norm_expr(c.similar_field).alias("__s"))
        blocks = (
            df.group_by(c.keys).agg(pl.col("row_id"), pl.col("__s"))
            if c.keys
            else df.select(pl.col("row_id").implode(), pl.col("__s").implode())
        )
        skipped = 0
        for ids, texts in zip(blocks["row_id"].to_list(), blocks["__s"].to_list(), strict=True):
            pairs = sorted(zip(ids, texts, strict=True))
            if len(pairs) > c.max_group_size:
                skipped += 1
                continue
            parent = list(range(len(pairs)))

            def find(i: int, parent: list[int] = parent) -> int:
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    if fuzz.ratio(pairs[i][1], pairs[j][1]) >= c.min_score:
                        a, b = find(i), find(j)
                        if a != b:
                            parent[max(a, b)] = min(a, b)
            clusters: dict[int, list[int]] = {}
            for i, (rid, _) in enumerate(pairs):
                clusters.setdefault(find(i), []).append(rid)
            groups += [sorted(v) for v in clusters.values() if len(v) > 1]
        groups.sort(key=lambda ids: ids[0])
        if skipped:
            meta.setdefault("warnings", []).append(
                f"{skipped} group(s) larger than {c.max_group_size} rows were not compared."
            )
    evidence = [
        _rows_evidence(
            ds, ds.frame.filter(pl.col("row_id").is_in(ids)), shown_cols, f"duplicate group {n + 1}"
        )
        for n, ids in enumerate(groups[:MAX_EVIDENCE_GROUPS])
    ]
    rows = sum(len(g) for g in groups)
    meta["duplicate_rows"] = rows
    return _done(
        len(groups),
        f"No duplicates on {', '.join(shown_cols)} ({c.match}).",
        f"{len(groups)} duplicate group(s), {rows} row(s), on {', '.join(shown_cols)} ({c.match}).",
        evidence,
        meta,
    )


def _iban_ok(value: str) -> bool:
    s = value[4:] + value[:4]
    digits = "".join(str(int(ch, 36)) for ch in s)
    return int(digits) % 97 == 1


def _field_format(c: FieldFormatCheck, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
    ds = _need(ctx, c.dataset)
    _need_column(ds, c.field)
    df = _filter(ds.frame, c)
    col = pl.col(c.field)
    ok = col.str.contains(_FORMATS[c.format])
    if c.length is not None:
        ok = ok & (col.str.len_chars() == c.length)
    blank_bad = c.required or c.format == "not_empty"
    bad = pl.when(col.is_null()).then(pl.lit(blank_bad)).otherwise(~ok)
    hits = df.filter(bad)
    if c.format == "iban":
        good_shape = df.filter(~bad & col.is_not_null())
        failed_checksum = [
            r for r, v in good_shape.select("row_id", c.field).iter_rows() if not _iban_ok(v)
        ]
        if failed_checksum:
            hits = pl.concat([hits, df.filter(pl.col("row_id").is_in(failed_checksum))]).unique(
                "row_id"
            )
    desc = c.format + (f" ({c.length} characters)" if c.length else "")
    evidence = [_rows_evidence(ds, hits, [c.field], f"{c.field} not {desc}")] if hits.height else []
    return _done(
        hits.height,
        f"All {df.height} value(s) of {c.field} match {desc}.",
        f"{hits.height} value(s) of {c.field} do not match {desc}.",
        evidence,
        meta,
    )


def _date_rule(c: DateRuleCheck, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
    ds = _need(ctx, c.dataset)
    _need_column(ds, c.field)
    if c.other_field:
        _need_column(ds, c.other_field)
    df = _filter(ds.frame, c).filter(pl.col(c.field).is_not_null())
    col = pl.col(c.field)
    shown = [c.field, *([c.other_field] if c.other_field else [])]
    if c.rule == "within_period":
        # Literal period, else the review's tax period (1.2.0), else the dataset period.
        p_start, p_end = ctx.period or (ds.period_start, ds.period_end)
        start, end = c.period_start or p_start, c.period_end or p_end
        if start is None or end is None:
            raise DataCheckError("Set the dataset period or the check's period_start/period_end.")
        meta["period"] = [start.isoformat(), end.isoformat()]
        hits, what = df.filter((col < start) | (col > end)), f"outside {start} – {end}"
    elif c.rule == "not_weekend":
        days = [_WEEKDAYS[d] for d in c.weekend_days or []]
        hits, what = (
            df.filter(col.dt.weekday().is_in(days)),
            f"on {', '.join(c.weekend_days or [])}",
        )
    elif c.rule == "not_future":
        meta["as_of"] = ctx.as_of.isoformat()
        hits, what = df.filter(col > ctx.as_of), f"after {ctx.as_of}"
    elif c.rule == "max_days_from":
        assert c.other_field and c.max_days is not None
        gap = (col - pl.col(c.other_field)).dt.total_days().abs()
        hits = df.filter(gap.fill_null(0) > c.max_days)
        what = f"more than {c.max_days} days from {c.other_field}"
    else:
        assert c.other_field
        hits = df.filter((col > pl.col(c.other_field)).fill_null(False))
        what = f"after {c.other_field}"
    evidence = [_rows_evidence(ds, hits, shown, f"{c.field} {what}")] if hits.height else []
    return _done(
        hits.height,
        f"No {c.field} values {what} ({df.height} checked).",
        f"{hits.height} row(s) with {c.field} {what}.",
        evidence,
        meta,
    )


def _aggregate(a: Aggregate, ctx: DataContext) -> tuple[LoadedDataset, pl.DataFrame, Decimal]:
    ds = _need(ctx, a.dataset)
    if a.field:
        _need_column(ds, a.field)
    df = _filter(ds.frame, a)
    value = (
        Decimal(df.height) if a.aggregate == "count" else _sum(df, a.field or "", a.use_absolute)
    )
    return ds, df, value


def _ratio(c: RatioCheck, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
    nds, ndf, num = _aggregate(c.numerator, ctx)
    dds, ddf, den = _aggregate(c.denominator, ctx)
    lo = _ref(c.min, ctx, meta) if c.min else None
    hi = _ref(c.max, ctx, meta) if c.max else None
    meta.update({"numerator": str(num), "denominator": str(den)})
    if den == 0:
        meta["exception_count"] = 0
        return DataEvaluation(
            CheckOutcome.NEEDS_HUMAN_REVIEW,
            True,
            "The denominator is zero; review manually.",
            [],
            meta,
        )
    ratio = num / den
    shown = ratio.quantize(Decimal("0.000001"))
    meta["ratio"] = str(shown)
    bounds = f"[{lo if lo is not None else '−∞'}, {hi if hi is not None else '∞'}]"
    if (lo is not None and ratio < lo) or (hi is not None and ratio > hi):
        detail = {"numerator": num, "denominator": den, "ratio": shown, "min": lo, "max": hi}
        evidence = [
            _rows_evidence(nds, ndf, [c.numerator.field or "row_id"], "numerator rows", detail, 20),
            _rows_evidence(
                dds, ddf, [c.denominator.field or "row_id"], "denominator rows", detail, 20
            ),
        ]
        return _done(1, "", f"Ratio {shown} is outside {bounds}.", evidence, meta)
    return _done(0, f"Ratio {shown} is within {bounds}.", "", [], meta)


def evaluate_data(config: Any, ctx: DataContext) -> DataEvaluation:
    from app.engine import tax_checks

    meta: dict[str, Any] = {}
    try:
        if isinstance(config, tax_checks.TAX_CHECK_TYPES):
            ev = tax_checks.evaluate(config, ctx, meta)
        elif isinstance(config, ReconcileCheck):
            ev = _reconcile(config, ctx, meta)
        elif isinstance(config, ThresholdCheck):
            ev = _threshold(config, ctx, meta)
        elif isinstance(config, DuplicateCheck):
            ev = _duplicate(config, ctx, meta)
        elif isinstance(config, FieldFormatCheck):
            ev = _field_format(config, ctx, meta)
        elif isinstance(config, DateRuleCheck):
            ev = _date_rule(config, ctx, meta)
        else:
            ev = _ratio(config, ctx, meta)
    except InputMissing as exc:
        return DataEvaluation(CheckOutcome.NOT_APPLICABLE, False, str(exc), [], meta)
    except DataCheckError as exc:
        return DataEvaluation(CheckOutcome.NOT_APPLICABLE, True, str(exc), [], meta)
    warnings = ev.meta.get("warnings") or []
    if warnings:
        ev.message = " ".join([*warnings, ev.message]).strip()
    return ev
