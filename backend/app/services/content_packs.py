"""Installing content packs into an organisation (Phase F1).

Everything a pack installs is a draft: checklist versions in ``draft`` state with the
pack's disclaimer, and a draft rule pack version whose rules keep their open
questions, so nothing becomes usable or verified without a person publishing and
verifying it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Checklist,
    ChecklistKind,
    ChecklistVersion,
    ContentPackInstall,
    Requirement,
    RulePack,
    User,
)
from app.packs import Pack
from app.services import audit, rule_packs


class PackInstallConflict(ValueError):
    pass


def installs(db: Session, org_id: uuid.UUID) -> list[ContentPackInstall]:
    return list(
        db.scalars(
            select(ContentPackInstall)
            .where(ContentPackInstall.org_id == org_id)
            .order_by(ContentPackInstall.created_at)
        )
    )


def install(db: Session, org_id: uuid.UUID, pack: Pack, actor: User) -> ContentPackInstall:
    m = pack.manifest
    exists = db.scalar(
        select(ContentPackInstall.id).where(
            ContentPackInstall.org_id == org_id,
            ContentPackInstall.pack_id == m.id,
            ContentPackInstall.pack_version == m.version,
        )
    )
    if exists is not None:
        raise PackInstallConflict("This pack version is already installed.")
    version_ids: list[str] = []
    for cl in m.checklists:
        c = Checklist(
            org_id=org_id,
            name=f"{cl.name} · {m.id} v{m.version}"[:200],
            description=cl.description,
            kind=ChecklistKind.SYNTHETIC_DEMO,
        )
        db.add(c)
        db.flush()
        v = ChecklistVersion(
            org_id=org_id, checklist_id=c.id, version_number=1, disclaimer=m.disclaimer
        )
        db.add(v)
        db.flush()
        for i, r in enumerate(cl.requirements):
            db.add(
                Requirement(org_id=org_id, checklist_version_id=v.id, ordinal=i, **r.model_dump())
            )
        version_ids.append(str(v.id))
    rpv_id = None
    if m.rules is not None:
        name = f"{m.title} rules v{m.version}"[:200]
        if db.scalar(select(RulePack.id).where(RulePack.org_id == org_id, RulePack.name == name)):
            raise PackInstallConflict("A rule pack with this pack's name already exists.")
        rp = rule_packs.create_pack(db, org_id, name, "SYNTHETIC", m.description[:2000], actor)
        db.flush()
        db.refresh(rp)
        draft = rp.versions[0]
        rule_packs.replace_rules(db, draft, m.rules.rules, actor)
        rpv_id = draft.id
    inst = ContentPackInstall(
        org_id=org_id,
        pack_id=m.id,
        pack_version=m.version,
        manifest_sha256=pack.sha256,
        checklist_version_ids=version_ids,
        rule_pack_version_id=rpv_id,
        installed_by_id=actor.id,
    )
    db.add(inst)
    db.flush()
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor.id,
        action="content_pack.installed",
        object_type="content_pack_install",
        object_id=inst.id,
        meta={"pack": m.id, "version": m.version, "sha256": pack.sha256},
    )
    return inst
