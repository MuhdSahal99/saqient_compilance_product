"""Golden-file tests for every Phase C formula.

Each file in tests/golden/ names a formula, a rule prefix and cases with inputs and
hand-checked expected outputs (the ``worked`` lines show the arithmetic). Rules
come from the synthetic rows in app/demo_tax.py, parsed exactly as the rule pack
service parses them.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app import calc, demo_tax
from app.models import RuleValueType
from app.services.rule_packs import parse_value

GOLDEN = Path(__file__).parent / "golden"


class DictRules(calc.RuleSource):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.values = {
            r["rule_key"]: parse_value(RuleValueType(r["value_type"]), r["value"]) for r in rows
        }

    def get(self, key: str) -> Any:
        if key not in self.values:
            raise calc.CalcError(f"No rule '{key}'.")
        return self.values[key]


def inputs(case: dict[str, Any]) -> calc.Inputs:
    lines = [
        calc.InputLine(
            key=i["key"],
            category=i.get("category", "input"),
            amount=Decimal(i["amount"]) if "amount" in i else None,
            value=i.get("value"),
            label=i["key"],
        )
        for i in case["inputs"]
    ]
    pe = date.fromisoformat(case["period_end"]) if "period_end" in case else None
    return calc.Inputs(lines=lines, period_end=pe)


def _cases() -> list[Any]:
    out = []
    for path in sorted(GOLDEN.glob("*.json")):
        spec = json.loads(path.read_text())
        for case in spec["cases"]:
            out.append(pytest.param(spec, case, id=f"{path.stem}:{case['name']}"))
    return out


@pytest.mark.parametrize(("spec", "case"), _cases())
def test_golden(spec: dict[str, Any], case: dict[str, Any]) -> None:
    rules = DictRules(demo_tax.rules())
    if "error" in case:
        with pytest.raises(calc.CalcError, match=case["error"].replace("(", r"\(")):
            calc.run(spec["formula"], inputs(case), rules, spec["prefix"])
        return
    got = {o.key: o for o in calc.run(spec["formula"], inputs(case), rules, spec["prefix"])}
    for key, want in case["expected"].items():
        assert key in got, f"{key} not computed"
        o = got[key]
        if o.amount is not None:
            assert o.amount == Decimal(want), f"{key}: {o.amount} != {want}"
        else:
            assert o.value == want, f"{key}: {o.value} != {want}"
        assert o.steps, f"{key} has no explanation"


def test_every_formula_has_a_golden_file() -> None:
    covered = {json.loads(p.read_text())["formula"] for p in GOLDEN.glob("*.json")}
    assert set(calc.FORMULAS) <= covered


def test_band_tax_and_rounding_rules() -> None:
    rules = DictRules(demo_tax.rules())
    bands = DictRules(demo_tax.rules()).get("syn.ct.rate_bands")
    from app.calc.corporate_tax import band_tax
    from app.services.rule_schemas import typed

    tax, steps = band_tax(Decimal("400000.01"), typed("syn.ct.rate_bands", bands))
    assert tax == Decimal("0.0012") and len(steps) == 2
    r = calc.Rounder(rules, "syn.ct")
    assert r(Decimal("0.005")) == Decimal("0.01")
    bad = DictRules([*demo_tax.rules(), demo_tax.row("syn.ct.rounding_mode", "string", "up", "x")])
    with pytest.raises(calc.CalcError):
        calc.Rounder(bad, "syn.ct")
