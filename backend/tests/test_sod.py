"""Phase E4: segregation of duties (engine 1.5.0) with the synthetic syn.sod matrix.

Synthetic matrix (app/demo_tax.py): SOD-01 vendor_maintain vs payment_release or
payment_run; SOD-02 journal_post vs journal_approve; SOD-03 role "AP Clerk" vs role
"Treasury Approver". The export, hand-checked:
  row 1 alice  AP Clerk           vendor_maintain   active   SOD-01 side a
  row 2 alice                     payment_release   active   SOD-01 side b
  row 3 bob    Treasury Approver  payment_run       active   SOD-03 side b
  row 4 bob    ap clerk  (spaces, lower case)       active   SOD-03 side a
  row 5 carol                     journal_post      locked   SOD-02 a (skipped when locked)
  row 6 carol                     journal_approve   locked   SOD-02 b (skipped when locked)
  row 7 dave                      journal_post      active   nothing
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.engine.sod_checks import breaches, user_codes
from app.models import Role
from app.services import rule_schemas
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import checklist, findings, req, results
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack

ROLES = (
    b"user_id,user_name,role,permission,status\n"
    b"alice,Alice (synthetic),AP Clerk,vendor_maintain,active\n"
    b"alice,Alice (synthetic),,payment_release,active\n"
    b"bob,Bob (synthetic),Treasury Approver,payment_run,active\n"
    b"bob,Bob (synthetic),  ap   clerk ,,active\n"
    b"carol,Carol (synthetic),,journal_post,locked\n"
    b"carol,Carol (synthetic),,journal_approve,locked\n"
    b"dave,Dave (synthetic),,journal_post,active\n"
)


def test_breaches_by_hand() -> None:
    rows: list[dict[str, Any]] = [
        {"row_id": 1, "user_id": "U1", "role": "Maker", "permission": "Checker"},
        {"row_id": 2, "user_id": "u1", "role": "x", "permission": None},
        {"row_id": 3, "user_id": "u2", "role": "maker", "permission": None},
    ]
    codes = user_codes(rows)
    assert set(codes) == {"u1", "u2"}
    hit = breaches(codes, {"maker"}, {"checker"})
    # Row 1 grants both sides through its role and permission columns.
    assert list(hit) == ["u1"] and [(r["row_id"], r["_side"]) for r in hit["u1"]] == [(1, "a+b")]
    assert breaches(codes, {"maker"}, {"nobody"}) == {}


def test_conflict_matrix_shape() -> None:
    ok = [{"id": "C1", "a": ["x"], "b": ["y"], "description": "d"}]
    assert rule_schemas.validate_shape("p.sod_conflicts", ok)[0].id == "C1"
    for bad in (
        [{"id": "C1", "a": ["X "], "b": ["x"], "description": "d"}],  # same code both sides
        ok + ok,  # duplicate id
        [{"id": "bad id", "a": ["x"], "b": ["y"], "description": "d"}],
        [{"id": "C1", "a": [], "b": ["y"], "description": "d"}],
        [],
    ):
        with pytest.raises(rule_schemas.RuleShapeError):
            rule_schemas.validate_shape("p.sod_conflicts", bad)


def test_sod_conflicts_through_a_review(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    ds = dataset(reviewer, entity, "user_roles", ROLES)
    cfg = {"type": "sod_conflict", "conflicts_rule": "syn.sod.sod_conflicts"}
    cv = checklist(
        reviewer,
        [
            req("SOD-ALL", cfg),
            req("SOD-ACT", {**cfg, "exclude_statuses": ["Locked"]}),
        ],
    )
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "Synthetic SoD review",
            "checklist_version_id": cv,
            "dataset_version_ids": [ds],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    res = results(reviewer, rid)
    for code in ("SOD-ALL", "SOD-ACT"):
        assert res[code]["outcome"] == "exceptions_found", res[code]
        assert any("Unverified" in w for w in res[code]["meta"]["warnings"])
    assert res["SOD-ALL"]["meta"]["users"] == 4

    def rows_of(code: str) -> dict[str, list[tuple[int, str]]]:
        out: dict[str, list[tuple[int, str]]] = {}
        for f in findings(reviewer, rid):
            if f["requirement_code"] != code:
                continue
            ev = f["evidence"][0]
            got = [dict(zip(ev["columns"], row, strict=True)) for row in ev["rows"]]
            out[f["finding_key"]] = [(g["row_id"], g["_side"]) for g in got]
        return out

    assert rows_of("SOD-ALL") == {
        "sod:SOD-01": [(1, "a"), (2, "b")],
        "sod:SOD-02": [(5, "a"), (6, "b")],
        "sod:SOD-03": [(3, "b"), (4, "a")],
    }
    assert set(rows_of("SOD-ACT")) == {"sod:SOD-01", "sod:SOD-03"}
