"""Audit workpaper calculations (Phase D): lead schedules and materiality.

Rule keys (all from the engagement's audit rule pack):

- ``<p>.amount_decimals`` / ``<p>.rounding_mode``  as for every workpaper
- ``<p>.materiality_share_ranges``  guidance ranges per benchmark type (overall
  materiality as a share of the benchmark) and for ``performance`` and ``trivial``
  (as shares of overall materiality)

Materiality percentages are the engagement team's judgement and are entered as
inputs; the pack only says whether a chosen percentage sits inside a guidance range.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

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

LEAD_KEY = re.compile(r"^lead_([a-z0-9]{1,20})_(cy|py)$")
SHARE = Decimal("0.0001")
BENCHMARKS = ("profit_before_tax", "revenue", "total_assets", "equity", "expenses", "other")
WITHIN, OUTSIDE, UNKNOWN = "within", "outside", "not_determinable"


def share(num: Decimal, den: Decimal) -> Decimal:
    return (num / den).quantize(SHARE, rounding=ROUND_HALF_UP)


@formula("lead_schedule", ("current_year", "prior_year"))
def lead_schedule(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    r = Rounder(rules, p)
    rk = [f"{p}.amount_decimals", f"{p}.rounding_mode"]
    leads: dict[str, dict[str, Decimal]] = {}
    for ln in inp.lines:
        m = LEAD_KEY.match(ln.key)
        if m is None or ln.amount is None:
            continue
        expected = "current_year" if m.group(2) == "cy" else "prior_year"
        if ln.category != expected:
            raise CalcError(
                f"Input '{ln.key}' must be in the {expected.replace('_', ' ')} category."
            )
        leads.setdefault(m.group(1), {})[m.group(2)] = ln.amount
    if not leads:
        raise CalcError("Add lead schedule balances (lead_<code>_cy and lead_<code>_py).")
    out: list[Output] = []
    tot_cy = tot_py = ZERO
    for code in sorted(leads):
        cy, py = r(leads[code].get("cy", ZERO)), r(leads[code].get("py", ZERO))
        tot_cy += cy
        tot_py += py
        mv = cy - py
        out.append(
            Output(
                f"lead_{code}_movement",
                f"{code.upper()} movement",
                "lead",
                "audit.lead_movement",
                amount=mv,
                steps=[Step("Current year − prior year", f"{fmt(cy)} − {fmt(py)}", fmt(mv))],
                rule_keys=rk,
            )
        )
        if py == ZERO:
            ch_steps = [Step("Change share", "prior year is zero", UNKNOWN)]
            change = UNKNOWN
        else:
            change = fmt(share(mv, abs(py)))
            ch_steps = [Step("Movement ÷ |prior year|", f"{fmt(mv)} ÷ {fmt(abs(py))}", change)]
        out.append(
            Output(
                f"lead_{code}_change",
                f"{code.upper()} change",
                "lead",
                "audit.lead_change",
                value=change,
                steps=ch_steps,
            )
        )
    for key, label, v in (
        ("total_cy", "Net current year", tot_cy),
        ("total_py", "Net prior year", tot_py),
    ):
        out.append(
            Output(
                key,
                label,
                "total",
                "audit.lead_total",
                amount=v,
                steps=[Step("Sum of lead schedules", f"{len(leads)} schedules", fmt(v))],
                rule_keys=rk,
            )
        )
    return out


def _range(rules: RuleSource, p: str, name: str) -> tuple[Decimal, Decimal] | None:
    ranges = rules.get(f"{p}.materiality_share_ranges")
    band = ranges.get(name) if isinstance(ranges, dict) else None
    if band is None:
        return None
    return Decimal(str(band["low"])), Decimal(str(band["high"]))


def _range_check(
    key: str, label: str, chosen: Decimal, band: tuple[Decimal, Decimal] | None, p: str
) -> Output:
    if band is None:
        result = UNKNOWN
        steps = [Step("Guidance range", "the pack has no range for this benchmark", result)]
    else:
        lo, hi = band
        result = WITHIN if lo <= chosen <= hi else OUTSIDE
        steps = [
            Step("Chosen share within guidance", f"{fmt(lo)} ≤ {fmt(chosen)} ≤ {fmt(hi)}", result)
        ]
    return Output(
        key,
        label,
        "check",
        "audit.materiality_range",
        value=result,
        steps=steps,
        rule_keys=[f"{p}.materiality_share_ranges"],
    )


def _pct(inp: Inputs, key: str) -> Decimal:
    v = inp.amount(key, required=True)
    if not ZERO < v <= 1:
        raise CalcError(f"'{key}' must be a share above 0 and at most 1 (e.g. 0.05 for 5%).")
    return v


@formula("materiality")
def materiality(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    r = Rounder(rules, p)
    rk = [f"{p}.amount_decimals", f"{p}.rounding_mode"]
    btype = next((ln.value for ln in inp.lines if ln.key == "benchmark_type"), None)
    if btype not in BENCHMARKS:
        raise CalcError(f"Set 'benchmark_type' to one of: {', '.join(BENCHMARKS)}.")
    rationale = next((ln.value for ln in inp.lines if ln.key == "rationale"), None)
    if not rationale or not rationale.strip():
        raise CalcError("Record the rationale for the benchmark and percentages ('rationale').")
    bench = inp.amount("benchmark", required=True)
    if bench <= ZERO:
        raise CalcError("The benchmark amount must be above zero.")
    o_pct, p_pct, t_pct = (
        _pct(inp, "overall_pct"),
        _pct(inp, "performance_pct"),
        _pct(inp, "trivial_pct"),
    )
    overall = r(bench * o_pct)
    perf = r(overall * p_pct)
    trivial = r(overall * t_pct)
    return [
        Output(
            "overall",
            "Overall materiality",
            "materiality",
            "audit.materiality_overall",
            amount=overall,
            steps=[
                Step(
                    f"Benchmark ({btype.replace('_', ' ')}) × share",
                    f"{fmt(bench)} × {fmt(o_pct)}",
                    fmt(overall),
                ),
                Step("Rationale (engagement team)", rationale.strip(), ""),
            ],
            rule_keys=rk,
        ),
        Output(
            "performance",
            "Performance materiality",
            "materiality",
            "audit.materiality_performance",
            amount=perf,
            steps=[Step("Overall × share", f"{fmt(overall)} × {fmt(p_pct)}", fmt(perf))],
            rule_keys=rk,
        ),
        Output(
            "trivial",
            "Clearly trivial threshold",
            "materiality",
            "audit.materiality_trivial",
            amount=trivial,
            steps=[Step("Overall × share", f"{fmt(overall)} × {fmt(t_pct)}", fmt(trivial))],
            rule_keys=rk,
        ),
        _range_check(
            "check:overall", "Overall share within guidance", o_pct, _range(rules, p, btype), p
        ),
        _range_check(
            "check:performance",
            "Performance share within guidance",
            p_pct,
            _range(rules, p, "performance"),
            p,
        ),
        _range_check(
            "check:trivial", "Trivial share within guidance", t_pct, _range(rules, p, "trivial"), p
        ),
    ]
