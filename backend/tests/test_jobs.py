"""Retries, idempotency, cancellation and bounded attempts for background jobs."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import get_sessionmaker
from app.models import (
    CheckResult,
    Finding,
    Job,
    JobKind,
    JobStatus,
    Review,
    ReviewRun,
    ReviewStatus,
    Role,
    SourceBlock,
)
from app.services import jobs, reviews
from app.services.jobs import Outcome, execute_job
from tests.conftest import Tenant, login, ready_version_id


def _queued_run(db, tenant: Tenant, monkeypatch) -> Job:  # type: ignore[no-untyped-def]
    """Create a review whose run job is queued but not executed."""
    client = login(tenant.users[Role.REVIEWER])
    vid = ready_version_id(client)
    monkeypatch.setattr(jobs, "enqueue", lambda job: None)
    from app.api import reviews as api_reviews

    monkeypatch.setattr(api_reviews, "enqueue", lambda job: None)
    r = client.post(
        "/api/reviews",
        json={
            "title": "R",
            "document_version_id": vid,
            "checklist_version_id": str(tenant.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.status_code == 201
    job = db.scalar(select(Job).where(Job.kind == JobKind.REVIEW_RUN))
    assert job.status == JobStatus.QUEUED
    return job


def counts(db) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    db.expire_all()
    return (
        db.scalar(select(func.count(CheckResult.id))),
        db.scalar(select(func.count(Finding.id))),
    )


def test_transient_failure_retries_then_succeeds_without_duplicates(
    tenant_a: Tenant, db, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    job = _queued_run(db, tenant_a, monkeypatch)
    real = reviews.evaluate
    calls = {"n": 0}

    def flaky(config, doc):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 5:  # fail midway through the first attempt
            raise ConnectionError("simulated outage")
        return real(config, doc)

    monkeypatch.setattr(reviews, "evaluate", flaky)
    factory = get_sessionmaker()
    assert execute_job(factory, job.id, job.org_id) is Outcome.RETRY
    assert counts(db) == (0, 0)  # nothing partial written
    db.refresh(job)
    assert job.status == JobStatus.QUEUED and job.attempts == 1
    assert execute_job(factory, job.id, job.org_id) is Outcome.COMPLETED
    first = counts(db)
    assert first == (8, 3)
    # Duplicate delivery of a completed job is a no-op.
    assert execute_job(factory, job.id, job.org_id) is Outcome.SKIPPED
    assert counts(db) == first


def test_attempts_are_bounded(tenant_a: Tenant, db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    job = _queued_run(db, tenant_a, monkeypatch)

    def always_fail(config, doc):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom with document text that must not be shown")

    monkeypatch.setattr(reviews, "evaluate", always_fail)
    factory = get_sessionmaker()
    outcomes = [execute_job(factory, job.id, job.org_id) for _ in range(5)]
    assert outcomes == [
        Outcome.RETRY,
        Outcome.RETRY,
        Outcome.FAILED,
        Outcome.SKIPPED,
        Outcome.SKIPPED,
    ]
    db.refresh(job)
    assert job.status == JobStatus.FAILED and job.attempts == 3
    assert "document text" not in (job.error or "")
    review = db.scalar(select(Review))
    db.refresh(review)
    assert review.status == ReviewStatus.DRAFT  # not left "running"


def test_cancel_before_start_and_at_checkpoint(tenant_a: Tenant, db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    job = _queued_run(db, tenant_a, monkeypatch)
    client = login(tenant_a.users[Role.ANALYST])
    r = client.post(f"/api/jobs/{job.id}/cancel")
    assert r.status_code == 200 and r.json()["cancel_requested"]
    assert execute_job(get_sessionmaker(), job.id, job.org_id) is Outcome.CANCELLED
    assert counts(db) == (0, 0)
    assert client.post(f"/api/jobs/{job.id}/cancel").status_code == 409

    # A new run, cancelled midway at a checkpoint.
    review = db.scalar(select(Review))
    db.refresh(review)
    run_job = reviews.start_run(db, review, None)
    db.commit()
    real = reviews.evaluate
    seen = {"n": 0}

    def cancel_midway(config, doc):  # type: ignore[no-untyped-def]
        seen["n"] += 1
        if seen["n"] == 3:
            with get_sessionmaker()() as s:
                j = s.get(Job, run_job.id)
                j.cancel_requested = True  # type: ignore[union-attr]
                s.commit()
        return real(config, doc)

    monkeypatch.setattr(reviews, "evaluate", cancel_midway)
    assert execute_job(get_sessionmaker(), run_job.id, run_job.org_id) is Outcome.CANCELLED
    assert counts(db) == (0, 0)
    run = db.scalar(select(ReviewRun).where(ReviewRun.job_id == run_job.id))
    assert run.finished_at is None


def test_extraction_retry_is_idempotent(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.ANALYST])
    ready_version_id(client)
    job = db.scalar(select(Job).where(Job.kind == JobKind.EXTRACT))
    before = db.scalar(select(func.count(SourceBlock.id)))
    # Force a re-delivery of the same work: reset to queued and run again.
    job.status = JobStatus.QUEUED
    db.commit()
    assert execute_job(get_sessionmaker(), job.id, job.org_id) is Outcome.COMPLETED
    db.expire_all()
    assert db.scalar(select(func.count(SourceBlock.id))) == before


def test_concurrent_run_refused(tenant_a: Tenant, db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    job = _queued_run(db, tenant_a, monkeypatch)
    client = login(tenant_a.users[Role.REVIEWER])
    review = db.scalar(select(Review))
    r = client.post(f"/api/reviews/{review.id}/runs")
    assert r.status_code == 409 and "already in progress" in r.json()["detail"]
    assert job.status == JobStatus.QUEUED
