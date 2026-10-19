"""Synthetic Phase D demo: an external audit engagement over the synthetic trading
entity, with lead schedules, a risk register, a confirmation, a proposed adjustment
and a PBC request assigned to the demo client user.

Every value is invented; the audit guidance rules stay unverified (draft pack).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo_direct_tax import PACK_NAME
from app.demo_finance import ENTITY_NAME
from app.models import (
    Assertion,
    AuditEngagement,
    ConfirmationType,
    DatasetKind,
    DatasetStatus,
    DatasetVersion,
    EngagementKind,
    EngagementRole,
    FsSection,
    LegalEntity,
    Organization,
    RiskLevel,
    RulePack,
    RulePackVersion,
    User,
)
from app.models import Dataset as DatasetModel
from app.schemas import (
    AccountMappingIn,
    AccountMappingsIn,
    AdjustmentIn,
    AdjustmentLineIn,
    ConfirmationIn,
    EngagementIn,
    EngagementSetupIn,
    LeadScheduleIn,
    LeadSchedulesIn,
    PbcRequestIn,
    ProcedureIn,
    RiskIn,
)
from app.services import audit_completion, audit_risks, engagements, lead_schedules, pbc

SCHEDULES = [
    ("A", "Cash and bank", FsSection.ASSET),
    ("B", "Receivables", FsSection.ASSET),
    ("C", "Property and equipment", FsSection.ASSET),
    ("L", "Payables", FsSection.LIABILITY),
    ("R", "Revenue", FsSection.INCOME),
    ("X", "Operating expenses", FsSection.EXPENSE),
]
MAPPINGS = {
    "1000": "A",
    "1100": "B",
    "1500": "C",
    "2000": "L",
    "4000": "R",
    "5100": "X",
    "5200": "X",
    "5300": "X",
}


def seed_audit(
    db: Session,
    org: Organization,
    admin: User,
    reviewer: User,
    analyst: User,
    client: User | None,
) -> AuditEngagement:
    entity = db.scalars(
        select(LegalEntity).where(LegalEntity.org_id == org.id, LegalEntity.name == ENTITY_NAME)
    ).one()
    tb = db.scalars(
        select(DatasetVersion)
        .join(DatasetModel, DatasetModel.id == DatasetVersion.dataset_id)
        .where(
            DatasetModel.org_id == org.id,
            DatasetModel.entity_id == entity.id,
            DatasetModel.kind == DatasetKind.TRIAL_BALANCE,
            DatasetVersion.status == DatasetStatus.READY,
        )
        .order_by(DatasetVersion.created_at.desc())
        .limit(1)
    ).one()
    rpv = db.scalars(
        select(RulePackVersion)
        .join(RulePack, RulePack.id == RulePackVersion.rule_pack_id)
        .where(RulePack.org_id == org.id, RulePack.name == PACK_NAME)
        .order_by(RulePackVersion.version_number.desc())
        .limit(1)
    ).one()

    e = engagements.create(
        db,
        entity,
        EngagementIn(
            entity_id=entity.id,
            kind=EngagementKind.EXTERNAL_AUDIT,
            name="FY2025 external audit (synthetic demo)",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
        ),
        admin,
    )
    e.is_demo = True
    engagements.put_member(db, e, reviewer.id, EngagementRole.MANAGER, admin)
    engagements.put_member(db, e, analyst.id, EngagementRole.SENIOR, admin)
    lead_schedules.set_up(
        db,
        e,
        EngagementSetupIn(
            cy_tb_version_id=tb.id, rule_pack_version_id=rpv.id, rules_prefix="syn.audit"
        ),
        admin,
    )
    lead_schedules.replace_schedules(
        db,
        e,
        LeadSchedulesIn(
            schedules=[LeadScheduleIn(code=c, name=n, section=s) for c, n, s in SCHEDULES]
        ),
        admin,
    )
    lead_schedules.replace_mappings(
        db,
        e,
        AccountMappingsIn(
            mappings=[AccountMappingIn(account_code=a, lead_code=c) for a, c in MAPPINGS.items()]
        ),
        admin,
    )
    risk = audit_risks.save_risk(
        db,
        e,
        RiskIn(
            ref="R1",
            title="Revenue recorded in the wrong period (synthetic)",
            lead_code="R",
            assertions=[Assertion.OCCURRENCE, Assertion.CUT_OFF],
            inherent_risk=RiskLevel.HIGH,
            significant=True,
            response="Cut-off testing of invoices either side of the year end.",
        ),
        analyst,
    )
    audit_risks.save_procedure(
        db,
        e,
        ProcedureIn(
            title="Test revenue cut-off (synthetic)",
            description="Trace invoices dated near the year end to delivery evidence.",
            assignee_id=analyst.id,
            risk_ids=[risk.id],
        ),
        analyst,
    )
    audit_completion.add_confirmation(
        db,
        e,
        ConfirmationIn(
            type=ConfirmationType.BANK,
            counterparty="Synthetic Bank (demo)",
            reference="CONF-A1",
            book_amount=Decimal("2850.00"),
        ),
        analyst,
    )
    audit_completion.save_adjustment(
        db,
        e,
        AdjustmentIn(
            ref="AJE-1",
            description="Synthetic accrual for unbilled utilities.",
            lines=[
                AdjustmentLineIn(account_code="5300", debit=Decimal("300.00")),
                AdjustmentLineIn(account_code="2000", credit=Decimal("300.00")),
            ],
        ),
        analyst,
    )
    pbc.create(
        db,
        e,
        PbcRequestIn(
            ref="PBC-1",
            title="Year-end bank statement (synthetic)",
            description="Upload the December 2025 statement for the synthetic bank account.",
            due_date=date(2026, 2, 15),
            assignee_id=client.id if client else None,
        ),
        analyst,
    )
    db.commit()
    return e
