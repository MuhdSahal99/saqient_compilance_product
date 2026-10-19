"""Synthetic Phase E demo: a month-end close checklist, a small risk-control matrix with
one planned test, and a draft management certification for the synthetic entity.

Every value is invented. Nothing here is guidance on how a real close or control
framework should look.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo_finance import ENTITY_NAME
from app.models import (
    Assertion,
    ControlAutomation,
    ControlFrequency,
    ControlNature,
    ControlTestKind,
    LegalEntity,
    Organization,
    RiskLevel,
    User,
)
from app.schemas import (
    CertificationIn,
    CloseItemIn,
    ClosePeriodIn,
    ControlIn,
    ControlRiskIn,
    ControlTestIn,
    ProcessIn,
)
from app.services import close, controls

CLOSE_ITEMS = [
    ("Post accruals (synthetic)", -1),
    ("Reconcile bank accounts (synthetic)", 2),
    ("Review intercompany balances (synthetic)", 3),
    ("Explain flux above threshold (synthetic)", 5),
]


def seed_assurance(
    db: Session, org: Organization, admin: User, reviewer: User, analyst: User
) -> None:
    entity = db.scalars(
        select(LegalEntity).where(LegalEntity.org_id == org.id, LegalEntity.name == ENTITY_NAME)
    ).one()
    period = close.create(
        db,
        entity,
        ClosePeriodIn(
            entity_id=entity.id,
            name="January 2026 close (synthetic demo)",
            period_end=date(2026, 1, 31),
            items=[CloseItemIn(title=t, day_offset=d, owner_id=analyst.id) for t, d in CLOSE_ITEMS],
        ),
        admin,
    )
    period.is_demo = True

    process = controls.create_process(
        db,
        entity,
        ProcessIn(
            entity_id=entity.id,
            name="Procure to pay (synthetic demo)",
            description="Synthetic demonstration content — not legal guidance.",
            owner_id=reviewer.id,
        ),
        admin,
    )
    process.is_demo = True
    risk = controls.save_risk(
        db,
        process,
        ControlRiskIn(
            ref="P2P-R1",
            description="Payments to vendors that were not approved (synthetic).",
            assertions=[Assertion.OCCURRENCE],
            rating=RiskLevel.HIGH,
        ),
        analyst,
    )
    controls.save_risk(
        db,
        process,
        ControlRiskIn(
            ref="P2P-R2",
            description="Vendor bank details changed without review (synthetic).",
            assertions=[Assertion.EXISTENCE],
            rating=RiskLevel.MEDIUM,
        ),
        analyst,
    )
    control = controls.save_control(
        db,
        process,
        ControlIn(
            ref="P2P-C1",
            title="Payment run approval (synthetic)",
            description="A second person approves each payment run before release.",
            key=True,
            nature=ControlNature.PREVENTIVE,
            automation=ControlAutomation.MANUAL,
            frequency=ControlFrequency.WEEKLY,
            owner_id=reviewer.id,
            risk_ids=[risk.id],
        ),
        analyst,
    )
    controls.add_test(
        db,
        control,
        ControlTestIn(
            kind=ControlTestKind.OPERATING,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 3, 31),
            procedure="Inspect approval evidence for a sample of payment runs (synthetic).",
            sample_size=5,
        ),
        analyst,
    )
    cert = controls.create_cert(
        db,
        entity,
        CertificationIn(
            entity_id=entity.id, period_start=date(2026, 1, 1), period_end=date(2026, 3, 31)
        ),
        admin,
    )
    cert.is_demo = True
    db.commit()
