"""Month-end close checklists, the close calendar and flux analysis (Phase E2)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.assurance_common import export, guard, name_of, sign_off_out, versions_out
from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.models import AssuranceObject, ClosePeriod, FluxReview, LegalEntity
from app.schemas import (
    CloseIn,
    CloseItemIn,
    CloseItemOut,
    ClosePeriodIn,
    ClosePeriodOut,
    FluxExplainIn,
    FluxIn,
    FluxOut,
    ReasonIn,
)
from app.services import assurance, flux
from app.services import close as svc

router = APIRouter(tags=["close and flux"])
FLUX = AssuranceObject.FLUX


def close_out(db: DB, p: ClosePeriod) -> ClosePeriodOut:
    today = date.today()
    items = [
        CloseItemOut(
            id=x.id,
            title=x.title,
            day_offset=x.day_offset,
            due_date=x.task.due_date,
            owner_id=x.task.owner_id,
            owner_name=name_of(db, x.task.owner_id),
            task_id=x.task_id,
            status=x.task.status.value,
            completion_note=x.task.completion_note,
            overdue=svc.overdue(x, today),
        )
        for x in p.items
    ]
    return ClosePeriodOut(
        id=p.id,
        entity_id=p.entity_id,
        entity_name=p.entity.name,
        name=p.name,
        period_end=p.period_end,
        status=p.status.value,
        closed_by_name=name_of(db, p.closed_by_id),
        closed_at=p.closed_at,
        note=p.note,
        items=items,
        done=sum(1 for x in p.items if x.task.status in svc.FINISHED),
        total=len(items),
        is_demo=p.is_demo,
    )


def _close(db: DB, ctx: Ctx, pid: uuid.UUID) -> ClosePeriod:
    return get_owned_or_404(db, ClosePeriod, pid, ctx.org.id)


@router.get(
    "/close-periods",
    response_model=list[ClosePeriodOut],
    summary="List closes (the close calendar)",
    description="Closes with checklist items, due dates and status; filter by entity or dates.",
)
def list_closes(
    db: DB,
    ctx: Ctx,
    entity_id: uuid.UUID | None = None,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
) -> list[ClosePeriodOut]:
    stmt = select(ClosePeriod).where(ClosePeriod.org_id == ctx.org.id)
    if entity_id:
        stmt = stmt.where(ClosePeriod.entity_id == entity_id)
    if from_:
        stmt = stmt.where(ClosePeriod.period_end >= from_)
    if to:
        stmt = stmt.where(ClosePeriod.period_end <= to)
    rows = db.scalars(stmt.order_by(ClosePeriod.period_end.desc()).limit(200)).unique()
    return [close_out(db, p) for p in rows]


@router.post(
    "/close-periods",
    response_model=ClosePeriodOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a close",
    description="One task per checklist item; can copy another close's checklist.",
)
def create_close(body: ClosePeriodIn, db: DB, ctx: Writer) -> ClosePeriodOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    p = guard(lambda: svc.create(db, entity, body, ctx.user))
    db.commit()
    return close_out(db, p)


@router.get("/close-periods/{period_id}", response_model=ClosePeriodOut, summary="Get a close")
def get_close(period_id: uuid.UUID, db: DB, ctx: Ctx) -> ClosePeriodOut:
    return close_out(db, _close(db, ctx, period_id))


@router.post(
    "/close-periods/{period_id}/items",
    response_model=ClosePeriodOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a checklist item",
)
def add_item(period_id: uuid.UUID, body: CloseItemIn, db: DB, ctx: Writer) -> ClosePeriodOut:
    p = _close(db, ctx, period_id)
    guard(lambda: svc.add_item(db, p, body, ctx.user))
    db.commit()
    return close_out(db, p)


@router.post(
    "/close-periods/{period_id}/close",
    response_model=ClosePeriodOut,
    summary="Mark the close closed",
    description="Every item must be done or cancelled (tasks are updated on the tasks endpoints).",
)
def mark_closed(period_id: uuid.UUID, body: CloseIn, db: DB, ctx: Decider) -> ClosePeriodOut:
    p = _close(db, ctx, period_id)
    guard(lambda: svc.close(db, p, body.note, ctx.user))
    db.commit()
    return close_out(db, p)


@router.post(
    "/close-periods/{period_id}/reopen", response_model=ClosePeriodOut, summary="Reopen a close"
)
def reopen_close(period_id: uuid.UUID, body: ReasonIn, db: DB, ctx: Decider) -> ClosePeriodOut:
    p = _close(db, ctx, period_id)
    guard(lambda: svc.reopen(db, p, body.reason, ctx.user))
    db.commit()
    return close_out(db, p)


# ---------------------------------------------------------------- flux


def _flux(db: DB, ctx: Ctx, fid: uuid.UUID) -> FluxReview:
    return get_owned_or_404(db, FluxReview, fid, ctx.org.id)


def flux_out(db: DB, r: FluxReview) -> FluxOut:
    v = guard(lambda: flux.view(db, r))
    for ln in v["lines"]:
        ln["explained_by_name"] = name_of(db, ln.pop("explained_by_id"))
    return FluxOut(
        id=r.id,
        entity_id=r.entity_id,
        entity_name=r.entity.name,
        name=r.name,
        as_of=r.as_of,
        currency=r.currency,
        cy_tb_version_id=r.cy_tb_version_id,
        py_tb_version_id=r.py_tb_version_id,
        rule_pack_version_id=r.rule_pack_version_id,
        rules_prefix=r.rules_prefix,
        is_demo=r.is_demo,
        sign_off=sign_off_out(db, r),
        versions=versions_out(db, r.org_id, FLUX, r.id),
        **v,
    )


@router.get("/flux-reviews", response_model=list[FluxOut], summary="List flux reviews")
def list_flux(db: DB, ctx: Ctx, entity_id: uuid.UUID | None = None) -> list[FluxOut]:
    stmt = select(FluxReview).where(FluxReview.org_id == ctx.org.id)
    if entity_id:
        stmt = stmt.where(FluxReview.entity_id == entity_id)
    rows = db.scalars(stmt.order_by(FluxReview.as_of.desc()).limit(100)).unique()
    return [flux_out(db, r) for r in rows]


@router.post(
    "/flux-reviews",
    response_model=FluxOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a flux review",
    description="Compares two trial balance versions of one entity account by account.",
)
def create_flux(body: FluxIn, db: DB, ctx: Writer) -> FluxOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    r = guard(lambda: flux.create(db, entity, body, ctx.user))
    db.commit()
    return flux_out(db, r)


@router.get("/flux-reviews/{flux_id}", response_model=FluxOut, summary="Get a flux review")
def get_flux(flux_id: uuid.UUID, db: DB, ctx: Ctx) -> FluxOut:
    return flux_out(db, _flux(db, ctx, flux_id))


@router.put(
    "/flux-reviews/{flux_id}/explanations",
    response_model=FluxOut,
    summary="Explain an account's change",
    description="An empty explanation removes it.",
)
def explain(flux_id: uuid.UUID, body: FluxExplainIn, db: DB, ctx: Writer) -> FluxOut:
    r = _flux(db, ctx, flux_id)
    guard(lambda: flux.explain(db, r, body, ctx.user))
    db.commit()
    return flux_out(db, r)


@router.post("/flux-reviews/{flux_id}/prepare", response_model=FluxOut, summary="Mark prepared")
def prepare_flux(flux_id: uuid.UUID, db: DB, ctx: Writer) -> FluxOut:
    r = _flux(db, ctx, flux_id)
    guard(lambda: assurance.prepare(db, r, FLUX, ctx.user))
    db.commit()
    return flux_out(db, r)


@router.post(
    "/flux-reviews/{flux_id}/sign-off",
    response_model=FluxOut,
    summary="Sign off",
    description="Every account over the threshold must be explained.",
)
def sign_off_flux(flux_id: uuid.UUID, db: DB, ctx: Decider) -> FluxOut:
    r = _flux(db, ctx, flux_id)
    guard(lambda: flux.sign_off(db, r, ctx.user))
    db.commit()
    return flux_out(db, r)


@router.post("/flux-reviews/{flux_id}/reopen", response_model=FluxOut, summary="Reopen")
def reopen_flux(flux_id: uuid.UUID, body: ReasonIn, db: DB, ctx: Decider) -> FluxOut:
    r = _flux(db, ctx, flux_id)
    guard(lambda: assurance.reopen(db, r, FLUX, body.reason, ctx.user))
    db.commit()
    return flux_out(db, r)


@router.get(
    "/flux-reviews/{flux_id}/versions/{version}/export",
    summary="Export a signed-off flux review",
    response_class=Response,
)
def export_flux(
    flux_id: uuid.UUID,
    version: int,
    db: DB,
    ctx: Ctx,
    fmt: str = Query(alias="format", pattern="^(html|pdf|csv)$"),
) -> Response:
    r = _flux(db, ctx, flux_id)
    return export(db, ctx, FLUX, r.id, version, fmt)
