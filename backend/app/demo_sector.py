"""Synthetic Phase F demo: one draft content pack installed and an FS draft workpaper on
the demo engagement.

The pack is a synthetic draft whose rules keep their open questions; the FS draft is
built from the synthetic trial balance. Nothing here is guidance.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditEngagement, Organization, TaxWorkpaper, User
from app.packs import catalog
from app.schemas import AuditWorkpaperIn
from app.services import content_packs, lead_schedules

DEMO_PACK = "aml-cft"


def seed_sector(
    db: Session, org: Organization, admin: User, analyst: User, engagement: AuditEngagement
) -> TaxWorkpaper:
    content_packs.install(db, org.id, catalog()[DEMO_PACK], admin)
    wp = lead_schedules.create_workpaper(
        db,
        engagement,
        AuditWorkpaperIn(kind="fs_draft", title="FY2025 financial statements draft (synthetic)"),
        analyst,
    )
    db.commit()
    return wp
