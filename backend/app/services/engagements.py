"""Audit engagements: phases, team, budget and actual hours (D1).

Status moves forward one phase at a time; moving back (or reopening a closed
engagement) needs a reason. Every change writes an audit event. A closed
engagement accepts no further changes until it is reopened.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AuditEngagement,
    EngagementBudget,
    EngagementMember,
    EngagementPhase,
    EngagementRole,
    EngagementStatus,
    LegalEntity,
    Membership,
    TimeEntry,
    User,
)
from app.schemas import EngagementBudgetIn, EngagementIn, TimeEntryIn
from app.services import audit

ORDER = list(EngagementStatus)
ZERO = Decimal("0.00")


class EngagementError(ValueError):
    pass


class EngagementConflict(EngagementError):
    pass


def _record(db: Session, e: AuditEngagement, actor: User, action: str, **meta: object) -> None:
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action=f"engagement.{action}",
        object_type="audit_engagement",
        object_id=e.id,
        meta={k: v for k, v in meta.items()},
    )


def require_open(e: AuditEngagement) -> None:
    if e.status == EngagementStatus.CLOSED:
        raise EngagementConflict("The engagement is closed. Reopen it with a reason first.")


def create(db: Session, entity: LegalEntity, body: EngagementIn, actor: User) -> AuditEngagement:
    e = AuditEngagement(
        org_id=entity.org_id,
        entity_id=entity.id,
        kind=body.kind,
        name=body.name.strip(),
        period_start=body.period_start,
        period_end=body.period_end,
        currency=entity.functional_currency,
        created_by_id=actor.id,
    )
    db.add(e)
    db.flush()
    _record(db, e, actor, "created", kind=body.kind.value, entity_id=str(entity.id))
    return e


def set_status(
    db: Session, e: AuditEngagement, target: EngagementStatus, reason: str, actor: User
) -> None:
    cur, nxt = ORDER.index(e.status), ORDER.index(target)
    if nxt == cur:
        raise EngagementError("The engagement is already at that status.")
    reason = reason.strip()
    if nxt > cur + 1:
        raise EngagementError("Move forward one phase at a time.")
    if nxt < cur and not reason:
        raise EngagementError("Moving an engagement back needs a reason.")
    previous = e.status
    e.status = target
    e.closed_at = now() if target == EngagementStatus.CLOSED else None
    _record(
        db,
        e,
        actor,
        "status_changed",
        **{"from": previous.value, "to": target.value, "reason": reason},
    )


def _staff_membership(db: Session, e: AuditEngagement, user_id: object) -> Membership:
    m = db.scalar(
        select(Membership).where(Membership.org_id == e.org_id, Membership.user_id == user_id)
    )
    if m is None:
        raise LookupError("user")
    return m


def put_member(
    db: Session, e: AuditEngagement, user_id: object, role: EngagementRole, actor: User
) -> EngagementMember:
    require_open(e)
    m = _staff_membership(db, e, user_id)
    if not m.user.is_active:
        raise EngagementError("That user is deactivated.")
    member = next((x for x in e.members if x.user_id == m.user_id), None)
    if member is None:
        member = EngagementMember(org_id=e.org_id, engagement_id=e.id, user_id=m.user_id, role=role)
        e.members.append(member)
    else:
        member.role = role
    db.flush()
    _record(db, e, actor, "member_set", user_id=str(m.user_id), role=role.value)
    return member


def remove_member(db: Session, e: AuditEngagement, user_id: object, actor: User) -> None:
    require_open(e)
    member = next((x for x in e.members if x.user_id == user_id), None)
    if member is None:
        raise LookupError("member")
    e.members.remove(member)
    db.flush()
    _record(db, e, actor, "member_removed", user_id=str(user_id))


def set_budgets(db: Session, e: AuditEngagement, body: EngagementBudgetIn, actor: User) -> None:
    require_open(e)
    phases = [p.phase for p in body.phases]
    if len(set(phases)) != len(phases):
        raise EngagementError("Each phase can appear once.")
    by_phase = {b.phase: b for b in e.budgets}
    for p in body.phases:
        if p.phase in by_phase:
            by_phase[p.phase].hours = p.hours
        else:
            e.budgets.append(
                EngagementBudget(org_id=e.org_id, engagement_id=e.id, phase=p.phase, hours=p.hours)
            )
    db.flush()
    _record(db, e, actor, "budget_set", phases={p.phase.value: str(p.hours) for p in body.phases})


def add_time(db: Session, e: AuditEngagement, body: TimeEntryIn, actor: User) -> TimeEntry:
    require_open(e)
    if not any(m.user_id == actor.id for m in e.members):
        raise EngagementError("Only engagement team members can record time.")
    t = TimeEntry(
        org_id=e.org_id,
        engagement_id=e.id,
        user_id=actor.id,
        phase=body.phase,
        work_date=body.work_date,
        hours=body.hours,
        note=body.note,
    )
    db.add(t)
    db.flush()
    _record(
        db,
        e,
        actor,
        "time_recorded",
        entry_id=str(t.id),
        phase=body.phase.value,
        hours=str(body.hours),
    )
    return t


def delete_time(
    db: Session, e: AuditEngagement, t: TimeEntry, actor: User, can_decide: bool
) -> None:
    require_open(e)
    if t.user_id != actor.id and not can_decide:
        raise PermissionError(
            "Only the person who recorded the time, or a reviewer, can delete it."
        )
    db.delete(t)
    db.flush()
    _record(db, e, actor, "time_deleted", entry_id=str(t.id), hours=str(t.hours))


def time_entries(db: Session, e: AuditEngagement) -> list[TimeEntry]:
    return list(
        db.scalars(
            select(TimeEntry)
            .where(TimeEntry.org_id == e.org_id, TimeEntry.engagement_id == e.id)
            .order_by(TimeEntry.work_date.desc(), TimeEntry.created_at.desc())
        )
    )


def hours(
    db: Session, e: AuditEngagement
) -> tuple[dict[EngagementPhase, Decimal], dict[uuid.UUID, Decimal]]:
    """Actual hours per phase and per user."""
    scope = (TimeEntry.org_id == e.org_id, TimeEntry.engagement_id == e.id)
    total = func.sum(TimeEntry.hours)
    by_phase = {
        p: Decimal(h)
        for p, h in db.execute(
            select(TimeEntry.phase, total).where(*scope).group_by(TimeEntry.phase)
        )
    }
    by_user = {
        u: Decimal(h)
        for u, h in db.execute(
            select(TimeEntry.user_id, total).where(*scope).group_by(TimeEntry.user_id)
        )
    }
    return by_phase, by_user


def phase_rows(
    e: AuditEngagement, actual: dict[EngagementPhase, Decimal]
) -> list[dict[str, object]]:
    budget = {b.phase: b.hours for b in e.budgets}
    rows: list[dict[str, object]] = []
    for p in EngagementPhase:
        b = Decimal(budget.get(p, ZERO))
        a = actual.get(p, ZERO)
        rows.append(
            {
                "phase": p,
                "budget_hours": b,
                "actual_hours": a,
                "variance_hours": b - a,
                "used_share": (a / b).quantize(Decimal("0.0001"), ROUND_HALF_UP) if b else None,
            }
        )
    return rows
