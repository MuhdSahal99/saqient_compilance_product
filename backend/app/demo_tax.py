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
    ]


def rules() -> list[dict[str, Any]]:
    """All synthetic direct-tax rules."""
    return ct_rules()
