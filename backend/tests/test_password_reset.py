"""Password reset by emailed single-use link."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail
from app.main import app
from app.models import AuditEvent, PasswordResetToken, Role
from tests.conftest import ApiClient, Tenant, login
from tests.test_members import token_from_last_mail

NEW = "a-brand-new-password"


@pytest.fixture(autouse=True)
def _outbox() -> None:
    mail.outbox.clear()


def request_reset(email: str) -> int:
    return (
        ApiClient(app).post("/api/auth/password-reset/request", json={"email": email}).status_code
    )


def test_reset_flow_revokes_sessions(tenant_a: Tenant, db: Session) -> None:
    user = tenant_a.users[Role.ANALYST]
    signed_in = login(user)
    assert request_reset(user.email.upper()) == 204
    assert len(mail.outbox) == 1 and mail.outbox[0].to == user.email
    assert "/reset-password#token=" in mail.outbox[0].text
    token = token_from_last_mail()
    stored = db.scalars(select(PasswordResetToken.token_hash)).all()
    assert token not in stored

    anon = ApiClient(app)
    r = anon.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": NEW})
    assert r.status_code == 204, r.text
    assert signed_in.get("/api/auth/me").status_code == 401  # every session ended
    assert (
        anon.post(
            "/api/auth/login", json={"email": user.email, "password": "correct-horse-battery"}
        ).status_code
        == 401
    )
    login(user, NEW)
    # Single use.
    again = anon.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": NEW}
    )
    assert again.status_code == 400
    actions = db.scalars(select(AuditEvent.action).where(AuditEvent.actor_id == user.id)).all()
    assert "auth.password_reset_requested" in actions and "auth.password_reset" in actions


def test_unknown_email_looks_the_same(tenant_a: Tenant) -> None:
    assert request_reset("nobody@example.com") == 204
    assert mail.outbox == []


def test_only_the_newest_link_works_and_links_expire(tenant_a: Tenant, db: Session) -> None:
    user = tenant_a.users[Role.VIEWER]
    request_reset(user.email)
    first = token_from_last_mail()
    request_reset(user.email)
    second = token_from_last_mail()
    anon = ApiClient(app)
    r = anon.post("/api/auth/password-reset/confirm", json={"token": first, "new_password": NEW})
    assert r.status_code == 400
    for row in db.scalars(select(PasswordResetToken)).all():
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    r = anon.post("/api/auth/password-reset/confirm", json={"token": second, "new_password": NEW})
    assert r.status_code == 400 and "invalid or has expired" in r.json()["detail"]


def test_reset_validation_and_rate_limit(tenant_a: Tenant) -> None:
    anon = ApiClient(app)
    short = anon.post(
        "/api/auth/password-reset/confirm", json={"token": "x" * 43, "new_password": "short"}
    )
    assert short.status_code == 422
    email = tenant_a.users[Role.VIEWER].email
    codes = [request_reset(email) for _ in range(6)]
    assert codes == [204] * 5 + [429]
    assert len(mail.outbox) == 5


def test_inactive_accounts_get_no_link(tenant_a: Tenant, db: Session) -> None:
    user = tenant_a.users[Role.VIEWER]
    user.is_active = False
    db.commit()
    assert request_reset(user.email) == 204
    assert mail.outbox == []
