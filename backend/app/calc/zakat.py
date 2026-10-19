"""Zakat base workpaper: additions and deductions by category, minimum base, rate
and a period-length factor, all from the pack.

Inputs: ``adjusted_net_profit`` (required); lines in category ``zakat_addition``
(e.g. capital, reserves, provisions, long-term financing) and ``zakat_deduction``
(e.g. net fixed assets, qualifying investments). Which balances belong in which
category is the preparer's mapping, cited with evidence.

Rule keys: ``<p>.zakat_rate``, ``<p>.zakat_year_days``,
``<p>.zakat_min_base_is_net_profit`` (boolean), ``<p>.amount_decimals`` and
``<p>.rounding_mode``.
"""

from __future__ import annotations

from decimal import Decimal

from app.calc import ZERO, CalcError, Inputs, Output, Rounder, RuleSource, Step, fmt, formula


@formula("zakat", ("zakat_addition", "zakat_deduction"))
def zakat(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    rnd = Rounder(rules, p)
    if inp.period_start is None or inp.period_end is None:
        raise CalcError("The workpaper needs a period.")
    profit = inp.amount("adjusted_net_profit", required=True)
    adds = inp.by_category("zakat_addition")
    deds = inp.by_category("zakat_deduction")
    add_total = sum((ln.amount or ZERO for ln in adds), ZERO)
    ded_total = sum((ln.amount or ZERO for ln in deds), ZERO)
    base = add_total - ded_total
    use_min = bool(rules.get(f"{p}.zakat_min_base_is_net_profit"))
    floor_used = use_min and profit > base
    chosen = profit if floor_used else base
    base_used = max(chosen, ZERO)
    rate = rules.decimal(f"{p}.zakat_rate")
    year_days = rules.decimal(f"{p}.zakat_year_days")
    days = Decimal((inp.period_end - inp.period_start).days + 1)
    factor_expr = f"{fmt(days)} ÷ {fmt(year_days)}"
    zakat_due = rnd(base_used * rate * days / year_days)
    return [
        Output(
            "additions",
            "Additions to the zakat base",
            "base",
            "zakat.additions",
            amount=add_total,
            steps=[
                Step(
                    "Sum of additions",
                    " + ".join(fmt(ln.amount or ZERO) for ln in adds) or "0",
                    fmt(add_total),
                )
            ],
        ),
        Output(
            "deductions",
            "Deductions from the zakat base",
            "base",
            "zakat.deductions",
            amount=ded_total,
            steps=[
                Step(
                    "Sum of deductions",
                    " + ".join(fmt(ln.amount or ZERO) for ln in deds) or "0",
                    fmt(ded_total),
                )
            ],
        ),
        Output(
            "base",
            "Zakat base before the minimum",
            "base",
            "zakat.base",
            amount=base,
            steps=[
                Step("Additions − deductions", f"{fmt(add_total)} − {fmt(ded_total)}", fmt(base))
            ],
        ),
        Output(
            "base_used",
            "Zakat base used",
            "result",
            "zakat.base_used",
            amount=base_used,
            steps=[
                Step(
                    "Minimum base is adjusted net profit" if use_min else "No minimum base",
                    f"max({fmt(base)}, {fmt(profit)})" if use_min else fmt(base),
                    fmt(chosen),
                ),
                Step("Not below zero", f"max({fmt(chosen)}, 0)", fmt(base_used)),
            ],
            rule_keys=[f"{p}.zakat_min_base_is_net_profit"],
        ),
        Output(
            "zakat",
            "Zakat",
            "result",
            "zakat.due",
            amount=zakat_due,
            steps=[
                Step(
                    "Base × rate × period days ÷ year days, rounded",
                    f"{fmt(base_used)} × {fmt(rate)} × {factor_expr}",
                    fmt(zakat_due),
                )
            ],
            rule_keys=[
                f"{p}.zakat_rate",
                f"{p}.zakat_year_days",
                f"{p}.amount_decimals",
                f"{p}.rounding_mode",
            ],
        ),
    ]
