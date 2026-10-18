"""Daily task due-date reminders (run by Celery beat).

Each owner gets at most one email per organisation per day, listing their open
tasks due within REMINDER_DAYS_AHEAD days, plus overdue tasks on the first day
overdue and then weekly. A unique dedupe key per owner, organisation and day
means a repeated run cannot send twice.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import mail
from app.config import get_settings
from app.models import (
    Finding,
    FindingStatus,
    Membership,
    NotificationKind,
    NotificationLog,
    Organization,
    Task,
    TaskStatus,
    User,
)
from app.services import notifications

logger = logging.getLogger("saqient.reminders")

# Statuses where the owner is the one who has to act.
OWNER_ACTION = (FindingStatus.CONFIRMED, FindingStatus.REMEDIATION_IN_PROGRESS)


@dataclass
class ReminderRun:
    sent: int = 0
    failed: int = 0
    skipped: int = 0


def _include(due: date, today: date, ahead: int) -> bool:
    if today <= due <= today + timedelta(days=ahead):
        return True
    overdue = (today - due).days
    return overdue == 1 or (overdue > 0 and overdue % 7 == 0)


def _when(due: date, today: date) -> tuple[str, str]:
    days = (due - today).days
    if days < 0:
        when_en, when_ar = f"overdue by {-days} day(s)", f"متأخرة {-days} يوم"
    elif days == 0:
        when_en, when_ar = "due today", "مستحقة اليوم"
    else:
        when_en, when_ar = f"due in {days} day(s)", f"مستحقة خلال {days} يوم"
    return when_en, when_ar


def _line(f: Finding, today: date) -> str:
    assert f.due_date is not None
    when_en, when_ar = _when(f.due_date, today)
    due = f.due_date.isoformat()
    return f"- {f.review.title}: {f.title} — {due}, {when_en} / {when_ar}"


def _task_line(t: Task, today: date) -> str:
    assert t.due_date is not None
    when_en, when_ar = _when(t.due_date, today)
    return f"- {t.title} — {t.due_date.isoformat()}, {when_en} / {when_ar}"


def reminder_mail(to: str, org_name: str, lines: list[str]) -> mail.Mail:
    url = f"{get_settings().app_base_url.rstrip('/')}/tasks"
    text = (
        f"You have {len(lines)} task(s) in {org_name} that need attention:\n\n"
        + "\n".join(lines)
        + f"\n\nOpen your tasks: {url}\n\n—\n"
        f"لديك {len(lines)} مهمة في {org_name} تحتاج إلى متابعة. "
        f"افتح مهامك: {url}\n"
    )
    return mail.Mail(to=to, subject=f"Saqient: tasks due in {org_name}", text=text)


def send_due_reminders(db: Session, today: date | None = None) -> ReminderRun:
    today = today or date.today()
    ahead = get_settings().reminder_days_ahead
    rows = db.scalars(
        select(Finding)
        .join(
            Membership,
            (Membership.org_id == Finding.org_id) & (Membership.user_id == Finding.owner_id),
        )
        .join(User, User.id == Finding.owner_id)
        .where(
            Finding.owner_id.is_not(None),
            Finding.due_date.is_not(None),
            Finding.status.in_(OWNER_ACTION),
            Finding.due_date <= today + timedelta(days=ahead),
            User.is_active.is_(True),
            User.is_demo.is_(False),
        )
        .order_by(Finding.org_id, Finding.owner_id, Finding.due_date, Finding.created_at)
    ).all()
    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[str]] = defaultdict(list)
    for f in rows:
        assert f.due_date is not None and f.owner_id is not None
        if _include(f.due_date, today, ahead):
            grouped[(f.org_id, f.owner_id)].append(_line(f, today))
    # General tasks (tax obligations, later PBC and close items; ADR 0009).
    tasks = db.scalars(
        select(Task)
        .join(
            Membership,
            (Membership.org_id == Task.org_id) & (Membership.user_id == Task.owner_id),
        )
        .join(User, User.id == Task.owner_id)
        .where(
            Task.owner_id.is_not(None),
            Task.due_date.is_not(None),
            Task.status.in_((TaskStatus.OPEN, TaskStatus.IN_PROGRESS)),
            Task.due_date <= today + timedelta(days=ahead),
            User.is_active.is_(True),
            User.is_demo.is_(False),
        )
        .order_by(Task.org_id, Task.owner_id, Task.due_date, Task.created_at)
    ).all()
    for t in tasks:
        assert t.due_date is not None and t.owner_id is not None
        if _include(t.due_date, today, ahead):
            grouped[(t.org_id, t.owner_id)].append(_task_line(t, today))
    result = ReminderRun()
    for (org_id, user_id), lines in grouped.items():
        key = f"task_due:{org_id}:{user_id}:{today.isoformat()}"
        if db.scalar(select(NotificationLog.id).where(NotificationLog.dedupe_key == key)):
            result.skipped += 1
            continue
        user = db.get(User, user_id)
        org = db.get(Organization, org_id)
        assert user is not None and org is not None
        message = reminder_mail(user.email, org.name, lines)
        entry = notifications.send_logged(
            db,
            message,
            org_id=org_id,
            kind=NotificationKind.TASK_DUE_REMINDER,
            object_type="user",
            object_id=user_id,
            recipient_user_id=user_id,
            dedupe_key=key,
        )
        try:
            db.commit()
        except IntegrityError:  # another run got there first
            db.rollback()
            result.skipped += 1
            continue
        if entry.status.value == "failed":
            result.failed += 1
        else:
            result.sent += 1
    logger.info(
        "due reminders",
        extra={"sent": result.sent, "failed": result.failed, "skipped": result.skipped},
    )
    return result
