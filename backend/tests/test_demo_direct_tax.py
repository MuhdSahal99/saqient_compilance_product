"""The synthetic Phase C demo seed builds with the golden values."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo_direct_tax import seed_direct_tax
from app.models import (
    LegalEntity,
    LossEntryKind,
    RelatedPartyTransaction,
    Role,
    TaxGroupMembership,
    TaxLossEntry,
    WorkpaperStatus,
)
from tests.conftest import Tenant


def test_direct_tax_seed(tenant_a: Tenant, db: Session) -> None:
    u = tenant_a.users
    ct, sbr, p2, zakat = seed_direct_tax(
        db, tenant_a.org, u[Role.ORG_ADMIN], u[Role.REVIEWER], u[Role.ANALYST]
    )
    assert all(w.is_demo for w in (ct, sbr, p2, zakat))
    assert ct.status is WorkpaperStatus.SIGNED_OFF and ct.warnings

    def amount(wp, key):  # type: ignore[no-untyped-def]
        return next(ln for ln in wp.lines if ln.line_key == f"calc:{key}")

    assert amount(ct, "tax").amount == Decimal(39000)  # golden ct_bridge case 1
    assert amount(sbr, "conditions").value == "met"
    assert amount(p2, "AE:top_up").amount == Decimal(435000)
    assert amount(zakat, "zakat").amount == Decimal(150000)
    kinds = sorted(
        e.kind
        for e in db.scalars(select(TaxLossEntry).where(TaxLossEntry.entity_id == ct.entity_id))
    )
    assert kinds == sorted([LossEntryKind.INCURRED, LossEntryKind.USED])
    assert len(db.scalars(select(TaxGroupMembership)).all()) == 2
    assert len(db.scalars(select(RelatedPartyTransaction)).all()) == 2
    ksa = db.get(LegalEntity, zakat.entity_id)
    assert ksa is not None and ksa.functional_currency == "SAR"
