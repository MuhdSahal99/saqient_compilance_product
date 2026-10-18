"""Legal entities and tax groups (organisation master data)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import DB, Admin, Ctx, get_owned_or_404
from app.models import LegalEntity, TaxGroup
from app.schemas import (
    LegalEntityIn,
    LegalEntityOut,
    LegalEntityPatch,
    TaxGroupIn,
    TaxGroupOut,
    TaxGroupPatch,
)
from app.services import entities as svc

router = APIRouter(tags=["entities"])


@router.get("/entities", response_model=list[LegalEntityOut], summary="List legal entities")
def list_entities(ctx: Ctx, db: DB, include_inactive: bool = False) -> list[LegalEntityOut]:
    stmt = select(LegalEntity).where(LegalEntity.org_id == ctx.org_id)
    if not include_inactive:
        stmt = stmt.where(LegalEntity.is_active.is_(True))
    rows = db.scalars(stmt.order_by(LegalEntity.name)).unique().all()
    return [svc.entity_out(e) for e in rows]


@router.post(
    "/entities",
    response_model=LegalEntityOut,
    status_code=201,
    summary="Register a legal entity",
    description="Organisation admins only. The TRN is encrypted at rest and returned masked.",
)
def create_entity(body: LegalEntityIn, ctx: Admin, db: DB) -> LegalEntityOut:
    return svc.entity_out(svc.create_entity(db, ctx.org_id, body, ctx.user))


@router.get("/entities/{entity_id}", response_model=LegalEntityOut, summary="Get a legal entity")
def get_entity(entity_id: uuid.UUID, ctx: Ctx, db: DB) -> LegalEntityOut:
    return svc.entity_out(get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id))


@router.patch(
    "/entities/{entity_id}",
    response_model=LegalEntityOut,
    summary="Update a legal entity",
    description="Organisation admins only. Set is_active=false to archive.",
)
def update_entity(
    entity_id: uuid.UUID, body: LegalEntityPatch, ctx: Admin, db: DB
) -> LegalEntityOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    return svc.entity_out(svc.update_entity(db, e, body, ctx.user))


@router.get("/tax-groups", response_model=list[TaxGroupOut], summary="List tax groups")
def list_tax_groups(ctx: Ctx, db: DB) -> list[TaxGroupOut]:
    rows = db.scalars(
        select(TaxGroup).where(TaxGroup.org_id == ctx.org_id).order_by(TaxGroup.name)
    ).all()
    return [svc.tax_group_out(db, g) for g in rows]


@router.post(
    "/tax-groups",
    response_model=TaxGroupOut,
    status_code=201,
    summary="Create a tax group",
    description="Organisation admins only.",
)
def create_tax_group(body: TaxGroupIn, ctx: Admin, db: DB) -> TaxGroupOut:
    return svc.tax_group_out(db, svc.create_tax_group(db, ctx.org_id, body, ctx.user))


@router.patch(
    "/tax-groups/{group_id}",
    response_model=TaxGroupOut,
    summary="Update a tax group",
    description="Organisation admins only.",
)
def update_tax_group(group_id: uuid.UUID, body: TaxGroupPatch, ctx: Admin, db: DB) -> TaxGroupOut:
    g = get_owned_or_404(db, TaxGroup, group_id, ctx.org_id)
    return svc.tax_group_out(db, svc.update_tax_group(db, g, body, ctx.user))
