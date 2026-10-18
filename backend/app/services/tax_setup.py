"""Tax periods and per-entity VAT configuration (tax code treatments, VAT accounts).

Tax codes and accounts are the client's own ERP configuration, not regulatory
content: they say how an ERP code is treated, while which return box a
treatment lands in comes from the rule pack.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    DatasetKind,
    EntityTaxAccount,
    EntityTaxCode,
    LegalEntity,
    TaxPeriod,
    TaxPeriodStatus,
    User,
)
from app.schemas import TaxPeriodIn, VatSetupIn
from app.services import audit


def create_period(db: Session, e: LegalEntity, body: TaxPeriodIn, actor: User) -> TaxPeriod:
    overlap = db.scalar(
        select(TaxPeriod).where(
            TaxPeriod.org_id == e.org_id,
            TaxPeriod.entity_id == e.id,
            TaxPeriod.tax_type == body.tax_type,
            TaxPeriod.period_start <= body.period_end,
            TaxPeriod.period_end >= body.period_start,
        )
    )
    if overlap is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "It overlaps an existing tax period.")
    p = TaxPeriod(org_id=e.org_id, entity_id=e.id, **body.model_dump())
    db.add(p)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That tax period already exists.") from exc
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="tax_period.created",
        object_type="tax_period",
        object_id=p.id,
        meta={
            "entity_id": str(e.id),
            "tax_type": p.tax_type.value,
            "start": p.period_start.isoformat(),
            "end": p.period_end.isoformat(),
        },
    )
    return p


def set_period_status(db: Session, p: TaxPeriod, new: TaxPeriodStatus, actor: User) -> None:
    old = p.status
    p.status = new
    audit.record(
        db,
        org_id=p.org_id,
        actor_id=actor.id,
        action="tax_period.status_changed",
        object_type="tax_period",
        object_id=p.id,
        meta={"from": old.value, "to": new.value},
    )


def replace_vat_setup(db: Session, e: LegalEntity, body: VatSetupIn, actor: User) -> None:
    codes = [(c.register, c.tax_code.strip()) for c in body.tax_codes]
    if len(codes) != len(set(codes)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Each tax code may appear once per register."
        )
    accts = [(a.role, a.account_code.strip()) for a in body.tax_accounts]
    if len(accts) != len(set(accts)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Duplicate VAT account.")
    db.execute(delete(EntityTaxCode).where(EntityTaxCode.entity_id == e.id))
    db.execute(delete(EntityTaxAccount).where(EntityTaxAccount.entity_id == e.id))
    for c in body.tax_codes:
        db.add(
            EntityTaxCode(
                org_id=e.org_id,
                entity_id=e.id,
                register=DatasetKind(c.register),
                tax_code=c.tax_code.strip(),
                treatment=c.treatment,
                recoverable=c.recoverable,
                description=c.description,
            )
        )
    for a in body.tax_accounts:
        db.add(
            EntityTaxAccount(
                org_id=e.org_id, entity_id=e.id, role=a.role, account_code=a.account_code.strip()
            )
        )
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="entity.vat_setup_replaced",
        object_type="legal_entity",
        object_id=e.id,
        meta={"tax_codes": len(body.tax_codes), "tax_accounts": len(body.tax_accounts)},
    )


def vat_setup(
    db: Session, org_id: uuid.UUID, entity_id: uuid.UUID
) -> tuple[list[EntityTaxCode], list[EntityTaxAccount]]:
    codes = list(
        db.scalars(
            select(EntityTaxCode)
            .where(EntityTaxCode.org_id == org_id, EntityTaxCode.entity_id == entity_id)
            .order_by(EntityTaxCode.register, EntityTaxCode.tax_code)
        )
    )
    accts = list(
        db.scalars(
            select(EntityTaxAccount)
            .where(EntityTaxAccount.org_id == org_id, EntityTaxAccount.entity_id == entity_id)
            .order_by(EntityTaxAccount.role, EntityTaxAccount.account_code)
        )
    )
    return codes, accts
