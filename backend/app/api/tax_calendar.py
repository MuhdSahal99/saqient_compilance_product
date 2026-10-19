"""Tax calendar (obligations from rule packs) and general tasks."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.deps import DB, DECIDE_ROLES, Ctx, Decider, Writer, get_owned_or_404
from app.models import (
    LegalEntity,
    RulePackVersion,
    Task,
    TaskSource,
    TaskStatus,
    TaxObligation,
)
from app.schemas import (
    TaskIn,
    TaskOut,
    TaskPatch,
    TaxCalendarGenerateIn,
    TaxCalendarResultOut,
    TaxObligationOut,
)
from app.services import audit
from app.services import tax_calendar as svc

router = APIRouter(tags=["tax calendar"])


def task_out(t: Task, today: date | None = None) -> TaskOut:
    today = today or date.today()
    return TaskOut(
        id=t.id,
        source_kind=t.source_kind,
        source_id=t.source_id,
        entity_id=t.entity_id,
        entity_name=t.entity.name if t.entity else None,
        title=t.title,
        description=t.description,
        owner_id=t.owner_id,
        owner_name=t.owner.full_name if t.owner else None,
        due_date=t.due_date,
        is_overdue=bool(t.due_date and t.due_date < today and t.status not in svc.CLOSED),
        status=t.status,
        completion_note=t.completion_note,
        completed_at=t.completed_at,
        created_at=t.created_at,
    )


def obligation_out(o: TaxObligation) -> TaxObligationOut:
    return TaxObligationOut(
        id=o.id,
        entity_id=o.entity_id,
        entity_name=o.entity.name,
        tax_period_id=o.tax_period_id,
        obligation_key=o.obligation_key,
        label=o.label,
        tax_type=o.tax_type,
        period_start=o.period_start,
        period_end=o.period_end,
        due_date=o.due_date,
        formula=o.formula,
        rule_key=o.rule_key,
        rule_pack_version_id=o.rule_pack_version_id,
        rule_verified=o.rule_verified,
        rule_snapshot=o.rule_snapshot,
        task=task_out(o.task) if o.task else None,
    )


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.post(
    "/entities/{entity_id}/tax-calendar/generate",
    response_model=TaxCalendarResultOut,
    summary="Generate the entity's obligations from a rule pack",
    description="Reads <prefix>.obligations (and <prefix>.go_live_waves) from a published "
    "pack and creates or updates obligations and their tasks in the range. Idempotent; a "
    "done or cancelled obligation is never changed. Reviewers and admins.",
)
def generate(
    entity_id: uuid.UUID, body: TaxCalendarGenerateIn, ctx: Decider, db: DB
) -> TaxCalendarResultOut:
    entity = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    version = get_owned_or_404(db, RulePackVersion, body.rule_pack_version_id, ctx.org_id)
    try:
        result = svc.generate(
            db,
            entity=entity,
            version=version,
            prefix=body.prefix,
            start=body.start,
            end=body.end,
            actor=ctx.user,
            owner_id=body.owner_id,
            include_einvoicing=body.include_einvoicing,
            waves_rule=body.waves_rule,
        )
    except svc.CalendarError as exc:
        db.rollback()
        raise _bad(exc) from exc
    db.commit()
    return TaxCalendarResultOut(
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        periods_created=result.periods_created,
        warnings=result.warnings,
        obligations=[obligation_out(o) for o in result.obligations],
    )


@router.get("/tax-obligations", response_model=list[TaxObligationOut], summary="List obligations")
def list_obligations(
    ctx: Ctx,
    db: DB,
    entity_id: uuid.UUID | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
) -> list[TaxObligationOut]:
    q = select(TaxObligation).where(TaxObligation.org_id == ctx.org_id)
    if entity_id is not None:
        q = q.where(TaxObligation.entity_id == entity_id)
    if due_from is not None:
        q = q.where(TaxObligation.due_date >= due_from)
    if due_to is not None:
        q = q.where(TaxObligation.due_date <= due_to)
    rows = db.scalars(q.order_by(TaxObligation.due_date, TaxObligation.label).limit(1000))
    return [obligation_out(o) for o in rows]


@router.get("/tasks", response_model=list[TaskOut], summary="List tasks (not findings)")
def list_tasks(
    ctx: Ctx,
    db: DB,
    mine: bool = False,
    entity_id: uuid.UUID | None = None,
    status_in: Annotated[list[TaskStatus] | None, Query(alias="status")] = None,
) -> list[TaskOut]:
    q = select(Task).where(Task.org_id == ctx.org_id)
    if mine:
        q = q.where(Task.owner_id == ctx.user.id)
    if entity_id is not None:
        q = q.where(Task.entity_id == entity_id)
    if status_in:
        q = q.where(Task.status.in_(status_in))
    rows = db.scalars(q.order_by(Task.due_date.asc().nulls_last(), Task.created_at).limit(1000))
    return [task_out(t) for t in rows]


@router.post("/tasks", response_model=TaskOut, status_code=201, summary="Create a task")
def create_task(body: TaskIn, ctx: Writer, db: DB) -> TaskOut:
    if body.entity_id is not None:
        get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org_id)
    task = Task(
        org_id=ctx.org_id,
        source_kind=TaskSource.MANUAL,
        entity_id=body.entity_id,
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        created_by_id=ctx.user.id,
    )
    db.add(task)
    db.flush()
    try:
        if body.owner_id is not None:
            svc.update_task(db, task, actor=ctx.user, owner_id=body.owner_id)
    except svc.CalendarError as exc:
        db.rollback()
        raise _bad(exc) from exc
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="task.created",
        object_type="task",
        object_id=task.id,
        meta={"source_kind": task.source_kind.value},
    )
    db.commit()
    db.refresh(task)
    return task_out(task)


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskOut,
    summary="Update a task",
    description="Owners update their own tasks; reviewers and admins any task. Closing "
    "(done or cancelled) needs a note.",
)
def patch_task(task_id: uuid.UUID, body: TaskPatch, ctx: Writer, db: DB) -> TaskOut:
    task = get_owned_or_404(db, Task, task_id, ctx.org_id)
    if ctx.role not in DECIDE_ROLES and task.owner_id != ctx.user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner or a reviewer can do this.")
    if ctx.role not in DECIDE_ROLES and (body.owner_id or body.clear_owner):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a reviewer can reassign tasks.")
    try:
        svc.update_task(
            db,
            task,
            actor=ctx.user,
            status=body.status,
            owner_id=body.owner_id,
            clear_owner=body.clear_owner,
            due_date=body.due_date,
            note=body.note,
        )
    except svc.CalendarError as exc:
        db.rollback()
        raise _bad(exc) from exc
    db.commit()
    db.refresh(task)
    return task_out(task)
