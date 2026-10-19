from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Membership, Organization, Role, User, UserSession
from app.security import hash_token, tokens_equal

SESSION_COOKIE = "saqient_session"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DB = Annotated[Session, Depends(get_db)]


@dataclass
class Context:
    user: User
    org: Organization
    role: Role
    session: UserSession

    @property
    def org_id(self) -> uuid.UUID:
        return self.org.id


def now() -> datetime:
    return datetime.now(UTC)


# The client role (audit client contacts) may only reach sign-in and the request portal.
CLIENT_PATHS = ("/api/auth/", "/api/portal/")


def current_context(request: Request, db: DB) -> Context:
    ctx = _session_context(request, db)
    if ctx.role is Role.CLIENT and not request.url.path.startswith(CLIENT_PATHS):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This account can only use the client request portal."
        )
    return ctx


def _session_context(request: Request, db: DB) -> Context:
    settings = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    t = now()
    if (
        sess is None
        or sess.revoked_at is not None
        or sess.expires_at <= t
        or sess.last_seen_at + timedelta(minutes=settings.session_idle_minutes) <= t
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")

    # Membership is re-resolved on every request; removal takes effect immediately.
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == sess.user_id, Membership.org_id == sess.org_id
        )
    )
    if membership is None or not membership.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session no longer valid.")
    if membership.user.is_demo and not settings.demo_mode:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Demo accounts are disabled.")

    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        if not header or not tokens_equal(header, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing or invalid CSRF token.")

    if (t - sess.last_seen_at).total_seconds() > 60:
        sess.last_seen_at = t
        db.commit()
    return Context(
        user=membership.user, org=membership.organization, role=membership.role, session=sess
    )


Ctx = Annotated[Context, Depends(current_context)]

WRITE_ROLES = (Role.ORG_ADMIN, Role.REVIEWER, Role.ANALYST)
DECIDE_ROLES = (Role.ORG_ADMIN, Role.REVIEWER)


def require_role(*roles: Role) -> Callable[[Context], Context]:
    def checker(ctx: Ctx) -> Context:
        if ctx.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not permit this action.")
        return ctx

    return checker


Writer = Annotated[Context, Depends(require_role(*WRITE_ROLES))]
PortalCtx = Annotated[Context, Depends(require_role(Role.CLIENT))]
Decider = Annotated[Context, Depends(require_role(*DECIDE_ROLES))]
Admin = Annotated[Context, Depends(require_role(Role.ORG_ADMIN))]

M = TypeVar("M")


def get_owned_or_404(
    db: Session, model: type[M], obj_id: uuid.UUID, org_id: uuid.UUID, **filters: Any
) -> M:
    """Fetch a tenant-owned object. Objects in other organisations are reported as missing."""
    stmt = select(model).where(
        model.id == obj_id,  # type: ignore[attr-defined]
        model.org_id == org_id,  # type: ignore[attr-defined]
    )
    for key, value in filters.items():
        stmt = stmt.where(getattr(model, key) == value)
    obj = db.scalar(stmt)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return obj
