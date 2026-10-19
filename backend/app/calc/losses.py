"""Tax loss transfers and tax group membership tests.

Rule keys (all from the pack, never from code):

- ``<p>.loss_transfer_min_ownership``  decimal  common ownership needed to transfer losses
- ``<p>.tax_group_min_ownership``      decimal  parent ownership needed for membership

Losses used against profit (and the offset cap) are computed by the CT bridge.
"""

from __future__ import annotations

from app.calc import (
    ZERO,
    CalcError,
    Inputs,
    Output,
    RuleSource,
    Step,
    fmt,
    formula,
)
from app.calc.corporate_tax import FAIL, PASS, UNKNOWN, _flag_test, _overall


@formula("loss_transfer")
def loss_transfer(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    """Whether a loss transfer meets the pack's conditions on the preparer's inputs."""
    amount = inp.amount("amount", required=True)
    available = inp.amount("available_balance", required=True)
    ownership = inp.amount("common_ownership", required=True)
    if amount <= ZERO:
        raise CalcError("The amount to transfer must be above zero.")
    if not ZERO <= ownership <= 1:
        raise CalcError("Common ownership is a share between 0 and 1.")
    minimum = rules.decimal(f"{p}.loss_transfer_min_ownership")
    own = PASS if ownership >= minimum else FAIL
    avail = PASS if amount <= available else FAIL
    out = [
        Output(
            "test:ownership",
            "Common ownership at or above the minimum",
            "test",
            "loss.transfer_ownership",
            value=own,
            steps=[Step("Ownership ≥ minimum", f"{fmt(ownership)} ≥ {fmt(minimum)}", own)],
            rule_keys=[f"{p}.loss_transfer_min_ownership"],
        ),
        Output(
            "test:available",
            "Amount within the transferor's available losses",
            "test",
            "loss.transfer_available",
            value=avail,
            steps=[Step("Amount ≤ available balance", f"{fmt(amount)} ≤ {fmt(available)}", avail)],
        ),
        _flag_test(inp, "same_business_continuity", "Ownership held through the period", True),
        _flag_test(inp, "both_resident", "Both entities meet the residence condition", True),
    ]
    overall = _overall([o.value or UNKNOWN for o in out])
    out.append(
        Output(
            "conditions",
            "Loss transfer conditions",
            "result",
            "loss.transfer_overall",
            value=overall,
            steps=[Step("All conditions", ", ".join(f"{o.key}={o.value}" for o in out), overall)],
        )
    )
    return out


@formula("tax_group_test", ("member",))
def tax_group_test(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    """Per member: the parent's ownership against the pack's minimum and a matching
    financial year end. Members are input lines in category 'member' whose amount is
    the parent's share; '<key>_same_year_end' flags carry the year-end assertion."""
    members = inp.by_category("member")
    if not members:
        raise CalcError("Add at least one member.")
    minimum = rules.decimal(f"{p}.tax_group_min_ownership")
    out: list[Output] = []
    for m in members:
        assert m.amount is not None
        own = PASS if m.amount >= minimum else FAIL
        out.append(
            Output(
                f"test:{m.key}:ownership",
                f"{m.label}: parent ownership at or above the minimum",
                "test",
                "group.ownership",
                value=own,
                steps=[Step("Ownership ≥ minimum", f"{fmt(m.amount)} ≥ {fmt(minimum)}", own)],
                rule_keys=[f"{p}.tax_group_min_ownership"],
            )
        )
        fye = _flag_test(inp, f"{m.key}_same_year_end", f"{m.label}: same year end", True)
        out.append(
            Output(
                f"test:{m.key}:year_end",
                fye.label,
                fye.section,
                "group.year_end",
                value=fye.value,
                steps=fye.steps,
            )
        )
    overall = _overall([o.value or UNKNOWN for o in out])
    out.append(
        Output(
            "conditions",
            "Tax group conditions",
            "result",
            "group.overall",
            value=overall,
            steps=[Step("All members", ", ".join(f"{o.key}={o.value}" for o in out), overall)],
        )
    )
    return out
