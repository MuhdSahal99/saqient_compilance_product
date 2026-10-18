"""Tax loss register, loss transfers and tax group membership history (Phase C3)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app import calc
from app.api.workpapers import _bad, workpaper_out
from app.deps import DB, Admin, Ctx, Decider, Writer, get_owned_or_404
from app.models import LegalEntity, TaxGroup, TaxGroupMembership, TaxLossEntry, TaxWorkpaper
from app.schemas import (
    CalcLineOut,
    GroupMembershipOut,
    GroupTestIn,
    GroupTestOut,
    LossEntryIn,
    LossEntryOut,
    LossPostingOut,
    LossRegisterOut,
    LossTransferIn,
    LossTransferOut,
    MembershipEndIn,
    MembershipIn,
    WorkpaperOut,
)
from app.services import tax_losses as svc
from app.services.workpapers import WorkpaperError

router = APIRouter(tags=["tax losses and groups"])


def entry_out(e: TaxLossEntry) -> LossEntryOut:
    return LossEntryOut(
        id=e.id,
        entity_id=e.entity_id,
        kind=e.kind,
        period_start=e.period_start,
        period_end=e.period_end,
        amount=e.amount,
        signed_amount=svc.signed(e),
        currency=e.currency,
        workpaper_id=e.workpaper_id,
        counterparty_entity_id=e.counterparty_entity_id,
        counterparty_name=e.counterparty.name if e.counterparty else None,
        transfer_id=e.transfer_id,
        explanation=e.explanation,
        rule_snapshots=e.rule_snapshots,
        evidence=e.evidence,
        note=e.note,
        created_at=e.created_at,
    )


def membership_out(m: TaxGroupMembership) -> GroupMembershipOut:
    return GroupMembershipOut(
        id=m.id,
        tax_group_id=m.tax_group_id,
        entity_id=m.entity_id,
        entity_name=m.entity.name,
        is_parent=m.is_parent,
        ownership_share=m.ownership_share,
        joined_on=m.joined_on,
        left_on=m.left_on,
        evidence=m.evidence,
        note=m.note,
    )


def _404(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


@router.get(
    "/entities/{entity_id}/tax-losses",
    response_model=LossRegisterOut,
    summary="Tax loss register",
    description="Every loss movement of the entity and the running balance.",
)
def register(entity_id: uuid.UUID, db: DB, ctx: Ctx) -> LossRegisterOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    rows = svc.entries(db, e)
    return LossRegisterOut(
        entity_id=e.id,
        currency=e.functional_currency,
        balance=sum((svc.signed(x) for x in rows), svc.ZERO),
        entries=[entry_out(x) for x in rows],
    )


@router.post(
    "/entities/{entity_id}/tax-losses",
    response_model=LossEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a loss movement",
    description="A manual loss incurred, used or forfeited, with a note and evidence.",
)
def add_entry(entity_id: uuid.UUID, body: LossEntryIn, db: DB, ctx: Writer) -> LossEntryOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    try:
        row = svc.add_entry(db, e, body, ctx.user)
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return entry_out(row)


@router.post(
    "/workpapers/{workpaper_id}/post-losses",
    response_model=LossPostingOut,
    summary="Post a workpaper to the loss register",
    description=(
        "Records a signed-off corporate tax workpaper's loss for the period and losses "
        "used. Posting again adds nothing."
    ),
)
def post_losses(workpaper_id: uuid.UUID, db: DB, ctx: Decider) -> LossPostingOut:
    wp = get_owned_or_404(db, TaxWorkpaper, workpaper_id, ctx.org.id)
    try:
        created, warnings = svc.post_workpaper(db, wp, ctx.user)
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return LossPostingOut(created=[entry_out(x) for x in created], warnings=warnings)


@router.post(
    "/workpapers/{workpaper_id}/prefill-losses",
    response_model=WorkpaperOut,
    summary="Fill losses brought forward from the register",
)
def prefill_losses(workpaper_id: uuid.UUID, db: DB, ctx: Writer) -> WorkpaperOut:
    wp = get_owned_or_404(db, TaxWorkpaper, workpaper_id, ctx.org.id)
    try:
        svc.prefill_workpaper(db, wp, ctx.user)
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.post(
    "/tax-losses/transfers",
    response_model=LossTransferOut,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer losses between entities",
    description=(
        "Checks the transfer against the pack's conditions (ownership, available balance "
        "and the preparer's assertions) and records both sides when they are met."
    ),
)
def transfer(body: LossTransferIn, db: DB, ctx: Decider) -> LossTransferOut:
    source = get_owned_or_404(db, LegalEntity, body.from_entity_id, ctx.org.id)
    target = get_owned_or_404(db, LegalEntity, body.to_entity_id, ctx.org.id)
    try:
        made, ev = svc.transfer(db, source, target, body, ctx.user)
    except LookupError as exc:
        raise _404(exc) from exc
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return LossTransferOut(
        entries=[entry_out(x) for x in made],
        lines=[CalcLineOut(**x) for x in ev.lines()],
        warnings=ev.warnings,
    )


@router.get(
    "/tax-groups/{group_id}/memberships",
    response_model=list[GroupMembershipOut],
    summary="Tax group membership history",
)
def list_memberships(group_id: uuid.UUID, db: DB, ctx: Ctx) -> list[GroupMembershipOut]:
    g = get_owned_or_404(db, TaxGroup, group_id, ctx.org.id)
    return [membership_out(m) for m in svc.memberships(db, g)]


@router.post(
    "/tax-groups/{group_id}/memberships",
    response_model=GroupMembershipOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a dated membership",
    description="An entity can be in one tax group at a time; a group has one parent.",
)
def add_membership(
    group_id: uuid.UUID, body: MembershipIn, db: DB, ctx: Admin
) -> GroupMembershipOut:
    g = get_owned_or_404(db, TaxGroup, group_id, ctx.org.id)
    e = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    try:
        m = svc.add_membership(db, g, e, body, ctx.user)
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return membership_out(m)


@router.post(
    "/tax-group-memberships/{membership_id}/end",
    response_model=GroupMembershipOut,
    summary="End a membership",
)
def end_membership(
    membership_id: uuid.UUID, body: MembershipEndIn, db: DB, ctx: Admin
) -> GroupMembershipOut:
    m = get_owned_or_404(db, TaxGroupMembership, membership_id, ctx.org.id)
    try:
        svc.end_membership(db, m, body.left_on, body.note, ctx.user)
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return membership_out(m)


@router.post(
    "/tax-groups/{group_id}/ct-test",
    response_model=GroupTestOut,
    summary="Test tax group conditions on a date",
    description=(
        "Parent ownership of each member against the pack's minimum and a matching "
        "financial year end. A proposal for a reviewer, not a determination."
    ),
)
def group_test(group_id: uuid.UUID, body: GroupTestIn, db: DB, ctx: Writer) -> GroupTestOut:
    g = get_owned_or_404(db, TaxGroup, group_id, ctx.org.id)
    try:
        ev = svc.group_test(db, g, body, ctx.user)
    except LookupError as exc:
        raise _404(exc) from exc
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return GroupTestOut(
        on=body.on,
        calc_version=calc.CALC_VERSION,
        result_hash=ev.result_hash,
        lines=[CalcLineOut(**x) for x in ev.lines()],
        warnings=ev.warnings,
    )
