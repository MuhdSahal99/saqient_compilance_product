"""Phase D2–D3: lead schedules with prior-year comparison, materiality, preparer sign-off.

Hand-checked values:
  A Cash and bank = 1000 + 1100: CY 150000 + 50000 = 200000, PY 100000 + 20000 = 120000,
    movement 80000, change 80000 / 120000 = 0.66666… → 0.6667
  B Payables = 2000: CY -120000, PY -80000, movement -40000, change -40000 / 80000 = -0.5
  5000 is unmapped (CY 370000, PY 310000); 7777 is mapped but in neither trial balance.
  Materiality: PBT 1500000 × 0.05 = 75000.00; performance × 0.7 = 52500.00;
    trivial × 0.1 = 7500.00 (0.1 is above the synthetic 0.02–0.06 guidance → outside).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_engagements import new_engagement
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack, lines, new_paper, put_in

CY_TB = (
    b"account_code,account_name,balance\n"
    b"1000,Synthetic cash,150000\n"
    b"1100,Synthetic bank,50000\n"
    b"2000,Synthetic payables,-120000\n"
    b"3000,Synthetic equity,-50000\n"
    b"4000,Synthetic revenue,-400000\n"
    b"5000,Synthetic expenses,370000\n"
)
PY_TB = (
    b"account_code,account_name,balance\n"
    b"1000,Synthetic cash,100000\n"
    b"1100,Synthetic bank,20000\n"
    b"2000,Synthetic payables,-80000\n"
    b"3000,Synthetic equity,-50000\n"
    b"4000,Synthetic revenue,-300000\n"
    b"5000,Synthetic expenses,310000\n"
)
SCHEDULES = [
    {"code": "a", "name": "Cash and bank", "section": "asset"},
    {"code": "B", "name": "Payables", "section": "liability"},
    {"code": "C", "name": "Equity", "section": "equity"},
    {"code": "R", "name": "Revenue", "section": "income"},
]
MAPPINGS = [
    {"account_code": "1000", "lead_code": "A"},
    {"account_code": "1100", "lead_code": "a"},
    {"account_code": "2000", "lead_code": "B"},
    {"account_code": "3000", "lead_code": "C"},
    {"account_code": "4000", "lead_code": "R"},
    {"account_code": "7777", "lead_code": "R"},
]


def test_lead_schedules_workpaper_and_materiality(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    cy = dataset(analyst, entity, "trial_balance", CY_TB)
    py = dataset(analyst, entity, "trial_balance", PY_TB)
    eid = new_engagement(reviewer, entity.id).json()["id"]

    assert viewer.get(f"/api/engagements/{eid}/lead-report").status_code == 422  # no TB yet
    setup = {"cy_tb_version_id": cy, "py_tb_version_id": py}
    assert analyst.put(f"/api/engagements/{eid}/setup", json=setup).status_code == 403
    assert (
        reviewer.put(
            f"/api/engagements/{eid}/setup", json={**setup, "py_tb_version_id": cy}
        ).status_code
        == 422
    )
    assert (
        reviewer.put(
            f"/api/engagements/{eid}/setup", json={**setup, "rules_prefix": "syn.audit"}
        ).status_code
        == 422
    )
    r = reviewer.put(
        f"/api/engagements/{eid}/setup",
        json={**setup, "rule_pack_version_id": rpv, "rules_prefix": "syn.audit"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cy_tb_version_id"] == cy

    assert (
        viewer.put(
            f"/api/engagements/{eid}/lead-schedules", json={"schedules": SCHEDULES}
        ).status_code
        == 403
    )
    dup = analyst.put(
        f"/api/engagements/{eid}/lead-schedules", json={"schedules": [*SCHEDULES, SCHEDULES[0]]}
    )
    assert dup.status_code == 422
    s = analyst.put(f"/api/engagements/{eid}/lead-schedules", json={"schedules": SCHEDULES})
    assert [x["code"] for x in s.json()] == ["A", "B", "C", "R"]
    bad_map = analyst.put(
        f"/api/engagements/{eid}/account-mappings",
        json={"mappings": [{"account_code": "1000", "lead_code": "Z"}]},
    )
    assert bad_map.status_code == 422
    m = analyst.put(f"/api/engagements/{eid}/account-mappings", json={"mappings": MAPPINGS})
    assert m.status_code == 200, m.text
    # A schedule with mapped accounts cannot be dropped.
    assert (
        analyst.put(
            f"/api/engagements/{eid}/lead-schedules", json={"schedules": SCHEDULES[1:]}
        ).status_code
        == 422
    )

    rep = viewer.get(f"/api/engagements/{eid}/lead-report").json()
    by = {x["code"]: x for x in rep["schedules"]}
    assert Decimal(by["A"]["cy"]) == 200000 and Decimal(by["A"]["py"]) == 120000
    assert Decimal(by["A"]["movement"]) == 80000
    assert Decimal(by["A"]["change_share"]) == Decimal("0.6667")
    assert [a["account_code"] for a in by["A"]["accounts"]] == ["1000", "1100"]
    assert Decimal(by["B"]["change_share"]) == Decimal("-0.5")
    assert [u["account_code"] for u in rep["unmapped"]] == ["5000"]
    assert Decimal(rep["unmapped"][0]["py"]) == 310000
    assert rep["missing_accounts"] == ["7777"]
    assert Decimal(rep["cy_net"]) == 0 and Decimal(rep["py_net"]) == 0
    assert rep["current"]["id"] == cy and rep["prior"]["id"] == py

    # Audit workpapers come from the engagement, never from the tax endpoint.
    assert (
        new_paper(analyst, entity.id, rpv, kind="materiality", rules_prefix="syn.audit").status_code
        == 422
    )
    wp = analyst.post(
        f"/api/engagements/{eid}/workpapers",
        json={"kind": "lead_schedule", "title": "Synthetic leads"},
    )
    assert wp.status_code == 201, wp.text
    paper = wp.json()
    assert paper["engagement_id"] == eid and paper["computed_at"]
    got = lines(paper)
    assert Decimal(got["calc:lead_a_movement"]["amount"]) == 80000
    assert got["calc:lead_a_change"]["value"] == "0.6667"
    ev = got["lead_a_cy"]["evidence"][0]
    assert ev["dataset_version_id"] == cy and ev["account_codes"] == ["1000", "1100"]
    assert len(ev["row_ids"]) == 2
    wid = paper["id"]

    # Preparer step, then a different reviewer signs off.
    assert reviewer.post(f"/api/workpapers/{wid}/sign-off").status_code == 422  # not prepared
    assert viewer.post(f"/api/workpapers/{wid}/prepare").status_code == 403
    prep = reviewer.post(f"/api/workpapers/{wid}/prepare")
    assert prep.status_code == 200 and prep.json()["prepared_by_name"]
    assert reviewer.post(f"/api/workpapers/{wid}/sign-off").status_code == 422  # same person
    assert analyst.post(f"/api/workpapers/{wid}/sign-off").status_code == 403
    signed = admin.post(f"/api/workpapers/{wid}/sign-off")
    assert signed.status_code == 200, signed.text
    snap = admin.get(f"/api/workpapers/{wid}/snapshots/1").json()
    assert snap["prepared_by"] and snap["engagement_id"] == eid
    assert (
        admin.post(
            f"/api/workpapers/{wid}/reopen", json={"reason": "Synthetic late adjustment"}
        ).status_code
        == 200
    )
    reopened = admin.get(f"/api/workpapers/{wid}").json()
    assert reopened["prepared_by_name"] is None
    assert analyst.post(f"/api/workpapers/{wid}/reload-leads").status_code == 200

    # Materiality with the team's percentages and rationale.
    mat = analyst.post(
        f"/api/engagements/{eid}/workpapers",
        json={"kind": "materiality", "title": "Synthetic materiality"},
    )
    assert mat.status_code == 201, mat.text
    mid = mat.json()["id"]
    assert put_in(analyst, mid, "benchmark_type", value="profit_before_tax").status_code == 200
    assert put_in(analyst, mid, "benchmark", amount="1500000").status_code == 200
    for key, v in (("overall_pct", "0.05"), ("performance_pct", "0.7"), ("trivial_pct", "0.1")):
        assert put_in(analyst, mid, key, amount=v).status_code == 200
    assert analyst.post(f"/api/workpapers/{mid}/compute").status_code == 422  # no rationale
    assert (
        put_in(analyst, mid, "rationale", value="Synthetic: profit-focused users").status_code
        == 200
    )
    out = analyst.post(f"/api/workpapers/{mid}/compute")
    assert out.status_code == 200, out.text
    ml = lines(out.json())
    assert Decimal(ml["calc:overall"]["amount"]) == Decimal("75000.00")
    assert Decimal(ml["calc:performance"]["amount"]) == Decimal("52500.00")
    assert Decimal(ml["calc:trivial"]["amount"]) == Decimal("7500.00")
    assert ml["calc:check:trivial"]["value"] == "outside"
    assert out.json()["warnings"]  # synthetic draft rules are flagged
    listed = viewer.get(f"/api/engagements/{eid}/workpapers").json()
    assert {x["kind"] for x in listed} == {"lead_schedule", "materiality"}


def test_lead_schedule_validation_and_tenancy(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    other_entity = make_entity(db, tenant_a)
    eid = new_engagement(admin, entity.id).json()["id"]
    sales = dataset(
        analyst,
        entity,
        "sales_register",
        b"invoice_number,invoice_date,net_amount,tax_amount\nS1,2026-01-01,100,5\n",
    )
    foreign_tb = dataset(analyst, other_entity, "trial_balance", CY_TB)
    assert (
        admin.put(f"/api/engagements/{eid}/setup", json={"cy_tb_version_id": sales}).status_code
        == 422
    )
    assert (
        admin.put(
            f"/api/engagements/{eid}/setup", json={"cy_tb_version_id": foreign_tb}
        ).status_code
        == 422
    )
    assert (
        analyst.post(
            f"/api/engagements/{eid}/workpapers", json={"kind": "materiality", "title": "x"}
        ).status_code
        == 422
    )

    b_admin = login(tenant_b.users[Role.ORG_ADMIN])
    b_entity = make_entity(db, tenant_b)
    b_tb = dataset(b_admin, b_entity, "trial_balance", PY_TB)
    b_rpv = ct_pack(b_admin)
    assert (
        admin.put(f"/api/engagements/{eid}/setup", json={"cy_tb_version_id": b_tb}).status_code
        == 404
    )
    assert (
        admin.put(
            f"/api/engagements/{eid}/setup",
            json={"rule_pack_version_id": b_rpv, "rules_prefix": "syn.audit"},
        ).status_code
        == 404
    )
    for path in ("lead-report", "lead-schedules", "account-mappings", "workpapers"):
        assert b_admin.get(f"/api/engagements/{eid}/{path}").status_code == 404
    assert (
        b_admin.put(f"/api/engagements/{eid}/lead-schedules", json={"schedules": []}).status_code
        == 404
    )
    assert (
        b_admin.put(f"/api/engagements/{eid}/account-mappings", json={"mappings": []}).status_code
        == 404
    )
    assert (
        b_admin.post(
            f"/api/engagements/{eid}/workpapers", json={"kind": "materiality", "title": "x"}
        ).status_code
        == 404
    )
