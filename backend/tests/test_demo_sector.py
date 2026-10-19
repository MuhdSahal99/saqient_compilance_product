"""The synthetic Phase F demo seed installs a draft pack and drafts the FS."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.demo_audit import seed_audit
from app.demo_direct_tax import seed_direct_tax
from app.demo_finance import seed_finance
from app.demo_sector import DEMO_PACK, seed_sector
from app.models import ContentPackInstall, Role, WorkpaperKind
from tests.conftest import Tenant


def test_sector_seed(tenant_a: Tenant, db: Session) -> None:
    u = tenant_a.users
    admin, reviewer, analyst = u[Role.ORG_ADMIN], u[Role.REVIEWER], u[Role.ANALYST]
    seed_finance(db, get_sessionmaker(), tenant_a.org, admin, reviewer, analyst)
    seed_direct_tax(db, tenant_a.org, admin, reviewer, analyst)
    db.commit()
    e = seed_audit(db, tenant_a.org, admin, reviewer, analyst, u[Role.CLIENT])
    wp = seed_sector(db, tenant_a.org, admin, analyst, e)
    inst = db.scalars(
        select(ContentPackInstall).where(ContentPackInstall.org_id == tenant_a.org.id)
    ).one()
    assert inst.pack_id == DEMO_PACK and inst.checklist_version_ids
    assert wp.kind is WorkpaperKind.FS_DRAFT and wp.engagement_id == e.id
    keys = {ln.line_key for ln in wp.lines}
    assert any(k.startswith("fs_") for k in keys)
    assert any(k.startswith("calc:balance_check_") for k in keys)
