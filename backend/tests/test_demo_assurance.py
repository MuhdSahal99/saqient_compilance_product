"""The synthetic Phase E demo seed builds a close checklist, a control matrix and a
draft certification on the demo entity."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.demo_assurance import seed_assurance
from app.demo_finance import seed_finance
from app.models import ClosePeriod, ControlCertification, ControlProcess, Role
from app.services import controls
from tests.conftest import Tenant


def test_assurance_seed(tenant_a: Tenant, db: Session) -> None:
    u = tenant_a.users
    admin, reviewer, analyst = u[Role.ORG_ADMIN], u[Role.REVIEWER], u[Role.ANALYST]
    seed_finance(db, get_sessionmaker(), tenant_a.org, admin, reviewer, analyst)
    db.commit()
    seed_assurance(db, tenant_a.org, admin, reviewer, analyst)
    period = db.scalars(select(ClosePeriod).where(ClosePeriod.org_id == tenant_a.org.id)).one()
    assert period.is_demo and len(period.items) == 4
    process = db.scalars(
        select(ControlProcess).where(ControlProcess.org_id == tenant_a.org.id)
    ).one()
    assert process.is_demo and len(process.risks) == 2 and len(process.controls) == 1
    # One risk is deliberately left without a control so the matrix shows the gap.
    assert len(controls.unmitigated(process)) == 1
    cert = db.scalars(
        select(ControlCertification).where(ControlCertification.org_id == tenant_a.org.id)
    ).one()
    assert cert.is_demo and cert.statement == ""
