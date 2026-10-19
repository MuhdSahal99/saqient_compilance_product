"""Month-end close checklists and the close calendar (E2).

Each checklist item is a general task (ADR 0009) owned by a member and due a number of
days after the period end; the offsets are the organisation's own schedule, not rules.
A close can be marked closed only when every item is done or cancelled.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    CloseItem,
    ClosePeriod,
    ClosePeriodStatus,
    LegalEntity,
    Task,
    TaskSource,
    TaskStatus,
    User,
)
from app.schemas import CloseItemIn, ClosePeriodIn
from app.services import audit
from app.services import tb as tbs
from app.services.assurance import AssuranceConflict, AssuranceError

FINISHED = (TaskStatus.DONE, TaskStatus.CANCELLED)


def _record(db: Session, p: ClosePeriod, actor: User, action: str, **meta: object) -> None:
    audit.record(
        db,
        org_id=p.org_id,
        actor_id=actor.id,
        action=f"close_period.{action}",
        object_type="close_period",
        object_id=p.id,
        meta=meta,
    )


def _item(db: Session, p: ClosePeriod, i: int, it: CloseItemIn, actor: User) -> CloseItem:
    tbs.require_member(db, p.org_id, it.owner_id)
    task = Task(
        org_id=p.org_id,
        source_kind=TaskSource.CLOSE_CHECKLIST,
        source_id=p.id,
        entity_id=p.entity_id,
        title=f"{p.entity.name}: {it.title} ({p.name})"[:300],
        owner_id=it.owner_id,
        due_date=p.period_end + timedelta(days=it.day_offset),
        created_by_id=actor.id,
    )
    db.add(task)
    db.flush()
    return CloseItem(
        org_id=p.org_id, ordinal=i, title=it.title.strip(), day_offset=it.day_offset, task=task
    )


def create(db: Session, entity: LegalEntity, body: ClosePeriodIn, actor: User) -> ClosePeriod:
    if db.scalar(
        select(ClosePeriod.id).where(
            ClosePeriod.entity_id == entity.id, ClosePeriod.period_end == body.period_end
        )
    ):
        raise AssuranceError("This entity already has a close for that period end.")
    items = list(body.items)
    if body.copy_from_id is not None:
        src = db.scalar(
            select(ClosePeriod).where(
                ClosePeriod.id == body.copy_from_id, ClosePeriod.org_id == entity.org_id
            )
        )
        if src is None:
            raise LookupError("close period")
        items = [
            CloseItemIn(title=x.title, day_offset=x.day_offset, owner_id=x.task.owner_id)
            for x in src.items
        ] + items
    if not items:
        raise AssuranceError("Add at least one checklist item.")
    p = ClosePeriod(
        org_id=entity.org_id,
        entity_id=entity.id,
        name=body.name.strip(),
        period_end=body.period_end,
        created_by_id=actor.id,
    )
    p.entity = entity
    db.add(p)
    db.flush()
    p.items = [_item(db, p, i, it, actor) for i, it in enumerate(items)]
    db.flush()
    _record(db, p, actor, "created", items=len(items), copied=bool(body.copy_from_id))
    return p


def add_item(db: Session, p: ClosePeriod, it: CloseItemIn, actor: User) -> None:
    if p.status is ClosePeriodStatus.CLOSED:
        raise AssuranceConflict("The close is closed. Reopen it first.")
    p.items.append(_item(db, p, len(p.items), it, actor))
    db.flush()
    _record(db, p, actor, "item_added", title=it.title)


def close(db: Session, p: ClosePeriod, note: str, actor: User) -> None:
    if p.status is ClosePeriodStatus.CLOSED:
        raise AssuranceConflict("The close is already closed.")
    open_items = [x.title for x in p.items if x.task.status not in FINISHED]
    if open_items:
        raise AssuranceError(
            f"{len(open_items)} item(s) are not done: {', '.join(open_items[:5])}."
        )
    p.status, p.closed_by_id, p.closed_at, p.note = (
        ClosePeriodStatus.CLOSED,
        actor.id,
        now(),
        note.strip(),
    )
    db.flush()
    _record(db, p, actor, "closed")


def reopen(db: Session, p: ClosePeriod, reason: str, actor: User) -> None:
    if p.status is not ClosePeriodStatus.CLOSED:
        raise AssuranceConflict("The close is not closed.")
    p.status, p.closed_by_id, p.closed_at = ClosePeriodStatus.OPEN, None, None
    p.note = reason.strip()
    db.flush()
    _record(db, p, actor, "reopened", reason=reason.strip())


def overdue(x: CloseItem, today: date) -> bool:
    return x.task.status not in FINISHED and x.task.due_date is not None and x.task.due_date < today
