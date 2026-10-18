"""Phase B (B4): scheduled e-invoice sampling monitors."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import demo_einvoice as demo
from app.models import AuditEvent, EInvoiceFile, EInvoiceMonitor, Role
from app.services import monitors as svc
from app.worker import run_due_monitors_task
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import (
    VALIDATE_AE,
    checklist,
    findings,
    req,
    results,
    synthetic_pack,
    upload_batch,
)


def _files(prefix: str, n: int) -> bytes:
    return demo.zip_of(
        [
            (
                f"{prefix}-{i}.xml",
                demo.invoice_xml(demo.InvoiceSpec(number=f"{prefix}-{i}", uuid=f"{prefix}-u{i}")),
            )
            for i in range(n)
        ]
    )


def test_draw_sample_is_reproducible_and_order_free() -> None:
    files = [EInvoiceFile(sha256=f"{i:064x}") for i in range(20)]
    a = svc.draw_sample("seed-1", files, 5)
    b = svc.draw_sample("seed-1", list(reversed(files)), 5)
    assert [f.sha256 for f in a] == [f.sha256 for f in b]
    assert [f.sha256 for f in svc.draw_sample("seed-2", files, 5)] != [f.sha256 for f in a]
    assert len(svc.draw_sample("s", files, 50)) == 20
    jan31 = datetime(2026, 1, 31, 6, tzinfo=UTC)
    assert svc.next_after(jan31, svc.MonitorCadence.MONTHLY) == datetime(2026, 2, 28, 6, tzinfo=UTC)
    assert svc.next_after(jan31, svc.MonitorCadence.WEEKLY) == jan31 + timedelta(days=7)


def test_monitor_samples_new_files_into_reviews(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin)
    cv = checklist(reviewer, [req("EINV-01", VALIDATE_AE)])
    assert upload_batch(analyst, entity, _files("A", 6)).status_code == 201

    body = {
        "entity_id": str(entity.id),
        "name": "Weekly sample",
        "checklist_version_id": cv,
        "rule_pack_version_id": rpv,
        "sample_size": 4,
        "cadence": "weekly",
    }
    assert analyst.post("/api/einvoice-monitors", json=body).status_code == 403
    r = reviewer.post("/api/einvoice-monitors", json=body)
    assert r.status_code == 201, r.text
    mon = r.json()
    assert mon["is_active"] and len(mon["seed"]) == 32

    run = reviewer.post(f"/api/einvoice-monitors/{mon['id']}/run")
    assert run.status_code == 200, run.text
    first = run.json()
    assert first["status"] == "review_created"
    assert (first["population"], first["sampled"]) == (6, 4)
    assert first["window_start"] is None and first["seed"] == mon["seed"]
    review = reviewer.get(f"/api/reviews/{first['review_id']}").json()
    assert review["einvoice_count"] == 4 and review["entity_id"] == str(entity.id)
    assert results(reviewer, first["review_id"])["EINV-01"]["outcome"] == "no_exceptions"

    # The sample is the documented ranking over the window's files.
    stored = list(db.scalars(select(EInvoiceFile).where(EInvoiceFile.entity_id == entity.id)))
    expect = {f.id for f in svc.draw_sample(mon["seed"], stored, 4)}
    links = reviewer.get(f"/api/reviews/{first['review_id']}/einvoices")
    assert links.status_code == 200
    assert {uuid.UUID(x["id"]) for x in links.json()} == expect
    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get(f"/api/reviews/{first['review_id']}/einvoices").status_code == 404

    # Nothing new since the last run: no review.
    again = reviewer.post(f"/api/einvoice-monitors/{mon['id']}/run").json()
    assert again["status"] == "no_files" and again["review_id"] is None

    # New files with a bad one: only the new window is sampled.
    bad = demo.invoice_xml(demo.InvoiceSpec(number="B-BAD", uuid="b-bad", payable_override="1"))
    assert upload_batch(analyst, entity, bad, "bad.xml", "application/xml").status_code == 201
    third = reviewer.post(f"/api/einvoice-monitors/{mon['id']}/run").json()
    assert (third["population"], third["sampled"]) == (1, 1)
    assert [f["finding_key"] for f in findings(reviewer, third["review_id"])] == [
        "arithmetic:payable"
    ]
    runs = reviewer.get(f"/api/einvoice-monitors/{mon['id']}/runs").json()
    assert [x["status"] for x in runs] == ["review_created", "no_files", "review_created"]
    actions = set(
        db.scalars(select(AuditEvent.action).where(AuditEvent.object_id == uuid.UUID(mon["id"])))
    )
    assert {"einvoice_monitor.created", "einvoice_monitor.ran"} <= actions


def test_scheduled_run_picks_due_monitors_only(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin)
    cv = checklist(reviewer, [req("EINV-01", VALIDATE_AE)])
    upload_batch(login(tenant_a.users[Role.ANALYST]), entity, _files("C", 3))
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    base = {
        "entity_id": str(entity.id),
        "checklist_version_id": cv,
        "rule_pack_version_id": rpv,
        "sample_size": 2,
        "cadence": "daily",
    }
    due = reviewer.post(
        "/api/einvoice-monitors", json={**base, "name": "Due", "first_run_at": past}
    ).json()
    later = reviewer.post(
        "/api/einvoice-monitors", json={**base, "name": "Later", "first_run_at": future}
    ).json()
    paused = reviewer.post(
        "/api/einvoice-monitors", json={**base, "name": "Paused", "first_run_at": past}
    ).json()
    p = reviewer.patch(f"/api/einvoice-monitors/{paused['id']}", json={"is_active": False})
    assert p.status_code == 200 and not p.json()["is_active"]

    out = run_due_monitors_task.apply().get()
    assert out == {"ran": 1, "failed": 0, "reviews": 1}
    db.expire_all()
    m = db.get(EInvoiceMonitor, uuid.UUID(due["id"]))
    assert m is not None and m.next_run_at > datetime.now(UTC)
    assert reviewer.get(f"/api/einvoice-monitors/{later['id']}/runs").json() == []
    assert reviewer.get(f"/api/einvoice-monitors/{paused['id']}/runs").json() == []


def test_monitor_validation_roles_and_tenant_isolation(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    cv = checklist(reviewer, [req("EINV-01", VALIDATE_AE)])
    body = {
        "entity_id": str(entity.id),
        "name": "M",
        "checklist_version_id": cv,
        "sample_size": 0,
        "cadence": "daily",
    }
    assert reviewer.post("/api/einvoice-monitors", json=body).status_code == 422
    body["sample_size"] = 3
    mon = admin.post("/api/einvoice-monitors", json=body)
    assert mon.status_code == 201
    mid = mon.json()["id"]
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.get("/api/einvoice-monitors").status_code == 200
    assert viewer.post(f"/api/einvoice-monitors/{mid}/run").status_code == 403
    assert (
        viewer.patch(f"/api/einvoice-monitors/{mid}", json={"is_active": False}).status_code == 403
    )

    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get("/api/einvoice-monitors").json() == []
    assert (
        other.patch(f"/api/einvoice-monitors/{mid}", json={"is_active": False}).status_code == 404
    )
    assert other.post(f"/api/einvoice-monitors/{mid}/run").status_code == 404
    assert other.get(f"/api/einvoice-monitors/{mid}/runs").status_code == 404
    assert other.post(f"/api/einvoice-monitors/{uuid.uuid4()}/run").status_code == 404
    # A foreign entity or checklist cannot be used.
    assert other.post("/api/einvoice-monitors", json=body).status_code == 404
