"""Phase D7: confirmations, adjustments schedule and the summary of unadjusted differences.

Signed materiality: profit before tax 1500000 × 0.05 = 75000.00 overall; clearly
trivial 75000 × 0.1 = 7500.00.
  AJE1 Dr 5000 expense 6000 / Cr 2000 payables 6000: profit −6000, net assets −6000
  AJE2 Dr 1000 cash 80000 / Cr 4000 revenue 80000: profit +80000, net assets +80000
  Passed AJE1 + AJE2: profit 74000, net assets 74000 → below 75000; AJE1 ≤ 7500 is trivial.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import ApiClient, Tenant, login, upload
from tests.test_datasets import make_entity
from tests.test_engagements import new_engagement
from tests.test_lead_schedules import CY_TB, PY_TB
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack, put_in

SCHEDULES = [
    {"code": "A", "name": "Cash", "section": "asset"},
    {"code": "B", "name": "Payables", "section": "liability"},
    {"code": "C", "name": "Equity", "section": "equity"},
    {"code": "R", "name": "Revenue", "section": "income"},
    {"code": "E", "name": "Expenses", "section": "expense"},
]
MAPPINGS = [
    {"account_code": a, "lead_code": c}
    for a, c in (
        ("1000", "A"),
        ("1100", "A"),
        ("2000", "B"),
        ("3000", "C"),
        ("4000", "R"),
        ("5000", "E"),
    )
]


def engagement_with_materiality(db: Session, tenant: Tenant) -> tuple[str, dict[Role, ApiClient]]:
    c = {
        r: login(tenant.users[r])
        for r in (Role.ORG_ADMIN, Role.REVIEWER, Role.ANALYST, Role.VIEWER)
    }
    entity = make_entity(db, tenant)
    rpv = ct_pack(c[Role.ORG_ADMIN])
    cy = dataset(c[Role.ANALYST], entity, "trial_balance", CY_TB)
    py = dataset(c[Role.ANALYST], entity, "trial_balance", PY_TB)
    eid = new_engagement(c[Role.REVIEWER], entity.id).json()["id"]
    setup = {
        "cy_tb_version_id": cy,
        "py_tb_version_id": py,
        "rule_pack_version_id": rpv,
        "rules_prefix": "syn.audit",
    }
    assert c[Role.REVIEWER].put(f"/api/engagements/{eid}/setup", json=setup).status_code == 200
    a = c[Role.ANALYST]
    assert (
        a.put(f"/api/engagements/{eid}/lead-schedules", json={"schedules": SCHEDULES}).status_code
        == 200
    )
    assert (
        a.put(f"/api/engagements/{eid}/account-mappings", json={"mappings": MAPPINGS}).status_code
        == 200
    )
    mid = a.post(
        f"/api/engagements/{eid}/workpapers", json={"kind": "materiality", "title": "Synthetic"}
    ).json()["id"]
    put_in(a, mid, "benchmark_type", value="profit_before_tax")
    put_in(a, mid, "rationale", value="Synthetic rationale")
    put_in(a, mid, "benchmark", amount="1500000")
    for k, v in (("overall_pct", "0.05"), ("performance_pct", "0.7"), ("trivial_pct", "0.1")):
        put_in(a, mid, k, amount=v)
    assert a.post(f"/api/workpapers/{mid}/compute").status_code == 200
    assert a.post(f"/api/workpapers/{mid}/prepare").status_code == 200
    assert c[Role.REVIEWER].post(f"/api/workpapers/{mid}/sign-off").status_code == 200
    return eid, c


def adj(ref: str, lines: list[tuple[str, str, str]], **over: Any) -> dict[str, Any]:
    return {
        "ref": ref,
        "description": f"Synthetic adjustment {ref}",
        "lines": [{"account_code": a, "debit": d, "credit": cr} for a, d, cr in lines],
        **over,
    }


def test_adjustments_and_sud(tenant_a: Tenant, db: Session) -> None:
    eid, c = engagement_with_materiality(db, tenant_a)
    analyst, reviewer, viewer = c[Role.ANALYST], c[Role.REVIEWER], c[Role.VIEWER]
    url = f"/api/engagements/{eid}/adjustments"
    assert (
        analyst.post(url, json=adj("X", [("5000", "10", "0"), ("2000", "0", "9")])).status_code
        == 422
    )
    assert (
        analyst.post(url, json=adj("X", [("5000", "10", "10"), ("2000", "0", "0")])).status_code
        == 422
    )
    assert (
        viewer.post(url, json=adj("X", [("5000", "1", "0"), ("2000", "0", "1")])).status_code == 403
    )
    a1 = analyst.post(url, json=adj("AJE1", [("5000", "6000", "0"), ("2000", "0", "6000")]))
    assert a1.status_code == 201, a1.text
    assert (
        Decimal(a1.json()["profit_effect"]) == -6000
        and Decimal(a1.json()["net_assets_effect"]) == -6000
    )
    a2 = analyst.post(
        url, json=adj("AJE2", [("1000", "80000", "0"), ("4000", "0", "80000")])
    ).json()
    assert Decimal(a2["profit_effect"]) == 80000 and Decimal(a2["net_assets_effect"]) == 80000
    a3 = analyst.post(url, json=adj("AJE3", [("9999", "100", "0"), ("1000", "0", "100")])).json()
    assert a3["unmapped_accounts"] == ["9999"]
    assert (
        analyst.post(url, json=adj("AJE1", [("5000", "1", "0"), ("2000", "0", "1")])).status_code
        == 422
    )

    def decide(client: ApiClient, aid: str, status: str, reason: str = "") -> int:
        return int(
            client.post(
                f"/api/adjustments/{aid}/status", json={"status": status, "reason": reason}
            ).status_code
        )

    assert decide(analyst, a1.json()["id"], "passed", "Synthetic: trivial") == 403
    assert decide(reviewer, a1.json()["id"], "passed") == 422
    assert decide(reviewer, a1.json()["id"], "passed", "Synthetic: below trivial") == 200
    assert decide(reviewer, a2["id"], "passed", "Synthetic: management declined") == 200
    assert decide(analyst, a3["id"], "recorded") == 200
    # A decided adjustment cannot be edited until it is reopened with a reason.
    upd = adj("AJE3", [("9999", "200", "0"), ("1000", "0", "200")])
    assert analyst.put(f"/api/adjustments/{a3['id']}", json=upd).status_code == 422
    assert decide(analyst, a3["id"], "proposed") == 422
    assert decide(analyst, a3["id"], "proposed", "Synthetic: client reversed it") == 200
    assert analyst.put(f"/api/adjustments/{a3['id']}", json=upd).status_code == 200

    s = viewer.get(f"/api/engagements/{eid}/sud").json()
    assert [x["ref"] for x in s["adjustments"]] == ["AJE1", "AJE2"]
    assert Decimal(s["profit_effect"]) == 74000 and Decimal(s["net_assets_effect"]) == 74000
    assert s["total_vs_overall"] == "below"
    assert s["clearly_trivial"] == ["AJE1"]
    assert Decimal(s["materiality"]["overall"]) == Decimal("75000.00")
    assert s["steps"]


def test_confirmations(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    url = f"/api/engagements/{eid}/confirmations"
    body = {
        "type": "bank",
        "counterparty": "Synthetic Bank",
        "reference": "BANK-01",
        "book_amount": "200000",
    }
    assert (
        analyst.post(url, json={**body, "reference": "AE07 0331 2345 6789 0123 456"}).status_code
        == 422
    )
    c = analyst.post(url, json=body)
    assert c.status_code == 201, c.text
    cid = c.json()["id"]
    assert c.json()["status"] == "planned" and c.json()["currency"] == "AED"

    def move(**b: Any) -> Any:
        return analyst.post(f"/api/confirmations/{cid}/status", json=b)

    assert (
        move(status="responded", responded_on="2026-01-20", confirmed_amount="1").status_code == 422
    )
    assert move(status="sent").status_code == 422
    assert move(status="sent", sent_on="2026-01-10").status_code == 200
    doc = upload(analyst, title="Synthetic bank reply").json()["id"]
    assert (
        move(status="responded", responded_on="2026-01-05", confirmed_amount="195000").status_code
        == 422
    )
    r = move(
        status="responded",
        responded_on="2026-01-20",
        confirmed_amount="195000",
        response_document_id=doc,
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["difference"]) == 5000
    assert move(status="closed").status_code == 422
    done = move(status="closed", conclusion="Synthetic: difference is an uncleared cheque, traced.")
    assert done.status_code == 200 and done.json()["status"] == "closed"
    assert move(status="sent", sent_on="2026-02-01").status_code == 422

    b = login(tenant_b.users[Role.ORG_ADMIN])
    b_doc = upload(b, title="Synthetic foreign").json()["id"]
    c2 = analyst.post(
        url, json={**body, "type": "receivable", "counterparty": "Synthetic Customer"}
    ).json()["id"]
    analyst.post(
        f"/api/confirmations/{c2}/status", json={"status": "sent", "sent_on": "2026-01-10"}
    )
    foreign = analyst.post(
        f"/api/confirmations/{c2}/status",
        json={
            "status": "responded",
            "responded_on": "2026-01-11",
            "confirmed_amount": "1",
            "response_document_id": b_doc,
        },
    )
    assert foreign.status_code == 404
    assert b.get(url).status_code == 404
    assert b.post(url, json=body).status_code == 404
    assert (
        b.post(
            f"/api/confirmations/{cid}/status", json={"status": "closed", "conclusion": "x"}
        ).status_code
        == 404
    )
    assert b.get(f"/api/engagements/{eid}/adjustments").status_code == 404
    assert b.get(f"/api/engagements/{eid}/sud").status_code == 404
    assert (
        b.post(
            f"/api/engagements/{eid}/adjustments", json=adj("X", [("1", "1", "0"), ("2", "0", "1")])
        ).status_code
        == 404
    )
    assert len(analyst.get(url).json()) == 2
