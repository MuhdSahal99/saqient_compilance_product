"""Cross-tenant access with guessed or foreign UUIDs must look like 'not found'."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Finding, Job, ReportSnapshot, Role, SourceBlock
from app.services.jobs import Outcome, execute_job
from tests.conftest import Tenant, login, ready_version_id
from tests.test_reviews import findings, start_review


def test_foreign_ids_return_404_everywhere(tenant_a: Tenant, tenant_b: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    a = login(tenant_a.users[Role.REVIEWER])
    review = start_review(a, tenant_a)
    fs = findings(a, review["id"])
    for f in fs:
        a.post(
            f"/api/findings/{f['id']}/decision",
            json={"decision": "confirmed", "rationale": "ok ok"},
        )
    report = a.post(f"/api/reviews/{review['id']}/signoff").json()
    block_id = db.scalar(select(SourceBlock.id))
    job_id = db.scalar(select(Job.id))

    b = login(tenant_b.users[Role.ORG_ADMIN])  # most privileged user in the other tenant
    gets = [
        f"/api/documents/{review['document_id']}",
        f"/api/document-versions/{review['document_version_id']}/blocks",
        f"/api/document-versions/{review['document_version_id']}/download",
        f"/api/reviews/{review['id']}",
        f"/api/reviews/{review['id']}/results",
        f"/api/findings/{fs[0]['id']}",
        f"/api/findings/{fs[0]['id']}/comments",
        f"/api/checklist-versions/{tenant_a.checklist_version.id}",  # type: ignore[union-attr]
        f"/api/checklists/{tenant_a.checklist_version.checklist_id}",  # type: ignore[union-attr]
        f"/api/jobs/{job_id}",
        f"/api/reports/{report['id']}/export?format=html",
        f"/api/reports/{report['id']}/export?format=csv",
        f"/api/reports/{report['id']}/export?format=pdf",
    ]
    for path in gets:
        assert b.get(path).status_code == 404, path
    posts = [
        (f"/api/findings/{fs[0]['id']}/decision", {"decision": "dismissed", "rationale": "xxxxx"}),
        (f"/api/findings/{fs[0]['id']}/assignment", {"owner_id": None}),
        (f"/api/findings/{fs[0]['id']}/comments", {"body": "x"}),
        (f"/api/reviews/{review['id']}/runs", None),
        (f"/api/reviews/{review['id']}/reopen", {"reason": "because"}),
        (f"/api/document-versions/{review['document_version_id']}/retry", None),
        (f"/api/jobs/{job_id}/cancel", None),
        (f"/api/checklists/{tenant_a.checklist_version.checklist_id}/drafts", None),  # type: ignore[union-attr]
        (
            "/api/findings/bulk-assign",
            {"finding_ids": [fs[0]["id"]], "owner_id": str(tenant_b.users[Role.ANALYST].id)},
        ),
    ]
    for path, body in posts:
        assert b.post(path, json=body).status_code == 404, path
    assert b.delete(f"/api/documents/{review['document_id']}").status_code == 404

    # Using tenant A's objects to build a review in tenant B is refused.
    r = b.post(
        "/api/reviews",
        json={
            "title": "x",
            "document_version_id": review["document_version_id"],
            "checklist_version_id": str(tenant_b.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.status_code == 404
    vid_b = ready_version_id(b)
    r = b.post(
        "/api/reviews",
        json={
            "title": "x",
            "document_version_id": vid_b,
            "checklist_version_id": str(tenant_a.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.status_code == 404
    # Manual findings cannot cite another tenant's blocks.
    review_b = b.post(
        "/api/reviews",
        json={
            "title": "B",
            "document_version_id": vid_b,
            "checklist_version_id": str(tenant_b.checklist_version.id),
        },
    ).json()  # type: ignore[union-attr]
    r = b.post(
        f"/api/reviews/{review_b['id']}/findings",
        json={"title": "x", "severity": "low", "block_ids": [str(block_id)]},
    )
    assert r.status_code == 404
    # Assigning to a user from another tenant is refused.
    fb = findings(b, review_b["id"])[0]
    b.post(f"/api/findings/{fb['id']}/decision", json={"decision": "confirmed"})
    r = b.post(
        f"/api/findings/{fb['id']}/assignment",
        json={"owner_id": str(tenant_a.users[Role.ANALYST].id)},
    )
    assert r.status_code == 422

    # Lists only show own tenant data.
    assert all(f["review_id"] == review_b["id"] for f in b.get("/api/findings").json()["items"])
    assert b.get("/api/reports").json()["total"] == 0
    assert {d["id"] for d in b.get("/api/documents").json()["items"]} == {review_b["document_id"]}
    assert all(e["object_id"] != review["id"] for e in b.get("/api/audit-events").json()["items"])
    assert {m["email"] for m in b.get("/api/members").json()} == {
        u.email for u in tenant_b.users.values()
    }


def test_random_uuids_404(tenant_a: Tenant) -> None:
    a = login(tenant_a.users[Role.ORG_ADMIN])
    for path in ("documents", "reviews", "findings", "jobs"):
        assert a.get(f"/api/{path}/{uuid.uuid4()}").status_code == 404


def test_cannot_switch_to_foreign_org(tenant_a: Tenant, tenant_b: Tenant) -> None:
    a = login(tenant_a.users[Role.ORG_ADMIN])
    r = a.post("/api/auth/switch-org", json={"org_id": str(tenant_b.org.id)})
    assert r.status_code == 404
    assert a.get("/api/auth/me").json()["org"]["id"] == str(tenant_a.org.id)


def test_jobs_respect_tenant_boundary(tenant_a: Tenant, tenant_b: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    a = login(tenant_a.users[Role.REVIEWER])
    start_review(a, tenant_a)
    job = db.scalar(select(Job).order_by(Job.created_at.desc()))
    # Delivering tenant A's job with tenant B's org id does nothing.
    assert execute_job(get_sessionmaker(), job.id, tenant_b.org.id) is Outcome.SKIPPED
    assert db.scalar(select(Finding).where(Finding.org_id == tenant_b.org.id)) is None
    assert db.scalar(select(ReportSnapshot)) is None
