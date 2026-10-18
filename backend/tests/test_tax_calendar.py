"""Phase B (B6): tax calendar from rule packs, obligation tasks and reminders.

Golden dates are worked by hand from the synthetic obligation rule in
app/demo_einvoice.py: quarterly, calendar quarters, due on the 28th of the month
after the period ends.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app import mail
from app.models import Role
from app.services.reminders import send_due_reminders
from app.services.rule_schemas import Obligation
from app.services.tax_calendar import due_date, periods
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import synthetic_pack


@pytest.fixture(autouse=True)
def _outbox() -> None:
    mail.outbox.clear()


def test_period_enumeration_golden() -> None:
    d = date
    assert periods("monthly", "calendar", 12, d(2026, 1, 1), d(2026, 3, 31)) == [
        (d(2026, 1, 1), d(2026, 1, 31)),
        (d(2026, 2, 1), d(2026, 2, 28)),
        (d(2026, 3, 1), d(2026, 3, 31)),
    ]
    assert periods("quarterly", "calendar", 3, d(2026, 1, 1), d(2026, 12, 31)) == [
        (d(2026, 1, 1), d(2026, 3, 31)),
        (d(2026, 4, 1), d(2026, 6, 30)),
        (d(2026, 7, 1), d(2026, 9, 30)),
        (d(2026, 10, 1), d(2026, 12, 31)),
    ]
    # Fiscal quarters for a May year end end in Feb, May, Aug and Nov.
    assert periods("quarterly", "fiscal", 5, d(2026, 1, 1), d(2026, 12, 31)) == [
        (d(2025, 12, 1), d(2026, 2, 28)),
        (d(2026, 3, 1), d(2026, 5, 31)),
        (d(2026, 6, 1), d(2026, 8, 31)),
        (d(2026, 9, 1), d(2026, 11, 30)),
    ]
    assert periods("annual", "fiscal", 3, d(2026, 1, 1), d(2026, 12, 31)) == [
        (d(2025, 4, 1), d(2026, 3, 31))
    ]
    assert periods("annual", "calendar", 3, d(2026, 1, 1), d(2026, 12, 30)) == []


def test_due_date_golden() -> None:
    ob = Obligation(
        id="x", label="X", tax_type="vat", frequency="monthly", months_after=1, day_of_month=31
    )
    # 31 Jan + 1 month = 28 Feb (2026 is not a leap year); day 31 clamps to 28.
    assert due_date(ob, date(2026, 1, 31))[0] == date(2026, 2, 28)
    ob = Obligation(
        id="x", label="X", tax_type="vat", frequency="quarterly", months_after=0, days_after=30
    )
    got, formula = due_date(ob, date(2026, 3, 31))
    assert got == date(2026, 4, 30) and formula == "period end + 0 month(s) + 30 day(s)"
    ob = Obligation(
        id="x", label="X", tax_type="vat", frequency="quarterly", months_after=1, day_of_month=28
    )
    assert due_date(ob, date(2026, 12, 31))[0] == date(2027, 1, 28)


def _generate(client, entity, rpv, **over):  # type: ignore[no-untyped-def]
    body = {
        "rule_pack_version_id": rpv,
        "prefix": "syn.vat",
        "start": "2026-01-01",
        "end": "2026-12-31",
        "waves_rule": "syn.einvoice.go_live_waves",
        **over,
    }
    return client.post(f"/api/entities/{entity.id}/tax-calendar/generate", json=body)


def test_generate_obligations_tasks_and_periods(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin, with_bundle=False)
    admin.patch(
        f"/api/entities/{entity.id}",
        json={
            "size_basis_amount": "60000000",
            "size_basis_currency": "AED",
            "size_basis_year": 2025,
        },
    )
    owner = tenant_a.users[Role.ANALYST]

    r = _generate(reviewer, entity, rpv, owner_id=str(owner.id))
    assert r.status_code == 200, r.text
    out = r.json()
    # 4 quarterly VAT returns + the ASP milestone 2026-09-30 (go-live 2027-01-01 is outside).
    assert (out["created"], out["updated"], out["unchanged"]) == (5, 0, 0)
    assert out["periods_created"] == 4
    assert any("Unverified" in w for w in out["warnings"])
    dues = sorted((o["obligation_key"], o["due_date"]) for o in out["obligations"])
    assert dues == [
        ("einvoicing:asp", "2026-09-30"),
        ("vat_return", "2026-04-28"),
        ("vat_return", "2026-07-28"),
        ("vat_return", "2026-10-28"),
        ("vat_return", "2027-01-28"),
    ]
    q1 = next(o for o in out["obligations"] if o["due_date"] == "2026-04-28")
    assert q1["period_start"] == "2026-01-01" and q1["period_end"] == "2026-03-31"
    assert q1["formula"] == "period end + 1 month(s), day 28 of that month"
    assert q1["rule_snapshot"]["rule_key"] == "syn.vat.obligations"
    assert not q1["rule_verified"] and q1["tax_period_id"]
    assert q1["task"]["owner_id"] == str(owner.id) and q1["task"]["status"] == "open"
    periods_listed = reviewer.get(f"/api/entities/{entity.id}/tax-periods").json()
    assert len(periods_listed) == 4

    # Close Q1 with a note, then regenerate: nothing is duplicated or moved.
    analyst = login(owner)
    no_note = analyst.patch(f"/api/tasks/{q1['task']['id']}", json={"status": "done"})
    assert no_note.status_code == 422
    done = analyst.patch(
        f"/api/tasks/{q1['task']['id']}", json={"status": "done", "note": "Synthetic ref 001"}
    )
    assert done.status_code == 200 and done.json()["completed_at"]
    again = _generate(reviewer, entity, rpv).json()
    assert (again["created"], again["updated"], again["unchanged"]) == (0, 0, 5)
    assert again["periods_created"] == 0

    listed = analyst.get(
        "/api/tax-obligations", params={"entity_id": str(entity.id), "due_to": "2026-07-31"}
    ).json()
    assert [o["due_date"] for o in listed] == ["2026-04-28", "2026-07-28"]
    mine = analyst.get("/api/tasks", params={"mine": "true", "status": "open"}).json()
    assert len(mine) == 4
    assert (
        analyst.patch(f"/api/tasks/{mine[0]['id']}", json={"due_date": "2026-05-01"}).status_code
        == 422
    )


def test_reminder_digest_includes_obligation_tasks(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin, with_bundle=False)
    owner = tenant_a.users[Role.ANALYST]
    r = _generate(
        admin, entity, rpv, owner_id=str(owner.id), include_einvoicing=False, end="2026-06-30"
    )
    assert r.status_code == 200, r.text
    # Q1 due 2026-04-28; reminder window covers it from a few days before.
    run = send_due_reminders(db, today=date(2026, 4, 27))
    assert run.sent == 1
    assert len(mail.outbox) == 1 and mail.outbox[0].to == owner.email
    assert "VAT return (synthetic)" in mail.outbox[0].text
    assert "due in 1 day(s)" in mail.outbox[0].text
    assert send_due_reminders(db, today=date(2026, 4, 27)).skipped == 1


def test_calendar_validation_roles_and_tenant_isolation(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin, with_bundle=False)
    analyst = login(tenant_a.users[Role.ANALYST])
    assert _generate(analyst, entity, rpv).status_code == 403
    assert _generate(admin, entity, rpv, end="2025-01-01").status_code == 422
    assert _generate(admin, entity, rpv, end="2030-12-31").status_code == 422
    assert _generate(admin, entity, rpv, prefix="syn.none").status_code == 422
    # The e-invoicing milestones need a size basis or a notified date.
    assert _generate(admin, entity, rpv).status_code == 422
    stranger = tenant_b.users[Role.ANALYST]
    assert (
        _generate(
            admin, entity, rpv, include_einvoicing=False, owner_id=str(stranger.id)
        ).status_code
        == 422
    )
    ok = _generate(admin, entity, rpv, include_einvoicing=False)
    assert ok.status_code == 200
    task_id = ok.json()["obligations"][0]["task"]["id"]
    # An analyst who does not own the task cannot change it; a viewer cannot at all.
    assert analyst.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"}).status_code == 403
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"}).status_code == 403
    assert viewer.get("/api/tasks").status_code == 200
    manual = analyst.post(
        "/api/tasks", json={"title": "Synthetic manual task", "due_date": "2026-05-01"}
    )
    assert manual.status_code == 201 and manual.json()["source_kind"] == "manual"

    other = login(tenant_b.users[Role.ORG_ADMIN])
    other_rpv = synthetic_pack(other, with_bundle=False)
    assert _generate(other, entity, other_rpv).status_code == 404
    other_entity = make_entity(db, tenant_b)
    assert _generate(other, other_entity, rpv).status_code == 404
    assert (
        other.patch(f"/api/tasks/{task_id}", json={"status": "done", "note": "x"}).status_code
        == 404
    )
    assert other.patch(f"/api/tasks/{uuid.uuid4()}", json={"status": "done"}).status_code == 404
    assert other.get("/api/tasks").json() == []
    assert other.get("/api/tax-obligations").json() == []
    assert (
        other.post("/api/tasks", json={"title": "x", "entity_id": str(entity.id)}).status_code
        == 404
    )
