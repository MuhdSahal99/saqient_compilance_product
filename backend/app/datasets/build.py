"""Turn a mapped, all-text table into a typed canonical dataset.

Rules (no silent changes to values):
- Amounts: optional thousands separators, a leading minus, a trailing minus or
  parentheses for negatives; at most 16 integer digits and 4 decimals. More
  decimals are an error, never rounded. Result: Decimal(20, 4).
- Dates: one declared format from a fixed list; Excel date-times are accepted.
- Currency: ISO 4217 letters; a missing currency takes the entity's functional
  currency, so every amount has one.
- Text: trimmed; empty becomes null; over 1000 characters is an error.
Any invalid value fails the build with the first errors listed by row id.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from app.datasets.schemas import SCHEMAS, CanonicalSchema
from app.models import DatasetKind

AMOUNT_DTYPE = pl.Decimal(20, 4)
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d")
MAX_TEXT = 1000
MAX_ERRORS_KEPT = 100
_AMOUNT_RE = r"^-?\d{1,16}(\.\d{1,4})?$"
_EXCEL_DT = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$"


@dataclass
class BuildOptions:
    default_currency: str
    date_format: str = "%Y-%m-%d"
    decimal_separator: str = "."


@dataclass
class BuildResult:
    frame: pl.DataFrame | None
    errors: list[dict[str, Any]]
    error_count: int
    derived_fields: list[str] = field(default_factory=list)
    totals: dict[str, str] = field(default_factory=dict)


def _amount_text(col: pl.Expr, decimal_separator: str) -> pl.Expr:
    s = col.str.strip_chars().str.replace_all(r"[\s ']", "")
    neg = s.str.starts_with("(") & s.str.ends_with(")") | s.str.ends_with("-")
    s = s.str.strip_chars("()").str.strip_chars_end("-")
    if decimal_separator == ",":
        s = s.str.replace_all(r"\.", "").str.replace_all(",", ".")
    else:
        s = s.str.replace_all(",", "")
    return pl.when(neg & ~s.str.starts_with("-")).then(pl.lit("-") + s).otherwise(s)


def build_canonical(
    kind: DatasetKind, raw: pl.DataFrame, mapping: dict[str, str], opts: BuildOptions
) -> BuildResult:
    schema: CanonicalSchema = SCHEMAS[kind]
    if opts.date_format not in DATE_FORMATS:
        raise ValueError("unsupported date format")
    df = raw.select([pl.col(src).alias(dst) for dst, src in mapping.items()]).with_row_index(
        "row_id", offset=1
    )
    df = df.with_columns(pl.col("row_id").cast(pl.Int64))
    exprs: list[pl.Expr] = [pl.col("row_id")]
    checks: list[tuple[str, pl.Expr, str]] = []  # (field, bad mask, message)

    for f in schema.fields:
        if f.name not in mapping:
            continue
        src = pl.col(f.name)
        blank = src.is_null() | (src.str.strip_chars() == "")
        if f.type == "amount":
            text = _amount_text(src, opts.decimal_separator)
            ok = text.str.contains(_AMOUNT_RE)
            checks.append((f.name, ~blank & ~ok, "not a valid amount (max 4 decimals)"))
            exprs.append(
                pl.when(blank)
                .then(None)
                .otherwise(text)
                .cast(AMOUNT_DTYPE, strict=False)
                .alias(f.name)
            )
        elif f.type == "date":
            s = src.str.strip_chars()
            is_excel = s.str.contains(_EXCEL_DT)
            parsed = (
                pl.when(is_excel)
                .then(s.str.slice(0, 10).str.strptime(pl.Date, "%Y-%m-%d", strict=False))
                .otherwise(s.str.strptime(pl.Date, opts.date_format, strict=False))
            )
            checks.append((f.name, ~blank & parsed.is_null(), "not a valid date"))
            exprs.append(parsed.alias(f.name))
        elif f.type == "currency":
            s = src.str.strip_chars().str.to_uppercase()
            checks.append((f.name, ~blank & ~s.str.contains(r"^[A-Z]{3}$"), "not an ISO 4217 code"))
            exprs.append(
                pl.when(blank).then(pl.lit(opts.default_currency)).otherwise(s).alias(f.name)
            )
        else:
            s = src.str.strip_chars()
            checks.append(
                (f.name, s.str.len_chars() > MAX_TEXT, f"longer than {MAX_TEXT} characters")
            )
            exprs.append(pl.when(blank).then(None).otherwise(s).alias(f.name))
        if f.required:
            checks.append((f.name, blank, "required value is empty"))

    flags = df.with_columns([mask.alias(f"__bad_{i}") for i, (_, mask, _) in enumerate(checks)])
    errors: list[dict[str, Any]] = []
    error_count = 0
    for i, (name, _, message) in enumerate(checks):
        bad = flags.filter(pl.col(f"__bad_{i}"))
        error_count += bad.height
        for row in (
            bad.select("row_id", pl.col(name).alias("value")).head(MAX_ERRORS_KEPT).iter_rows()
        ):
            errors.append(
                {
                    "row_id": row[0],
                    "column": mapping[name],
                    "field": name,
                    "message": message,
                    "value": (row[1] or "")[:80],
                }
            )
    if error_count:
        errors.sort(key=lambda e: (e["row_id"], e["field"]))
        return BuildResult(None, errors[:MAX_ERRORS_KEPT], error_count)

    out = df.select(exprs)
    if "currency" not in out.columns:
        out = out.with_columns(pl.lit(opts.default_currency).alias("currency"))
    out, derived = _derive(kind, out)
    out = out.sort("row_id")
    totals = {
        c: str(out[c].fill_null(0).sum()) for c in out.columns if out.schema[c] == AMOUNT_DTYPE
    }
    return BuildResult(out, [], 0, derived, totals)


def _zero() -> pl.Expr:
    return pl.lit(0).cast(AMOUNT_DTYPE)


def _derive(kind: DatasetKind, df: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Fill the alternative representation of amounts so checks can rely on both."""
    derived: list[str] = []
    cols = set(df.columns)
    if {"debit", "credit"} <= cols:
        df = df.with_columns(
            pl.col("debit").fill_null(_zero()), pl.col("credit").fill_null(_zero())
        )
    if kind in (DatasetKind.GENERAL_LEDGER, DatasetKind.BANK_STATEMENT):
        # Ledger: amount = debit - credit. Bank: amount = credit (money in) - debit (money out).
        sign = 1 if kind is DatasetKind.GENERAL_LEDGER else -1
        if "amount" not in cols and {"debit", "credit"} <= cols:
            expr = (
                pl.col("debit") - pl.col("credit")
                if sign == 1
                else pl.col("credit") - pl.col("debit")
            )
            df = df.with_columns(expr.cast(AMOUNT_DTYPE).alias("amount"))
            derived.append("amount")
        elif "amount" in cols and not {"debit", "credit"} & cols:
            pos = pl.when(pl.col("amount") > 0).then(pl.col("amount")).otherwise(_zero())
            neg = pl.when(pl.col("amount") < 0).then(-pl.col("amount")).otherwise(_zero())
            df = df.with_columns(
                (pos if sign == 1 else neg).cast(AMOUNT_DTYPE).alias("debit"),
                (neg if sign == 1 else pos).cast(AMOUNT_DTYPE).alias("credit"),
            )
            derived += ["debit", "credit"]
    if kind is DatasetKind.TRIAL_BALANCE and "balance" not in cols:
        df = df.with_columns(
            (pl.col("debit") - pl.col("credit")).cast(AMOUNT_DTYPE).alias("balance")
        )
        derived.append("balance")
    return df, derived


def to_parquet(frame: pl.DataFrame) -> tuple[bytes, str]:
    buf = io.BytesIO()
    frame.write_parquet(buf, compression="zstd", statistics=True)
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def from_parquet(data: bytes) -> pl.DataFrame:
    return pl.read_parquet(io.BytesIO(data))
