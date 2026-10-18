"""Invitations, role changes and member removal."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail
from app.main import app
from app.models import AuditEvent, Invitation, Membership, NotificationLog, Role, User
from tests.conftest import PASSWORD, ApiClient, Tenant, login


@pytest.fixture(autouse=True)
def _outbox() -> None:
    mail.outbox.clear()


def token_from_last_mail() -> str:
    match = re.search(r"#token=([A-Za-z0-9_\-]+)", mail.outbox[-1].text)
    assert match, mail.outbox[-1].text
    return match.group(1)


def membership_id(db: Session, tenant: Tenant, role: Role) -> str:
    m = db.scalar(
        select(Membership).where(
            Membership.org_id == tenant.org.id, Membership.user_id == tenant.users[role].id
        )
    )
    assert m is not None
    return str(m.id)


def test_invite_new_person_accept_and_sign_in(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    r = admin.post("/api/invitations", json={"email": "New.Person@Example.com", "role": "analyst"})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["email"] == "new.person@example.com" and inv["last_delivery"] == "sent"
    assert len(mail.outbox) == 1 and mail.outbox[0].to == "new.person@example.com"
    assert "analyst" in mail.outbox[0].text and "محلل" in mail.outbox[0].text
    assert "http://localhost:5173/accept-invite#token=" in mail.outbox[0].text
    token = token_from_last_mail()
    # The token is stored only as a hash, and the log keeps no body.
    row = db.get(Invitation, uuid.UUID(inv["id"]))
    assert row is not None and token not in row.token_hash
    log = db.scalar(select(NotificationLog).where(NotificationLog.object_id == row.id))
    assert log is not None and log.status.value == "sent"
    assert admin.get("/api/invitations").json()[0]["id"] == inv["id"]

    anon = ApiClient(app)
    looked = anon.post("/api/invitations/lookup", json={"token": token})
    assert looked.status_code == 200
    assert looked.json() == {
        "organization_name": "Org a",
        "email": "new.person@example.com",
        "role": "analyst",
        "has_account": False,
        "expires_at": looked.json()["expires_at"],
    }
    short = anon.post(
        "/api/invitations/accept", json={"token": token, "password": "short", "full_name": "N P"}
    )
    assert short.status_code == 422
    ok = anon.post(
        "/api/invitations/accept",
        json={"token": token, "password": "a-long-enough-password", "full_name": "New Person"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["role"] == "analyst" and ok.json()["org"]["name"] == "Org a"
    assert anon.get("/api/auth/me").status_code == 200  # signed in by the accept
    # Single use.
    again = ApiClient(app).post(
        "/api/invitations/accept",
        json={"token": token, "password": "a-long-enough-password", "full_name": "X"},
    )
    assert again.status_code == 404
    assert admin.get("/api/invitations").json() == []
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.org_id == tenant_a.org.id)))
    assert {"invitation.created", "invitation.accepted"} <= actions


def test_existing_account_joins_with_its_password(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    b_viewer = tenant_b.users[Role.VIEWER]
    admin.post("/api/invitations", json={"email": b_viewer.email, "role": "reviewer"})
    token = token_from_last_mail()
    anon = ApiClient(app)
    assert anon.post("/api/invitations/lookup", json={"token": token}).json()["has_account"]
    wrong = anon.post("/api/invitations/accept", json={"token": token, "password": "nope-nope"})
    assert wrong.status_code == 422
    # A failed attempt does not use up the invitation.
    ok = anon.post("/api/invitations/accept", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 200, ok.text
    assert ok.json()["role"] == "reviewer"
    assert {m["org"]["name"] for m in ok.json()["memberships"]} == {"Org a", "Org b"}
    user = db.get(User, b_viewer.id)
    assert user is not None and user.full_name == b_viewer.full_name


def test_invitation_rules(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    member = tenant_a.users[Role.VIEWER].email
    assert (
        admin.post("/api/invitations", json={"email": member, "role": "viewer"}).status_code == 409
    )
    first = admin.post("/api/invitations", json={"email": "x@example.com", "role": "viewer"})
    dup = admin.post("/api/invitations", json={"email": "X@example.com", "role": "analyst"})
    assert dup.status_code == 409 and "Resend" in dup.json()["detail"]
    old_token = token_from_last_mail()
    resent = admin.post(f"/api/invitations/{first.json()['id']}/resend")
    assert resent.status_code == 200 and len(mail.outbox) == 2
    new_token = token_from_last_mail()
    anon = ApiClient(app)
    assert anon.post("/api/invitations/lookup", json={"token": old_token}).status_code == 404
    assert anon.post("/api/invitations/lookup", json={"token": new_token}).status_code == 200
    # Expired invitations stop working and can be replaced.
    row = db.get(Invitation, uuid.UUID(first.json()["id"]))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert anon.post("/api/invitations/lookup", json={"token": new_token}).status_code == 404
    assert admin.get("/api/invitations").json()[0]["is_expired"] is True
    replaced = admin.post("/api/invitations", json={"email": "x@example.com", "role": "analyst"})
    assert replaced.status_code == 201
    # Revoked invitations stop working.
    token = token_from_last_mail()
    assert admin.delete(f"/api/invitations/{replaced.json()['id']}").status_code == 204
    assert anon.post("/api/invitations/lookup", json={"token": token}).status_code == 404
    assert admin.delete(f"/api/invitations/{replaced.json()['id']}").status_code == 409


def test_failed_delivery_is_recorded(tenant_a: Tenant, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(message: mail.Mail, settings: object = None) -> bool:
        raise mail.MailError("Delivery failed (ConnectionRefusedError).")

    monkeypatch.setattr(mail, "send", boom)
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    r = admin.post("/api/invitations", json={"email": "y@example.com", "role": "viewer"})
    assert r.status_code == 201 and r.json()["last_delivery"] == "failed"


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ANALYST, Role.VIEWER])
def test_only_admins_manage_members(tenant_a: Tenant, db: Session, role: Role) -> None:
    client = login(tenant_a.users[role])
    assert client.get("/api/invitations").status_code == 403
    assert (
        client.post("/api/invitations", json={"email": "z@example.com", "role": "viewer"})
    ).status_code == 403
    target = membership_id(db, tenant_a, Role.VIEWER)
    assert client.patch(f"/api/members/{target}", json={"role": "org_admin"}).status_code == 403
    assert client.delete(f"/api/members/{target}").status_code == 403


def test_role_changes_and_last_admin(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    own = membership_id(db, tenant_a, Role.ORG_ADMIN)
    r = admin.patch(f"/api/members/{own}", json={"role": "reviewer"})
    assert r.status_code == 409 and "at least one admin" in r.json()["detail"]
    assert admin.delete(f"/api/members/{own}").status_code == 409

    analyst_m = membership_id(db, tenant_a, Role.ANALYST)
    r = admin.patch(f"/api/members/{analyst_m}", json={"role": "org_admin"})
    assert r.status_code == 200 and r.json()["role"] == "org_admin"
    # With a second admin, the first can step down.
    assert admin.patch(f"/api/members/{own}", json={"role": "reviewer"}).status_code == 200
    assert admin.get("/api/invitations").status_code == 403  # now a reviewer

    new_admin = login(tenant_a.users[Role.ANALYST])
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "member.role_changed")).all()
    assert [e.meta for e in events] == [
        {"from": "analyst", "to": "org_admin"},
        {"from": "org_admin", "to": "reviewer"},
    ]
    assert new_admin.get("/api/invitations").status_code == 200


def test_removing_a_member_ends_their_session(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.get("/api/auth/me").status_code == 200
    assert (
        admin.delete(f"/api/members/{membership_id(db, tenant_a, Role.VIEWER)}").status_code == 204
    )
    assert viewer.get("/api/auth/me").status_code == 401
    emails = {m["email"] for m in admin.get("/api/members").json()}
    assert tenant_a.users[Role.VIEWER].email not in emails


def test_members_are_tenant_isolated(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    admin_a = login(tenant_a.users[Role.ORG_ADMIN])
    admin_b = login(tenant_b.users[Role.ORG_ADMIN])
    b_member = membership_id(db, tenant_b, Role.VIEWER)
    assert admin_a.patch(f"/api/members/{b_member}", json={"role": "org_admin"}).status_code == 404
    assert admin_a.delete(f"/api/members/{b_member}").status_code == 404
    inv = admin_b.post("/api/invitations", json={"email": "b@example.com", "role": "viewer"})
    assert admin_a.post(f"/api/invitations/{inv.json()['id']}/resend").status_code == 404
    assert admin_a.delete(f"/api/invitations/{inv.json()['id']}").status_code == 404
    assert admin_a.get("/api/invitations").json() == []


def test_invitation_endpoints_are_rate_limited(tenant_a: Tenant) -> None:
    anon = ApiClient(app)
    codes = [
        anon.post("/api/invitations/lookup", json={"token": "x" * 43}).status_code
        for _ in range(12)
    ]
    assert codes[:10] == [404] * 10 and codes[-1] == 429
