"""The synthetic Phase D demo seed builds an engagement on the demo trial balance."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.demo_audit import seed_audit
from app.demo_direct_tax import seed_direct_tax
from app.demo_finance import seed_finance
from app.models import AuditRisk, LeadSchedule, PbcRequest, Role
from tests.conftest import Tenant


def test_audit_seed(tenant_a: Tenant, db: Session) -> None:
    u = tenant_a.users
    admin, reviewer, analyst = u[Role.ORG_ADMIN], u[Role.REVIEWER], u[Role.ANALYST]
    seed_finance(db, get_sessionmaker(), tenant_a.org, admin, reviewer, analyst)
    seed_direct_tax(db, tenant_a.org, admin, reviewer, analyst)
    db.commit()
    e = seed_audit(db, tenant_a.org, admin, reviewer, analyst, u[Role.CLIENT])
    assert e.is_demo and e.cy_tb_version_id is not None and e.rules_prefix == "syn.audit"
    assert (
        len(db.scalars(select(LeadSchedule).where(LeadSchedule.engagement_id == e.id)).all()) == 6
    )
    assert db.scalars(select(AuditRisk).where(AuditRisk.engagement_id == e.id)).one().significant
    pbc = db.scalars(select(PbcRequest).where(PbcRequest.engagement_id == e.id)).one()
    assert pbc.assignee_id == u[Role.CLIENT].id
