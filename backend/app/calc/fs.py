"""Financial statement draft and IFRS 16 lease recalculation (Phase F3).

``fs_draft`` presents mapped trial balance lead schedules by section with prior-year
comparatives, checks that the statement of financial position balances against the
year's result, and compares each note total the preparer enters with its face line.
Trial balance signs are debit positive: liabilities, equity and income are presented
with the sign reversed.

``lease_ifrs16`` recalculates a lease liability as the present value of equal
payments at the entity's own discount rate per period (in arrears or in advance), the
right-of-use asset, straight-line depreciation over the term and the first period's
interest. The discount rate is the entity's judgement, entered as an input; the pack
supplies only rounding and tolerances. Both are drafts for a qualified reviewer.
"""

from __future__ import annotations

import re
from decimal import Decimal

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

FS_KEY = re.compile(r"^fs_(asset|liability|equity|income|expense)_([a-z0-9]{1,20})_(cy|py)$")
NOTE_KEY = re.compile(r"^note_([a-z0-9]{1,20})$")
SIGN = {"asset": 1, "liability": -1, "equity": -1, "income": -1, "expense": 1}
TOTALS = (
    ("asset", "total_assets", "Total assets"),
    ("liability", "total_liabilities", "Total liabilities"),
    ("equity", "total_equity", "Total equity"),
    ("income", "total_income", "Total income"),
    ("expense", "total_expenses", "Total expenses"),
)
YEARS = (("cy", "current year"), ("py", "prior year"))


@formula("fs_draft", ("current_year", "prior_year", "note"))
def fs_draft(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    r = Rounder(rules, p)
    rk = [f"{p}.amount_decimals", f"{p}.rounding_mode"]
    tolerance = rules.decimal(f"{p}.fs_note_tolerance")
    face: dict[str, dict[str, Decimal]] = {}
    section_of: dict[str, str] = {}
    for ln in inp.lines:
        m = FS_KEY.match(ln.key)
        if m is None or ln.amount is None:
            continue
        section, code, year = m.groups()
        expected = "current_year" if year == "cy" else "prior_year"
        if ln.category != expected:
            raise CalcError(
                f"Input '{ln.key}' must be in the {expected.replace('_', ' ')} category."
            )
        if section_of.setdefault(code, section) != section:
            raise CalcError(f"Lead schedule '{code}' appears in two sections.")
        face.setdefault(code, {})[year] = r(ln.amount * SIGN[section])
    if not face:
        raise CalcError("Add trial balance lines (fs_<section>_<code>_cy and _py).")
    out: list[Output] = []
    totals: dict[tuple[str, str], Decimal] = {}
    for code in sorted(face):
        section = section_of[code]
        for year, label in YEARS:
            if year not in face[code]:
                continue
            v = face[code][year]
            totals[(section, year)] = totals.get((section, year), ZERO) + v
            sign = "as recorded" if SIGN[section] == 1 else "sign reversed (credit balance)"
            out.append(
                Output(
                    f"face_{code}_{year}",
                    f"{code.upper()} ({label})",
                    section,
                    "fs.face_line",
                    amount=v,
                    steps=[
                        Step(f"Trial balance, {sign}", f"{section} lead {code.upper()}", fmt(v))
                    ],
                    rule_keys=rk,
                )
            )
    for year, label in YEARS:
        if not any(y == year for (_, y) in totals):
            continue
        t = {s: totals.get((s, year), ZERO) for s in SIGN}
        for section, key, name in TOTALS:
            out.append(
                Output(
                    f"{key}_{year}",
                    f"{name} ({label})",
                    "total",
                    "fs.section_total",
                    amount=t[section],
                    steps=[Step(f"Sum of {section} lines", label, fmt(t[section]))],
                    rule_keys=rk,
                )
            )
        profit = t["income"] - t["expense"]
        out.append(
            Output(
                f"profit_{year}",
                f"Profit for the year ({label})",
                "total",
                "fs.profit",
                amount=profit,
                steps=[
                    Step(
                        "Income − expenses",
                        f"{fmt(t['income'])} − {fmt(t['expense'])}",
                        fmt(profit),
                    )
                ],
            )
        )
        diff = t["asset"] - t["liability"] - t["equity"] - profit
        out.append(
            Output(
                f"balance_check_{year}",
                f"Balance check ({label})",
                "check",
                "fs.balance_check",
                value="balanced" if diff == ZERO else f"difference {fmt(diff)}",
                steps=[
                    Step(
                        "Assets − liabilities − equity − profit",
                        f"{fmt(t['asset'])} − {fmt(t['liability'])} − {fmt(t['equity'])} − "
                        f"{fmt(profit)}",
                        fmt(diff),
                    )
                ],
            )
        )
    for ln in sorted(inp.lines, key=lambda x: x.key):
        m = NOTE_KEY.match(ln.key)
        if m is None or ln.amount is None:
            continue
        if ln.category != "note":
            raise CalcError(f"Input '{ln.key}' must be in the note category.")
        code = m.group(1)
        note = r(ln.amount)
        line = face.get(code, {}).get("cy")
        if line is None:
            value, steps = "no face line", [Step("Face line", f"no lead {code.upper()}", "—")]
        else:
            d = note - line
            value = "agrees" if abs(d) <= tolerance else f"differs by {fmt(d)}"
            steps = [
                Step("Note total − face line", f"{fmt(note)} − {fmt(line)}", fmt(d)),
                Step("Within tolerance", f"|{fmt(d)}| ≤ {fmt(tolerance)}", value),
            ]
        out.append(
            Output(
                f"note_{code}_check",
                f"Note {code.upper()} cross-check",
                "check",
                "fs.note_check",
                value=value,
                steps=steps,
                rule_keys=[f"{p}.fs_note_tolerance"],
            )
        )
    return out


def _value(inp: Inputs, key: str) -> str:
    for ln in inp.lines:
        if ln.key == key and ln.value is not None and ln.value.strip():
            return ln.value.strip()
    raise CalcError(f"Enter the input '{key}'.")


@formula("lease_ifrs16")
def lease_ifrs16(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    r = Rounder(rules, p)
    rk = [f"{p}.amount_decimals", f"{p}.rounding_mode"]
    payment = inp.amount("payment", required=True)
    try:
        n = int(_value(inp, "periods"))
        rate = Decimal(_value(inp, "rate_per_period"))
    except (ValueError, ArithmeticError) as exc:
        raise CalcError("periods must be a whole number and rate_per_period a number.") from exc
    timing = _value(inp, "timing").lower()
    if n < 1 or n > 1200:
        raise CalcError("periods must be between 1 and 1200.")
    if rate < 0 or rate >= 1:
        raise CalcError("rate_per_period must be at least 0 and below 1.")
    if timing not in ("arrears", "advance"):
        raise CalcError("timing must be arrears or advance.")
    if payment <= 0:
        raise CalcError("payment must be positive.")
    if rate == ZERO:
        pv = payment * n
        pv_expr = f"{fmt(payment)} × {n}"
    else:
        annuity = (1 - (1 + rate) ** -n) / rate
        pv = payment * annuity * (1 + rate if timing == "advance" else 1)
        pv_expr = f"{fmt(payment)} × (1 − (1 + {fmt(rate)})^−{n}) ÷ {fmt(rate)}"
        if timing == "advance":
            pv_expr += f" × (1 + {fmt(rate)})"
    liability = r(pv)
    idc = inp.amount("initial_direct_costs")
    prepaid = inp.amount("prepaid_payments")
    incentives = inp.amount("incentives")
    rou = r(liability + idc + prepaid - incentives)
    dep = r(rou / n)
    opening = liability - payment if timing == "advance" else liability
    interest1 = r(opening * rate)
    closing1 = opening + interest1 - (ZERO if timing == "advance" else payment)
    total_interest = r(payment * n - liability)
    return [
        Output(
            "lease_liability",
            "Lease liability at commencement",
            "liability",
            "ifrs16.liability",
            amount=liability,
            steps=[Step(f"Present value, payments in {timing}", pv_expr, fmt(liability))],
            rule_keys=rk,
        ),
        Output(
            "rou_asset",
            "Right-of-use asset at commencement",
            "asset",
            "ifrs16.rou",
            amount=rou,
            steps=[
                Step(
                    "Liability + direct costs + prepaid − incentives",
                    f"{fmt(liability)} + {fmt(idc)} + {fmt(prepaid)} − {fmt(incentives)}",
                    fmt(rou),
                )
            ],
            rule_keys=rk,
        ),
        Output(
            "depreciation_per_period",
            "Depreciation per period (straight line over the term)",
            "asset",
            "ifrs16.depreciation",
            amount=dep,
            steps=[Step("Right-of-use asset ÷ periods", f"{fmt(rou)} ÷ {n}", fmt(dep))],
            rule_keys=rk,
        ),
        Output(
            "first_period_interest",
            "Interest in the first period",
            "liability",
            "ifrs16.interest",
            amount=interest1,
            steps=[Step("Opening balance × rate", f"{fmt(opening)} × {fmt(rate)}", fmt(interest1))],
            rule_keys=rk,
        ),
        Output(
            "closing_liability_first_period",
            "Liability after the first period",
            "liability",
            "ifrs16.closing",
            amount=closing1,
            steps=[
                Step(
                    "Opening + interest − payment in arrears",
                    f"{fmt(opening)} + {fmt(interest1)}"
                    + ("" if timing == "advance" else f" − {fmt(payment)}"),
                    fmt(closing1),
                )
            ],
        ),
        Output(
            "total_interest",
            "Total interest over the term",
            "liability",
            "ifrs16.total_interest",
            amount=total_interest,
            steps=[
                Step(
                    "Payments − liability",
                    f"{fmt(payment)} × {n} − {fmt(liability)}",
                    fmt(total_interest),
                )
            ],
            rule_keys=rk,
        ),
    ]
