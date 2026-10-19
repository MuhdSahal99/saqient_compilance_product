"""Phase D6: journal entry tests (engine 1.4.0) with the synthetic syn.audit rules.

Synthetic parameters (app/demo_tax.py): weekend days 6 and 7 (Sat, Sun); holidays
2025-03-30, 2025-06-06, 2025-12-02; round multiple 5000; approval limit 50000 with a
0.04 band, so entries from 48000 up to 49999.99 are flagged; at least 3 entries for a
usual poster; Benford needs 50 amounts, MAD bands 0.005 / 0.011 / 0.016.

The ledger, hand-checked:
  J1 Mon 2025-03-03  1234.56 alice      nothing
  J2 Sat 2025-03-01   777.77 alice      weekend
  J3 Fri 2025-06-06   888.12 alice      holiday
  J4 Thu 2025-04-10 10000.00 bob        round amount; bob has 1 entry (unusual)
  J5 Mon 2025-05-12 49000.00 alice      just below the limit
  J6 Mon 2026-01-05  2500.50 carol      posted after the 2025-12-31 close, document
                                        dated 2025-12-30; carol has 1 entry (unusual)
  J7 Tue 2025-07-01   333.33 (none)     no poster
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.engine.je_checks import benford_mad, conformity, entry_debits, first_digit
from app.models import Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import checklist, findings, req, results
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack

ENTRIES = [
    ("J1", "2025-03-03", "1234.56", "alice", "2025-03-03"),
    ("J2", "2025-03-01", "777.77", "alice", "2025-03-01"),
    ("J3", "2025-06-06", "888.12", "alice", "2025-06-06"),
    ("J4", "2025-04-10", "10000", "bob", "2025-04-10"),
    ("J5", "2025-05-12", "49000", "alice", "2025-05-12"),
    ("J6", "2026-01-05", "2500.50", "carol", "2025-12-30"),
    ("J7", "2025-07-01", "333.33", "", "2025-07-01"),
]
HEADER = b"entry_id,posting_date,account_code,description,debit,credit,posted_by,document_date\n"


def gl(entries: list[tuple[str, str, str, str, str]]) -> bytes:
    lines = [
        f"{e},{d},6000,Synthetic expense,{amt},,{u},{doc}\n{e},{d},1000,Synthetic bank,,{amt},{u},{doc}\n"
        for e, d, amt, u, doc in entries
    ]
    return HEADER + "".join(lines).encode()


def je(test: str, **extra: Any) -> dict[str, Any]:
    return {"type": "journal_entry_test", "test": test, "rules_prefix": "syn.audit", **extra}


def test_benford_helpers_by_hand() -> None:
    # All first digits 1: |1 - 0.30103| + (sum of the other expected shares = 0.69897), / 9.
    mad, shares = benford_mad({1: 50})
    assert mad == pytest.approx(1.39794 / 9, abs=1e-5) and shares[1] == 1.0
    assert (
        conformity(mad, {"close": "0.005", "acceptable": "0.011", "marginal": "0.016"})
        == "nonconformity"
    )
    # Counts of 1000 close to Benford: deviations sum to 0.000910, MAD 0.000101.
    near = dict(zip(range(1, 10), [301, 176, 125, 97, 79, 67, 58, 51, 46], strict=True))
    mad2, _ = benford_mad(near)
    assert mad2 == pytest.approx(0.000910 / 9, abs=2e-6)
    assert (
        conformity(mad2, {"close": "0.005", "acceptable": "0.011", "marginal": "0.016"}) == "close"
    )
    assert (
        conformity(0.012, {"close": "0.005", "acceptable": "0.011", "marginal": "0.016"})
        == "marginal"
    )
    from decimal import Decimal

    assert first_digit(Decimal("9.99")) is None
    assert first_digit(Decimal("10")) == 1 and first_digit(Decimal("48000.50")) == 4
    assert entry_debits(
        [
            {"entry_id": "A", "debit": 5, "credit": None},
            {"entry_id": "A", "debit": None, "credit": 5},
        ]
    ) == {"A": 5}
    assert entry_debits([{"entry_id": "B", "amount": 7}, {"entry_id": "B", "amount": -7}]) == {
        "B": 7
    }


def test_journal_entry_tests_through_a_review(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    ds = dataset(reviewer, entity, "general_ledger", gl(ENTRIES))
    ones = [(f"B{i}", "2025-08-04", str(100 + i), "alice", "2025-08-04") for i in range(60)]
    ds_ones = dataset(reviewer, make_entity(db, tenant_a), "general_ledger", gl(ones))
    reqs = [
        req("JE-WKD", je("weekend")),
        req("JE-HOL", je("holiday")),
        req("JE-RND", je("round_amount")),
        req("JE-USR", je("unusual_user")),
        req("JE-LIM", je("below_limit")),
        req("JE-PCL", je("post_close", close_date="2025-12-31")),
        req("JE-BEN", je("benford")),
    ]
    cv = checklist(reviewer, reqs)

    def run(version: str) -> tuple[str, dict[str, dict[str, Any]]]:
        r = reviewer.post(
            "/api/reviews",
            json={
                "title": "Synthetic JE testing",
                "checklist_version_id": cv,
                "dataset_version_ids": [version],
                "rule_pack_version_id": rpv,
            },
        )
        assert r.status_code == 201, r.text
        return r.json()["id"], results(reviewer, r.json()["id"])

    rid, res = run(ds)

    def rows_of(code: str, key: str) -> set[str]:
        fs = [
            f
            for f in findings(reviewer, rid)
            if f["requirement_code"] == code and f["finding_key"] == key
        ]
        assert len(fs) == 1, (code, key, res[code])
        ev = fs[0]["evidence"][0]
        cols = ev["columns"]
        return {dict(zip(cols, row, strict=True))["entry_id"] for row in ev["rows"]}

    for code in ("JE-WKD", "JE-HOL", "JE-RND", "JE-USR", "JE-LIM", "JE-PCL"):
        assert res[code]["outcome"] == "exceptions_found", (code, res[code])
        if code != "JE-PCL":  # the post-close test reads no rules
            assert any("Unverified" in w for w in res[code]["meta"]["warnings"])
    assert rows_of("JE-WKD", "weekend") == {"J2"}
    assert rows_of("JE-HOL", "holiday") == {"J3"}
    assert rows_of("JE-RND", "round_amount") == {"J4"}
    assert rows_of("JE-USR", "unusual_user") == {"J4", "J6"}
    assert rows_of("JE-USR", "missing_user") == {"J7"}
    assert rows_of("JE-LIM", "below_limit") == {"J5"}
    assert rows_of("JE-PCL", "post_close") == {"J6"}
    assert res["JE-LIM"]["meta"]["band"] == ["48000.00", "50000"]
    # 14 lines are too few for Benford.
    assert res["JE-BEN"]["outcome"] == "not_applicable"

    rid2, res2 = run(ds_ones)
    ben = res2["JE-BEN"]
    assert ben["outcome"] == "exceptions_found" and ben["meta"]["conformity"] == "nonconformity"
    assert ben["meta"]["population"] == 120  # 60 entries, 2 lines each, all >= 10
    f = [x for x in findings(reviewer, rid2) if x["requirement_code"] == "JE-BEN"][0]
    assert f["evidence"][0]["detail"]["mad"] == ben["meta"]["mad"]
    assert res2["JE-WKD"]["outcome"] == "no_exceptions"


def test_journal_entry_test_validation() -> None:
    from pydantic import ValidationError

    from app.engine.versions import parse_check

    with pytest.raises(ValidationError):
        parse_check(je("payroll"))
    with pytest.raises(ValidationError):
        parse_check(je("weekend", rules_prefix="Bad Prefix"))
