"""Data checks (engine deterministic-1.1.0) on hand-built canonical frames.

Expected values are worked out by hand in the comments next to each assertion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from app.datasets.build import from_parquet, to_parquet
from app.datasets.schemas import SCHEMAS
from app.engine import CheckEvaluation, DocumentContext, evaluate, parse_config
from app.engine.data_checks import DataContext, LoadedDataset, evaluate_data
from app.engine.versions import ENGINE_VERSION, is_data_check, parse_check
from app.models import CheckOutcome, DatasetKind
from app.services.reviews import result_hash
from app.services.rule_packs import RuleNotFound
from tests.engine_golden import GOLDEN, golden_outputs

K = DatasetKind
DEC = pl.Decimal(20, 4)


def frame(kind: DatasetKind, rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Build a canonical frame: row_id from 1, Decimal(20,4) amounts, Date dates."""
    schema = SCHEMAS[kind]
    cols: dict[str, Any] = {"row_id": list(range(1, len(rows) + 1))}
    names = sorted({k for r in rows for k in r})
    for n in names:
        cols[n] = [r.get(n) for r in rows]
    df = pl.DataFrame(cols, strict=False)
    casts = []
    for n in names:
        f = schema.get(n)
        t = f.type if f else ("amount" if n in ("amount", "balance") else "text")
        if t == "amount":
            casts.append(pl.col(n).cast(pl.String).str.to_decimal(scale=4).cast(DEC))
        elif t == "date":
            casts.append(pl.col(n).cast(pl.String).str.to_date("%Y-%m-%d"))
    return df.with_columns(casts) if casts else df


@dataclass
class FakeRule:
    key: str
    value: Any
    verified: bool = False

    def warning(self) -> str | None:
        return None if self.verified else f"Unverified rule '{self.key}'."

    def snapshot(self) -> dict[str, Any]:
        return {"rule_key": self.key, "value": str(self.value), "verified": self.verified}


def ctx(
    datasets: dict[DatasetKind, pl.DataFrame],
    rules: dict[str, Any] | None = None,
    as_of: date = date(2025, 12, 31),
    period: tuple[date, date] | None = (date(2025, 1, 1), date(2025, 12, 31)),
) -> DataContext:
    rules = rules or {}

    def resolve(key: str) -> FakeRule:
        if key not in rules:
            raise RuleNotFound(f"No rule '{key}' effective on {as_of.isoformat()}.")
        return FakeRule(key, Decimal(rules[key]))

    loaded = {
        k: LoadedDataset(
            version_id=f"00000000-0000-0000-0000-00000000000{i}",
            version_number=1,
            kind=k,
            frame=df,
            period_start=period[0] if period else None,
            period_end=period[1] if period else None,
        )
        for i, (k, df) in enumerate(sorted(datasets.items(), key=lambda kv: kv[0].value))
    }
    return DataContext(datasets=loaded, resolve_rule=resolve, as_of=as_of)


def run(config: dict[str, Any], c: DataContext) -> Any:
    parsed = parse_check(config)
    assert is_data_check(parsed)
    return evaluate_data(parsed, c)  # type: ignore[arg-type]


GL = frame(
    K.GENERAL_LEDGER,
    [
        {
            "entry_id": "JE-1",
            "posting_date": "2025-01-05",
            "account_code": "1100",
            "amount": "100.00",
            "document_date": "2025-01-01",
            "currency": "AED",
        },
        {
            "entry_id": "JE-1",
            "posting_date": "2025-01-05",
            "account_code": "1100",
            "amount": "50.00",
            "document_date": "2025-01-05",
            "currency": "AED",
        },
        {
            "entry_id": "JE-2",
            "posting_date": "2025-01-03",
            "account_code": "4000",
            "amount": "-150.00",
            "document_date": "2024-11-01",
            "currency": "AED",
        },
        {
            "entry_id": "JE-3",
            "posting_date": "2026-02-01",
            "account_code": "6000",
            "amount": "-1500.00",
            "document_date": "2026-02-02",
            "currency": "AED",
        },
        {
            "entry_id": "JE-4",
            "posting_date": "2025-06-30",
            "account_code": "6000",
            "amount": "1500.00",
            "document_date": None,
            "currency": "AED",
        },
    ],
)
TB = frame(
    K.TRIAL_BALANCE,
    [
        {"account_code": "1100", "balance": "150.00", "currency": "AED"},
        {"account_code": "4000", "balance": "-149.00", "currency": "AED"},
        {"account_code": "5000", "balance": "10.00", "currency": "AED"},
        {"account_code": "6000", "balance": "0.00", "currency": "AED"},
    ],
)
PURCHASES = frame(
    K.PURCHASE_REGISTER,
    [
        {
            "invoice_number": "INV-1",
            "invoice_date": "2025-03-01",
            "supplier_name": "Synthetic Trading LLC",
            "supplier_trn": "100000000000003",
            "net_amount": "1000.00",
            "tax_amount": "50.00",
            "currency": "AED",
        },
        {
            "invoice_number": "INV-1",
            "invoice_date": "2025-03-01",
            "supplier_name": "Synthetic Trading L.L.C",
            "supplier_trn": "100000000000003",
            "net_amount": "1000.00",
            "tax_amount": "50.00",
            "currency": "AED",
        },
        {
            "invoice_number": "inv 1",
            "invoice_date": "2025-03-02",
            "supplier_name": "Other Supplies Co",
            "supplier_trn": "100000000000003",
            "net_amount": "1000.00",
            "tax_amount": "50.00",
            "currency": "aed",
        },
        {
            "invoice_number": "INV-9",
            "invoice_date": "2025-03-09",
            "supplier_name": "Synthetic Tradng LLC",
            "supplier_trn": "12345",
            "net_amount": "2000.00",
            "tax_amount": "0.00",
            "currency": "AED",
        },
        {
            "invoice_number": "INV-10",
            "invoice_date": "2025-03-10",
            "supplier_name": "No TRN Shop",
            "supplier_trn": None,
            "net_amount": "0.00",
            "tax_amount": "0.00",
            "currency": "AED",
        },
    ],
)


# ---------------------------------------------------------------- reconcile

RECONCILE = {
    "type": "reconcile",
    "left": {"dataset": "general_ledger", "group_by": ["account_code"], "sum": "amount"},
    "right": {"dataset": "trial_balance", "group_by": ["account_code"], "sum": "balance"},
    "tolerance_absolute": "0.50",
}


def test_reconcile_gl_to_tb_by_account() -> None:
    ev = run(RECONCILE, ctx({K.GENERAL_LEDGER: GL, K.TRIAL_BALANCE: TB}))
    # 1100: 100+50=150 vs 150 ok. 4000: -150 vs -149, diff -1 > 0.50.
    # 5000: 0 (missing in GL) vs 10, diff -10. 6000: -1500+1500=0 vs 0 ok.
    assert ev.outcome == CheckOutcome.EXCEPTIONS_FOUND and ev.needs_attention
    assert ev.meta == {"groups_compared": 4, "exception_count": 2}
    assert ev.message == "2 of 4 group(s) do not reconcile."
    gl4000, tb4000, gl5000, tb5000 = ev.evidence
    assert gl4000["dataset_kind"] == "general_ledger" and gl4000["row_ids"] == [3]
    assert tb4000["dataset_kind"] == "trial_balance" and tb4000["row_ids"] == [2]
    assert Decimal(gl4000["detail"]["difference"]) == Decimal("-1")
    assert gl4000["detail"]["group.account_code"] == "4000"
    assert gl5000["row_ids"] == [] and gl5000["row_count"] == 0
    assert tb5000["row_ids"] == [3]
    assert Decimal(tb5000["detail"]["difference"]) == Decimal("-10")


def test_reconcile_tolerances_and_missing_groups() -> None:
    c = ctx({K.GENERAL_LEDGER: GL, K.TRIAL_BALANCE: TB})
    # 1 absolute tolerance clears 4000 (|diff| = 1); 5000 still differs by 10.
    ev = run({**RECONCILE, "tolerance_absolute": "1"}, c)
    assert ev.meta["exception_count"] == 1
    # 1% of |-149| = 1.49 also clears 4000.
    ev = run({**RECONCILE, "tolerance_absolute": "0", "tolerance_percent": "1"}, c)
    assert ev.meta["exception_count"] == 1
    # A missing group is reported as missing rather than compared with zero.
    ev = run({**RECONCILE, "missing_as_zero": False}, c)
    assert ev.meta["exception_count"] == 2
    assert ev.evidence[2]["detail"]["reason"] == "missing on the left"
    assert ev.evidence[2]["detail"]["difference"] is None


def test_reconcile_totals_without_groups() -> None:
    ev = run(
        {
            "type": "reconcile",
            "left": {"dataset": "general_ledger", "sum": "amount"},
            "right": {"dataset": "trial_balance", "sum": "balance"},
        },
        ctx({K.GENERAL_LEDGER: GL, K.TRIAL_BALANCE: TB}),
    )
    # GL total 0; TB total 150-149+10+0 = 11.
    assert ev.outcome == CheckOutcome.EXCEPTIONS_FOUND
    assert Decimal(ev.evidence[0]["detail"]["difference"]) == Decimal("-11")


# ---------------------------------------------------------------- threshold


def test_threshold_rows_against_a_rule_value() -> None:
    config = {
        "type": "threshold",
        "dataset": "general_ledger",
        "field": "amount",
        "use_absolute": True,
        "flag_if": "gte",
        "value": {"rule": "demo.large_entry"},
    }
    ev = run(config, ctx({K.GENERAL_LEDGER: GL}, rules={"demo.large_entry": "1500"}))
    # |amount| >= 1500: rows 4 (-1500) and 5 (1500).
    assert ev.outcome == CheckOutcome.EXCEPTIONS_FOUND
    assert ev.evidence[0]["row_ids"] == [4, 5]
    assert ev.evidence[0]["columns"] == ["row_id", "amount", "currency"]
    assert ev.evidence[0]["rows"][0] == [4, "-1500.0000", "AED"]
    # The unverified rule is recorded and its warning leads the message.
    assert ev.message.startswith("Unverified rule 'demo.large_entry'.")
    assert ev.meta["rules"] == [
        {"rule_key": "demo.large_entry", "value": "1500", "verified": False}
    ]


def test_threshold_aggregates_and_filters() -> None:
    c = ctx({K.PURCHASE_REGISTER: PURCHASES})
    total = {
        "type": "threshold",
        "dataset": "purchase_register",
        "aggregate": "sum",
        "field": "net_amount",
        "flag_if": "gte",
        "value": {"value": "5000"},
    }
    ev = run(total, c)
    # 1000+1000+1000+2000+0 = 5000, which is >= 5000.
    assert ev.outcome == CheckOutcome.EXCEPTIONS_FOUND
    assert ev.meta["aggregate_value"] == "5000.0000"
    filtered = {**total, "where": [{"field": "tax_amount", "op": "gt", "value": "0"}]}
    ev = run(filtered, c)
    # Only rows with tax: 1000 * 3 = 3000.
    assert ev.outcome == CheckOutcome.NO_EXCEPTIONS and not ev.needs_attention
    assert ev.meta["aggregate_value"] == "3000.0000"
    count = {
        "type": "threshold",
        "dataset": "purchase_register",
        "aggregate": "count",
        "where": [{"field": "supplier_trn", "op": "is_null"}],
        "flag_if": "gt",
        "value": {"value": "0"},
    }
    ev = run(count, c)
    assert ev.outcome == CheckOutcome.EXCEPTIONS_FOUND and ev.evidence[0]["row_ids"] == [5]


# ---------------------------------------------------------------- duplicate


def test_duplicate_exact_normalised_and_similar() -> None:
    c = ctx({K.PURCHASE_REGISTER: PURCHASES})
    base = {
        "type": "duplicate",
        "dataset": "purchase_register",
        "keys": ["invoice_number", "supplier_trn"],
    }
    exact = run(base, c)
    assert exact.outcome == CheckOutcome.EXCEPTIONS_FOUND
    assert [e["row_ids"] for e in exact.evidence] == [[1, 2]]
    # "inv 1" normalises to "inv1", like "INV-1".
    norm = run({**base, "match": "normalised"}, c)
    assert [e["row_ids"] for e in norm.evidence] == [[1, 2, 3]]
    assert norm.meta["duplicate_rows"] == 3
    similar = run(
        {
            "type": "duplicate",
            "dataset": "purchase_register",
            "keys": ["supplier_trn"],
            "match": "similar",
            "similar_field": "supplier_name",
            "min_score": 90,
        },
        c,
    )
    # Same TRN 100000000000003: rows 1-2 normalise to the same name; row 3 differs.
    # Row 4 ("Synthetic Tradng LLC") is close to 1-2 but has another TRN.
    assert [e["row_ids"] for e in similar.evidence] == [[1, 2]]
    unblocked = run(
        {
            "type": "duplicate",
            "dataset": "purchase_register",
            "match": "similar",
            "similar_field": "supplier_name",
            "min_score": 90,
        },
        c,
    )
    # Without a blocking key, row 4 joins (ratio of synthetictradingllc/synthetictradngllc = 97).
    assert [e["row_ids"] for e in unblocked.evidence] == [[1, 2, 4]]


def test_no_duplicates() -> None:
    ev = run(
        {"type": "duplicate", "dataset": "general_ledger", "keys": ["entry_id", "amount"]},
        ctx({K.GENERAL_LEDGER: GL}),
    )
    assert ev.outcome == CheckOutcome.NO_EXCEPTIONS and ev.evidence == []


# ---------------------------------------------------------------- field format


def test_field_format_trn_and_currency() -> None:
    c = ctx({K.PURCHASE_REGISTER: PURCHASES})
    trn = {
        "type": "field_format",
        "dataset": "purchase_register",
        "field": "supplier_trn",
        "format": "digits",
        "length": 15,
    }
    ev = run(trn, c)
    # Row 4 "12345" is too short; row 5 is blank but not required.
    assert ev.evidence[0]["row_ids"] == [4]
    ev = run({**trn, "required": True}, c)
    assert ev.evidence[0]["row_ids"] == [4, 5]
    cur = run(
        {
            "type": "field_format",
            "dataset": "purchase_register",
            "field": "currency",
            "format": "currency_code",
        },
        c,
    )
    assert cur.evidence[0]["row_ids"] == [3]  # "aed"


def test_field_format_iban_checksum() -> None:
    bank = frame(
        K.BANK_STATEMENT,
        [
            {
                "transaction_date": "2025-01-02",
                "amount": "1.00",
                "reference": "GB82WEST12345698765432",
            },
            {
                "transaction_date": "2025-01-02",
                "amount": "1.00",
                "reference": "GB82WEST12345698765431",
            },
            {"transaction_date": "2025-01-02", "amount": "1.00", "reference": "not an iban"},
        ],
    )
    ev = run(
        {
            "type": "field_format",
            "dataset": "bank_statement",
            "field": "reference",
            "format": "iban",
        },
        ctx({K.BANK_STATEMENT: bank}),
    )
    # Row 1 is the published example IBAN; row 2 fails mod-97; row 3 fails the shape.
    assert ev.evidence[0]["row_ids"] == [2, 3]


# ---------------------------------------------------------------- date rules


def test_date_rules() -> None:
    c = ctx({K.GENERAL_LEDGER: GL}, as_of=date(2025, 12, 31))
    base = {"type": "date_rule", "dataset": "general_ledger", "field": "posting_date"}
    period = run({**base, "rule": "within_period"}, c)
    assert period.evidence[0]["row_ids"] == [4]  # 2026-02-01
    assert period.meta["period"] == ["2025-01-01", "2025-12-31"]
    explicit = run(
        {**base, "rule": "within_period", "period_start": "2025-01-04", "period_end": "2025-12-31"},
        c,
    )
    assert explicit.evidence[0]["row_ids"] == [3, 4]  # 2025-01-03 and 2026-02-01
    # 2025-01-03 is a Friday.
    weekend = run({**base, "rule": "not_weekend", "weekend_days": ["fri", "sat"]}, c)
    assert weekend.evidence[0]["row_ids"] == [3]
    weekend2 = run({**base, "rule": "not_weekend", "weekend_days": ["sat", "sun"]}, c)
    # 2025-01-05 (rows 1, 2) and 2026-02-01 (row 4) are Sundays.
    assert weekend2.evidence[0]["row_ids"] == [1, 2, 4]
    future = run({**base, "rule": "not_future"}, c)
    assert future.evidence[0]["row_ids"] == [4]
    gap = run({**base, "rule": "max_days_from", "other_field": "document_date", "max_days": 30}, c)
    # Row 3: 2025-01-03 vs 2024-11-01 = 63 days; row 5 has no document date.
    assert gap.evidence[0]["row_ids"] == [3]
    before = run({**base, "rule": "not_after_field", "other_field": "document_date"}, c)
    # Posting after the document date: rows 1 (01-05 > 01-01) and 3.
    assert before.evidence[0]["row_ids"] == [1, 3]


def test_within_period_needs_a_period() -> None:
    ev = run(
        {
            "type": "date_rule",
            "dataset": "general_ledger",
            "field": "posting_date",
            "rule": "within_period",
        },
        ctx({K.GENERAL_LEDGER: GL}, period=None),
    )
    assert ev.outcome == CheckOutcome.NOT_APPLICABLE and ev.needs_attention


# ---------------------------------------------------------------- ratio


def test_ratio_effective_tax_rate() -> None:
    c = ctx({K.PURCHASE_REGISTER: PURCHASES}, rules={"demo.rate": "0.05"})
    config = {
        "type": "ratio",
        "numerator": {"dataset": "purchase_register", "field": "tax_amount"},
        "denominator": {
            "dataset": "purchase_register",
            "field": "net_amount",
            "where": [{"field": "tax_amount", "op": "gt", "value": "0"}],
        },
        "min": {"value": "0.049"},
        "max": {"rule": "demo.rate"},
    }
    ev = run(config, c)
    # 150 / 3000 = 0.05, within [0.049, 0.05].
    assert ev.outcome == CheckOutcome.NO_EXCEPTIONS
    assert (ev.meta["numerator"], ev.meta["denominator"]) == ("150.0000", "3000.0000")
    unfiltered = {**config, "denominator": {"dataset": "purchase_register", "field": "net_amount"}}
    ev = run(unfiltered, c)
    # 150 / 5000 = 0.03 < 0.049.
    assert ev.outcome == CheckOutcome.EXCEPTIONS_FOUND
    zero = {
        **config,
        "denominator": {
            "dataset": "purchase_register",
            "field": "net_amount",
            "where": [{"field": "invoice_number", "op": "eq", "value": "INV-10"}],
        },
    }
    assert run(zero, c).outcome == CheckOutcome.NEEDS_HUMAN_REVIEW


# ---------------------------------------------------------------- inputs and validation


def test_missing_rule_dataset_or_column_is_not_applicable() -> None:
    threshold = {
        "type": "threshold",
        "dataset": "general_ledger",
        "field": "amount",
        "flag_if": "gt",
        "value": {"rule": "demo.missing"},
    }
    ev = run(threshold, ctx({K.GENERAL_LEDGER: GL}))
    assert ev.outcome == CheckOutcome.NOT_APPLICABLE and "demo.missing" in ev.message
    ev = run(threshold, ctx({}))
    assert ev.outcome == CheckOutcome.NOT_APPLICABLE and "general ledger" in ev.message
    ev = run(
        {
            "type": "field_format",
            "dataset": "general_ledger",
            "field": "reference",
            "format": "alphanumeric",
        },
        ctx({K.GENERAL_LEDGER: GL}),
    )
    assert ev.outcome == CheckOutcome.NOT_APPLICABLE and "not mapped" in ev.message


@pytest.mark.parametrize(
    "config",
    [
        {
            "type": "threshold",
            "dataset": "general_ledger",
            "field": "nope",
            "flag_if": "gt",
            "value": {"value": "1"},
        },
        {
            "type": "threshold",
            "dataset": "general_ledger",
            "field": "description",
            "flag_if": "gt",
            "value": {"value": "1"},
        },
        {
            "type": "threshold",
            "dataset": "general_ledger",
            "field": "amount",
            "flag_if": "gt",
            "value": {"value": "1", "rule": "x.y"},
        },
        {
            "type": "date_rule",
            "dataset": "general_ledger",
            "field": "posting_date",
            "rule": "not_weekend",
        },
        {"type": "duplicate", "dataset": "general_ledger"},
        {
            "type": "field_format",
            "dataset": "general_ledger",
            "field": "account_code",
            "format": "regex",
            "pattern": ".*",
        },
        {
            "type": "reconcile",
            "left": {"dataset": "general_ledger", "sum": "amount", "group_by": ["account_code"]},
            "right": {"dataset": "trial_balance", "sum": "balance"},
        },
        {
            "type": "threshold",
            "dataset": "general_ledger",
            "field": "amount",
            "flag_if": "gt",
            "value": {"value": "1"},
            "where": [{"field": "posting_date", "op": "gt", "value": "not-a-date"}],
        },
    ],
)
def test_invalid_configs_are_rejected(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        parse_check(config)


def test_engine_versions() -> None:
    threshold = {
        "type": "threshold",
        "dataset": "general_ledger",
        "field": "amount",
        "flag_if": "gt",
        "value": {"value": "1"},
    }
    assert ENGINE_VERSION == "deterministic-1.4.0"
    with pytest.raises(ValidationError):
        parse_check(threshold, "deterministic-1.0.0")
    # 1.1.0 still parses its own data checks, but not the 1.2.0 ones.
    assert parse_check(threshold, "deterministic-1.1.0") == parse_check(threshold)
    rc = {"type": "reverse_charge"}
    parse_check(rc)
    with pytest.raises(ValidationError):
        parse_check(rc, "deterministic-1.1.0")
    assert parse_check(rc, "deterministic-1.2.0") == parse_check(rc)
    # 1.3.0 adds the withholding check; 1.2.0 does not accept it.
    wht = {
        "type": "wht_rates",
        "rates_rule": "syn.wht.wht_rates",
        "resident_country_rule": "syn.wht.resident_country",
        "tolerance_rule": "syn.wht.tolerance",
    }
    parse_check(wht)
    with pytest.raises(ValidationError):
        parse_check(wht, "deterministic-1.2.0")
    assert parse_check(wht, "deterministic-1.3.0") == parse_check(wht)
    # 1.4.0 adds journal entry tests; 1.3.0 does not accept them.
    je = {"type": "journal_entry_test", "test": "weekend", "rules_prefix": "syn.audit"}
    parse_check(je)
    with pytest.raises(ValidationError):
        parse_check(je, "deterministic-1.3.0")
    with pytest.raises(ValueError, match="Unknown engine version"):
        parse_check(threshold, "deterministic-9.9.9")
    text = {"type": "required_text", "phrases": ["retention"]}
    assert parse_check(text, "deterministic-1.0.0") == parse_check(text) == parse_config(text)


def test_text_checks_are_unchanged_from_1_0_0() -> None:
    """The 1.0.0 text-check outputs are frozen; 1.1.0 must reproduce them exactly."""
    assert golden_outputs() == json.loads(GOLDEN.read_text())


# ---------------------------------------------------------------- reproducibility

ALL_CONFIGS = [
    RECONCILE,
    {
        "type": "threshold",
        "dataset": "general_ledger",
        "field": "amount",
        "use_absolute": True,
        "flag_if": "gte",
        "value": {"rule": "demo.large_entry"},
    },
    {
        "type": "duplicate",
        "dataset": "purchase_register",
        "keys": ["supplier_trn"],
        "match": "similar",
        "similar_field": "supplier_name",
    },
    {
        "type": "duplicate",
        "dataset": "purchase_register",
        "keys": ["invoice_number"],
        "match": "normalised",
    },
    {
        "type": "field_format",
        "dataset": "purchase_register",
        "field": "supplier_trn",
        "format": "digits",
        "length": 15,
        "required": True,
    },
    {
        "type": "date_rule",
        "dataset": "general_ledger",
        "field": "posting_date",
        "rule": "not_weekend",
        "weekend_days": ["sat", "sun"],
    },
    {
        "type": "ratio",
        "numerator": {"dataset": "purchase_register", "field": "tax_amount"},
        "denominator": {"dataset": "purchase_register", "field": "net_amount"},
        "max": {"value": "0.05"},
    },
]


def _hashes(datasets: dict[DatasetKind, pl.DataFrame]) -> list[str]:
    c = ctx(datasets, rules={"demo.large_entry": "1000"})
    out = []
    for config in ALL_CONFIGS:
        ev = run(config, c)
        out.append(
            result_hash(
                CheckEvaluation(ev.outcome, ev.needs_attention, ev.message, ev.evidence), ev.meta
            )
        )
    return out


def test_every_check_is_reproducible_including_from_parquet() -> None:
    datasets = {K.GENERAL_LEDGER: GL, K.TRIAL_BALANCE: TB, K.PURCHASE_REGISTER: PURCHASES}
    first = _hashes(datasets)
    assert first == _hashes(datasets)
    reloaded = {k: from_parquet(to_parquet(df)[0]) for k, df in datasets.items()}
    assert first == _hashes(reloaded)
    # Row order in storage does not matter: checks sort by row id.
    shuffled = {k: df.sample(fraction=1.0, shuffle=True, seed=7) for k, df in datasets.items()}
    assert first == _hashes(shuffled)
    assert len(set(first)) == len(first)


def test_text_check_hash_is_stable() -> None:
    doc = DocumentContext("t", "", "policy", [], [])
    ev = evaluate(parse_config({"type": "manual"}), doc)
    assert result_hash(ev, {}) == result_hash(ev, {})
