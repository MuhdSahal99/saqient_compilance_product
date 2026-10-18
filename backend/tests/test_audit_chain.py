from __future__ import annotations

import os
import threading
import uuid

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from app.db import get_sessionmaker
from app.models import Role
from app.services import audit
from tests.conftest import Tenant, login, upload


def _tamper(db: Session, sql: str, **params: object) -> None:
    db.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update"))
    db.execute(text(sql), params)
    db.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update"))
    db.commit()


def test_events_are_chained_and_verify(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    assert upload(admin).status_code == 201
    assert upload(admin, data=b"Another synthetic policy text.").status_code == 201
    events = admin.get("/api/audit-events?page_size=200").json()["items"]
    seqs = sorted(e["seq"] for e in events)
    assert seqs == list(range(1, len(seqs) + 1))
    resp = admin.get("/api/audit-events/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["checked"] == len(seqs)
    assert body["head_seq"] == len(seqs)
    assert len(body["head_hash"]) == 64


def test_update_is_rejected_by_database(tenant_a: Tenant, db: Session) -> None:
    audit.record(db, org_id=tenant_a.org.id, actor_id=None, action="x", object_type="t")
    db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE audit_events SET action = 'y'"))
    db.rollback()


def test_tampered_content_is_reported(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    for i in range(4):
        audit.record(db, org_id=tenant_a.org.id, actor_id=None, action=f"a.{i}", object_type="t")
        audit.record(db, org_id=tenant_b.org.id, actor_id=None, action=f"b.{i}", object_type="t")
    db.commit()
    _tamper(
        db,
        "UPDATE audit_events SET metadata = '{\"edited\": true}' WHERE org_id = :o AND seq = 3",
        o=tenant_a.org.id,
    )
    a = login(tenant_a.users[Role.ORG_ADMIN]).get("/api/audit-events/verify").json()
    assert a["ok"] is False
    assert a["first_broken_seq"] == 3
    assert "content" in a["reason"]
    # Another tenant's chain is independent and unaffected.
    b = login(tenant_b.users[Role.ORG_ADMIN]).get("/api/audit-events/verify").json()
    assert b["ok"] is True
    assert b["checked"] >= 4  # plus the sign-in event


def test_removed_event_is_reported(tenant_a: Tenant, db: Session) -> None:
    for i in range(3):
        audit.record(db, org_id=tenant_a.org.id, actor_id=None, action=f"a.{i}", object_type="t")
    db.commit()
    db.execute(
        text("DELETE FROM audit_events WHERE org_id = :o AND seq = 2"), {"o": tenant_a.org.id}
    )
    db.commit()
    result = audit.verify_chain(db, tenant_a.org.id)
    assert not result.ok
    assert result.first_broken_seq == 3


def test_relinked_chain_after_edit_is_still_detected(tenant_a: Tenant, db: Session) -> None:
    """Rewriting an event and its own hash still breaks the next event's link."""
    for i in range(3):
        audit.record(db, org_id=tenant_a.org.id, actor_id=None, action=f"a.{i}", object_type="t")
    db.commit()
    first = db.execute(
        text("SELECT * FROM audit_events WHERE org_id = :o AND seq = 1"), {"o": tenant_a.org.id}
    ).one()
    forged = audit.compute_hash(
        event_id=first.id,
        org_id=first.org_id,
        seq=1,
        actor_id=None,
        action="forged",
        object_type="t",
        object_id=None,
        meta={},
        created_at=first.created_at,
        prev_hash=audit.GENESIS_HASH,
    )
    _tamper(
        db,
        "UPDATE audit_events SET action = 'forged', hash = :h WHERE id = :id",
        h=forged,
        id=first.id,
    )
    result = audit.verify_chain(db, tenant_a.org.id)
    assert not result.ok
    assert result.first_broken_seq == 2


@pytest.mark.parametrize("role", [Role.REVIEWER, Role.ANALYST, Role.VIEWER])
def test_verify_is_admin_only(tenant_a: Tenant, role: Role) -> None:
    assert login(tenant_a.users[role]).get("/api/audit-events/verify").status_code == 403


def test_verify_requires_sign_in() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/audit-events/verify").status_code == 401


def test_concurrent_appends_keep_one_chain(tenant_a: Tenant, db: Session) -> None:
    org_id = tenant_a.org.id

    def worker(n: int) -> None:
        with get_sessionmaker()() as s:
            for i in range(10):
                audit.record(s, org_id=org_id, actor_id=None, action=f"w{n}.{i}", object_type="t")
                s.commit()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    result = audit.verify_chain(db, org_id)
    assert result.ok
    assert result.checked == 40


def test_migration_backfills_existing_events(tenant_a: Tenant, db: Session) -> None:
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    db.close()
    command.downgrade(cfg, "0002")
    try:
        with get_sessionmaker()() as s:
            for i in range(5):
                s.execute(
                    text(
                        "INSERT INTO audit_events (id, org_id, action, object_type, metadata, "
                        "created_at) VALUES (:id, :o, :a, 't', CAST(:m AS jsonb), "
                        "now() - make_interval(secs => :i))"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "o": tenant_a.org.id,
                        "a": f"old.{i}",
                        "m": '{"n": 1}',
                        "i": 10 - i,
                    },
                )
            s.execute(
                text(
                    "INSERT INTO audit_events (id, org_id, action, object_type, metadata) "
                    "VALUES (:id, NULL, 'auth.login_failed', 'user', '{}')"
                ),
                {"id": uuid.uuid4()},
            )
            s.commit()
    finally:
        command.upgrade(cfg, "head")
    with get_sessionmaker()() as s:
        org_chain = audit.verify_chain(s, tenant_a.org.id)
        assert org_chain.ok and org_chain.checked == 5
        assert audit.verify_chain(s, None).ok
        # New events continue the backfilled chain.
        audit.record(s, org_id=tenant_a.org.id, actor_id=None, action="new", object_type="t")
        s.commit()
        after = audit.verify_chain(s, tenant_a.org.id)
        assert after.ok and after.head_seq == 6
