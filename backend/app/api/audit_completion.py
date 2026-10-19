"""Confirmations and the adjustments schedule with the SUD (Phase D7)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.engagements import _guard, get_engagement
from app.deps import DB, DECIDE_ROLES, Ctx, Writer, get_owned_or_404
from app.models import AuditAdjustment, AuditConfirmation
from app.schemas import (
    AdjustmentDecisionIn,
    AdjustmentIn,
    AdjustmentOut,
    ConfirmationIn,
    ConfirmationOut,
    ConfirmationUpdateIn,
    SudOut,
)
from app.services import audit_completion as svc

router = APIRouter(tags=["audit completion"])


def _conf_out(c: AuditConfirmation) -> ConfirmationOut:
    return ConfirmationOut(
        id=c.id,
        type=c.type,
        counterparty=c.counterparty,
        reference=c.reference,
        book_amount=c.book_amount,
        currency=c.currency,
        status=c.status,
        sent_on=c.sent_on,
        responded_on=c.responded_on,
        confirmed_amount=c.confirmed_amount,
        difference=svc.difference(c),
        response_document_id=c.response_document_id,
        conclusion=c.conclusion,
    )


@router.get(
    "/engagements/{engagement_id}/confirmations",
    response_model=list[ConfirmationOut],
    summary="List confirmations",
)
def list_confirmations(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[ConfirmationOut]:
    e = get_engagement(db, ctx, engagement_id)
    return [_conf_out(c) for c in svc.confirmations(db, e)]


@router.post(
    "/engagements/{engagement_id}/confirmations",
    response_model=ConfirmationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Plan a confirmation",
    description="Bank, receivable, payable, legal or other, in the engagement currency.",
)
def add_confirmation(
    engagement_id: uuid.UUID, body: ConfirmationIn, db: DB, ctx: Writer
) -> ConfirmationOut:
    e = get_engagement(db, ctx, engagement_id)
    c = _guard(lambda: svc.add_confirmation(db, e, body, ctx.user))
    db.commit()
    return _conf_out(c)


@router.post(
    "/confirmations/{confirmation_id}/status",
    response_model=ConfirmationOut,
    summary="Move a confirmation on",
    description=(
        "planned → sent (date) → responded (date, amount, response document) or no "
        "response → closed (conclusion)."
    ),
)
def update_confirmation(
    confirmation_id: uuid.UUID, body: ConfirmationUpdateIn, db: DB, ctx: Writer
) -> ConfirmationOut:
    c = get_owned_or_404(db, AuditConfirmation, confirmation_id, ctx.org.id)
    e = get_engagement(db, ctx, c.engagement_id)
    _guard(lambda: svc.update_confirmation(db, e, c, body, ctx.user))
    db.commit()
    return _conf_out(c)


def _adj_out(db: DB, ctx: Ctx, a: AuditAdjustment) -> AdjustmentOut:
    e = get_engagement(db, ctx, a.engagement_id)
    return AdjustmentOut.model_validate(svc.adjustment_view(a, svc.effects(db, e)))


@router.get(
    "/engagements/{engagement_id}/adjustments",
    response_model=list[AdjustmentOut],
    summary="List the adjustments schedule",
)
def list_adjustments(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[AdjustmentOut]:
    e = get_engagement(db, ctx, engagement_id)
    eff = svc.effects(db, e)
    return [
        AdjustmentOut.model_validate(svc.adjustment_view(a, eff)) for a in svc.adjustments(db, e)
    ]


@router.post(
    "/engagements/{engagement_id}/adjustments",
    response_model=AdjustmentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Propose an adjustment",
    description="Lines must balance; effects follow the account mapping.",
)
def add_adjustment(
    engagement_id: uuid.UUID, body: AdjustmentIn, db: DB, ctx: Writer
) -> AdjustmentOut:
    e = get_engagement(db, ctx, engagement_id)
    a = _guard(lambda: svc.save_adjustment(db, e, body, ctx.user))
    db.commit()
    return _adj_out(db, ctx, a)


@router.put(
    "/adjustments/{adjustment_id}",
    response_model=AdjustmentOut,
    summary="Change a proposed adjustment",
)
def update_adjustment(
    adjustment_id: uuid.UUID, body: AdjustmentIn, db: DB, ctx: Writer
) -> AdjustmentOut:
    a = get_owned_or_404(db, AuditAdjustment, adjustment_id, ctx.org.id)
    e = get_engagement(db, ctx, a.engagement_id)
    _guard(lambda: svc.save_adjustment(db, e, body, ctx.user, a))
    db.commit()
    return _adj_out(db, ctx, a)


@router.post(
    "/adjustments/{adjustment_id}/status",
    response_model=AdjustmentOut,
    summary="Record or pass an adjustment",
    description=(
        "recorded: booked by the client. passed: left unbooked, needs a reviewer and a "
        "reason, and appears on the summary of unadjusted differences. Back to proposed "
        "needs a reason."
    ),
)
def decide_adjustment(
    adjustment_id: uuid.UUID, body: AdjustmentDecisionIn, db: DB, ctx: Writer
) -> AdjustmentOut:
    a = get_owned_or_404(db, AuditAdjustment, adjustment_id, ctx.org.id)
    e = get_engagement(db, ctx, a.engagement_id)
    try:
        _guard(lambda: svc.decide_adjustment(db, e, a, body, ctx.user, ctx.role in DECIDE_ROLES))
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    db.commit()
    return _adj_out(db, ctx, a)


@router.get(
    "/engagements/{engagement_id}/sud",
    response_model=SudOut,
    summary="Summary of unadjusted differences",
    description=(
        "Passed adjustments with their profit and net assets effects, compared with the "
        "latest signed-off materiality workpaper."
    ),
)
def sud(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> SudOut:
    e = get_engagement(db, ctx, engagement_id)
    return SudOut.model_validate(svc.sud(db, e))
