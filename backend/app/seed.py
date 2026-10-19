"""Seed synthetic demo data. Refuses to run unless DEMO_MODE=true outside production.

Usage: uv run python -m app.seed [--reset]
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import demo_content as dc
from app.config import get_settings
from app.db import get_sessionmaker
from app.demo_assurance import seed_assurance
from app.demo_audit import seed_audit
from app.demo_direct_tax import seed_direct_tax
from app.demo_finance import seed_finance
from app.demo_sector import seed_sector
from app.demo_vat import seed_vat
from app.models import (
    Base,
    Checklist,
    ChecklistKind,
    ChecklistState,
    ChecklistVersion,
    Document,
    Finding,
    FindingStatus,
    Membership,
    Organization,
    Requirement,
    Role,
    Severity,
    Source,
    SourceVerification,
    User,
)
from app.security import hash_password
from app.services import reviews
from app.services.documents import create_version
from app.services.jobs import execute_job

DEMO_PASSWORD = "Demo-Password-2026!"

ORGS = [
    (
        "Alpha Synthetic Audit Team",
        "alpha-synthetic",
        [
            ("admin@alpha.example", "Demo Admin (Alpha)", Role.ORG_ADMIN),
            ("reviewer@alpha.example", "Demo Reviewer (Alpha)", Role.REVIEWER),
            ("analyst@alpha.example", "Demo Analyst (Alpha)", Role.ANALYST),
            ("viewer@alpha.example", "Demo Viewer (Alpha)", Role.VIEWER),
            ("client@alpha.example", "Demo Client (Alpha)", Role.CLIENT),
        ],
    ),
    (
        "Beta Synthetic Compliance Unit",
        "beta-synthetic",
        [
            ("admin@beta.example", "Demo Admin (Beta)", Role.ORG_ADMIN),
            ("reviewer@beta.example", "Demo Reviewer (Beta)", Role.REVIEWER),
        ],
    ),
]


def _guard() -> None:
    s = get_settings()
    if s.is_production or not s.demo_mode:
        sys.exit("Refusing to seed: requires DEMO_MODE=true and APP_ENV other than production.")


def reset(db: Session) -> None:
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    db.execute(text(f"TRUNCATE {tables} CASCADE"))  # noqa: S608 - table names from metadata
    db.commit()


def seed_checklist(db: Session, org: Organization, publisher: User) -> ChecklistVersion:
    source = Source(
        org_id=org.id,
        verification_status=SourceVerification.SYNTHETIC,
        last_reviewed_at=date(2026, 10, 1),
        **dc.DEMO_SOURCE,
    )
    db.add(source)
    checklist = Checklist(
        org_id=org.id,
        name=dc.CHECKLIST_NAME,
        description=dc.CHECKLIST_DESCRIPTION,
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
    for i, raw in enumerate(dc.DEMO_REQUIREMENTS):
        req = dict(raw)
        db.add(
            Requirement(
                org_id=org.id,
                checklist_version_id=version.id,
                ordinal=i,
                code=str(req["code"]),
                title=str(req["title"]),
                description=str(req["description"]),
                category=str(req["category"]),
                severity=Severity(str(req["severity"])),
                human_instructions=str(req["human_instructions"]),
                check_config=req["check_config"],
                source_id=source.id,
                source_reference=f"Synthetic demo source, item {req['code']}",
                jurisdiction=None,
                document_type="policy",
                owner="Demo checklist owner",
            )
        )
    db.commit()
    return version


def seed() -> None:
    _guard()
    factory = get_sessionmaker()
    with factory() as db:
        if db.scalar(select(Organization).where(Organization.slug == "alpha-synthetic")):
            print("Demo data already present. Use --reset to recreate it.")
            return
        pw = hash_password(DEMO_PASSWORD)
        created: dict[str, tuple[Organization, dict[Role, User]]] = {}
        for name, slug, users in ORGS:
            org = Organization(name=name, slug=slug, is_demo=True)
            db.add(org)
            db.flush()
            by_role: dict[Role, User] = {}
            for email, full_name, role in users:
                u = User(email=email, full_name=full_name, password_hash=pw, is_demo=True)
                db.add(u)
                db.flush()
                db.add(Membership(org_id=org.id, user_id=u.id, role=role))
                by_role[role] = u
            created[slug] = (org, by_role)
        db.commit()

        for slug, (org, role_users) in created.items():
            admin = role_users[Role.ORG_ADMIN]
            reviewer = role_users.get(Role.REVIEWER, admin)
            cv = seed_checklist(db, org, admin)
            doc = Document(
                org_id=org.id,
                title=dc.POLICY_TITLE,
                document_type="policy",
                description="Synthetic sample document for the demo.",
                tags=["synthetic", "vendor"],
                is_demo=True,
                created_by_id=admin.id,
            )
            db.add(doc)
            db.flush()
            version, job = create_version(
                db,
                org_id=org.id,
                user_id=admin.id,
                document=doc,
                filename="synthetic-vendor-policy.pdf",
                declared_mime="application/pdf",
                data=dc.policy_pdf_bytes(),
                allow_duplicate=True,
            )
            db.commit()
            execute_job(factory, job.id, org.id)
            db.refresh(version)

            if slug != "alpha-synthetic":
                continue
            review, run_job = reviews.create_review(
                db,
                org_id=org.id,
                user_id=reviewer.id,
                title="Q4 vendor policy review (synthetic demo)",
                document_version=version,
                checklist_version=cv,
            )
            db.commit()
            execute_job(factory, run_job.id, org.id)
            db.refresh(review)
            # Decide one finding and assign it, leaving the rest for the demo walkthrough.
            finding = db.scalar(
                select(Finding)
                .where(Finding.review_id == review.id, Finding.severity == Severity.HIGH)
                .order_by(Finding.created_at)
                .limit(1)
            )
            if finding is not None:
                reviews.decide(
                    db,
                    finding,
                    FindingStatus.CONFIRMED.value,
                    "Confirmed during synthetic demo setup.",
                    reviewer,
                )
                due = date.today() + timedelta(days=14)
                reviews.assign(db, finding, role_users[Role.ANALYST], due, reviewer)
                db.commit()
            seed_finance(db, factory, org, admin, reviewer, role_users[Role.ANALYST])
            seed_vat(db, factory, org, admin, reviewer, role_users[Role.ANALYST])
            seed_direct_tax(db, org, admin, reviewer, role_users[Role.ANALYST])
            db.commit()
            engagement = seed_audit(
                db, org, admin, reviewer, role_users[Role.ANALYST], role_users.get(Role.CLIENT)
            )
            seed_assurance(db, org, admin, reviewer, role_users[Role.ANALYST])
            seed_sector(db, org, admin, role_users[Role.ANALYST], engagement)
        print("Seeded synthetic demo data. Demo password:", DEMO_PASSWORD)  # demo-only value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="truncate all tables first")
    args = parser.parse_args()
    _guard()
    if args.reset:
        with get_sessionmaker()() as db:
            reset(db)
    seed()


if __name__ == "__main__":
    main()
