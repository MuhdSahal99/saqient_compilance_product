"""Content packs (Phase F1): browse the shipped synthetic draft packs and install them."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.assurance_common import name_of
from app.deps import DB, Admin, Ctx
from app.models import ContentPackInstall
from app.packs import Pack, catalog
from app.schemas import ContentPackOut, PackChecklistOut, PackInstallOut, PackRequirementOut
from app.services import content_packs as svc

router = APIRouter(tags=["content packs"])


def install_out(db: DB, i: ContentPackInstall) -> PackInstallOut:
    return PackInstallOut(
        id=i.id,
        pack_version=i.pack_version,
        manifest_sha256=i.manifest_sha256,
        checklist_version_ids=[uuid.UUID(x) for x in i.checklist_version_ids],
        rule_pack_version_id=i.rule_pack_version_id,
        installed_by_name=name_of(db, i.installed_by_id),
        created_at=i.created_at,
    )


def pack_out(db: DB, p: Pack, done: list[ContentPackInstall]) -> ContentPackOut:
    m = p.manifest
    return ContentPackOut(
        id=m.id,
        version=m.version,
        title=m.title,
        sector=m.sector,
        jurisdiction=m.jurisdiction,
        status=m.status,
        synthetic=m.synthetic,
        disclaimer=m.disclaimer,
        description=m.description,
        dataset_kinds=m.dataset_kinds,
        open_questions=m.open_questions,
        manifest_sha256=p.sha256,
        checklists=[
            PackChecklistOut(
                name=c.name,
                requirements=[
                    PackRequirementOut(
                        code=r.code,
                        title=r.title,
                        category=r.category,
                        severity=r.severity,
                        check_type=str(r.check_config.get("type", "manual")),
                    )
                    for r in c.requirements
                ],
            )
            for c in m.checklists
        ],
        rule_count=len(m.rules.rules) if m.rules else 0,
        installs=[install_out(db, i) for i in done if i.pack_id == m.id],
    )


def _pack(pack_id: str) -> Pack:
    p = catalog().get(pack_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return p


@router.get(
    "/content-packs",
    response_model=list[ContentPackOut],
    summary="List content packs",
    description="Shipped packs are synthetic drafts, not legal guidance.",
)
def list_packs(db: DB, ctx: Ctx) -> list[ContentPackOut]:
    done = svc.installs(db, ctx.org.id)
    return [pack_out(db, p, done) for p in catalog().values()]


@router.get("/content-packs/{pack_id}", response_model=ContentPackOut, summary="Get a pack")
def get_pack(pack_id: str, db: DB, ctx: Ctx) -> ContentPackOut:
    return pack_out(db, _pack(pack_id), svc.installs(db, ctx.org.id))


@router.post(
    "/content-packs/{pack_id}/install",
    response_model=ContentPackOut,
    status_code=status.HTTP_201_CREATED,
    summary="Install a pack as draft checklists and rules",
    description="Org admins only. Installed content stays draft until people publish and "
    "verify it.",
)
def install_pack(pack_id: str, db: DB, ctx: Admin) -> ContentPackOut:
    p = _pack(pack_id)
    try:
        svc.install(db, ctx.org.id, p, ctx.user)
    except svc.PackInstallConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return pack_out(db, p, svc.installs(db, ctx.org.id))
