"""Audit engagements (Phase D1): phases, team and budget versus actual hours."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.deps import DB, DECIDE_ROLES, Ctx, Decider, Writer, get_owned_or_404
from app.models import AuditEngagement, EngagementRole, EngagementStatus, LegalEntity, TimeEntry
from app.schemas import (
    EngagementBudgetIn,
    EngagementIn,
    EngagementMemberIn,
    EngagementMemberOut,
    EngagementOut,
    EngagementStatusIn,
    EngagementSummaryOut,
    PhaseHoursOut,
    TimeEntryIn,
    TimeEntryOut,
)
from app.services import engagements as svc

router = APIRouter(tags=["audit engagements"])


def bad(exc: svc.EngagementError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, svc.EngagementConflict)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, str(exc))


def get_engagement(db: DB, ctx: Ctx, engagement_id: uuid.UUID) -> AuditEngagement:
    return get_owned_or_404(db, AuditEngagement, engagement_id, ctx.org.id)


def _summary(e: AuditEngagement) -> dict[str, object]:
    return {
        "id": e.id,
        "entity_id": e.entity_id,
        "entity_name": e.entity.name,
        "kind": e.kind,
        "name": e.name,
        "period_start": e.period_start,
        "period_end": e.period_end,
        "currency": e.currency,
        "status": e.status,
        "is_demo": e.is_demo,
        "created_at": e.created_at,
    }


def engagement_out(db: DB, e: AuditEngagement) -> EngagementOut:
    by_phase, by_user = svc.hours(db, e)
    phases = [PhaseHoursOut.model_validate(r) for r in svc.phase_rows(e, by_phase)]
    return EngagementOut(
        **_summary(e),
        closed_at=e.closed_at,
        members=[
            EngagementMemberOut(
                user_id=m.user_id,
                full_name=m.user.full_name,
                email=m.user.email,
                role=m.role,
                actual_hours=by_user.get(m.user_id, svc.ZERO),
            )
            for m in sorted(
                e.members, key=lambda m: (list(EngagementRole).index(m.role), m.user.full_name)
            )
        ],
        phases=phases,
        budget_hours=sum((p.budget_hours for p in phases), Decimal("0.00")),
        actual_hours=sum((p.actual_hours for p in phases), Decimal("0.00")),
    )


@router.get(
    "/engagements",
    response_model=list[EngagementSummaryOut],
    summary="List audit engagements",
    description="Engagements of this organisation, newest first.",
)
def list_engagements(
    db: DB,
    ctx: Ctx,
    entity_id: uuid.UUID | None = None,
    status_: Annotated[EngagementStatus | None, Query(alias="status")] = None,
) -> list[EngagementSummaryOut]:
    stmt = select(AuditEngagement).where(AuditEngagement.org_id == ctx.org.id)
    if entity_id:
        stmt = stmt.where(AuditEngagement.entity_id == entity_id)
    if status_:
        stmt = stmt.where(AuditEngagement.status == status_)
    rows = db.scalars(stmt.order_by(AuditEngagement.created_at.desc()).limit(500)).unique()
    return [EngagementSummaryOut(**_summary(e)) for e in rows]


@router.post(
    "/engagements",
    response_model=EngagementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an audit engagement",
    description="Starts an engagement in planning for one entity and period.",
)
def create_engagement(body: EngagementIn, db: DB, ctx: Decider) -> EngagementOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    e = svc.create(db, entity, body, ctx.user)
    db.commit()
    return engagement_out(db, e)


@router.get(
    "/engagements/{engagement_id}",
    response_model=EngagementOut,
    summary="Get an audit engagement",
    description="Team, budget and actual hours per phase.",
)
def read_engagement(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> EngagementOut:
    return engagement_out(db, get_engagement(db, ctx, engagement_id))


@router.post(
    "/engagements/{engagement_id}/status",
    response_model=EngagementOut,
    summary="Move an engagement to another phase",
    description=(
        "Forward one phase at a time, through to closed. Moving back or reopening a "
        "closed engagement needs a reason."
    ),
)
def set_status(
    engagement_id: uuid.UUID, body: EngagementStatusIn, db: DB, ctx: Decider
) -> EngagementOut:
    e = get_engagement(db, ctx, engagement_id)
    try:
        svc.set_status(db, e, body.status, body.reason, ctx.user)
    except svc.EngagementError as exc:
        raise bad(exc) from exc
    db.commit()
    return engagement_out(db, e)


@router.put(
    "/engagements/{engagement_id}/members/{user_id}",
    response_model=EngagementOut,
    summary="Add or change a team member",
    description="The user must be an active member of this organisation.",
)
def put_member(
    engagement_id: uuid.UUID, user_id: uuid.UUID, body: EngagementMemberIn, db: DB, ctx: Decider
) -> EngagementOut:
    e = get_engagement(db, ctx, engagement_id)
    try:
        svc.put_member(db, e, user_id, body.role, ctx.user)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except svc.EngagementError as exc:
        raise bad(exc) from exc
    db.commit()
    return engagement_out(db, e)


@router.delete(
    "/engagements/{engagement_id}/members/{user_id}",
    response_model=EngagementOut,
    summary="Remove a team member",
    description="Hours already recorded stay on the engagement.",
)
def remove_member(
    engagement_id: uuid.UUID, user_id: uuid.UUID, db: DB, ctx: Decider
) -> EngagementOut:
    e = get_engagement(db, ctx, engagement_id)
    try:
        svc.remove_member(db, e, user_id, ctx.user)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except svc.EngagementError as exc:
        raise bad(exc) from exc
    db.commit()
    return engagement_out(db, e)


@router.put(
    "/engagements/{engagement_id}/budget",
    response_model=EngagementOut,
    summary="Set budgeted hours per phase",
)
def set_budget(
    engagement_id: uuid.UUID, body: EngagementBudgetIn, db: DB, ctx: Decider
) -> EngagementOut:
    e = get_engagement(db, ctx, engagement_id)
    try:
        svc.set_budgets(db, e, body, ctx.user)
    except svc.EngagementError as exc:
        raise bad(exc) from exc
    db.commit()
    return engagement_out(db, e)


def _time_out(t: TimeEntry) -> TimeEntryOut:
    return TimeEntryOut(
        id=t.id,
        user_id=t.user_id,
        user_name=t.user.full_name,
        phase=t.phase,
        work_date=t.work_date,
        hours=t.hours,
        note=t.note,
    )


@router.get(
    "/engagements/{engagement_id}/time-entries",
    response_model=list[TimeEntryOut],
    summary="List recorded time",
)
def list_time(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[TimeEntryOut]:
    e = get_engagement(db, ctx, engagement_id)
    return [_time_out(t) for t in svc.time_entries(db, e)]


@router.post(
    "/engagements/{engagement_id}/time-entries",
    response_model=TimeEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record your time",
    description="Team members record their own hours against a phase.",
)
def add_time(engagement_id: uuid.UUID, body: TimeEntryIn, db: DB, ctx: Writer) -> TimeEntryOut:
    e = get_engagement(db, ctx, engagement_id)
    try:
        t = svc.add_time(db, e, body, ctx.user)
    except svc.EngagementError as exc:
        raise bad(exc) from exc
    db.commit()
    return _time_out(t)


@router.delete(
    "/time-entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a time entry",
    description="Your own entries, or anyone's if you are a reviewer or admin.",
)
def delete_time(entry_id: uuid.UUID, db: DB, ctx: Writer) -> Response:
    t = get_owned_or_404(db, TimeEntry, entry_id, ctx.org.id)
    e = get_engagement(db, ctx, t.engagement_id)
    try:
        svc.delete_time(db, e, t, ctx.user, ctx.role in DECIDE_ROLES)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except svc.EngagementError as exc:
        raise bad(exc) from exc
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
