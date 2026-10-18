"""Organisation members: invitations and role changes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Invitation,
    Membership,
    NotificationKind,
    NotificationLog,
    Role,
    User,
    UserSession,
)
from app.security import hash_password, hash_token, new_token, verify_password
from app.services import audit, notifications


class MemberError(Exception):
    """Business-rule violation; message is safe to show."""


class InvalidInvitation(MemberError):
    pass


INVALID_INVITATION = "This invitation link is invalid or has expired."
LAST_ADMIN = "An organisation needs at least one admin."


def _now() -> datetime:
    return datetime.now(UTC)


def _is_open(inv: Invitation, at: datetime) -> bool:
    return inv.accepted_at is None and inv.revoked_at is None and inv.expires_at > at


# ---------------------------------------------------------------- invitations


def create_invitation(
    db: Session, *, org_id: uuid.UUID, actor: User, email: str, role: Role
) -> tuple[Invitation, str]:
    email = email.strip().lower()
    member = db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org_id, func.lower(User.email) == email)
    )
    if member is not None:
        raise MemberError("This person is already a member.")
    t = _now()
    existing = db.scalar(
        select(Invitation).where(
            Invitation.org_id == org_id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
    )
    if existing is not None:
        if existing.expires_at > t:
            raise MemberError("This person already has an open invitation. Resend it instead.")
        existing.revoked_at = t  # expired: replace it
        db.flush()
    token = new_token()
    inv = Invitation(
        org_id=org_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by_id=actor.id,
        expires_at=t + timedelta(days=get_settings().invitation_ttl_days),
    )
    db.add(inv)
    db.flush()
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor.id,
        action="invitation.created",
        object_type="invitation",
        object_id=inv.id,
        meta={"role": role.value},
    )
    return inv, token


def renew_token(db: Session, inv: Invitation, actor: User) -> str:
    # Expired invitations can be resent; accepted or revoked ones cannot.
    if inv.accepted_at is not None or inv.revoked_at is not None:
        raise MemberError("Only open invitations can be resent.")
    token = new_token()
    inv.token_hash = hash_token(token)
    inv.expires_at = _now() + timedelta(days=get_settings().invitation_ttl_days)
    audit.record(
        db,
        org_id=inv.org_id,
        actor_id=actor.id,
        action="invitation.resent",
        object_type="invitation",
        object_id=inv.id,
    )
    return token


def send_invitation(db: Session, inv: Invitation, token: str) -> NotificationLog:
    message = notifications.invitation_mail(
        inv.email,
        inv.organization.name,
        inv.invited_by.full_name if inv.invited_by else None,
        inv.role,
        notifications.link("/accept-invite", token),
        inv.expires_at,
    )
    entry = notifications.send_logged(
        db,
        message,
        org_id=inv.org_id,
        kind=NotificationKind.INVITATION,
        object_type="invitation",
        object_id=inv.id,
    )
    inv.last_sent_at = _now()
    return entry


def revoke(db: Session, inv: Invitation, actor: User) -> None:
    if inv.accepted_at is not None or inv.revoked_at is not None:
        raise MemberError("This invitation is no longer open.")
    inv.revoked_at = _now()
    audit.record(
        db,
        org_id=inv.org_id,
        actor_id=actor.id,
        action="invitation.revoked",
        object_type="invitation",
        object_id=inv.id,
    )


def find_open(db: Session, token: str) -> Invitation:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    if inv is None or not _is_open(inv, _now()):
        raise InvalidInvitation(INVALID_INVITATION)
    return inv


def accept(
    db: Session, token: str, *, password: str, full_name: str | None
) -> tuple[User, Membership]:
    """Accept an invitation, creating the account if the email has none.

    An existing account proves ownership with its password. The claim is a single
    conditional UPDATE, so a token can be used once even under concurrent requests.
    """
    inv = find_open(db, token)
    user = db.scalar(select(User).where(func.lower(User.email) == inv.email))
    if user is not None:
        if not user.is_active or not verify_password(user.password_hash, password):
            raise MemberError("The password does not match the existing account for this email.")
    else:
        if not full_name or not full_name.strip():
            raise MemberError("Enter your name.")
        if len(password) < 12:
            raise MemberError("Choose a password of at least 12 characters.")
    t = _now()
    claimed = db.execute(
        update(Invitation)
        .where(
            Invitation.id == inv.id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > t,
        )
        .values(accepted_at=t)
        .returning(Invitation.id)
    ).first()
    if claimed is None:
        raise InvalidInvitation(INVALID_INVITATION)
    if user is None:
        assert full_name is not None
        user = User(
            email=inv.email,
            full_name=full_name.strip()[:200],
            password_hash=hash_password(password),
        )
        db.add(user)
        db.flush()
    membership = db.scalar(
        select(Membership).where(Membership.org_id == inv.org_id, Membership.user_id == user.id)
    )
    if membership is None:
        membership = Membership(org_id=inv.org_id, user_id=user.id, role=inv.role)
        db.add(membership)
    db.execute(update(Invitation).where(Invitation.id == inv.id).values(accepted_by_id=user.id))
    db.flush()
    audit.record(
        db,
        org_id=inv.org_id,
        actor_id=user.id,
        action="invitation.accepted",
        object_type="invitation",
        object_id=inv.id,
        meta={"role": membership.role.value},
    )
    return user, membership


# ---------------------------------------------------------------- members


def _ensure_another_admin(db: Session, org_id: uuid.UUID, leaving: Membership) -> None:
    # Lock the org's admin rows so two concurrent demotions cannot both pass.
    admins = db.scalars(
        select(Membership.id)
        .where(Membership.org_id == org_id, Membership.role == Role.ORG_ADMIN)
        .with_for_update()
    ).all()
    if leaving.role == Role.ORG_ADMIN and len([a for a in admins if a != leaving.id]) == 0:
        raise MemberError(LAST_ADMIN)


def change_role(db: Session, m: Membership, role: Role, actor: User) -> None:
    if m.role == role:
        return
    if m.role == Role.ORG_ADMIN:
        _ensure_another_admin(db, m.org_id, m)
    previous = m.role
    m.role = role
    audit.record(
        db,
        org_id=m.org_id,
        actor_id=actor.id,
        action="member.role_changed",
        object_type="user",
        object_id=m.user_id,
        meta={"from": previous.value, "to": role.value},
    )


def remove(db: Session, m: Membership, actor: User) -> None:
    _ensure_another_admin(db, m.org_id, m)
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == m.user_id,
            UserSession.org_id == m.org_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    audit.record(
        db,
        org_id=m.org_id,
        actor_id=actor.id,
        action="member.removed",
        object_type="user",
        object_id=m.user_id,
        meta={"role": m.role.value},
    )
    db.delete(m)
