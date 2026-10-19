"""Audit engagements (Phase D1): phases, team and budget versus actual hours."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.deps import DB, DECIDE_ROLES, Ctx, Decider, Writer, get_owned_or_404
from app.models import (
    AuditEngagement,
    EngagementRole,
    EngagementStatus,
    LegalEntity,
    TaxWorkpaper,
    TimeEntry,
)
from app.schemas import (
    AccountMappingOut,
    AccountMappingsIn,
    AuditWorkpaperIn,
    EngagementBudgetIn,
    EngagementIn,
    EngagementMemberIn,
    EngagementMemberOut,
    EngagementOut,
    EngagementSetupIn,
    EngagementStatusIn,
    EngagementSummaryOut,
    LeadReportOut,
    LeadScheduleOut,
    LeadSchedulesIn,
    PhaseHoursOut,
    TimeEntryIn,
    TimeEntryOut,
    WorkpaperOut,
    WorkpaperSummaryOut,
)
from app.services import engagements as svc
from app.services import lead_schedules as leads
from app.services.workpapers import WorkpaperError

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
        cy_tb_version_id=e.cy_tb_version_id,
        py_tb_version_id=e.py_tb_version_id,
        rule_pack_version_id=e.rule_pack_version_id,
        rules_prefix=e.rules_prefix,
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


# ---------------------------------------------------------------- lead schedules (D2)


def _guard(fn):  # type: ignore[no-untyped-def]
    """Map service errors to HTTP errors (404 for ids from other tenants)."""
    try:
        return fn()
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except svc.EngagementError as exc:
        raise bad(exc) from exc
    except WorkpaperError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.put(
    "/engagements/{engagement_id}/setup",
    response_model=EngagementOut,
    summary="Choose trial balances and the audit rule pack",
    description=(
        "Current and prior-year trial balance versions of the engagement's entity, and the "
        "published rule pack (with key prefix) that audit workpapers read."
    ),
)
def set_up(
    engagement_id: uuid.UUID, body: EngagementSetupIn, db: DB, ctx: Decider
) -> EngagementOut:
    e = get_engagement(db, ctx, engagement_id)
    _guard(lambda: leads.set_up(db, e, body, ctx.user))
    db.commit()
    return engagement_out(db, e)


@router.get(
    "/engagements/{engagement_id}/lead-schedules",
    response_model=list[LeadScheduleOut],
    summary="List lead schedules",
)
def list_schedules(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[LeadScheduleOut]:
    e = get_engagement(db, ctx, engagement_id)
    return [LeadScheduleOut.model_validate(x) for x in leads.schedules(db, e)]


@router.put(
    "/engagements/{engagement_id}/lead-schedules",
    response_model=list[LeadScheduleOut],
    summary="Replace the lead schedules",
    description="Codes are stored upper case. A schedule with mapped accounts cannot be removed.",
)
def put_schedules(
    engagement_id: uuid.UUID, body: LeadSchedulesIn, db: DB, ctx: Writer
) -> list[LeadScheduleOut]:
    e = get_engagement(db, ctx, engagement_id)
    _guard(lambda: leads.replace_schedules(db, e, body, ctx.user))
    db.commit()
    return [LeadScheduleOut.model_validate(x) for x in leads.schedules(db, e)]


@router.get(
    "/engagements/{engagement_id}/account-mappings",
    response_model=list[AccountMappingOut],
    summary="List account mappings",
)
def list_mappings(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[AccountMappingOut]:
    e = get_engagement(db, ctx, engagement_id)
    return [AccountMappingOut(account_code=a, lead_code=c) for a, c in leads.mappings(db, e)]


@router.put(
    "/engagements/{engagement_id}/account-mappings",
    response_model=list[AccountMappingOut],
    summary="Replace the account mappings",
    description="Maps trial balance account codes to lead schedule codes.",
)
def put_mappings(
    engagement_id: uuid.UUID, body: AccountMappingsIn, db: DB, ctx: Writer
) -> list[AccountMappingOut]:
    e = get_engagement(db, ctx, engagement_id)
    _guard(lambda: leads.replace_mappings(db, e, body, ctx.user))
    db.commit()
    return [AccountMappingOut(account_code=a, lead_code=c) for a, c in leads.mappings(db, e)]


@router.get(
    "/engagements/{engagement_id}/lead-report",
    response_model=LeadReportOut,
    summary="Lead schedules with prior-year comparison",
    description=(
        "Mapped balances per lead schedule and account, movement and change share, "
        "unmapped accounts and mapped accounts missing from both trial balances."
    ),
)
def lead_report(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> LeadReportOut:
    e = get_engagement(db, ctx, engagement_id)
    return LeadReportOut.model_validate(_guard(lambda: leads.report(db, e)))


@router.get(
    "/engagements/{engagement_id}/workpapers",
    response_model=list[WorkpaperSummaryOut],
    summary="List the engagement's audit workpapers",
)
def list_workpapers(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[WorkpaperSummaryOut]:
    from app.api.workpapers import _summary as wp_summary

    e = get_engagement(db, ctx, engagement_id)
    rows = db.scalars(
        select(TaxWorkpaper)
        .where(TaxWorkpaper.org_id == ctx.org.id, TaxWorkpaper.engagement_id == e.id)
        .order_by(TaxWorkpaper.created_at)
    ).unique()
    return [WorkpaperSummaryOut(**wp_summary(wp)) for wp in rows]


@router.post(
    "/engagements/{engagement_id}/workpapers",
    response_model=WorkpaperOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an audit workpaper",
    description=(
        "Lead schedule workpapers are filled from the lead report and computed; materiality "
        "workpapers start empty for the team's benchmark, percentages and rationale."
    ),
)
def create_workpaper(
    engagement_id: uuid.UUID, body: AuditWorkpaperIn, db: DB, ctx: Writer
) -> WorkpaperOut:
    from app.api.workpapers import workpaper_out

    e = get_engagement(db, ctx, engagement_id)
    wp = _guard(lambda: leads.create_workpaper(db, e, body, ctx.user))
    db.commit()
    return workpaper_out(db, wp)


@router.post(
    "/workpapers/{workpaper_id}/reload-leads",
    response_model=WorkpaperOut,
    summary="Reload a lead schedule workpaper",
    description="Replaces its balances with the current lead report and computes again.",
)
def reload_leads(workpaper_id: uuid.UUID, db: DB, ctx: Writer) -> WorkpaperOut:
    from app.api.workpapers import workpaper_out

    wp = get_owned_or_404(db, TaxWorkpaper, workpaper_id, ctx.org.id)
    if wp.engagement_id is None or wp.kind.value not in ("lead_schedule", "fs_draft"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Not a lead schedule or FS draft workpaper."
        )
    e = get_engagement(db, ctx, wp.engagement_id)
    load = leads.load_lead_balances if wp.kind.value == "lead_schedule" else leads.load_fs_balances
    _guard(lambda: load(db, e, wp, ctx.user))
    db.commit()
    return workpaper_out(db, wp)
