"""E-invoice monitoring: validate a reproducible sample of new invoices on a schedule.

Each run takes the entity's files uploaded since the previous run, ranks them by
SHA-256(seed + ":" + file sha256) and validates the first ``sample_size`` in a new
review. The seed, window and method are stored with the run, so anyone can
re-draw the same sample. Runs never send anything to an e-invoicing platform.
"""

from __future__ import annotations

import calendar
import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ChecklistState,
    ChecklistVersion,
    EInvoiceFile,
    EInvoiceMonitor,
    EInvoiceMonitorRun,
    Job,
    LegalEntity,
    Membership,
    MonitorCadence,
    MonitorRunStatus,
    RulePackVersion,
)
from app.services import audit
from app.services.reviews import ReviewError, create_review

logger = logging.getLogger(__name__)

MAX_SAMPLE = 500
SAMPLE_METHOD = "rank by SHA-256(seed:file_sha256), take the first N"


class MonitorError(ValueError):
    pass


def sample_rank(seed: str, file_sha256: str) -> str:
    return hashlib.sha256(f"{seed}:{file_sha256}".encode()).hexdigest()


def draw_sample(seed: str, files: list[EInvoiceFile], size: int) -> list[EInvoiceFile]:
    """Deterministic: the same seed and files give the same sample in any order."""
    return sorted(files, key=lambda f: (sample_rank(seed, f.sha256), f.sha256))[:size]


def next_after(when: datetime, cadence: MonitorCadence) -> datetime:
    if cadence is MonitorCadence.DAILY:
        return when + timedelta(days=1)
    if cadence is MonitorCadence.WEEKLY:
        return when + timedelta(days=7)
    month = when.month % 12 + 1
    year = when.year + (1 if when.month == 12 else 0)
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


def _check_inputs(
    checklist_version: ChecklistVersion, rule_pack_version: RulePackVersion | None
) -> None:
    if checklist_version.state != ChecklistState.PUBLISHED:
        raise MonitorError("Choose a published checklist version.")
    if rule_pack_version is not None and rule_pack_version.state != ChecklistState.PUBLISHED:
        raise MonitorError("Choose a published rule pack version.")


def create_monitor(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    entity: LegalEntity,
    name: str,
    checklist_version: ChecklistVersion,
    rule_pack_version: RulePackVersion | None,
    sample_size: int,
    cadence: MonitorCadence,
    first_run_at: datetime | None = None,
) -> EInvoiceMonitor:
    _check_inputs(checklist_version, rule_pack_version)
    if not 1 <= sample_size <= MAX_SAMPLE:
        raise MonitorError(f"The sample size must be between 1 and {MAX_SAMPLE}.")
    now = datetime.now(UTC)
    m = EInvoiceMonitor(
        org_id=org_id,
        entity_id=entity.id,
        name=name,
        checklist_version_id=checklist_version.id,
        rule_pack_version_id=rule_pack_version.id if rule_pack_version else None,
        sample_size=sample_size,
        cadence=cadence,
        seed=secrets.token_hex(16),
        is_active=True,
        next_run_at=first_run_at or next_after(now, cadence),
        created_by_id=actor_id,
    )
    db.add(m)
    db.flush()
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor_id,
        action="einvoice_monitor.created",
        object_type="einvoice_monitor",
        object_id=m.id,
        meta={"entity_id": str(entity.id), "sample_size": sample_size, "cadence": cadence.value},
    )
    return m


def update_monitor(
    db: Session,
    m: EInvoiceMonitor,
    *,
    actor_id: uuid.UUID,
    is_active: bool | None = None,
    sample_size: int | None = None,
    name: str | None = None,
) -> EInvoiceMonitor:
    changes: dict[str, object] = {}
    if sample_size is not None:
        if not 1 <= sample_size <= MAX_SAMPLE:
            raise MonitorError(f"The sample size must be between 1 and {MAX_SAMPLE}.")
        changes["sample_size"] = [m.sample_size, sample_size]
        m.sample_size = sample_size
    if is_active is not None and is_active != m.is_active:
        changes["is_active"] = [m.is_active, is_active]
        m.is_active = is_active
        if is_active and m.next_run_at < datetime.now(UTC):
            m.next_run_at = next_after(datetime.now(UTC), m.cadence)
    if name is not None:
        m.name = name
        changes["name"] = True
    audit.record(
        db,
        org_id=m.org_id,
        actor_id=actor_id,
        action="einvoice_monitor.updated",
        object_type="einvoice_monitor",
        object_id=m.id,
        meta=changes,
    )
    return m


@dataclass
class RunOutcome:
    run: EInvoiceMonitorRun
    job: Job | None = None


def run_monitor(
    db: Session,
    m: EInvoiceMonitor,
    org_id: uuid.UUID,
    *,
    now: datetime | None = None,
    triggered_by: uuid.UUID | None = None,
) -> RunOutcome:
    """Draw the sample and create its review (the caller commits, then enqueues the job)."""
    if m.org_id != org_id or m.entity.org_id != org_id:
        raise MonitorError("Monitor not found.")
    now = now or datetime.now(UTC)
    start = m.covered_until
    q = select(EInvoiceFile).where(
        EInvoiceFile.org_id == org_id,
        EInvoiceFile.entity_id == m.entity_id,
        EInvoiceFile.created_at <= now,
    )
    if start is not None:
        q = q.where(EInvoiceFile.created_at > start)
    population = list(db.scalars(q))
    sample = draw_sample(m.seed, population, m.sample_size)
    run = EInvoiceMonitorRun(
        org_id=org_id,
        monitor_id=m.id,
        window_start=start,
        window_end=now,
        population=len(population),
        sampled=len(sample),
        seed=m.seed,
        sample_method=SAMPLE_METHOD,
        status=MonitorRunStatus.NO_FILES,
        triggered_by_id=triggered_by,
    )
    db.add(run)
    job: Job | None = None
    actor = triggered_by or m.created_by_id
    member = actor is not None and db.scalar(
        select(Membership.id).where(Membership.org_id == org_id, Membership.user_id == actor)
    )
    if sample and not member:
        run.status = MonitorRunStatus.FAILED
        run.message = "The monitor's creator is no longer a member; ask a reviewer to run it."
    elif sample:
        rpv = db.get(RulePackVersion, m.rule_pack_version_id) if m.rule_pack_version_id else None
        try:
            _check_inputs(m.checklist_version, rpv)
            assert actor is not None
            review, job = create_review(
                db,
                org_id=org_id,
                user_id=actor,
                title=f"{m.name}: sample of {len(sample)} from {len(population)}"[:300],
                document_version=None,
                checklist_version=m.checklist_version,
                rule_pack_version=rpv,
                as_of_date=now.date(),
                entity=m.entity,
                einvoice_files=sample,
            )
        except (MonitorError, ReviewError) as exc:
            run.status = MonitorRunStatus.FAILED
            run.message = str(exc)[:500]
        else:
            run.review_id = review.id
            run.status = MonitorRunStatus.REVIEW_CREATED
    m.covered_until = now if run.status is not MonitorRunStatus.FAILED else m.covered_until
    m.last_run_at = now
    while m.next_run_at <= now:
        m.next_run_at = next_after(m.next_run_at, m.cadence)
    db.flush()
    audit.record(
        db,
        org_id=org_id,
        actor_id=triggered_by,
        action="einvoice_monitor.ran",
        object_type="einvoice_monitor",
        object_id=m.id,
        meta={
            "run_id": str(run.id),
            "status": run.status.value,
            "population": run.population,
            "sampled": run.sampled,
            "review_id": str(run.review_id) if run.review_id else None,
        },
    )
    return RunOutcome(run, job)


@dataclass
class DueRun:
    ran: int = 0
    failed: int = 0
    jobs: list[Job] = field(default_factory=list)


def run_due(db: Session, now: datetime | None = None) -> DueRun:
    """Run every active monitor whose time has come; each commits on its own."""
    now = now or datetime.now(UTC)
    due = list(
        db.execute(
            select(EInvoiceMonitor.id, EInvoiceMonitor.org_id).where(
                EInvoiceMonitor.is_active.is_(True), EInvoiceMonitor.next_run_at <= now
            )
        )
    )
    out = DueRun()
    for monitor_id, org_id in due:
        m = db.get(EInvoiceMonitor, monitor_id)
        if m is None or m.org_id != org_id:
            continue
        try:
            outcome = run_monitor(db, m, org_id, now=now)
            db.commit()
        except Exception:
            db.rollback()
            out.failed += 1
            logger.exception("monitor run failed", extra={"monitor_id": str(monitor_id)})
            continue
        out.ran += 1
        if outcome.run.status is MonitorRunStatus.FAILED:
            out.failed += 1
        if outcome.job is not None:
            out.jobs.append(outcome.job)
    return out
