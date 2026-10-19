"""Phase D4: risk register per assertion, procedures and audit programmes."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import ApiClient, Tenant, login, upload
from tests.test_datasets import make_entity
from tests.test_engagements import new_engagement

MANUAL = {"type": "manual"}


def programme(client: ApiClient, publish: bool = True, kind: str = "audit_programme") -> str:
    r = client.post(
        "/api/checklists",
        json={
            "name": f"Synthetic audit programme {uuid.uuid4().hex[:4]}",
            "kind": kind,
            "requirements": [
                {
                    "code": "REV-1",
                    "title": "Test revenue cut-off",
                    "severity": "high",
                    "check_config": MANUAL,
                },
                {
                    "code": "CASH-1",
                    "title": "Confirm bank balances",
                    "severity": "high",
                    "check_config": MANUAL,
                },
            ],
        },
    )
    assert r.status_code == 201, r.text
    if publish:
        assert client.post(f"/api/checklist-versions/{r.json()['id']}/publish").status_code == 200
    return str(r.json()["id"])


def risk(client: ApiClient, eid: str, ref: str, **over: Any):  # type: ignore[no-untyped-def]
    body = {
        "ref": ref,
        "title": f"Synthetic risk {ref}",
        "assertions": ["occurrence", "cut_off"],
        "inherent_risk": "high",
        **over,
    }
    return client.post(f"/api/engagements/{eid}/risks", json=body)


def test_risks_procedures_and_programme(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]

    r1 = risk(analyst, eid, "R1", significant=True, fraud=True)
    assert r1.status_code == 201, r1.text
    r2 = risk(analyst, eid, "R2", assertions=["existence"], inherent_risk="medium")
    r3 = risk(analyst, eid, "R3", assertions=["valuation"], inherent_risk="low", significant=True)
    assert risk(analyst, eid, "R1").status_code == 422  # duplicate ref
    assert risk(analyst, eid, "R9", assertions=["existence", "existence"]).status_code == 422
    assert risk(analyst, eid, "R9", assertions=["solvency"]).status_code == 422
    assert risk(analyst, eid, "R9", lead_code="ZZ").status_code == 422  # no such lead schedule
    assert risk(viewer, eid, "R9").status_code == 403

    pid = programme(reviewer)
    draft = programme(reviewer, publish=False)
    policy = programme(reviewer, kind="internal_policy")
    assert (
        analyst.post(
            f"/api/engagements/{eid}/programme", json={"checklist_version_id": draft}
        ).status_code
        == 422
    )
    assert (
        analyst.post(
            f"/api/engagements/{eid}/programme", json={"checklist_version_id": policy}
        ).status_code
        == 422
    )
    procs = analyst.post(f"/api/engagements/{eid}/programme", json={"checklist_version_id": pid})
    assert procs.status_code == 200, procs.text
    assert sorted(p["requirement_code"] for p in procs.json()) == ["CASH-1", "REV-1"]
    again = analyst.post(f"/api/engagements/{eid}/programme", json={"checklist_version_id": pid})
    assert len(again.json()) == 2  # already planned requirements are skipped

    rev = next(p for p in procs.json() if p["requirement_code"] == "REV-1")
    upd = analyst.put(
        f"/api/procedures/{rev['id']}",
        json={
            "title": rev["title"],
            "requirement_id": rev["requirement_id"],
            "assignee_id": str(tenant_a.users[Role.ANALYST].id),
            "risk_ids": [r1.json()["id"], r2.json()["id"]],
        },
    )
    assert upd.status_code == 200, upd.text
    assert set(upd.json()["risk_ids"]) == {r1.json()["id"], r2.json()["id"]}
    assert upd.json()["assignee_name"]

    cov = viewer.get(f"/api/engagements/{eid}/risk-coverage").json()
    assert cov["uncovered"] == ["R3"]
    assert cov["significant_open"] == ["R1", "R3"]
    assert len(cov["unlinked_procedures"]) == 1

    done = {"status": "done", "conclusion": ""}
    assert analyst.post(f"/api/procedures/{rev['id']}/status", json=done).status_code == 422
    ok = analyst.post(
        f"/api/procedures/{rev['id']}/status",
        json={"status": "done", "conclusion": "Synthetic: no cut-off exceptions in 25 items."},
    )
    assert ok.status_code == 200 and ok.json()["completed_at"]
    cov = viewer.get(f"/api/engagements/{eid}/risk-coverage").json()
    assert cov["significant_open"] == ["R3"]
    r1_cov = next(x for x in cov["risks"] if x["ref"] == "R1")
    assert r1_cov["procedures"] == 1 and r1_cov["done"] == 1

    # A procedure can only cite a review linked to this engagement.
    doc = upload(analyst).json()
    review = analyst.post(
        "/api/reviews",
        json={
            "title": "Synthetic programme review",
            "checklist_version_id": pid,
            "document_version_id": doc["latest_version"]["id"],
        },
    )
    assert review.status_code == 201, review.text
    rid = review.json()["id"]
    body = {"title": "Synthetic walkthrough", "review_id": rid, "risk_ids": [r3.json()["id"]]}
    assert analyst.post(f"/api/engagements/{eid}/procedures", json=body).status_code == 422
    assert viewer.post(f"/api/engagements/{eid}/reviews/{rid}").status_code == 403
    assert analyst.post(f"/api/engagements/{eid}/reviews/{rid}").status_code == 204
    walk = analyst.post(f"/api/engagements/{eid}/procedures", json=body)
    assert walk.status_code == 201, walk.text
    assert [x["id"] for x in viewer.get(f"/api/engagements/{eid}/reviews").json()] == [rid]
    other_e = new_engagement(reviewer, entity.id).json()["id"]
    assert analyst.post(f"/api/engagements/{other_e}/reviews/{rid}").status_code == 422

    listed = viewer.get(f"/api/engagements/{eid}/risks").json()
    assert [x["ref"] for x in listed] == ["R1", "R2", "R3"]
    assert analyst.delete(f"/api/risks/{r2.json()['id']}").status_code == 204
    assert len(viewer.get(f"/api/engagements/{eid}/risks").json()) == 2


def test_risk_tenancy(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    rid = risk(analyst, eid, "R1").json()["id"]
    pid = analyst.post(f"/api/engagements/{eid}/procedures", json={"title": "Synthetic"}).json()[
        "id"
    ]

    b = login(tenant_b.users[Role.ORG_ADMIN])
    b_reviewer = login(tenant_b.users[Role.REVIEWER])
    b_prog = programme(b_reviewer)
    assert (
        analyst.post(
            f"/api/engagements/{eid}/programme", json={"checklist_version_id": b_prog}
        ).status_code
        == 404
    )
    for path in ("risks", "procedures", "risk-coverage", "reviews"):
        assert b.get(f"/api/engagements/{eid}/{path}").status_code == 404
    assert risk(b, eid, "R2").status_code == 404
    assert (
        b.put(
            f"/api/risks/{rid}",
            json={"ref": "R1", "title": "x", "assertions": ["existence"], "inherent_risk": "low"},
        ).status_code
        == 404
    )
    assert b.delete(f"/api/risks/{rid}").status_code == 404
    assert (
        b.post(f"/api/procedures/{pid}/status", json={"status": "in_progress"}).status_code == 404
    )
    # Foreign risk ids and assignees are refused.
    b_entity = make_entity(db, tenant_b)
    b_eid = new_engagement(b, b_entity.id).json()["id"]
    b_risk = risk(b, b_eid, "R1").json()["id"]
    assert (
        analyst.post(
            f"/api/engagements/{eid}/procedures", json={"title": "x", "risk_ids": [b_risk]}
        ).status_code
        == 404
    )
    foreign_user = str(tenant_b.users[Role.ANALYST].id)
    assert (
        analyst.post(
            f"/api/engagements/{eid}/procedures", json={"title": "x", "assignee_id": foreign_user}
        ).status_code
        == 404
    )
