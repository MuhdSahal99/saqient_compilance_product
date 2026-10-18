"""Daily task due-date reminders."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail
from app.models import Finding, FindingStatus, NotificationLog, Role, Severity
from app.services.reminders import send_due_reminders
from app.worker import celery_app, send_due_reminders_task
from tests.conftest import Tenant, login
from tests.test_reviews import start_review

TODAY = date(2026, 3, 10)


@pytest.fixture(autouse=True)
def _outbox() -> None:
    mail.outbox.clear()


def make_tasks(db: Session, tenant: Tenant, plan: list[tuple[Role, FindingStatus, int]]) -> None:
    """Add manual findings with owners, statuses and due dates (days from TODAY)."""
    client = login(tenant.users[Role.ANALYST])
    review_id = uuid.UUID(start_review(client, tenant)["id"])
    for i, (role, status, days) in enumerate(plan):
        db.add(
            Finding(
                org_id=tenant.org.id,
                review_id=review_id,
                is_manual=True,
                title=f"Synthetic task {i + 1}",
                severity=Severity.MEDIUM,
                evidence=[],
                status=status,
                owner_id=tenant.users[role].id,
                due_date=TODAY + timedelta(days=days),
            )
        )
    db.commit()


def test_one_digest_per_owner_and_day(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    rp = FindingStatus.REMEDIATION_IN_PROGRESS
    make_tasks(
        db,
        tenant_a,
        [
            (Role.ANALYST, rp, 0),  # due today
            (Role.ANALYST, FindingStatus.CONFIRMED, 3),  # due in 3 days (the window edge)
            (Role.ANALYST, rp, 4),  # outside the window
            (Role.ANALYST, rp, -1),  # first day overdue
            (Role.ANALYST, rp, -3),  # overdue, not a weekly day
            (Role.REVIEWER, rp, -7),  # overdue a week
            (Role.VIEWER, FindingStatus.READY_FOR_REREVIEW, 0),  # waiting on a reviewer
        ],
    )
    make_tasks(db, tenant_b, [(Role.ANALYST, rp, 1)])

    run = send_due_reminders(db, TODAY)
    assert (run.sent, run.failed, run.skipped) == (3, 0, 0)
    by_to = {m.to: m for m in mail.outbox}
    assert set(by_to) == {
        tenant_a.users[Role.ANALYST].email,
        tenant_a.users[Role.REVIEWER].email,
        tenant_b.users[Role.ANALYST].email,
    }
    analyst = by_to[tenant_a.users[Role.ANALYST].email].text
    assert "You have 3 task(s) in Org a" in analyst
    assert "due today" in analyst and "due in 3 day(s)" in analyst
    assert "overdue by 1 day(s)" in analyst and "overdue by 3" not in analyst
    assert "http://localhost:5173/tasks" in analyst
    assert "overdue by 7 day(s)" in by_to[tenant_a.users[Role.REVIEWER].email].text
    # Each organisation's email lists only its own tasks.
    assert "Org a" not in by_to[tenant_b.users[Role.ANALYST].email].text

    # A second run the same day sends nothing.
    again = send_due_reminders(db, TODAY)
    assert (again.sent, again.skipped) == (0, 3) and len(mail.outbox) == 3
    logs = db.scalars(select(NotificationLog)).all()
    assert len(logs) == 3 and {log.kind.value for log in logs} == {"task_due_reminder"}
    assert all(log.org_id in (tenant_a.org.id, tenant_b.org.id) for log in logs)


def test_inactive_owners_and_failures(
    tenant_a: Tenant, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    rp = FindingStatus.REMEDIATION_IN_PROGRESS
    make_tasks(db, tenant_a, [(Role.ANALYST, rp, 0), (Role.REVIEWER, rp, 0)])
    tenant_a.users[Role.REVIEWER].is_active = False
    db.commit()

    def boom(message: mail.Mail, settings: object = None) -> bool:
        raise mail.MailError("Delivery failed (TimeoutError).")

    monkeypatch.setattr(mail, "send", boom)
    run = send_due_reminders(db, TODAY)
    assert (run.sent, run.failed) == (0, 1)
    log = db.scalar(select(NotificationLog))
    assert log is not None and log.status.value == "failed"
    assert log.error == "Delivery failed (TimeoutError)."


def test_beat_schedule_and_task() -> None:
    entry = celery_app.conf.beat_schedule["task-due-reminders"]
    assert entry["task"] == send_due_reminders_task.name == "saqient.send_due_reminders"
    assert send_due_reminders_task.apply().get() == {"sent": 0, "failed": 0, "skipped": 0}
