"""Synthetic finance demo data: one entity, a ledger, a trial balance, a rule pack and a review.

Every value here is invented for the demo. The rule pack uses the SYNTHETIC
jurisdiction, so its rules stay unverified and cannot be verified; reports flag
them as such. Nothing here is a real rate, threshold or regulation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app import demo_content as dc
from app.engine.versions import ENGINE_VERSION, parse_check
from app.models import (
    Checklist,
    ChecklistKind,
    ChecklistState,
    ChecklistVersion,
    DatasetKind,
    DatasetStatus,
    DatasetVersion,
    Organization,
    Requirement,
    Review,
    RulePackVersion,
    Severity,
    User,
)
from app.schemas import LegalEntityIn, RuleIn
from app.services import datasets, entities, reviews, rule_packs
from app.services.jobs import execute_job

ENTITY_NAME = "Synthetic Trading LLC (demo)"
RULE_PACK_NAME = "Synthetic finance thresholds (demo)"
CHECKLIST_NAME = "Synthetic ledger checks (demo)"
REVIEW_TITLE = "December ledger checks (synthetic demo)"
AS_OF = date(2025, 12, 31)

# December 2025. JE-1003 is large, JE-1004 is posted on a Saturday, and one
# JE-1005 line is entered twice, so the ledger no longer agrees with the trial
# balance on account 5300.
GL_CSV = (
    b"Journal,Date,Account,Narration,Debit,Credit\n"
    b"JE-1001,2025-12-01,1100,Synthetic customer invoice,12500.00,\n"
    b"JE-1001,2025-12-01,4000,Synthetic customer invoice,,12500.00\n"
    b"JE-1002,2025-12-02,5100,Synthetic office rent,8000.00,\n"
    b"JE-1002,2025-12-02,1000,Synthetic office rent,,8000.00\n"
    b"JE-1003,2025-12-03,1500,Synthetic equipment purchase,62000.00,\n"
    b"JE-1003,2025-12-03,2000,Synthetic equipment purchase,,62000.00\n"
    b"JE-1004,2025-12-06,5200,Synthetic travel expense,450.00,\n"
    b"JE-1004,2025-12-06,1000,Synthetic travel expense,,450.00\n"
    b"JE-1005,2025-12-08,5300,Synthetic utilities,1200.00,\n"
    b"JE-1005,2025-12-08,1000,Synthetic utilities,,1200.00\n"
    b"JE-1005,2025-12-08,5300,Synthetic utilities,1200.00,\n"
    b"JE-1006,2025-12-10,1000,Synthetic customer receipt,12500.00,\n"
    b"JE-1006,2025-12-10,1100,Synthetic customer receipt,,12500.00\n"
)
GL_MAPPING = {
    "entry_id": "Journal",
    "posting_date": "Date",
    "account_code": "Account",
    "description": "Narration",
    "debit": "Debit",
    "credit": "Credit",
}

TB_CSV = (
    b"Account,Account name,Debit,Credit\n"
    b"1000,Synthetic bank,2850.00,\n"
    b"1100,Synthetic receivables,0.00,\n"
    b"1500,Synthetic equipment,62000.00,\n"
    b"2000,Synthetic payables,,62000.00\n"
    b"4000,Synthetic revenue,,12500.00\n"
    b"5100,Synthetic rent,8000.00,\n"
    b"5200,Synthetic travel,450.00,\n"
    b"5300,Synthetic utilities,1200.00,\n"
)
TB_MAPPING = {
    "account_code": "Account",
    "account_name": "Account name",
    "debit": "Debit",
    "credit": "Credit",
}

RULES = [
    RuleIn(
        rule_key="demo.large_entry",
        title="Large journal line threshold (synthetic)",
        value_type="decimal",
        value="50000.00",
        unit="AED",
        effective_from=date(2020, 1, 1),
        source_note="Synthetic demonstration value; not taken from any regulation or policy.",
        todo="Replace with your organisation's own threshold and its source before real use.",
    )
]

REQUIREMENTS: list[dict[str, Any]] = [
    {
        "code": "GL-01",
        "title": "Large journal lines are reviewed",
        "severity": "medium",
        "instructions": "Check each flagged line has an approved supporting document.",
        "config": {
            "type": "threshold",
            "dataset": "general_ledger",
            "field": "amount",
            "use_absolute": True,
            "flag_if": "gte",
            "value": {"rule": "demo.large_entry"},
        },
    },
    {
        "code": "GL-02",
        "title": "Weekend postings are explained",
        "severity": "low",
        "instructions": "Confirm each weekend posting has a business reason.",
        "config": {
            "type": "date_rule",
            "dataset": "general_ledger",
            "field": "posting_date",
            "rule": "not_weekend",
            "weekend_days": ["sat", "sun"],
        },
    },
    {
        "code": "GL-03",
        "title": "No duplicate journal lines",
        "severity": "medium",
        "instructions": "Decide whether repeated lines are genuine or entered twice.",
        "config": {
            "type": "duplicate",
            "dataset": "general_ledger",
            "keys": ["entry_id", "account_code", "amount"],
        },
    },
    {
        "code": "GL-04",
        "title": "Ledger agrees to the trial balance",
        "severity": "high",
        "instructions": "Explain or correct every account where the totals differ.",
        "config": {
            "type": "reconcile",
            "left": {"dataset": "general_ledger", "group_by": ["account_code"], "sum": "amount"},
            "right": {"dataset": "trial_balance", "group_by": ["account_code"], "sum": "balance"},
        },
    },
]


def _import(
    db: Session,
    factory: sessionmaker[Session],
    org: Organization,
    entity: Any,
    analyst: User,
    kind: DatasetKind,
    name: str,
    data: bytes,
    mapping: dict[str, str],
) -> DatasetVersion:
    ds = datasets.create_dataset(
        db,
        org_id=org.id,
        entity=entity,
        kind=kind,
        name=name,
        period_start=date(2025, 12, 1),
        period_end=AS_OF,
        actor=analyst,
    )
    ds.is_demo = True
    v, job = datasets.create_version(
        db,
        dataset=ds,
        filename=f"{kind.value}-synthetic.csv",
        declared_mime="text/csv",
        data=data,
        actor=analyst,
        allow_duplicate=True,
    )
    db.commit()
    execute_job(factory, job.id, org.id)
    db.refresh(v)
    build = datasets.confirm_mapping(
        db, v, mapping, date_format="%Y-%m-%d", decimal_separator=".", actor=analyst
    )
    db.commit()
    execute_job(factory, build.id, org.id)
    db.refresh(v)
    if v.status != DatasetStatus.READY:
        raise RuntimeError(f"Synthetic {kind.value} did not build: {v.failure_message}")
    return v


def _checklist(db: Session, org: Organization, publisher: User) -> ChecklistVersion:
    checklist = Checklist(
        org_id=org.id,
        name=CHECKLIST_NAME,
        description="Deterministic checks over a synthetic general ledger and trial balance.",
        kind=ChecklistKind.SYNTHETIC_DEMO,
    )
    db.add(checklist)
    db.flush()
    version = ChecklistVersion(
        org_id=org.id,
        checklist_id=checklist.id,
        version_number=1,
        state=ChecklistState.PUBLISHED,
        disclaimer=dc.SYNTHETIC_NOTICE,
        published_at=datetime.now(UTC),
        published_by_id=publisher.id,
    )
    db.add(version)
    db.flush()
    for i, req in enumerate(REQUIREMENTS):
        parse_check(req["config"], ENGINE_VERSION)  # fail loudly if a config drifts
        db.add(
            Requirement(
                org_id=org.id,
                checklist_version_id=version.id,
                ordinal=i,
                code=req["code"],
                title=req["title"],
                description=req["title"],
                category="General ledger",
                severity=Severity(req["severity"]),
                human_instructions=req["instructions"],
                check_config=req["config"],
                source_reference=f"Synthetic demo checklist, item {req['code']}",
                owner="Demo checklist owner",
            )
        )
    return version


def seed_finance(
    db: Session,
    factory: sessionmaker[Session],
    org: Organization,
    admin: User,
    reviewer: User,
    analyst: User,
) -> Review:
    entity = entities.create_entity(
        db,
        org.id,
        LegalEntityIn(
            name=ENTITY_NAME,
            country="AE",
            fiscal_year_end_month=12,
            fiscal_year_end_day=31,
            functional_currency="AED",
            timezone="Asia/Dubai",
        ),
        admin,
    )
    pack = rule_packs.create_pack(
        db,
        org.id,
        RULE_PACK_NAME,
        "SYNTHETIC",
        "Invented values for the demo. Not legal or tax guidance.",
        reviewer,
    )
    db.flush()
    rp_version: RulePackVersion = pack.versions[0]
    rule_packs.replace_rules(db, rp_version, RULES, reviewer)
    db.flush()
    db.refresh(rp_version)
    rule_packs.publish(db, rp_version, reviewer)
    cv = _checklist(db, org, reviewer)
    db.commit()

    gl = _import(
        db,
        factory,
        org,
        entity,
        analyst,
        DatasetKind.GENERAL_LEDGER,
        "December 2025 ledger (synthetic)",
        GL_CSV,
        GL_MAPPING,
    )
    tb = _import(
        db,
        factory,
        org,
        entity,
        analyst,
        DatasetKind.TRIAL_BALANCE,
        "December 2025 trial balance (synthetic)",
        TB_CSV,
        TB_MAPPING,
    )

    review, job = reviews.create_review(
        db,
        org_id=org.id,
        user_id=reviewer.id,
        title=REVIEW_TITLE,
        document_version=None,
        checklist_version=cv,
        dataset_versions=[gl, tb],
        rule_pack_version=rp_version,
        as_of_date=AS_OF,
    )
    db.commit()
    execute_job(factory, job.id, org.id)
    db.refresh(review)
    return review
