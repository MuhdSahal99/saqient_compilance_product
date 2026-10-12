from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditEvent, Role, UserSession
from tests.conftest import PASSWORD, ApiClient, Tenant, login


def test_login_me_logout_invalidates_session(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.REVIEWER])
    assert "saqient_session" in client.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "reviewer"
    assert me.json()["org"]["slug"] == "a"
    cookie = client.cookies.get("saqient_session")

    assert client.post("/api/auth/logout").status_code == 204
    # Replaying the old cookie after logout must fail.
    replay = TestClient(app)
    replay.cookies.set("saqient_session", cookie)
    assert replay.get("/api/auth/me").status_code == 401
    actions = set(db.scalars(select(AuditEvent.action)))
    assert {"auth.login", "auth.logout"} <= actions


def test_session_token_is_stored_hashed(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.VIEWER])
    token = client.cookies.get("saqient_session")
    stored = db.scalars(select(UserSession.token_hash)).all()
    assert token not in stored and len(stored) == 1


def test_wrong_password_and_unknown_user_same_error(tenant_a: Tenant) -> None:
    c = TestClient(app)
    r1 = c.post("/api/auth/login", json={"email": "viewer@a.example", "password": "nope"})
    r2 = c.post("/api/auth/login", json={"email": "ghost@a.example", "password": "nope"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_unauthenticated_requests_rejected() -> None:
    c = TestClient(app)
    for path in ("/api/documents", "/api/reviews", "/api/findings", "/api/dashboard"):
        assert c.get(path).status_code == 401


def test_csrf_required_for_unsafe_methods(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.REVIEWER])
    client.csrf = ""
    r = client.post("/api/auth/logout")
    assert r.status_code == 403
    r = client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403


def test_login_rate_limited(tenant_a: Tenant) -> None:
    c = TestClient(app)
    codes = [
        c.post("/api/auth/login", json={"email": "viewer@a.example", "password": "bad"}).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert codes[-1] == 429


def test_change_password_revokes_other_sessions(tenant_a: Tenant) -> None:
    user = tenant_a.users[Role.ANALYST]
    first, second = login(user), login(user)
    r = first.post(
        "/api/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-new-long-password"},
    )
    assert r.status_code == 204
    assert first.get("/api/auth/me").status_code == 200
    assert second.get("/api/auth/me").status_code == 401


def test_demo_users_rejected_without_demo_mode(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    user = tenant_a.users[Role.VIEWER]
    user.is_demo = True
    db.commit()
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert r.status_code == 401
    assert "demo" in r.json()["detail"].lower()


def test_removed_membership_takes_effect_immediately(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    from app.models import Membership

    client: ApiClient = login(tenant_a.users[Role.ANALYST])
    m = db.scalar(select(Membership).where(Membership.user_id == tenant_a.users[Role.ANALYST].id))
    db.delete(m)
    db.commit()
    assert client.get("/api/documents").status_code == 401


def test_security_headers_present(tenant_a: Tenant) -> None:
    r = TestClient(app).get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_cors_rejects_unknown_origin() -> None:
    c = TestClient(app)
    ok = c.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    bad = c.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers
