"""Bank reconciliations (Phase E1): auto-match, manual matches, ageing and sign-off."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.assurance_common import export, guard, name_of, sign_off_out, versions_out
from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.models import AssuranceObject, BankReconciliation, LegalEntity
from app.schemas import (
    BankRecIn,
    BankRecListOut,
    BankRecOut,
    BankRecUpdateIn,
    ManualMatchIn,
    ReasonIn,
)
from app.services import assurance
from app.services import bank_recs as svc

router = APIRouter(tags=["bank reconciliations"])
KIND = AssuranceObject.BANK_RECONCILIATION


def _get(db: DB, ctx: Ctx, rec_id: uuid.UUID) -> BankReconciliation:
    return get_owned_or_404(db, BankReconciliation, rec_id, ctx.org.id)


def _list(r: BankReconciliation) -> dict[str, object]:
    return {
        "id": r.id,
        "entity_id": r.entity_id,
        "entity_name": r.entity.name,
        "name": r.name,
        "account_label": r.account_label,
        "period_start": r.period_start,
        "period_end": r.period_end,
        "currency": r.currency,
        "status": r.status,
        "version": r.version,
        "is_demo": r.is_demo,
        "created_at": r.created_at,
    }


def rec_out(db: DB, r: BankReconciliation) -> BankRecOut:
    v = guard(lambda: svc.view(db, r))
    for m in v["matches"]:
        m["created_by_name"] = name_of(db, m.pop("created_by_id"))
    return BankRecOut(
        **_list(r),
        statement_version_id=r.statement_version_id,
        ledger_version_id=r.ledger_version_id,
        gl_accounts=r.gl_accounts,
        rule_pack_version_id=r.rule_pack_version_id,
        rules_prefix=r.rules_prefix,
        bank_closing_balance=r.bank_closing_balance,
        book_opening_balance=r.book_opening_balance,
        matcher_version=r.matcher_version,
        matched_at=r.matched_at,
        warnings=v["warnings"],
        parameters=v["parameters"],
        sign_off=sign_off_out(db, r),
        summary=v["summary"],
        items=v["items"],
        matches=v["matches"],
        versions=versions_out(db, r.org_id, KIND, r.id),
    )


@router.get(
    "/bank-reconciliations",
    response_model=list[BankRecListOut],
    summary="List bank reconciliations",
    description="Bank reconciliations of this organisation, newest first.",
)
def list_recs(db: DB, ctx: Ctx, entity_id: uuid.UUID | None = None) -> list[BankRecListOut]:
    stmt = select(BankReconciliation).where(BankReconciliation.org_id == ctx.org.id)
    if entity_id:
        stmt = stmt.where(BankReconciliation.entity_id == entity_id)
    rows = db.scalars(stmt.order_by(BankReconciliation.created_at.desc()).limit(500)).unique()
    return [BankRecListOut(**_list(r)) for r in rows]


@router.post(
    "/bank-reconciliations",
    response_model=BankRecOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a bank reconciliation",
    description=(
        "Reconciles a bank statement version with ledger lines of the given GL accounts for "
        "the period, and runs the deterministic auto-match with the pack's tolerance and window."
    ),
)
def create_rec(body: BankRecIn, db: DB, ctx: Writer) -> BankRecOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    r = guard(lambda: svc.create(db, entity, body, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.get(
    "/bank-reconciliations/{rec_id}",
    response_model=BankRecOut,
    summary="Get a bank reconciliation",
    description="Lines, matches, unmatched items with ageing, and the balance proof with steps.",
)
def get_rec(rec_id: uuid.UUID, db: DB, ctx: Ctx) -> BankRecOut:
    return rec_out(db, _get(db, ctx, rec_id))


@router.put(
    "/bank-reconciliations/{rec_id}",
    response_model=BankRecOut,
    summary="Update balances and GL accounts",
    description="Changing the GL accounts clears all matches and re-runs the auto-match.",
)
def update_rec(rec_id: uuid.UUID, body: BankRecUpdateIn, db: DB, ctx: Writer) -> BankRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: svc.update(db, r, body, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/bank-reconciliations/{rec_id}/auto-match",
    response_model=BankRecOut,
    summary="Re-run the auto-match",
    description="Replaces automatic matches; manual matches are kept.",
)
def auto_match(rec_id: uuid.UUID, db: DB, ctx: Writer) -> BankRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: svc.auto_match(db, r, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/bank-reconciliations/{rec_id}/matches",
    response_model=BankRecOut,
    status_code=status.HTTP_201_CREATED,
    summary="Match lines by hand",
    description="Bank and book lines whose totals agree within tolerance; a reason is required.",
)
def add_match(rec_id: uuid.UUID, body: ManualMatchIn, db: DB, ctx: Writer) -> BankRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: svc.manual_match(db, r, body, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.delete(
    "/bank-reconciliations/{rec_id}/matches/{match_id}",
    response_model=BankRecOut,
    summary="Remove a match",
    description="Returns the lines to the unmatched list; a reason is required.",
)
def remove_match(
    rec_id: uuid.UUID,
    match_id: uuid.UUID,
    db: DB,
    ctx: Writer,
    reason: Annotated[str, Query(min_length=3, max_length=2000)],
) -> BankRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: svc.unmatch(db, r, match_id, reason, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/bank-reconciliations/{rec_id}/prepare",
    response_model=BankRecOut,
    summary="Mark prepared",
)
def prepare(rec_id: uuid.UUID, db: DB, ctx: Writer) -> BankRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: assurance.prepare(db, r, KIND, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/bank-reconciliations/{rec_id}/sign-off",
    response_model=BankRecOut,
    summary="Sign off",
    description=(
        "A reviewer or admin who did not prepare it signs off; the difference must be zero. "
        "Freezes an immutable snapshot (version n)."
    ),
)
def sign_off(rec_id: uuid.UUID, db: DB, ctx: Decider) -> BankRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: svc.sign_off(db, r, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/bank-reconciliations/{rec_id}/reopen",
    response_model=BankRecOut,
    summary="Reopen",
    description="Needs a reason; the next sign-off creates version n+1.",
)
def reopen(rec_id: uuid.UUID, body: ReasonIn, db: DB, ctx: Decider) -> BankRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: assurance.reopen(db, r, KIND, body.reason, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.get(
    "/bank-reconciliations/{rec_id}/versions/{version}/export",
    summary="Export a signed-off bank reconciliation",
    response_class=Response,
)
def export_rec(
    rec_id: uuid.UUID,
    version: int,
    db: DB,
    ctx: Ctx,
    fmt: str = Query(alias="format", pattern="^(html|pdf|csv)$"),
) -> Response:
    r = _get(db, ctx, rec_id)
    return export(db, ctx, KIND, r.id, version, fmt)
