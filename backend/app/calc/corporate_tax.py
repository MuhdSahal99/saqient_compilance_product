"""Corporate tax: accounting profit to taxable income bridge, SBR and QFZP tests.

The structure (which adjustments exist and how a limitation is computed) is
modelled generically; every amount, share, threshold and date comes from the pack:

- ``<p>.rate_bands``                      json  rate bands on taxable income
- ``<p>.entertainment_deductible_share``  decimal  deductible share of entertainment
- ``<p>.interest_ebitda_share``           decimal  share of tax EBITDA allowed as net interest
- ``<p>.interest_de_minimis``             decimal  net interest always allowed
- ``<p>.loss_offset_cap_share``           decimal  share of taxable income losses may offset
- ``<p>.sbr_revenue_threshold``           decimal  Small Business Relief revenue limit
- ``<p>.sbr_last_period_end``             date     last period end SBR can apply to
- ``<p>.qfzp_de_minimis_share``           decimal  non-qualifying income share limit
- ``<p>.qfzp_de_minimis_amount``          decimal  non-qualifying income amount limit
- ``<p>.amount_decimals`` / ``<p>.rounding_mode``
"""

from __future__ import annotations

from datetime import date
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
from app.services.rule_schemas import typed

# Adjustment categories a preparer can enter (section "adjustment").
ADD_BACK = ("non_deductible", "other_add")
DEDUCT = ("exempt_income", "other_deduct")
SIGNED = ("related_party",)
ENTERTAINMENT = "entertainment"
ADJUSTMENT_CATEGORIES = (*ADD_BACK, *DEDUCT, *SIGNED, ENTERTAINMENT)


def band_tax(income: Decimal, bands: list[object]) -> tuple[Decimal, list[Step]]:
    """Tax on ``income`` across contiguous bands (lower inclusive, upper exclusive)."""
    total, steps = ZERO, []
    for b in bands:
        lower, upper, rate = b.lower, b.upper, b.rate  # type: ignore[attr-defined]
        if income <= lower:
            break
        top = income if upper is None else min(income, upper)
        part = (top - lower) * rate
        total += part
        steps.append(
            Step(
                f"Band {fmt(lower)}–{fmt(upper) if upper is not None else '∞'} at {fmt(rate)}",
                f"({fmt(top)} − {fmt(lower)}) × {fmt(rate)}",
                fmt(part),
            )
        )
    return total, steps


@formula("corporate_tax", ADJUSTMENT_CATEGORIES)
def ct_bridge(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    rnd = Rounder(rules, p)
    out: list[Output] = []
    ap = inp.amount("accounting_profit", required=True)

    def total(cats: tuple[str, ...]) -> Decimal:
        return sum((ln.amount or ZERO for c in cats for ln in inp.by_category(c)), ZERO)

    add_back, deduct, signed = total(ADD_BACK), total(DEDUCT), total(SIGNED)
    ent_share = rules.decimal(f"{p}.entertainment_deductible_share")
    ent_spend = total((ENTERTAINMENT,))
    ent_dis = rnd(ent_spend * (1 - ent_share))
    out.append(
        Output(
            "entertainment_disallowed",
            "Entertainment not deductible",
            "adjustment",
            "ct.entertainment",
            amount=ent_dis,
            steps=[
                Step(
                    "Entertainment spend × non-deductible share",
                    f"{fmt(ent_spend)} × (1 − {fmt(ent_share)})",
                    fmt(ent_dis),
                )
            ],
            rule_keys=[f"{p}.entertainment_deductible_share"],
        )
    )
    adjusted = ap + add_back + ent_dis + signed - deduct
    out.append(
        Output(
            "adjusted_profit",
            "Adjusted profit before interest limitation",
            "bridge",
            "ct.adjusted_profit",
            amount=adjusted,
            steps=[
                Step(
                    "Accounting profit + add-backs + entertainment + related-party − deductions",
                    f"{fmt(ap)} + {fmt(add_back)} + {fmt(ent_dis)} + {fmt(signed)} − {fmt(deduct)}",
                    fmt(adjusted),
                )
            ],
        )
    )

    nie = inp.amount("net_interest_expense")
    da = inp.amount("depreciation_amortisation")
    cf_in = inp.amount("interest_brought_forward")
    share = rules.decimal(f"{p}.interest_ebitda_share")
    de_min = rules.decimal(f"{p}.interest_de_minimis")
    ebitda = adjusted + nie + da
    capacity = rnd(max(de_min, share * max(ebitda, ZERO)))
    disallowed = max(ZERO, nie - capacity)
    spare = max(ZERO, capacity - nie)
    cf_used = min(cf_in, spare)
    cf_out = cf_in - cf_used + disallowed
    interest_keys = [f"{p}.interest_ebitda_share", f"{p}.interest_de_minimis"]
    out += [
        Output(
            "tax_ebitda",
            "Tax EBITDA",
            "interest",
            "ct.tax_ebitda",
            amount=ebitda,
            steps=[
                Step(
                    "Adjusted profit + net interest expense + depreciation and amortisation",
                    f"{fmt(adjusted)} + {fmt(nie)} + {fmt(da)}",
                    fmt(ebitda),
                )
            ],
        ),
        Output(
            "interest_capacity",
            "Net interest allowed",
            "interest",
            "ct.interest_capacity",
            amount=capacity,
            steps=[
                Step(
                    "Greater of de minimis and share × tax EBITDA",
                    f"max({fmt(de_min)}, {fmt(share)} × max({fmt(ebitda)}, 0))",
                    fmt(capacity),
                )
            ],
            rule_keys=interest_keys,
        ),
        Output(
            "interest_disallowed",
            "Net interest disallowed this period",
            "adjustment",
            "ct.interest_disallowed",
            amount=disallowed,
            steps=[
                Step(
                    "max(0, net interest − allowed)",
                    f"max(0, {fmt(nie)} − {fmt(capacity)})",
                    fmt(disallowed),
                )
            ],
            rule_keys=interest_keys,
        ),
        Output(
            "interest_brought_forward_used",
            "Disallowed interest brought forward and used",
            "adjustment",
            "ct.interest_cf_used",
            amount=cf_used,
            steps=[
                Step(
                    "min(brought forward, unused capacity)",
                    f"min({fmt(cf_in)}, max(0, {fmt(capacity)} − {fmt(nie)}))",
                    fmt(cf_used),
                )
            ],
        ),
        Output(
            "interest_carried_forward",
            "Disallowed interest carried forward",
            "carry_forward",
            "ct.interest_cf_out",
            amount=cf_out,
            steps=[
                Step(
                    "Brought forward − used + disallowed this period",
                    f"{fmt(cf_in)} − {fmt(cf_used)} + {fmt(disallowed)}",
                    fmt(cf_out),
                )
            ],
        ),
    ]
    ti_pre = adjusted + disallowed - cf_used
    losses_bf = inp.amount("losses_brought_forward")
    cap_share = rules.decimal(f"{p}.loss_offset_cap_share")
    loss_used = rnd(min(losses_bf, max(ti_pre, ZERO) * cap_share))
    losses_cf = losses_bf - loss_used + (-ti_pre if ti_pre < 0 else ZERO)
    ti = ti_pre - loss_used if ti_pre > 0 else ti_pre
    bands = typed(f"{p}.rate_bands", rules.get(f"{p}.rate_bands"))
    tax_raw, band_steps = band_tax(max(ti, ZERO), bands)
    tax = rnd(tax_raw)
    out += [
        Output(
            "taxable_income_before_losses",
            "Taxable income before losses",
            "bridge",
            "ct.ti_before_losses",
            amount=ti_pre,
            steps=[
                Step(
                    "Adjusted profit + interest disallowed − brought-forward interest used",
                    f"{fmt(adjusted)} + {fmt(disallowed)} − {fmt(cf_used)}",
                    fmt(ti_pre),
                )
            ],
        ),
        Output(
            "losses_used",
            "Tax losses used",
            "losses",
            "ct.losses_used",
            amount=loss_used,
            steps=[
                Step(
                    "min(losses brought forward, share × taxable income before losses)",
                    f"min({fmt(losses_bf)}, {fmt(cap_share)} × max({fmt(ti_pre)}, 0))",
                    fmt(loss_used),
                )
            ],
            rule_keys=[f"{p}.loss_offset_cap_share"],
        ),
        Output(
            "losses_carried_forward",
            "Tax losses carried forward",
            "carry_forward",
            "ct.losses_cf",
            amount=losses_cf,
            steps=[
                Step(
                    "Brought forward − used + this period's loss",
                    f"{fmt(losses_bf)} − {fmt(loss_used)} + {fmt(-ti_pre if ti_pre < 0 else ZERO)}",
                    fmt(losses_cf),
                )
            ],
        ),
        Output(
            "taxable_income",
            "Taxable income",
            "result",
            "ct.taxable_income",
            amount=ti,
            steps=[
                Step("Before losses − losses used", f"{fmt(ti_pre)} − {fmt(loss_used)}", fmt(ti))
            ],
        ),
        Output(
            "tax",
            "Corporate tax",
            "result",
            "ct.tax",
            amount=tax,
            steps=[*band_steps, Step("Total, rounded", fmt(tax_raw), fmt(tax))],
            rule_keys=[f"{p}.rate_bands", f"{p}.amount_decimals", f"{p}.rounding_mode"],
        ),
    ]
    return out


PASS, FAIL, UNKNOWN = "met", "not_met", "not_determinable"


def _overall(results: list[str]) -> str:
    if FAIL in results:
        return FAIL
    if UNKNOWN in results:
        return UNKNOWN
    return PASS


def _flag_test(inp: Inputs, key: str, label: str, want: bool) -> Output:
    got = inp.flag(key)
    result = UNKNOWN if got is None else (PASS if got is want else FAIL)
    shown = "not entered" if got is None else str(got).lower()
    return Output(
        f"test:{key}",
        label,
        "test",
        "test.assertion",
        value=result,
        steps=[
            Step(
                "Preparer's assertion (with evidence)",
                f"{key} = {shown}; needed {str(want).lower()}",
                result,
            )
        ],
    )


@formula("sbr_test")
def sbr(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    """Small Business Relief conditions: revenue limit (this and earlier periods), last
    period end, and the exclusions the preparer asserts. Says whether the pack's
    conditions are met on the inputs; a person decides whether to elect."""
    limit = rules.decimal(f"{p}.sbr_revenue_threshold")
    last = rules.get(f"{p}.sbr_last_period_end")
    period_end = inp.period_end
    out: list[Output] = []
    revenue_keys = [ln.key for ln in inp.lines if ln.key.startswith("revenue")]
    if "revenue" not in revenue_keys:
        raise CalcError("Enter the input 'revenue' for this period.")
    for key in sorted(revenue_keys):
        rev = inp.amount(key)
        r = PASS if rev <= limit else FAIL
        out.append(
            Output(
                f"test:{key}",
                f"Revenue ({key.replace('_', ' ')}) within the limit",
                "test",
                "sbr.revenue",
                value=r,
                steps=[Step("Revenue ≤ threshold", f"{fmt(rev)} ≤ {fmt(limit)}", r)],
                rule_keys=[f"{p}.sbr_revenue_threshold"],
            )
        )
    if period_end is None:
        out.append(
            Output(
                "test:period_end",
                "Period ends on or before the last date",
                "test",
                "sbr.period_end",
                value=UNKNOWN,
                steps=[Step("Period end ≤ last date", "period end not given", UNKNOWN)],
            )
        )
    else:
        pe, ld = period_end, date.fromisoformat(str(last))
        r = PASS if pe <= ld else FAIL
        out.append(
            Output(
                "test:period_end",
                "Period ends on or before the last date",
                "test",
                "sbr.period_end",
                value=r,
                steps=[Step("Period end ≤ last date", f"{pe.isoformat()} ≤ {ld.isoformat()}", r)],
                rule_keys=[f"{p}.sbr_last_period_end"],
            )
        )
    out.append(_flag_test(inp, "is_qfzp", "Not a Qualifying Free Zone Person", False))
    out.append(
        _flag_test(inp, "is_mne_group_member", "Not a member of an in-scope MNE group", False)
    )
    overall = _overall([o.value or UNKNOWN for o in out])
    out.append(
        Output(
            "conditions",
            "Small Business Relief conditions",
            "result",
            "sbr.overall",
            value=overall,
            steps=[Step("All conditions", ", ".join(f"{o.key}={o.value}" for o in out), overall)],
        )
    )
    return out


@formula("qfzp_test")
def qfzp(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    """Qualifying Free Zone Person: de minimis on non-qualifying income plus the
    substance and compliance conditions the preparer asserts with evidence."""
    q = inp.amount("qualifying_income", required=True)
    nq = inp.amount("non_qualifying_income", required=True)
    share = rules.decimal(f"{p}.qfzp_de_minimis_share")
    cap_amt = rules.decimal(f"{p}.qfzp_de_minimis_amount")
    revenue = q + nq
    limit = min(share * revenue, cap_amt)
    r = PASS if nq <= limit else FAIL
    out = [
        Output(
            "de_minimis_limit",
            "Non-qualifying income limit",
            "test",
            "qfzp.limit",
            amount=limit,
            steps=[
                Step(
                    "Lower of share × total revenue and the fixed amount",
                    f"min({fmt(share)} × ({fmt(q)} + {fmt(nq)}), {fmt(cap_amt)})",
                    fmt(limit),
                )
            ],
            rule_keys=[f"{p}.qfzp_de_minimis_share", f"{p}.qfzp_de_minimis_amount"],
        ),
        Output(
            "test:de_minimis",
            "Non-qualifying income within the de minimis limit",
            "test",
            "qfzp.de_minimis",
            value=r,
            steps=[Step("Non-qualifying ≤ limit", f"{fmt(nq)} ≤ {fmt(limit)}", r)],
        ),
        _flag_test(inp, "adequate_substance", "Adequate substance in the free zone", True),
        _flag_test(inp, "audited_financial_statements", "Audited financial statements", True),
        _flag_test(inp, "transfer_pricing_compliant", "Transfer pricing rules followed", True),
        _flag_test(inp, "elected_out", "Has not elected to be taxed at the standard rate", False),
    ]
    overall = _overall([o.value for o in out if o.value is not None])
    out.append(
        Output(
            "conditions",
            "Qualifying Free Zone Person conditions",
            "result",
            "qfzp.overall",
            value=overall,
            steps=[
                Step(
                    "All conditions",
                    ", ".join(f"{o.key}={o.value}" for o in out if o.value),
                    overall,
                )
            ],
        )
    )
    return out
