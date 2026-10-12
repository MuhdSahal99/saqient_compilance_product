"""Background job execution, independent of Celery so it can be tested directly.

Guarantees:
- A job only touches objects in its own organisation (checked by handlers).
- Completed or cancelled jobs are no-ops when delivered again (idempotent).
- Handlers write their results in one transaction, so a failed attempt leaves
  nothing partial behind and a retry cannot duplicate results.
- Attempts are bounded by ``max_attempts``.
- Cancellation is honoured at handler checkpoints.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Job, JobKind, JobStatus

logger = logging.getLogger("saqient.jobs")


class JobCancelled(Exception):
    pass


class PermanentJobError(Exception):
    """Failure that retrying cannot fix. Message is safe to show users."""


class Outcome(str, Enum):
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


Handler = Callable[[Session, Job, "Checkpoint"], None]
_handlers: dict[JobKind, Handler] = {}


def handler(kind: JobKind) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return register


class Checkpoint:
    """Lets handlers report progress and honour cancellation between steps."""

    def __init__(self, session_factory: Callable[[], Session], job_id: uuid.UUID) -> None:
        self._factory = session_factory
        self._job_id = job_id

    def __call__(self, progress: int | None = None) -> None:
        with self._factory() as db:
            job = db.get(Job, self._job_id)
            if job is None or job.cancel_requested:
                raise JobCancelled()
            if progress is not None:
                job.progress = max(0, min(100, progress))
                db.commit()


def _now() -> datetime:
    return datetime.now(UTC)


def execute_job(
    session_factory: Callable[[], Session], job_id: uuid.UUID, org_id: uuid.UUID
) -> Outcome:
    with session_factory() as db:
        job = db.scalar(select(Job).where(Job.id == job_id, Job.org_id == org_id))
        if job is None:
            logger.warning("job not found for org", extra={"job_id": str(job_id)})
            return Outcome.SKIPPED
        if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED):
            return Outcome.SKIPPED
        if job.cancel_requested:
            job.status = JobStatus.CANCELLED
            job.finished_at = _now()
            db.commit()
            return Outcome.CANCELLED
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = job.started_at or _now()
        job.error = None
        db.commit()
        kind, attempts, max_attempts = job.kind, job.attempts, job.max_attempts

    checkpoint = Checkpoint(session_factory, job_id)
    fn = _handlers[kind]
    outcome: Outcome
    error: str | None = None
    try:
        with session_factory() as db:
            job = db.get(Job, job_id)
            assert job is not None
            fn(db, job, checkpoint)  # handler commits its own results
        outcome = Outcome.COMPLETED
    except JobCancelled:
        outcome = Outcome.CANCELLED
    except PermanentJobError as exc:
        outcome, error = Outcome.FAILED, str(exc)
    except Exception as exc:
        if type(exc).__name__ == "SoftTimeLimitExceeded":  # celery time limit
            outcome, error = Outcome.FAILED, "Processing exceeded the configured time limit."
            return _finish(session_factory, job_id, kind, outcome, error)
        # Unknown errors: log the class only (messages may contain document text).
        logger.exception(
            "job attempt failed", extra={"job_id": str(job_id), "error_class": type(exc).__name__}
        )
        if attempts < max_attempts:
            outcome, error = Outcome.RETRY, "Temporary processing error; retrying."
        else:
            outcome, error = Outcome.FAILED, "Processing failed after repeated attempts."
    return _finish(session_factory, job_id, kind, outcome, error)


def _finish(
    session_factory: Callable[[], Session],
    job_id: uuid.UUID,
    kind: JobKind,
    outcome: Outcome,
    error: str | None,
) -> Outcome:
    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job is not None
        job.status = {
            Outcome.COMPLETED: JobStatus.COMPLETED,
            Outcome.CANCELLED: JobStatus.CANCELLED,
            Outcome.FAILED: JobStatus.FAILED,
            Outcome.RETRY: JobStatus.QUEUED,
        }[outcome]
        job.error = error
        if outcome is Outcome.COMPLETED:
            job.progress = 100
        if outcome is not Outcome.RETRY:
            job.finished_at = _now()
        db.commit()
        on_finish = _finish_hooks.get(kind)
        if on_finish and outcome in (Outcome.FAILED, Outcome.CANCELLED):
            on_finish(db, job)
            db.commit()
    return outcome


_finish_hooks: dict[JobKind, Callable[[Session, Job], None]] = {}


def on_unsuccessful(
    kind: JobKind,
) -> Callable[[Callable[[Session, Job], None]], Callable[[Session, Job], None]]:
    def register(fn: Callable[[Session, Job], None]) -> Callable[[Session, Job], None]:
        _finish_hooks[kind] = fn
        return fn

    return register


def enqueue(job: Job) -> None:
    """Send a committed job to the worker (or run it inline in eager mode)."""
    from app.worker import run_job_task

    run_job_task.delay(str(job.id), str(job.org_id))
