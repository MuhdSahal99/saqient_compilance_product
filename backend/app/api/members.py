from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import client_ip, start_session
from app.config import get_settings
from app.deps import DB, Admin, get_owned_or_404, now
from app.models import Invitation, Membership, NotificationLog, User
from app.schemas import (
    InvitationAcceptIn,
    InvitationIn,
    InvitationLookupIn,
    InvitationLookupOut,
    InvitationOut,
    MemberOut,
    MemberRoleIn,
    MeOut,
)
from app.security import login_limiter
from app.services import members

router = APIRouter(tags=["members"])


def _out(db: DB, inv: Invitation) -> InvitationOut:
    last = db.scalar(
        select(NotificationLog.status)
        .where(NotificationLog.object_id == inv.id, NotificationLog.org_id == inv.org_id)
        .order_by(NotificationLog.created_at.desc())
        .limit(1)
    )
    return InvitationOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        invited_by_name=inv.invited_by.full_name if inv.invited_by else None,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
        is_expired=inv.expires_at <= now(),
        last_sent_at=inv.last_sent_at,
        last_delivery=last.value if last else None,
    )


def _member_out(m: Membership) -> MemberOut:
    return MemberOut(
        user_id=m.user_id,
        full_name=m.user.full_name,
        email=m.user.email,
        role=m.role,
        membership_id=m.id,
        joined_at=m.created_at,
    )


def _limit(request: Request) -> None:
    s = get_settings()
    if not login_limiter.hit(
        f"invite:{client_ip(request)}", s.login_rate_limit, s.login_rate_window_seconds
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try later.")


# ---------------------------------------------------------------- admin


@router.get("/invitations", response_model=list[InvitationOut])
def list_invitations(ctx: Admin, db: DB) -> list[InvitationOut]:
    rows = db.scalars(
        select(Invitation)
        .where(
            Invitation.org_id == ctx.org_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .order_by(Invitation.created_at.desc())
    ).all()
    return [_out(db, inv) for inv in rows]


@router.post("/invitations", status_code=201, response_model=InvitationOut)
def invite(body: InvitationIn, ctx: Admin, db: DB) -> InvitationOut:
    try:
        inv, token = members.create_invitation(
            db, org_id=ctx.org_id, actor=ctx.user, email=str(body.email), role=body.role
        )
        db.commit()
    except members.MemberError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except IntegrityError as exc:  # a concurrent invite for the same email
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This person already has an open invitation."
        ) from exc
    members.send_invitation(db, inv, token)
    db.commit()
    return _out(db, inv)


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationOut)
def resend(invitation_id: uuid.UUID, ctx: Admin, db: DB) -> InvitationOut:
    inv = get_owned_or_404(db, Invitation, invitation_id, ctx.org_id)
    try:
        token = members.renew_token(db, inv, ctx.user)
    except members.MemberError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    members.send_invitation(db, inv, token)
    db.commit()
    return _out(db, inv)


@router.delete("/invitations/{invitation_id}", status_code=204)
def revoke(invitation_id: uuid.UUID, ctx: Admin, db: DB) -> None:
    inv = get_owned_or_404(db, Invitation, invitation_id, ctx.org_id)
    try:
        members.revoke(db, inv, ctx.user)
    except members.MemberError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()


@router.patch("/members/{membership_id}", response_model=MemberOut)
def change_role(membership_id: uuid.UUID, body: MemberRoleIn, ctx: Admin, db: DB) -> MemberOut:
    m = get_owned_or_404(db, Membership, membership_id, ctx.org_id)
    try:
        members.change_role(db, m, body.role, ctx.user)
    except members.MemberError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    db.refresh(m)
    return _member_out(m)


@router.delete("/members/{membership_id}", status_code=204)
def remove_member(membership_id: uuid.UUID, ctx: Admin, db: DB) -> None:
    m = get_owned_or_404(db, Membership, membership_id, ctx.org_id)
    try:
        members.remove(db, m, ctx.user)
    except members.MemberError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()


# ---------------------------------------------------------------- public (token holders)


@router.post("/invitations/lookup", response_model=InvitationLookupOut)
def lookup(body: InvitationLookupIn, request: Request, db: DB) -> InvitationLookupOut:
    _limit(request)
    try:
        inv = members.find_open(db, body.token)
    except members.InvalidInvitation as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    has_account = db.scalar(select(User.id).where(User.email == inv.email)) is not None
    return InvitationLookupOut(
        organization_name=inv.organization.name,
        email=inv.email,
        role=inv.role,
        has_account=has_account,
        expires_at=inv.expires_at,
    )


@router.post("/invitations/accept", response_model=MeOut)
def accept(body: InvitationAcceptIn, request: Request, response: Response, db: DB) -> MeOut:
    _limit(request)
    try:
        user, membership = members.accept(
            db, body.token, password=body.password, full_name=body.full_name
        )
    except members.InvalidInvitation as exc:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except members.MemberError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return start_session(db, user, membership, response)
