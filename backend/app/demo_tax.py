"""Synthetic direct-tax rule rows (Phase C) for tests and the demo seed.

Every value is invented and deliberately differs from any published rate or
threshold. Rows are drafts with a TODO; only an admin with a source can verify a
rule, and SYNTHETIC packs cannot be verified at all.
"""

from __future__ import annotations

import json
from typing import Any

from app.demo_einvoice import SYNTHETIC_NOTE, SYNTHETIC_TODO

CT_RATE_BANDS = [
    {"lower": "0", "upper": "400000", "rate": "0"},
    {"lower": "400000", "upper": None, "rate": "0.12"},
]


def row(key: str, value_type: str, value: Any, title: str, unit: str = "") -> dict[str, Any]:
    raw = json.dumps(value) if value_type == "json" else str(value)
    return {
        "rule_key": key,
        "title": title,
        "value_type": value_type,
        "value": raw,
        "unit": unit,
        "effective_from": "2020-01-01",
        "effective_to": None,
        "source_url": None,
        "source_note": SYNTHETIC_NOTE,
        "todo": SYNTHETIC_TODO,
    }


def ct_rules(p: str = "syn.ct") -> list[dict[str, Any]]:
    return [
        row(f"{p}.amount_decimals", "integer", 2, "Amount decimals"),
        row(f"{p}.rounding_mode", "string", "half_up", "Rounding mode"),
        row(f"{p}.rate_bands", "json", CT_RATE_BANDS, "Corporate tax rate bands"),
        row(f"{p}.entertainment_deductible_share", "decimal", "0.40", "Entertainment share"),
        row(f"{p}.interest_ebitda_share", "decimal", "0.25", "Interest share of tax EBITDA"),
        row(f"{p}.interest_de_minimis", "decimal", "200000", "Interest de minimis", "currency"),
        row(f"{p}.loss_offset_cap_share", "decimal", "0.70", "Loss offset cap share"),
        row(f"{p}.sbr_revenue_threshold", "decimal", "2000000", "SBR revenue limit", "currency"),
        row(f"{p}.sbr_last_period_end", "date", "2026-12-31", "SBR last period end"),
        row(f"{p}.qfzp_de_minimis_share", "decimal", "0.04", "QFZP de minimis share"),
        row(f"{p}.qfzp_de_minimis_amount", "decimal", "4000000", "QFZP de minimis", "currency"),
        row(f"{p}.loss_transfer_min_ownership", "decimal", "0.80", "Loss transfer ownership"),
        row(f"{p}.tax_group_min_ownership", "decimal", "0.90", "Tax group ownership"),
        row(f"{p}.tp_master_file_entity_revenue", "decimal", "150000000", "MF entity", "currency"),
        row(f"{p}.tp_master_file_group_revenue", "decimal", "3000000000", "MF group", "currency"),
        row(f"{p}.tp_local_file_entity_revenue", "decimal", "150000000", "LF entity", "currency"),
        row(f"{p}.tp_local_file_group_revenue", "decimal", "3000000000", "LF group", "currency"),
        row(f"{p}.tp_disclosure_threshold", "decimal", "30000000", "TP disclosure", "currency"),
    ]


READINESS_ITEMS = ["entity_list", "cbcr_data", "deferred_tax", "covered_taxes"]


def p2_rules(p: str = "syn.p2") -> list[dict[str, Any]]:
    return [
        row(f"{p}.amount_decimals", "integer", 2, "Amount decimals"),
        row(f"{p}.rounding_mode", "string", "half_up", "Rounding mode"),
        row(f"{p}.p2_revenue_threshold", "decimal", "600000000", "Scope revenue", "currency"),
        row(f"{p}.p2_lookback_years", "integer", 4, "Scope look-back years"),
        row(f"{p}.p2_years_required", "integer", 2, "Years at or above the threshold"),
        row(f"{p}.p2_minimum_rate", "decimal", "0.14", "Minimum rate"),
        row(f"{p}.sbie_payroll_rate", "decimal", "0.06", "SBIE payroll rate"),
        row(f"{p}.sbie_assets_rate", "decimal", "0.05", "SBIE tangible assets rate"),
        row(f"{p}.etr_decimals", "integer", 4, "ETR decimals"),
        row(f"{p}.sh_de_minimis_revenue", "decimal", "8000000", "Safe harbour revenue", "currency"),
        row(f"{p}.sh_de_minimis_profit", "decimal", "800000", "Safe harbour profit", "currency"),
        row(f"{p}.sh_simplified_etr_rate", "decimal", "0.16", "Simplified ETR test rate"),
        row(f"{p}.p2_readiness_items", "json", READINESS_ITEMS, "Data readiness items"),
    ]


WHT_RATES = {"royalty": "0.12", "technical_services": "0.04", "rent": "0.04", "dividend": "0.04"}


def zakat_rules(p: str = "syn.zakat") -> list[dict[str, Any]]:
    return [
        row(f"{p}.amount_decimals", "integer", 2, "Amount decimals"),
        row(f"{p}.rounding_mode", "string", "half_up", "Rounding mode"),
        row(f"{p}.zakat_rate", "decimal", "0.03", "Zakat rate"),
        row(f"{p}.zakat_year_days", "integer", 365, "Days in a zakat year"),
        row(f"{p}.zakat_min_base_is_net_profit", "boolean", "true", "Minimum base"),
    ]


def wht_rules(p: str = "syn.wht") -> list[dict[str, Any]]:
    return [
        row(f"{p}.wht_rates", "json", WHT_RATES, "Withholding rates by payment type"),
        row(f"{p}.resident_country", "string", "SA", "Resident country"),
        row(f"{p}.tolerance", "decimal", "1.00", "Shortfall tolerance", "currency"),
    ]


MATERIALITY_RANGES = {
    "profit_before_tax": {"low": "0.04", "high": "0.09"},
    "revenue": {"low": "0.004", "high": "0.015"},
    "total_assets": {"low": "0.008", "high": "0.018"},
    "performance": {"low": "0.55", "high": "0.8"},
    "trivial": {"low": "0.02", "high": "0.06"},
}
BENFORD_BANDS = {"close": "0.005", "acceptable": "0.011", "marginal": "0.016"}


def audit_rules(p: str = "syn.audit") -> list[dict[str, Any]]:
    """Synthetic audit guidance: materiality ranges and journal entry test parameters."""
    return [
        row(f"{p}.amount_decimals", "integer", 2, "Amount decimals"),
        row(f"{p}.rounding_mode", "string", "half_up", "Rounding mode"),
        row(f"{p}.materiality_share_ranges", "json", MATERIALITY_RANGES, "Materiality guidance"),
        row(f"{p}.weekend_days", "json", [6, 7], "Weekend days (ISO weekday numbers)"),
        row(f"{p}.holidays", "json", ["2025-03-30", "2025-06-06", "2025-12-02"], "Holidays"),
        row(f"{p}.round_amount_multiple", "decimal", "5000", "Round amount multiple", "currency"),
        row(f"{p}.approval_limit", "decimal", "50000", "Journal approval limit", "currency"),
        row(f"{p}.below_limit_share", "decimal", "0.04", "Just below the limit (share)"),
        row(f"{p}.min_user_entries", "integer", 3, "Fewest entries for a usual poster"),
        row(f"{p}.benford_mad_bands", "json", BENFORD_BANDS, "Benford MAD conformity bands"),
        row(f"{p}.benford_min_population", "integer", 50, "Fewest amounts for Benford"),
    ]


def recon_rules(p: str = "syn.recon") -> list[dict[str, Any]]:
    """Synthetic reconciliation parameters (Phase E)."""
    return [
        row(f"{p}.amount_tolerance", "decimal", "0.00", "Matching amount tolerance", "currency"),
        row(f"{p}.date_window_days", "integer", 3, "Matching date window", "days"),
        row(f"{p}.ageing_buckets", "json", [30, 60, 90], "Ageing buckets (days)"),
        row(f"{p}.variance_abs", "decimal", "1000", "Variance needing explanation", "currency"),
        row(f"{p}.variance_pct", "decimal", "0.05", "Variance needing explanation (share)"),
        row(f"{p}.intercompany_abs", "decimal", "100", "Intercompany difference limit", "currency"),
        row(f"{p}.flux_abs", "decimal", "5000", "Flux needing explanation", "currency"),
        row(f"{p}.flux_pct", "decimal", "0.10", "Flux needing explanation (share)"),
    ]


SOD_CONFLICTS = [
    {
        "id": "SOD-01",
        "a": ["vendor_maintain"],
        "b": ["payment_release", "payment_run"],
        "description": "Maintain vendors and release payments (synthetic)",
    },
    {
        "id": "SOD-02",
        "a": ["journal_post"],
        "b": ["journal_approve"],
        "description": "Post and approve journals (synthetic)",
    },
    {
        "id": "SOD-03",
        "a": ["AP Clerk"],
        "b": ["Treasury Approver"],
        "description": "AP clerk role with treasury approver role (synthetic)",
    },
]


def sod_rules(p: str = "syn.sod") -> list[dict[str, Any]]:
    """Synthetic segregation-of-duties conflict matrix (Phase E)."""
    return [row(f"{p}.sod_conflicts", "json", SOD_CONFLICTS, "Conflict matrix")]


EXPENSE_LIMITS = {
    "meals": {"currency": "AED", "per_claim": "300", "receipt_over": "50"},
    "travel": {"currency": "AED", "per_claim": "5000", "receipt_over": "0"},
}


def ap_rules(p: str = "syn.ap") -> list[dict[str, Any]]:
    """Synthetic AP and expense analytics parameters (Phase E)."""
    return [
        row(
            f"{p}.dup_amount_tolerance", "decimal", "0.00", "Duplicate amount tolerance", "currency"
        ),
        row(f"{p}.dup_date_window_days", "integer", 30, "Duplicate date window", "days"),
        row(f"{p}.dup_name_similarity", "decimal", "90", "Vendor name similarity (0-100)"),
        row(f"{p}.dup_invoice_similarity", "decimal", "90", "Invoice number similarity (0-100)"),
        row(f"{p}.trn_countries", "json", ["AE"], "Countries where a vendor TRN is expected"),
        row(f"{p}.trn_min_amount", "decimal", "0", "Minimum payment for the TRN test", "currency"),
        row(f"{p}.dormant_days", "integer", 180, "Dormant vendor gap", "days"),
        row(f"{p}.qty_tolerance", "decimal", "0", "Three-way match quantity tolerance"),
        row(
            f"{p}.price_tolerance_pct", "decimal", "0.02", "Three-way match price tolerance (share)"
        ),
        row(f"{p}.expense_limits", "json", EXPENSE_LIMITS, "Expense policy limits"),
    ]


def rules() -> list[dict[str, Any]]:
    """All synthetic direct-tax, audit and assurance rules."""
    return [
        *ct_rules(),
        *p2_rules(),
        *zakat_rules(),
        *wht_rules(),
        *audit_rules(),
        *recon_rules(),
        *sod_rules(),
        *ap_rules(),
    ]
