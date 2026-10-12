from __future__ import annotations

import logging
import uuid

from celery import Celery, Task

from app.config import get_settings
from app.db import get_sessionmaker

# Register job handlers.
from app.services import documents as _documents  # noqa: F401
from app.services import reviews as _reviews  # noqa: F401
from app.services.jobs import Outcome, execute_job

logger = logging.getLogger("saqient.worker")
_settings = get_settings()

celery_app = Celery("saqient", broker=_settings.redis_url, backend=None)
celery_app.conf.update(
    task_always_eager=_settings.celery_task_always_eager,
    task_eager_propagates=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=_settings.processing_time_limit_seconds,
    task_time_limit=_settings.processing_time_limit_seconds + 30,
    task_serializer="json",
    accept_content=["json"],
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(bind=True, name="saqient.run_job", max_retries=10)
def run_job_task(self: Task, job_id: str, org_id: str) -> str:
    outcome = execute_job(get_sessionmaker(), uuid.UUID(job_id), uuid.UUID(org_id))
    if outcome is Outcome.RETRY:
        # Attempts are bounded by Job.max_attempts in the database, not by Celery.
        if celery_app.conf.task_always_eager:
            return run_job_task(job_id, org_id)
        raise self.retry(countdown=min(60, 5 * (self.request.retries + 1)))
    return outcome.value
