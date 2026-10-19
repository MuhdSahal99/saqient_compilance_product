"""Phase D1: audit engagements, team, phases and budget versus actual hours."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import ApiClient, Tenant, login
from tests.test_datasets import make_entity


def new_engagement(client: ApiClient, entity_id: Any, **over: Any):  # type: ignore[no-untyped-def]
    body = {
        "entity_id": str(entity_id),
        "kind": "external_audit",
        "name": f"Synthetic FY2025 audit {uuid.uuid4().hex[:4]}",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        **over,
    }
    return client.post("/api/engagements", json=body)


def test_engagement_lifecycle_and_hours(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    r = new_engagement(reviewer, entity.id)
    assert r.status_code == 201, r.text
    e = r.json()
    eid = e["id"]
    assert e["status"] == "planning" and e["currency"] == "AED"
    assert [p["phase"] for p in e["phases"]] == ["planning", "fieldwork", "completion", "reporting"]

    an = tenant_a.users[Role.ANALYST]
    rv = tenant_a.users[Role.REVIEWER]
    assert (
        reviewer.put(
            f"/api/engagements/{eid}/members/{rv.id}", json={"role": "manager"}
        ).status_code
        == 200
    )
    # Analysts cannot staff the engagement; non-members cannot record time.
    assert (
        analyst.put(f"/api/engagements/{eid}/members/{an.id}", json={"role": "staff"}).status_code
        == 403
    )
    entry = {"phase": "planning", "work_date": "2026-01-05", "hours": "3.5"}
    assert analyst.post(f"/api/engagements/{eid}/time-entries", json=entry).status_code == 422
    assert (
        reviewer.put(f"/api/engagements/{eid}/members/{an.id}", json={"role": "staff"}).status_code
        == 200
    )
    assert (
        reviewer.put(
            f"/api/engagements/{eid}/members/{uuid.uuid4()}", json={"role": "staff"}
        ).status_code
        == 404
    )

    b = reviewer.put(
        f"/api/engagements/{eid}/budget",
        json={
            "phases": [{"phase": "planning", "hours": "10"}, {"phase": "fieldwork", "hours": "40"}]
        },
    )
    assert b.status_code == 200, b.text
    dup = reviewer.put(
        f"/api/engagements/{eid}/budget",
        json={"phases": [{"phase": "planning", "hours": "1"}, {"phase": "planning", "hours": "2"}]},
    )
    assert dup.status_code == 422

    t1 = analyst.post(f"/api/engagements/{eid}/time-entries", json=entry)
    assert t1.status_code == 201, t1.text
    t2 = analyst.post(
        f"/api/engagements/{eid}/time-entries",
        json={"phase": "planning", "work_date": "2026-01-06", "hours": "8"},
    )
    reviewer.post(
        f"/api/engagements/{eid}/time-entries",
        json={"phase": "fieldwork", "work_date": "2026-02-01", "hours": "6.25"},
    )
    assert (
        analyst.post(
            f"/api/engagements/{eid}/time-entries", json={**entry, "hours": "25"}
        ).status_code
        == 422
    )
    assert viewer.post(f"/api/engagements/{eid}/time-entries", json=entry).status_code == 403

    got = viewer.get(f"/api/engagements/{eid}").json()
    phases = {p["phase"]: p for p in got["phases"]}
    # Planning: budget 10, actual 3.5 + 8 = 11.5, overrun 1.5, used 1.15.
    assert Decimal(phases["planning"]["actual_hours"]) == Decimal("11.5")
    assert Decimal(phases["planning"]["variance_hours"]) == Decimal("-1.5")
    assert Decimal(phases["planning"]["used_share"]) == Decimal("1.15")
    # Fieldwork: 6.25 of 40 = 0.15625 -> 0.1563 (4 dp).
    assert Decimal(phases["fieldwork"]["used_share"]) == Decimal("0.1563")
    assert phases["completion"]["used_share"] is None
    assert Decimal(got["budget_hours"]) == 50 and Decimal(got["actual_hours"]) == Decimal("17.75")
    members = {m["role"]: m for m in got["members"]}
    assert Decimal(members["staff"]["actual_hours"]) == Decimal("11.5")
    assert [m["role"] for m in got["members"]] == ["manager", "staff"]

    # Only the recorder or a reviewer can delete an entry.
    rv_entry = [
        t
        for t in viewer.get(f"/api/engagements/{eid}/time-entries").json()
        if t["user_id"] == str(rv.id)
    ][0]
    assert analyst.delete(f"/api/time-entries/{rv_entry['id']}").status_code == 403
    assert analyst.delete(f"/api/time-entries/{t2.json()['id']}").status_code == 204
    assert reviewer.delete(f"/api/time-entries/{t1.json()['id']}").status_code == 204

    # Status: forward one phase at a time; back needs a reason.
    def move(to: str, reason: str = "") -> int:
        return int(
            reviewer.post(
                f"/api/engagements/{eid}/status", json={"status": to, "reason": reason}
            ).status_code
        )

    assert move("completion") == 422
    assert (
        analyst.post(f"/api/engagements/{eid}/status", json={"status": "fieldwork"}).status_code
        == 403
    )
    assert move("fieldwork") == 200
    assert move("planning") == 422
    assert move("planning", "Scope extended by the synthetic client") == 200
    for s in ("fieldwork", "completion", "reporting", "closed"):
        assert move(s) == 200
    closed = viewer.get(f"/api/engagements/{eid}").json()
    assert closed["status"] == "closed" and closed["closed_at"]
    assert analyst.post(f"/api/engagements/{eid}/time-entries", json=entry).status_code == 409
    assert move("reporting", "Subsequent event to assess") == 200

    events = reviewer.get("/api/audit-events", params={"object_id": eid, "page_size": 200})
    actions = [ev["action"] for ev in events.json()["items"]]
    assert actions.count("engagement.status_changed") == 7
    assert {"engagement.created", "engagement.budget_set", "engagement.time_deleted"} <= set(
        actions
    )

    listed = viewer.get("/api/engagements", params={"status": "reporting"}).json()
    assert [x["id"] for x in listed] == [eid]


def test_engagement_validation_and_tenancy(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    assert new_engagement(analyst, entity.id).status_code == 403
    bad = new_engagement(reviewer, entity.id, period_end="2024-12-31")
    assert bad.status_code == 422
    assert new_engagement(reviewer, entity.id, kind="tax_audit").status_code == 422
    eid = new_engagement(reviewer, entity.id).json()["id"]

    other = login(tenant_b.users[Role.ORG_ADMIN])
    other_entity = make_entity(db, tenant_b)
    assert new_engagement(other, entity.id).status_code == 404
    assert other.get(f"/api/engagements/{eid}").status_code == 404
    assert other.get(f"/api/engagements/{eid}/time-entries").status_code == 404
    assert (
        other.post(f"/api/engagements/{eid}/status", json={"status": "fieldwork"}).status_code
        == 404
    )
    assert other.put(f"/api/engagements/{eid}/budget", json={"phases": []}).status_code == 404
    assert other.get("/api/engagements").json() == []
    # A user from another organisation cannot be added to the team.
    foreign = tenant_b.users[Role.ANALYST]
    assert (
        reviewer.put(
            f"/api/engagements/{eid}/members/{foreign.id}", json={"role": "staff"}
        ).status_code
        == 404
    )
    oe = new_engagement(other, other_entity.id).json()["id"]
    assert reviewer.get(f"/api/engagements/{oe}").status_code == 404
    assert reviewer.delete(f"/api/time-entries/{uuid.uuid4()}").status_code == 404
