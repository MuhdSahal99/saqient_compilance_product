"""Phase F4: AI suggestions need both a deployment provider and an org admin's opt-in."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import (
    AISuggestion,
    AISuggestionRun,
    AuditEvent,
    Job,
    JobStatus,
    Organization,
    Review,
    Role,
)
from app.services import ai_suggestions
from app.services.jobs import Checkpoint, PermanentJobError
from tests.conftest import Tenant, login
from tests.test_reviews import start_review


def _deployment_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "ai_enabled", True)
    monkeypatch.setattr(s, "ai_provider", "mock")


def test_opt_in_is_refused_while_the_deployment_has_no_provider(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    got = admin.get("/api/org/ai-settings").json()
    assert got["deployment_available"] is False and got["opted_in"] is False
    assert got["provider"] == "disabled" and got["model"] is None
    r = admin.put("/api/org/ai-settings", json={"opted_in": True})
    assert r.status_code == 409 and "not enabled" in r.json()["detail"]
    assert admin.put("/api/org/ai-settings", json={"opted_in": True, "x": 1}).status_code == 422
    # Opting out is always allowed.
    assert admin.put("/api/org/ai-settings", json={"opted_in": False}).status_code == 200


def test_org_admin_opts_in_per_organisation(
    tenant_a: Tenant, tenant_b: Tenant, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _deployment_mock(monkeypatch)
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    viewer = login(tenant_a.users[Role.VIEWER])
    review = start_review(reviewer, tenant_a)

    # Offered by the deployment, but the org has not opted in.
    status = reviewer.get("/api/ai/status").json()
    assert status["deployment_enabled"] is True and status["enabled"] is False
    assert status["available_features"] == []
    r = reviewer.post(f"/api/reviews/{review['id']}/ai-suggestions")
    assert r.status_code == 409 and "has not turned on" in r.json()["detail"]
    assert reviewer.get(f"/api/reviews/{review['id']}/ai-suggestions").json()["available"] is False

    for client in (reviewer, viewer):
        assert client.put("/api/org/ai-settings", json={"opted_in": True}).status_code == 403
    on = admin.put("/api/org/ai-settings", json={"opted_in": True})
    assert on.status_code == 200, on.text
    assert on.json()["opted_in"] is True and on.json()["opted_in_at"]
    assert on.json()["is_mock"] is True and on.json()["provider"] == "mock"
    assert viewer.get("/api/org/ai-settings").json()["opted_in"] is True
    assert reviewer.get("/api/ai/status").json()["available_features"] == [
        "review_suggestions",
        "contract_tax",
        "finding_explain",
        "letter_draft",
        "pack_qa",
    ]
    data = reviewer.post(f"/api/reviews/{review['id']}/ai-suggestions").json()
    assert data["available"] is True and data["run"]["job"]["status"] == "completed"
    assert data["run"]["model"] == "mock" and data["run"]["is_mock"] is True

    # Another organisation keeps its own setting.
    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get("/api/org/ai-settings").json()["opted_in"] is False
    other_review = start_review(other, tenant_b)
    assert other.post(f"/api/reviews/{other_review['id']}/ai-suggestions").status_code == 409
    assert other.post(f"/api/reviews/{review['id']}/ai-suggestions").status_code == 404

    off = admin.put("/api/org/ai-settings", json={"opted_in": False})
    assert off.json()["opted_in"] is False and off.json()["opted_in_at"] is None
    assert reviewer.post(f"/api/reviews/{review['id']}/ai-suggestions").status_code == 409
    actions = db.scalars(
        select(AuditEvent.action)
        .where(AuditEvent.org_id == tenant_a.org.id, AuditEvent.action.like("ai.org_%"))
        .order_by(AuditEvent.created_at)
    ).all()
    assert actions == ["ai.org_opted_in", "ai.org_opted_out"]


def test_queued_request_stops_if_the_org_opts_out(
    tenant_a: Tenant, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _deployment_mock(monkeypatch)
    reviewer = login(tenant_a.users[Role.REVIEWER])
    review_id = start_review(reviewer, tenant_a)["id"]
    org = db.get(Organization, tenant_a.org.id)
    assert org is not None
    org.ai_opt_in = True
    db.commit()
    review = db.get(Review, review_id)
    assert review is not None
    job = ai_suggestions.request_suggestions(db, review, tenant_a.users[Role.REVIEWER])
    org.ai_opt_in = False
    db.commit()
    with pytest.raises(PermanentJobError, match="turned off"):
        ai_suggestions.execute_suggestions(db, job, Checkpoint(get_sessionmaker(), job.id))
    db.rollback()
    run = db.scalar(select(AISuggestionRun).where(AISuggestionRun.job_id == job.id))
    assert run is not None
    assert db.scalars(select(AISuggestion).where(AISuggestion.run_id == run.id)).all() == []
    assert db.get(Job, job.id).status == JobStatus.QUEUED  # type: ignore[union-attr]
