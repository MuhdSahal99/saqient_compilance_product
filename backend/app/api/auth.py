from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select, update

from app.config import get_settings
from app.deps import DB, SESSION_COOKIE, Ctx, now
from app.models import Membership, User, UserSession
from app.schemas import (
    ChangePasswordIn,
    LoginIn,
    MembershipOut,
    MeOut,
    OrgOut,
    SwitchOrgIn,
    UserOut,
)
from app.security import (
    burn_password_check,
    hash_password,
    hash_token,
    login_limiter,
    new_token,
    verify_password,
)
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID = "Invalid email or password."


def _me(db: DB, user: User, sess: UserSession, membership: Membership) -> MeOut:
    settings = get_settings()
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    return MeOut(
        user=UserOut.model_validate(user),
        org=OrgOut.model_validate(membership.organization),
        role=membership.role,
        memberships=[
            MembershipOut(org=OrgOut.model_validate(m.organization), role=m.role)
            for m in memberships
        ],
        csrf_token=sess.csrf_token,
        demo_mode=settings.demo_mode,
        ai_enabled=settings.ai_enabled,
    )


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_absolute_hours * 3600,
        path="/",
    )


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: DB) -> MeOut:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    email = body.email.lower()
    if not login_limiter.hit(
        f"login:{ip}:{email}", settings.login_rate_limit, settings.login_rate_window_seconds
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-in attempts. Try again in a few minutes.",
        )
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        burn_password_check(body.password)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)
    if not verify_password(user.password_hash, body.password) or not user.is_active:
        audit.record(
            db,
            org_id=None,
            actor_id=user.id,
            action="auth.login_failed",
            object_type="user",
            object_id=user.id,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)
    if user.is_demo and not settings.demo_mode:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Demo accounts only work when demo mode is enabled."
        )
    membership = db.scalar(
        select(Membership)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
        .limit(1)
    )
    if membership is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Your account is not a member of any organisation."
        )
    token = new_token()
    t = now()
    sess = UserSession(
        token_hash=hash_token(token),
        csrf_token=new_token(),
        user_id=user.id,
        org_id=membership.org_id,
        last_seen_at=t,
        expires_at=t + timedelta(hours=settings.session_absolute_hours),
    )
    db.add(sess)
    audit.record(
        db,
        org_id=membership.org_id,
        actor_id=user.id,
        action="auth.login",
        object_type="user",
        object_id=user.id,
    )
    db.commit()
    _set_cookie(response, token)
    return _me(db, user, sess, membership)


@router.post("/logout", status_code=204)
def logout(ctx: Ctx, response: Response, db: DB) -> None:
    ctx.session.revoked_at = now()
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="auth.logout",
        object_type="user",
        object_id=ctx.user.id,
    )
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=MeOut)
def me(ctx: Ctx, db: DB) -> MeOut:
    membership = db.scalar(
        select(Membership).where(Membership.user_id == ctx.user.id, Membership.org_id == ctx.org_id)
    )
    assert membership is not None
    return _me(db, ctx.user, ctx.session, membership)


@router.post("/switch-org", response_model=MeOut)
def switch_org(body: SwitchOrgIn, ctx: Ctx, db: DB) -> MeOut:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == ctx.user.id, Membership.org_id == body.org_id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    ctx.session.org_id = membership.org_id
    audit.record(
        db,
        org_id=membership.org_id,
        actor_id=ctx.user.id,
        action="auth.switch_org",
        object_type="organization",
        object_id=membership.org_id,
    )
    db.commit()
    return _me(db, ctx.user, ctx.session, membership)


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordIn, ctx: Ctx, db: DB) -> None:
    if not verify_password(ctx.user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
    ctx.user.password_hash = hash_password(body.new_password)
    # Invalidate every other session for this user.
    db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == ctx.user.id,
            UserSession.id != ctx.session.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="auth.password_changed",
        object_type="user",
        object_id=ctx.user.id,
    )
    db.commit()


@router.patch("/locale", status_code=204)
def set_locale(locale: str, ctx: Ctx, db: DB) -> None:
    if locale not in ("en", "ar"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unsupported locale.")
    ctx.user.preferred_locale = locale
    db.commit()
