from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from app.models import AuditEvent, Finding, ReportSnapshot, Role
from tests.conftest import ApiClient, Tenant, login, ready_version_id


def start_review(client: ApiClient, tenant: Tenant) -> dict:  # type: ignore[type-arg]
    vid = ready_version_id(client)
    r = client.post(
        "/api/reviews",
        json={
            "title": "Synthetic review",
            "document_version_id": vid,
            "checklist_version_id": str(tenant.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.status_code == 201, r.text
    return r.json()


def findings(client: ApiClient, review_id: str) -> list[dict]:  # type: ignore[type-arg]
    return client.get("/api/findings", params={"review_id": review_id}).json()["items"]


def test_review_run_creates_results_and_proposed_findings(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    review = start_review(client, tenant_a)
    review = client.get(f"/api/reviews/{review['id']}").json()
    assert review["status"] == "in_review"
    run = review["latest_run"]
    assert run["job"]["status"] == "completed"
    assert run["engine_version"].startswith("deterministic-")
    assert "AI disabled" in run["engine_mode"]
    results = client.get(f"/api/reviews/{review['id']}/results").json()
    by_code = {r["requirement_code"]: r for r in results}
    assert len(results) == 8
    assert by_code["DEMO-01"]["outcome"] == "match_found"
    assert by_code["DEMO-01"]["evidence"][0]["paragraph_number"] is not None
    assert by_code["DEMO-05"]["outcome"] == "match_found" and by_code["DEMO-05"]["needs_attention"]
    assert by_code["DEMO-06"]["outcome"] == "no_match_found"
    assert by_code["DEMO-08"]["outcome"] == "needs_human_review"
    fs = findings(client, review["id"])
    assert {f["requirement_code"] for f in fs} == {"DEMO-05", "DEMO-06", "DEMO-08"}
    assert all(f["status"] == "proposed" for f in fs)  # automated ≠ decided


def test_review_requires_ready_document_and_published_checklist(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    from app.models import ChecklistState

    client = login(tenant_a.users[Role.REVIEWER])
    vid = ready_version_id(client)
    tenant_a.checklist_version.state = ChecklistState.DRAFT  # type: ignore[union-attr]
    db.add(tenant_a.checklist_version)
    db.commit()
    r = client.post(
        "/api/reviews",
        json={
            "title": "x",
            "document_version_id": vid,
            "checklist_version_id": str(tenant_a.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.status_code == 422 and "published" in r.json()["detail"]


def test_rerun_does_not_duplicate_findings(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.REVIEWER])
    review = start_review(client, tenant_a)
    before = len(findings(client, review["id"]))
    r = client.post(f"/api/reviews/{review['id']}/runs")
    assert r.status_code == 200
    assert r.json()["latest_run"]["job"]["status"] == "completed"
    assert len(findings(client, review["id"])) == before


def test_decisions_assignment_signoff_and_reopen(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    review = start_review(analyst, tenant_a)
    fs = {f["requirement_code"]: f for f in findings(reviewer, review["id"])}

    # Analysts and viewers cannot decide.
    assert (
        analyst.post(
            f"/api/findings/{fs['DEMO-05']['id']}/decision", json={"decision": "confirmed"}
        ).status_code
        == 403
    )
    assert (
        viewer.post(
            f"/api/findings/{fs['DEMO-05']['id']}/decision", json={"decision": "confirmed"}
        ).status_code
        == 403
    )

    # Dismissal and accepted risk need a rationale.
    r = reviewer.post(
        f"/api/findings/{fs['DEMO-08']['id']}/decision", json={"decision": "dismissed"}
    )
    assert r.status_code == 409 and "rationale" in r.json()["detail"]
    r = reviewer.post(
        f"/api/findings/{fs['DEMO-08']['id']}/decision",
        json={"decision": "accepted_risk", "rationale": "Approval minutes held offline."},
    )
    assert r.status_code == 200 and r.json()["status"] == "accepted_risk"

    # Cannot sign off with undecided findings.
    r = reviewer.post(f"/api/reviews/{review['id']}/signoff")
    assert r.status_code == 409 and "need a reviewer decision" in r.json()["detail"]

    r = reviewer.post(
        f"/api/findings/{fs['DEMO-05']['id']}/decision",
        json={"decision": "dismissed", "rationale": "Quoted as a bad example."},
    )
    assert r.status_code == 200
    r = reviewer.post(
        f"/api/findings/{fs['DEMO-06']['id']}/decision",
        json={"decision": "confirmed", "rationale": "No access review clause."},
    )
    assert r.json()["decided_by_name"] == "reviewer a"

    # Assign remediation (only confirmed findings; owner must be a member).
    analyst_id = str(tenant_a.users[Role.ANALYST].id)
    due = (date.today() - timedelta(days=1)).isoformat()
    r = reviewer.post(
        f"/api/findings/{fs['DEMO-05']['id']}/assignment", json={"owner_id": analyst_id}
    )
    assert r.status_code == 409
    r = reviewer.post(
        f"/api/findings/{fs['DEMO-06']['id']}/assignment",
        json={"owner_id": analyst_id, "due_date": due},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "remediation_in_progress" and r.json()["is_overdue"]
    tasks = analyst.get("/api/findings", params={"owner": "me"}).json()["items"]
    assert [t["id"] for t in tasks] == [fs["DEMO-06"]["id"]]

    # Sign off creates report v1; decisions are then locked.
    r = reviewer.post(f"/api/reviews/{review['id']}/signoff")
    assert r.status_code == 200 and r.json()["version"] == 1
    r = reviewer.post(
        f"/api/findings/{fs['DEMO-05']['id']}/decision", json={"decision": "confirmed"}
    )
    assert r.status_code == 409 and "signed off" in r.json()["detail"]
    assert reviewer.post(f"/api/reviews/{review['id']}/runs").status_code == 409

    # Remediation continues after sign-off: owner marks ready, reviewer resolves.
    r = analyst.post(
        f"/api/findings/{fs['DEMO-06']['id']}/remediation",
        json={"notes": "Added clause 4.2", "status": "ready_for_rereview"},
    )
    assert r.status_code == 200 and r.json()["status"] == "ready_for_rereview"
    r = analyst.post(
        f"/api/findings/{fs['DEMO-06']['id']}/remediation",
        json={"notes": "Added clause 4.2", "status": "resolved"},
    )
    assert r.status_code == 403
    r = reviewer.post(
        f"/api/findings/{fs['DEMO-06']['id']}/remediation",
        json={"notes": "Verified.", "status": "resolved"},
    )
    assert r.json()["status"] == "resolved"

    # Reopen needs a reason; the next sign-off is version 2 and v1 is unchanged.
    v1 = db.scalar(select(ReportSnapshot).where(ReportSnapshot.version == 1)).content
    assert (
        reviewer.post(f"/api/reviews/{review['id']}/reopen", json={"reason": "no"}).status_code
        == 422
    )
    r = reviewer.post(
        f"/api/reviews/{review['id']}/reopen", json={"reason": "Re-check after remediation"}
    )
    assert r.status_code == 200 and r.json()["status"] == "in_review"
    r = reviewer.post(f"/api/reviews/{review['id']}/signoff")
    assert r.json()["version"] == 2
    db.expire_all()
    snaps = db.scalars(select(ReportSnapshot).order_by(ReportSnapshot.version)).all()
    assert snaps[0].content == v1
    status_v2 = {f["requirement_code"]: f["status"] for f in snaps[1].content["findings"]}
    assert status_v2["DEMO-06"] == "resolved"

    actions = db.scalars(select(AuditEvent.action)).all()
    for expected in (
        "review.created",
        "finding.decided",
        "finding.assigned",
        "review.signed_off",
        "review.reopened",
        "finding.remediation_status",
    ):
        assert expected in actions
    reopen_event = db.scalar(select(AuditEvent).where(AuditEvent.action == "review.reopened"))
    assert reopen_event.meta["reason"] == "Re-check after remediation"


def test_manual_finding_and_comments(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    analyst = login(tenant_a.users[Role.ANALYST])
    review = start_review(analyst, tenant_a)
    blocks = analyst.get(f"/api/document-versions/{review['document_version_id']}/blocks").json()[
        "items"
    ]
    r = analyst.post(
        f"/api/reviews/{review['id']}/findings",
        json={
            "title": "Subcontractor clause is vague",
            "severity": "low",
            "block_ids": [blocks[-1]["id"]],
        },
    )
    assert r.status_code == 201
    f = r.json()
    assert f["is_manual"] and f["evidence"][0]["ref"] == blocks[-1]["ref"]
    assert f["automated_outcome"] is None
    c = analyst.post(f"/api/findings/{f['id']}/comments", json={"body": "Raised with owner."})
    assert c.status_code == 201
    assert (
        analyst.get(f"/api/findings/{f['id']}/comments").json()[0]["body"] == "Raised with owner."
    )
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.post(f"/api/findings/{f['id']}/comments", json={"body": "x"}).status_code == 403


def test_bulk_assign_checks_permissions(tenant_a: Tenant) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    review = start_review(reviewer, tenant_a)
    ids = [f["id"] for f in findings(reviewer, review["id"])]
    for fid in ids:
        reviewer.post(f"/api/findings/{fid}/decision", json={"decision": "confirmed"})
    body = {"finding_ids": ids, "owner_id": str(tenant_a.users[Role.ANALYST].id)}
    analyst = login(tenant_a.users[Role.ANALYST])
    assert analyst.post("/api/findings/bulk-assign", json=body).status_code == 403
    r = reviewer.post("/api/findings/bulk-assign", json=body)
    assert r.status_code == 200
    assert {f["status"] for f in r.json()} == {"remediation_in_progress"}


def test_dashboard_counts_are_real(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.REVIEWER])
    empty = client.get("/api/dashboard").json()
    assert empty["documents_processed"] == 0 and empty["active_reviews"] == 0
    review = start_review(client, tenant_a)
    d = client.get("/api/dashboard").json()
    assert d["documents_processed"] == 1
    assert d["active_reviews"] == 1
    assert d["findings_proposed"] == db.scalar(select(func.count(Finding.id)))
    assert d["coverage_definition"] == "The proportion of checklist items reviewed."
    cov = d["coverage"][0]
    assert cov["review_id"] == review["id"] and cov["total"] == 8 and cov["reviewed"] == 5
    assert "score" not in str(d).lower()
