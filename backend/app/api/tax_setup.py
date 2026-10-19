"""Tax periods and per-entity VAT setup."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import DB, Admin, Ctx, Decider, get_owned_or_404
from app.models import LegalEntity, TaxPeriod, TaxType
from app.schemas import (
    TaxAccountOut,
    TaxCodeOut,
    TaxPeriodIn,
    TaxPeriodOut,
    TaxPeriodPatch,
    VatSetupIn,
    VatSetupOut,
)
from app.services import tax_setup as svc

router = APIRouter(tags=["tax setup"])


@router.get(
    "/entities/{entity_id}/tax-periods",
    response_model=list[TaxPeriodOut],
    summary="List an entity's tax periods",
)
def list_periods(
    entity_id: uuid.UUID, ctx: Ctx, db: DB, tax_type: TaxType | None = None
) -> list[TaxPeriodOut]:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    stmt = select(TaxPeriod).where(TaxPeriod.org_id == ctx.org_id, TaxPeriod.entity_id == e.id)
    if tax_type:
        stmt = stmt.where(TaxPeriod.tax_type == tax_type)
    rows = db.scalars(stmt.order_by(TaxPeriod.period_start.desc())).all()
    return [TaxPeriodOut.model_validate(p) for p in rows]


@router.post(
    "/entities/{entity_id}/tax-periods",
    response_model=TaxPeriodOut,
    status_code=201,
    summary="Add a tax period",
    description="Periods of the same tax type may not overlap. Admins and reviewers.",
)
def create_period(entity_id: uuid.UUID, body: TaxPeriodIn, ctx: Decider, db: DB) -> TaxPeriodOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    p = svc.create_period(db, e, body, ctx.user)
    db.commit()
    db.refresh(p)
    return TaxPeriodOut.model_validate(p)


@router.patch(
    "/tax-periods/{period_id}",
    response_model=TaxPeriodOut,
    summary="Mark a tax period filed or open",
    description="Records that the client says the return was filed; Saqient files nothing.",
)
def patch_period(period_id: uuid.UUID, body: TaxPeriodPatch, ctx: Decider, db: DB) -> TaxPeriodOut:
    p = get_owned_or_404(db, TaxPeriod, period_id, ctx.org_id)
    svc.set_period_status(db, p, body.status, ctx.user)
    db.commit()
    db.refresh(p)
    return TaxPeriodOut.model_validate(p)


def _setup_out(db: DB, org_id: uuid.UUID, entity_id: uuid.UUID) -> VatSetupOut:
    codes, accts = svc.vat_setup(db, org_id, entity_id)
    return VatSetupOut(
        entity_id=entity_id,
        tax_codes=[TaxCodeOut.model_validate(c) for c in codes],
        tax_accounts=[TaxAccountOut.model_validate(a) for a in accts],
    )


@router.get(
    "/entities/{entity_id}/vat-setup",
    response_model=VatSetupOut,
    summary="Get an entity's VAT tax codes and VAT accounts",
)
def get_setup(entity_id: uuid.UUID, ctx: Ctx, db: DB) -> VatSetupOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    return _setup_out(db, ctx.org_id, e.id)


@router.put(
    "/entities/{entity_id}/vat-setup",
    response_model=VatSetupOut,
    summary="Replace an entity's VAT tax codes and VAT accounts",
    description="How each ERP tax code is treated (standard, zero-rated, reverse charge…) and "
    "which GL accounts hold VAT. Organisation admins only.",
)
def put_setup(entity_id: uuid.UUID, body: VatSetupIn, ctx: Admin, db: DB) -> VatSetupOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    svc.replace_vat_setup(db, e, body, ctx.user)
    db.commit()
    return _setup_out(db, ctx.org_id, e.id)
