"""Scheduled e-invoice sampling monitors."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import DB, Ctx, Decider, get_owned_or_404
from app.models import (
    ChecklistVersion,
    EInvoiceMonitor,
    EInvoiceMonitorRun,
    LegalEntity,
    RulePackVersion,
)
from app.schemas import (
    EInvoiceMonitorIn,
    EInvoiceMonitorOut,
    EInvoiceMonitorPatch,
    EInvoiceMonitorRunOut,
)
from app.services import monitors as svc
from app.services.jobs import enqueue

router = APIRouter(tags=["e-invoice monitors"])


def _out(m: EInvoiceMonitor) -> EInvoiceMonitorOut:
    out = EInvoiceMonitorOut.model_validate(m)
    out.entity_name = m.entity.name
    return out


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.get("/einvoice-monitors", response_model=list[EInvoiceMonitorOut], summary="List monitors")
def list_monitors(ctx: Ctx, db: DB, entity_id: uuid.UUID | None = None) -> list[EInvoiceMonitorOut]:
    q = select(EInvoiceMonitor).where(EInvoiceMonitor.org_id == ctx.org_id)
    if entity_id is not None:
        q = q.where(EInvoiceMonitor.entity_id == entity_id)
    return [_out(m) for m in db.scalars(q.order_by(EInvoiceMonitor.created_at.desc()))]


@router.post(
    "/einvoice-monitors",
    response_model=EInvoiceMonitorOut,
    status_code=201,
    summary="Create a sampling monitor",
    description="On each run the monitor validates a reproducible sample of the entity's "
    "e-invoices uploaded since the previous run, in a new review. Reviewers and admins.",
)
def create_monitor(body: EInvoiceMonitorIn, ctx: Decider, db: DB) -> EInvoiceMonitorOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org_id)
    cv = get_owned_or_404(db, ChecklistVersion, body.checklist_version_id, ctx.org_id)
    rpv = (
        get_owned_or_404(db, RulePackVersion, body.rule_pack_version_id, ctx.org_id)
        if body.rule_pack_version_id
        else None
    )
    try:
        m = svc.create_monitor(
            db,
            org_id=ctx.org_id,
            actor_id=ctx.user.id,
            entity=entity,
            name=body.name,
            checklist_version=cv,
            rule_pack_version=rpv,
            sample_size=body.sample_size,
            cadence=body.cadence,
            first_run_at=body.first_run_at,
        )
    except svc.MonitorError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    db.refresh(m)
    return _out(m)


@router.patch(
    "/einvoice-monitors/{monitor_id}",
    response_model=EInvoiceMonitorOut,
    summary="Pause, resume or resize a monitor",
)
def patch_monitor(
    monitor_id: uuid.UUID, body: EInvoiceMonitorPatch, ctx: Decider, db: DB
) -> EInvoiceMonitorOut:
    m = get_owned_or_404(db, EInvoiceMonitor, monitor_id, ctx.org_id)
    try:
        svc.update_monitor(
            db,
            m,
            actor_id=ctx.user.id,
            is_active=body.is_active,
            sample_size=body.sample_size,
            name=body.name,
        )
    except svc.MonitorError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    db.refresh(m)
    return _out(m)


@router.post(
    "/einvoice-monitors/{monitor_id}/run",
    response_model=EInvoiceMonitorRunOut,
    summary="Run a monitor now",
    description="Draws the sample from files uploaded since the previous run.",
)
def run_now(monitor_id: uuid.UUID, ctx: Decider, db: DB) -> EInvoiceMonitorRunOut:
    m = get_owned_or_404(db, EInvoiceMonitor, monitor_id, ctx.org_id)
    try:
        outcome = svc.run_monitor(db, m, ctx.org_id, triggered_by=ctx.user.id)
    except svc.MonitorError as exc:
        raise _unprocessable(exc) from exc
    db.commit()
    if outcome.job is not None:
        enqueue(outcome.job)
        db.expire_all()
    return EInvoiceMonitorRunOut.model_validate(db.get(EInvoiceMonitorRun, outcome.run.id))


@router.get(
    "/einvoice-monitors/{monitor_id}/runs",
    response_model=list[EInvoiceMonitorRunOut],
    summary="List a monitor's runs",
)
def list_runs(monitor_id: uuid.UUID, ctx: Ctx, db: DB) -> list[EInvoiceMonitorRunOut]:
    m = get_owned_or_404(db, EInvoiceMonitor, monitor_id, ctx.org_id)
    rows = db.scalars(
        select(EInvoiceMonitorRun)
        .where(EInvoiceMonitorRun.org_id == ctx.org_id, EInvoiceMonitorRun.monitor_id == m.id)
        .order_by(EInvoiceMonitorRun.created_at.desc())
        .limit(100)
    )
    return [EInvoiceMonitorRunOut.model_validate(r) for r in rows]
