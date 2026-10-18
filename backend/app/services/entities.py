"""Legal entities and tax groups. TRNs are encrypted at rest and never logged."""

from __future__ import annotations

import calendar
import uuid
from zoneinfo import available_timezones

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crypto import encrypt_field
from app.deps import get_owned_or_404
from app.models import LegalEntity, TaxGroup, User
from app.schemas import (
    LegalEntityIn,
    LegalEntityOut,
    LegalEntityPatch,
    TaxGroupIn,
    TaxGroupOut,
    TaxGroupPatch,
)
from app.services import audit

TRN_FIELD = "trn"


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


def _check_fye(month: int, day: int) -> None:
    # A non-leap year: a fiscal year cannot end on 29 February.
    if day > calendar.monthrange(2023, month)[1]:
        raise _bad("Fiscal year end day does not exist in that month.")


def _check_tz(tz: str) -> None:
    if tz not in available_timezones():
        raise _bad("Unknown time zone.")


def _set_trn(obj: LegalEntity | TaxGroup, trn: str | None, org_id: uuid.UUID) -> None:
    if trn is None:
        obj.trn_encrypted = None
        obj.trn_last4 = None
        return
    obj.trn_encrypted = encrypt_field(trn, org_id=org_id, field=f"{obj.__tablename__}.{TRN_FIELD}")
    obj.trn_last4 = trn[-4:]


def _masked(last4: str | None) -> str | None:
    return None if last4 is None else "•" * 8 + last4


def entity_out(e: LegalEntity) -> LegalEntityOut:
    return LegalEntityOut(
        id=e.id,
        name=e.name,
        country=e.country,
        trn_masked=_masked(e.trn_last4),
        fiscal_year_end_month=e.fiscal_year_end_month,
        fiscal_year_end_day=e.fiscal_year_end_day,
        functional_currency=e.functional_currency,
        timezone=e.timezone,
        tax_group_id=e.tax_group_id,
        tax_group_name=e.tax_group.name if e.tax_group else None,
        is_free_zone=e.is_free_zone,
        is_active=e.is_active,
        size_basis_amount=e.size_basis_amount,
        size_basis_currency=e.size_basis_currency,
        size_basis_year=e.size_basis_year,
        einvoice_go_live_override=e.einvoice_go_live_override,
        einvoice_go_live_note=e.einvoice_go_live_note or "",
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def tax_group_out(db: Session, g: TaxGroup) -> TaxGroupOut:
    count = db.scalar(select(func.count(LegalEntity.id)).where(LegalEntity.tax_group_id == g.id))
    return TaxGroupOut(
        id=g.id,
        name=g.name,
        country=g.country,
        trn_masked=_masked(g.trn_last4),
        entity_count=count or 0,
        created_at=g.created_at,
    )


def _commit_unique(db: Session, flush_only: bool = False) -> None:
    try:
        db.flush() if flush_only else db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That name is already in use.") from exc


def create_entity(db: Session, org_id: uuid.UUID, body: LegalEntityIn, actor: User) -> LegalEntity:
    _check_fye(body.fiscal_year_end_month, body.fiscal_year_end_day)
    _check_tz(body.timezone)
    if body.tax_group_id:
        get_owned_or_404(db, TaxGroup, body.tax_group_id, org_id)
    e = LegalEntity(
        org_id=org_id,
        name=body.name.strip(),
        country=body.country,
        fiscal_year_end_month=body.fiscal_year_end_month,
        fiscal_year_end_day=body.fiscal_year_end_day,
        functional_currency=body.functional_currency,
        timezone=body.timezone,
        tax_group_id=body.tax_group_id,
        is_free_zone=body.is_free_zone,
    )
    _set_trn(e, body.trn, org_id)
    db.add(e)
    _commit_unique(db, flush_only=True)
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor.id,
        action="entity.created",
        object_type="legal_entity",
        object_id=e.id,
        meta={"country": e.country, "has_trn": e.trn_encrypted is not None},
    )
    _commit_unique(db)
    db.refresh(e)
    return e


def update_entity(db: Session, e: LegalEntity, body: LegalEntityPatch, actor: User) -> LegalEntity:
    changes = body.model_dump(exclude_unset=True)
    month = body.fiscal_year_end_month or e.fiscal_year_end_month
    day = body.fiscal_year_end_day or e.fiscal_year_end_day
    _check_fye(month, day)
    e.fiscal_year_end_month, e.fiscal_year_end_day = month, day
    if body.name is not None:
        e.name = body.name.strip()
        _commit_unique(db, flush_only=True)
    if body.timezone is not None:
        _check_tz(body.timezone)
        e.timezone = body.timezone
    if body.functional_currency is not None:
        e.functional_currency = body.functional_currency
    if body.is_free_zone is not None:
        e.is_free_zone = body.is_free_zone
    if body.is_active is not None:
        e.is_active = body.is_active
    if body.clear_tax_group:
        e.tax_group_id = None
    elif body.tax_group_id is not None:
        get_owned_or_404(db, TaxGroup, body.tax_group_id, e.org_id)
        e.tax_group_id = body.tax_group_id
    if body.clear_size_basis:
        e.size_basis_amount = e.size_basis_currency = e.size_basis_year = None
    elif body.size_basis_amount is not None:
        if not body.size_basis_currency or not body.size_basis_year:
            raise _bad("A size basis needs an amount, a currency and a year.")
        e.size_basis_amount = body.size_basis_amount
        e.size_basis_currency = body.size_basis_currency
        e.size_basis_year = body.size_basis_year
    if body.clear_go_live_override:
        e.einvoice_go_live_override = None
        e.einvoice_go_live_note = ""
    elif body.einvoice_go_live_override is not None:
        if not (body.einvoice_go_live_note or "").strip():
            raise _bad("Say where the go-live date comes from (for example the notification).")
        e.einvoice_go_live_override = body.einvoice_go_live_override
        e.einvoice_go_live_note = (body.einvoice_go_live_note or "").strip()
    if body.clear_trn:
        _set_trn(e, None, e.org_id)
    elif body.trn is not None:
        _set_trn(e, body.trn, e.org_id)
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="entity.updated",
        object_type="legal_entity",
        object_id=e.id,
        meta={"fields": sorted(changes)},
    )
    _commit_unique(db)
    db.refresh(e)
    return e


def create_tax_group(db: Session, org_id: uuid.UUID, body: TaxGroupIn, actor: User) -> TaxGroup:
    g = TaxGroup(org_id=org_id, name=body.name.strip(), country=body.country)
    _set_trn(g, body.trn, org_id)
    db.add(g)
    _commit_unique(db, flush_only=True)
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor.id,
        action="tax_group.created",
        object_type="tax_group",
        object_id=g.id,
        meta={"country": g.country},
    )
    _commit_unique(db)
    return g


def update_tax_group(db: Session, g: TaxGroup, body: TaxGroupPatch, actor: User) -> TaxGroup:
    if body.name is not None:
        g.name = body.name.strip()
        _commit_unique(db, flush_only=True)
    if body.trn is not None:
        _set_trn(g, body.trn, g.org_id)
    audit.record(
        db,
        org_id=g.org_id,
        actor_id=actor.id,
        action="tax_group.updated",
        object_type="tax_group",
        object_id=g.id,
        meta={"fields": sorted(body.model_dump(exclude_unset=True))},
    )
    _commit_unique(db)
    return g
