"""Pillar Two / domestic minimum top-up tax: scope, jurisdictional ETR, safe harbours
and data readiness. A simplified model for preparing a review, not a GloBE return.

Inputs (per jurisdiction, the key ends in ``_<country>``, e.g. ``income_ae``):

- category ``globe_income``, ``covered_taxes``, ``payroll``, ``tangible_assets``
- category ``cbcr_revenue``, ``cbcr_pbt``, ``simplified_taxes`` (safe harbour data)
- category ``readiness``: a true/false flag per item code of ``<p>.p2_readiness_items``
- ``revenue_year_1`` .. ``revenue_year_N``: consolidated revenue, most recent first

Rule keys: ``<p>.p2_revenue_threshold``, ``<p>.p2_lookback_years``,
``<p>.p2_years_required``, ``<p>.p2_minimum_rate``, ``<p>.sbie_payroll_rate``,
``<p>.sbie_assets_rate``, ``<p>.etr_decimals``, ``<p>.sh_de_minimis_revenue``,
``<p>.sh_de_minimis_profit``, ``<p>.sh_simplified_etr_rate``, ``<p>.p2_readiness_items``,
plus ``<p>.amount_decimals`` / ``<p>.rounding_mode``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from app.calc import (
    ZERO,
    CalcError,
    Inputs,
    Output,
    Rounder,
    RuleSource,
    Step,
    fmt,
    formula,
)
from app.calc.corporate_tax import FAIL, PASS, UNKNOWN

JURISDICTION_CATEGORIES = (
    "globe_income",
    "covered_taxes",
    "payroll",
    "tangible_assets",
    "cbcr_revenue",
    "cbcr_pbt",
    "simplified_taxes",
)


def _jur(key: str) -> str:
    code = key.rsplit("_", 1)[-1]
    if "_" not in key or len(code) != 2 or not code.isalpha():
        raise CalcError(f"Input '{key}' must end in _ and a two-letter country code.")
    return code.upper()


def _scope(inp: Inputs, rules: RuleSource, p: str) -> Output:
    threshold = rules.decimal(f"{p}.p2_revenue_threshold")
    lookback = int(rules.decimal(f"{p}.p2_lookback_years"))
    needed = int(rules.decimal(f"{p}.p2_years_required"))
    given = [i for i in range(1, lookback + 1) if inp.has(f"revenue_year_{i}")]
    over = [i for i in given if inp.amount(f"revenue_year_{i}") >= threshold]
    steps = [
        Step(
            f"Year {i} revenue ≥ threshold",
            f"{fmt(inp.amount(f'revenue_year_{i}'))} ≥ {fmt(threshold)}",
            str(i in over),
        )
        for i in given
    ]
    if len(over) >= needed:
        result = "in_scope"
    elif len(over) + (lookback - len(given)) < needed:
        result = "not_in_scope"
    else:
        result = UNKNOWN
    steps.append(
        Step(
            f"Years at or above the threshold (of {lookback}; {needed} needed)",
            f"{len(over)} of {len(given)} entered",
            result,
        )
    )
    keys = [f"{p}.p2_revenue_threshold", f"{p}.p2_lookback_years", f"{p}.p2_years_required"]
    return Output(
        "scope", "Group in scope", "scope", "p2.scope", value=result, steps=steps, rule_keys=keys
    )


@formula("pillar_two", (*JURISDICTION_CATEGORIES, "readiness"))
def pillar_two(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    rnd = Rounder(rules, p)
    out = [_scope(inp, rules, p)]
    data: dict[str, dict[str, Decimal]] = {}
    for cat in JURISDICTION_CATEGORIES:
        for ln in inp.by_category(cat):
            assert ln.amount is not None
            jd = data.setdefault(_jur(ln.key), {})
            jd[cat] = jd.get(cat, ZERO) + ln.amount
    min_rate = rules.decimal(f"{p}.p2_minimum_rate")
    pay_rate = rules.decimal(f"{p}.sbie_payroll_rate")
    asset_rate = rules.decimal(f"{p}.sbie_assets_rate")
    etr_q = Decimal(1).scaleb(-int(rules.decimal(f"{p}.etr_decimals")))
    total_top_up = ZERO
    for j, d in sorted(data.items()):
        income, taxes = d.get("globe_income"), d.get("covered_taxes", ZERO)
        payroll, assets = d.get("payroll", ZERO), d.get("tangible_assets", ZERO)
        sbie = rnd(payroll * pay_rate + assets * asset_rate)
        out.append(
            Output(
                f"{j}:sbie",
                f"{j}: substance-based income exclusion",
                "jurisdiction",
                "p2.sbie",
                amount=sbie,
                steps=[
                    Step(
                        "Payroll × rate + tangible assets × rate",
                        f"{fmt(payroll)} × {fmt(pay_rate)} + {fmt(assets)} × {fmt(asset_rate)}",
                        fmt(sbie),
                    )
                ],
                rule_keys=[f"{p}.sbie_payroll_rate", f"{p}.sbie_assets_rate"],
            )
        )
        if income is not None:
            if income <= 0:
                etr_value, top_up = None, ZERO
                etr_steps = [Step("No GloBE income", f"income {fmt(income)} ≤ 0", "no top-up")]
            else:
                etr = (taxes / income).quantize(etr_q, rounding=ROUND_HALF_EVEN)
                pct = max(ZERO, min_rate - etr)
                excess = max(ZERO, income - sbie)
                top_up = rnd(pct * excess)
                etr_value = etr
                etr_steps = [
                    Step(
                        "ETR = covered taxes ÷ GloBE income",
                        f"{fmt(taxes)} ÷ {fmt(income)}",
                        fmt(etr),
                    ),
                    Step(
                        "Top-up % = max(0, minimum − ETR)",
                        f"max(0, {fmt(min_rate)} − {fmt(etr)})",
                        fmt(pct),
                    ),
                    Step(
                        "Excess profit = max(0, income − SBIE)",
                        f"max(0, {fmt(income)} − {fmt(sbie)})",
                        fmt(excess),
                    ),
                    Step(
                        "Top-up = top-up % × excess profit",
                        f"{fmt(pct)} × {fmt(excess)}",
                        fmt(top_up),
                    ),
                ]
            total_top_up += top_up
            out.append(
                Output(
                    f"{j}:etr",
                    f"{j}: effective tax rate",
                    "jurisdiction",
                    "p2.etr",
                    value=fmt(etr_value) if etr_value is not None else "n/a",
                    steps=etr_steps[:1],
                    rule_keys=[f"{p}.etr_decimals"],
                )
            )
            out.append(
                Output(
                    f"{j}:top_up",
                    f"{j}: top-up tax (simplified)",
                    "jurisdiction",
                    "p2.top_up",
                    amount=top_up,
                    steps=etr_steps,
                    rule_keys=[f"{p}.p2_minimum_rate", f"{p}.amount_decimals"],
                )
            )
        if "cbcr_revenue" in d or "cbcr_pbt" in d:
            out.append(_safe_harbour(j, d, sbie, rules, p))
    out.append(
        Output(
            "top_up_total",
            "Top-up tax, all jurisdictions (simplified)",
            "result",
            "p2.top_up_total",
            amount=total_top_up,
            steps=[
                Step(
                    "Sum of jurisdictions",
                    " + ".join(o.key for o in out if o.key.endswith(":top_up")) or "none",
                    fmt(total_top_up),
                )
            ],
        )
    )
    out += _readiness(inp, rules, p)
    return out


def _safe_harbour(
    j: str, d: dict[str, Decimal], sbie: Decimal, rules: RuleSource, p: str
) -> Output:
    rev, pbt = d.get("cbcr_revenue"), d.get("cbcr_pbt")
    taxes = d.get("simplified_taxes")
    dm_rev, dm_pbt = (
        rules.decimal(f"{p}.sh_de_minimis_revenue"),
        rules.decimal(f"{p}.sh_de_minimis_profit"),
    )
    sh_rate = rules.decimal(f"{p}.sh_simplified_etr_rate")
    steps: list[Step] = []
    tests: list[str] = []
    if rev is not None and pbt is not None:
        r = PASS if rev < dm_rev and pbt < dm_pbt else FAIL
        steps.append(
            Step(
                "De minimis: revenue < limit and profit < limit",
                f"{fmt(rev)} < {fmt(dm_rev)}; {fmt(pbt)} < {fmt(dm_pbt)}",
                r,
            )
        )
        tests.append(r)
    if pbt is not None and taxes is not None:
        if pbt <= 0:
            r = PASS
            steps.append(Step("Simplified ETR: no profit before tax", f"{fmt(pbt)} ≤ 0", r))
        else:
            r = PASS if taxes / pbt >= sh_rate else FAIL
            steps.append(
                Step(
                    "Simplified ETR ≥ transition rate",
                    f"{fmt(taxes)} ÷ {fmt(pbt)} ≥ {fmt(sh_rate)}",
                    r,
                )
            )
        tests.append(r)
    if pbt is not None:
        r = PASS if pbt <= sbie else FAIL
        steps.append(
            Step("Routine profits: profit before tax ≤ SBIE", f"{fmt(pbt)} ≤ {fmt(sbie)}", r)
        )
        tests.append(r)
    result = PASS if PASS in tests else (FAIL if tests else UNKNOWN)
    steps.append(Step("Any safe harbour met", ", ".join(tests) or "no data", result))
    return Output(
        f"{j}:safe_harbour",
        f"{j}: transitional safe harbour",
        "safe_harbour",
        "p2.safe_harbour",
        value=result,
        steps=steps,
        rule_keys=[
            f"{p}.sh_de_minimis_revenue",
            f"{p}.sh_de_minimis_profit",
            f"{p}.sh_simplified_etr_rate",
        ],
    )


def _readiness(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    items = [str(i) for i in rules.get(f"{p}.p2_readiness_items")]
    out: list[Output] = []
    ready = 0
    for code in items:
        f = inp.flag(f"ready_{code}")
        v = "ready" if f else ("not_ready" if f is False else UNKNOWN)
        ready += 1 if f else 0
        out.append(
            Output(
                f"readiness:{code}",
                f"Data ready: {code.replace('_', ' ')}",
                "readiness",
                "p2.readiness_item",
                value=v,
                steps=[Step("Preparer's assertion", f"ready_{code} = {v}", v)],
                rule_keys=[f"{p}.p2_readiness_items"],
            )
        )
    out.append(
        Output(
            "readiness",
            "Data readiness",
            "result",
            "p2.readiness",
            value=f"{ready}/{len(items)}",
            steps=[Step("Items ready", f"{ready} of {len(items)}", f"{ready}/{len(items)}")],
        )
    )
    return out
