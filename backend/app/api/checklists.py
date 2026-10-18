from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import DB, Ctx, Decider, get_owned_or_404
from app.engine.versions import parse_check
from app.models import (
    Checklist,
    ChecklistKind,
    ChecklistState,
    ChecklistVersion,
    Requirement,
    Source,
)
from app.schemas import (
    ChecklistCreateIn,
    ChecklistOut,
    ChecklistVersionDetailOut,
    ChecklistVersionOut,
    RequirementIn,
    RequirementOut,
    RequirementsReplaceIn,
    SourceOut,
)
from app.services import audit

router = APIRouter(tags=["checklists"])

SYNTHETIC_DISCLAIMER = "Synthetic demonstration content — not legal guidance."


def _version_out(db: Session, v: ChecklistVersion) -> ChecklistVersionOut:
    out = ChecklistVersionOut.model_validate(v)
    out.requirement_count = (
        db.scalar(
            select(func.count(Requirement.id)).where(Requirement.checklist_version_id == v.id)
        )
        or 0
    )
    return out


def _detail(db: Session, v: ChecklistVersion) -> ChecklistVersionDetailOut:
    base = _version_out(db, v)
    reqs = (
        db.scalars(
            select(Requirement)
            .where(Requirement.checklist_version_id == v.id)
            .order_by(Requirement.ordinal)
        )
        .unique()
        .all()
    )
    return ChecklistVersionDetailOut(
        **base.model_dump(),
        checklist_name=v.checklist.name,
        checklist_kind=v.checklist.kind,
        requirements=[RequirementOut.model_validate(r) for r in reqs],
    )


def _validate_requirements(db: Session, org_id: uuid.UUID, reqs: list[RequirementIn]) -> None:
    codes = [r.code for r in reqs]
    if len(codes) != len(set(codes)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Requirement codes must be unique."
        )
    for r in reqs:
        try:
            parse_check(r.check_config)
        except PydanticValidationError as exc:
            first = exc.errors()[0]
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{r.code}: invalid check configuration ({first['msg']}).",
            ) from exc
        if r.source_id is not None:
            get_owned_or_404(db, Source, r.source_id, org_id)


def _add_requirements(
    db: Session, org_id: uuid.UUID, version: ChecklistVersion, reqs: list[RequirementIn]
) -> None:
    for i, r in enumerate(reqs):
        db.add(
            Requirement(org_id=org_id, checklist_version_id=version.id, ordinal=i, **r.model_dump())
        )


@router.get("/checklists", response_model=list[ChecklistOut])
def list_checklists(ctx: Ctx, db: DB) -> list[ChecklistOut]:
    lists = db.scalars(
        select(Checklist).where(Checklist.org_id == ctx.org_id).order_by(Checklist.name)
    ).all()
    out = []
    for c in lists:
        item = ChecklistOut.model_validate(c)
        item.versions = [_version_out(db, v) for v in c.versions]
        out.append(item)
    return out


@router.get("/checklists/{checklist_id}", response_model=ChecklistOut)
def get_checklist(checklist_id: uuid.UUID, ctx: Ctx, db: DB) -> ChecklistOut:
    c = get_owned_or_404(db, Checklist, checklist_id, ctx.org_id)
    item = ChecklistOut.model_validate(c)
    item.versions = [_version_out(db, v) for v in c.versions]
    return item


@router.post("/checklists", status_code=201, response_model=ChecklistVersionDetailOut)
def create_checklist(body: ChecklistCreateIn, ctx: Decider, db: DB) -> ChecklistVersionDetailOut:
    if body.kind == ChecklistKind.SYNTHETIC_DEMO:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Synthetic demo checklists are created by the demo seed only.",
        )
    _validate_requirements(db, ctx.org_id, body.requirements)
    c = Checklist(org_id=ctx.org_id, name=body.name, description=body.description, kind=body.kind)
    db.add(c)
    db.flush()
    v = ChecklistVersion(org_id=ctx.org_id, checklist_id=c.id, version_number=1)
    db.add(v)
    db.flush()
    _add_requirements(db, ctx.org_id, v, body.requirements)
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="checklist.created",
        object_type="checklist",
        object_id=c.id,
    )
    db.commit()
    db.refresh(v)
    return _detail(db, v)


@router.get("/checklist-versions/{version_id}", response_model=ChecklistVersionDetailOut)
def get_version(version_id: uuid.UUID, ctx: Ctx, db: DB) -> ChecklistVersionDetailOut:
    return _detail(db, get_owned_or_404(db, ChecklistVersion, version_id, ctx.org_id))


@router.put(
    "/checklist-versions/{version_id}/requirements", response_model=ChecklistVersionDetailOut
)
def replace_requirements(
    version_id: uuid.UUID, body: RequirementsReplaceIn, ctx: Decider, db: DB
) -> ChecklistVersionDetailOut:
    v = get_owned_or_404(db, ChecklistVersion, version_id, ctx.org_id)
    if v.state != ChecklistState.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Published versions are immutable. Create a new draft to edit.",
        )
    _validate_requirements(db, ctx.org_id, body.requirements)
    for r in list(v.requirements):
        db.delete(r)
    db.flush()
    _add_requirements(db, ctx.org_id, v, body.requirements)
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="checklist.draft_edited",
        object_type="checklist_version",
        object_id=v.id,
        meta={"requirements": len(body.requirements)},
    )
    db.commit()
    db.refresh(v)
    return _detail(db, v)


@router.post("/checklist-versions/{version_id}/publish", response_model=ChecklistVersionDetailOut)
def publish(version_id: uuid.UUID, ctx: Decider, db: DB) -> ChecklistVersionDetailOut:
    v = get_owned_or_404(db, ChecklistVersion, version_id, ctx.org_id)
    if v.state != ChecklistState.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only drafts can be published.")
    if not v.requirements:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A checklist needs at least one requirement."
        )
    for r in v.requirements:
        try:
            parse_check(r.check_config)
        except PydanticValidationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{r.code}: invalid check configuration."
            ) from exc
    # Archive the previously published version; reviews keep pointing at it.
    for other in v.checklist.versions:
        if other.id != v.id and other.state == ChecklistState.PUBLISHED:
            other.state = ChecklistState.ARCHIVED
    v.state = ChecklistState.PUBLISHED
    v.published_at = datetime.now(UTC)
    v.published_by_id = ctx.user.id
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="checklist.published",
        object_type="checklist_version",
        object_id=v.id,
        meta={"version": v.version_number},
    )
    db.commit()
    return _detail(db, v)


@router.post(
    "/checklists/{checklist_id}/drafts", status_code=201, response_model=ChecklistVersionDetailOut
)
def new_draft(checklist_id: uuid.UUID, ctx: Decider, db: DB) -> ChecklistVersionDetailOut:
    c = get_owned_or_404(db, Checklist, checklist_id, ctx.org_id)
    if any(v.state == ChecklistState.DRAFT for v in c.versions):
        raise HTTPException(status.HTTP_409_CONFLICT, "A draft already exists for this checklist.")
    base = c.versions[-1] if c.versions else None
    v = ChecklistVersion(
        org_id=ctx.org_id,
        checklist_id=c.id,
        version_number=(base.version_number + 1) if base else 1,
        disclaimer=base.disclaimer if base else "",
    )
    db.add(v)
    db.flush()
    if base:
        for r in base.requirements:
            db.add(
                Requirement(
                    org_id=ctx.org_id,
                    checklist_version_id=v.id,
                    ordinal=r.ordinal,
                    code=r.code,
                    title=r.title,
                    description=r.description,
                    jurisdiction=r.jurisdiction,
                    document_type=r.document_type,
                    category=r.category,
                    severity=r.severity,
                    human_instructions=r.human_instructions,
                    check_config=dict(r.check_config),
                    source_id=r.source_id,
                    source_reference=r.source_reference,
                    effective_date=r.effective_date,
                    owner=r.owner,
                )
            )
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="checklist.draft_created",
        object_type="checklist_version",
        object_id=v.id,
        meta={"version": v.version_number},
    )
    db.commit()
    db.refresh(v)
    return _detail(db, v)


@router.get("/sources", response_model=list[SourceOut])
def list_sources(ctx: Ctx, db: DB) -> list[SourceOut]:
    rows = db.scalars(select(Source).where(Source.org_id == ctx.org_id).order_by(Source.title))
    return [SourceOut.model_validate(s) for s in rows]
