"""Transfer pricing documentation thresholds and arm's length range tests.

Rule keys (all from the pack):

- ``<p>.tp_master_file_entity_revenue`` / ``<p>.tp_master_file_group_revenue``
- ``<p>.tp_local_file_entity_revenue`` / ``<p>.tp_local_file_group_revenue``
- ``<p>.tp_disclosure_threshold``  total related-party transactions for the form

A file is indicated when the entity's revenue reaches its threshold, or when the
entity is in an MNE group whose consolidated revenue reaches the group threshold.
Whether a file is actually required is for a qualified person to confirm.
"""

from __future__ import annotations

from decimal import Decimal

from app.calc import Inputs, Output, RuleSource, Step, fmt, formula

REQUIRED, NOT_REQUIRED, UNKNOWN = "required", "not_required", "not_determinable"
WITHIN, OUTSIDE = "within", "outside"


def _file_test(inp: Inputs, rules: RuleSource, p: str, kind: str, label: str) -> Output:
    ent_key, grp_key = f"{p}.tp_{kind}_entity_revenue", f"{p}.tp_{kind}_group_revenue"
    ent_t, grp_t = rules.decimal(ent_key), rules.decimal(grp_key)
    rev = inp.amount("entity_revenue", required=True)
    in_group = inp.flag("in_mne_group")
    steps = [Step("Entity revenue ≥ threshold", f"{fmt(rev)} ≥ {fmt(ent_t)}", str(rev >= ent_t))]
    if rev >= ent_t:
        result = REQUIRED
    elif in_group is False:
        result = NOT_REQUIRED
        steps.append(Step("Not in an MNE group (preparer's assertion)", "in_mne_group = false", ""))
    elif in_group is None or not inp.has("group_revenue"):
        result = UNKNOWN
        steps.append(Step("Group revenue test", "MNE group membership or revenue not given", ""))
    else:
        grp = inp.amount("group_revenue")
        result = REQUIRED if grp >= grp_t else NOT_REQUIRED
        steps.append(
            Step("Group revenue ≥ threshold", f"{fmt(grp)} ≥ {fmt(grp_t)}", str(grp >= grp_t))
        )
    steps.append(Step("Result", "entity test or group test", result))
    return Output(
        f"test:{kind}",
        label,
        "test",
        f"tp.{kind}",
        value=result,
        steps=steps,
        rule_keys=[ent_key, grp_key],
    )


@formula("tp_documentation", ("range",))
def tp_documentation(inp: Inputs, rules: RuleSource, p: str) -> list[Output]:
    out = [
        _file_test(inp, rules, p, "master_file", "Master File indicated"),
        _file_test(inp, rules, p, "local_file", "Local File indicated"),
    ]
    total = inp.amount("rp_total", required=True)
    limit = rules.decimal(f"{p}.tp_disclosure_threshold")
    disc = REQUIRED if total >= limit else NOT_REQUIRED
    out.append(
        Output(
            "test:disclosure",
            "Related-party disclosure indicated",
            "test",
            "tp.disclosure",
            value=disc,
            steps=[
                Step(
                    "Total related-party transactions ≥ threshold",
                    f"{fmt(total)} ≥ {fmt(limit)}",
                    disc,
                )
            ],
            rule_keys=[f"{p}.tp_disclosure_threshold"],
        )
    )
    # Arm's length ranges: '<txn>.low', '<txn>.high', '<txn>.tested' in category 'range'.
    ranges: dict[str, dict[str, Decimal]] = {}
    for ln in inp.by_category("range"):
        txn, _, part = ln.key.rpartition(".")
        if txn and part in ("low", "high", "tested") and ln.amount is not None:
            ranges.setdefault(txn, {})[part] = ln.amount
    for txn, r in sorted(ranges.items()):
        if len(r) != 3:
            continue
        low, high, tested = r["low"], r["high"], r["tested"]
        res = WITHIN if low <= tested <= high else OUTSIDE
        out.append(
            Output(
                f"range:{txn}",
                f"{txn}: tested result inside the arm's length range",
                "range",
                "tp.range",
                value=res,
                steps=[
                    Step("Low ≤ tested ≤ high", f"{fmt(low)} ≤ {fmt(tested)} ≤ {fmt(high)}", res)
                ],
            )
        )
    return out
