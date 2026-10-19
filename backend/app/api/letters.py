"""Management letter from confirmed engagement findings (Phase D8)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.engagements import _guard, get_engagement
from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.models import LetterPoint, LetterSnapshot
from app.schemas import LetterOut, LetterPointIn, LetterPointOut, LetterVersionOut
from app.services import audit
from app.services import letters as svc

router = APIRouter(tags=["management letter"])


def _point(p: LetterPoint) -> LetterPointOut:
    f = p.finding
    return LetterPointOut(
        id=p.id,
        finding_id=f.id,
        finding_title=f.title,
        finding_status=f.status,
        severity=f.severity,
        observation=svc.observation(f),
        include=p.include,
        recommendation=p.recommendation,
        management_response=p.management_response,
        response_owner=p.response_owner,
        response_due=p.response_due,
        evidence_refs=svc.evidence_refs(f),
    )


def letter_out(db: DB, e: object) -> LetterOut:
    from app.models import AuditEngagement

    assert isinstance(e, AuditEngagement)
    return LetterOut(
        points=[_point(p) for p in svc.points(db, e)],
        versions=[
            LetterVersionOut(
                version=s.version,
                issued_by_name=s.content.get("issued_by"),
                issued_at=s.issued_at,
                points=len(s.content.get("points", [])),
            )
            for s in svc.snapshots(db, e)
        ],
    )


@router.get(
    "/engagements/{engagement_id}/letter",
    response_model=LetterOut,
    summary="Management letter draft and issued versions",
)
def get_letter(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> LetterOut:
    return letter_out(db, get_engagement(db, ctx, engagement_id))


@router.post(
    "/engagements/{engagement_id}/letter/refresh",
    response_model=LetterOut,
    summary="Add new confirmed findings to the letter",
    description=(
        "Adds a point for each confirmed finding of the engagement's linked reviews that is "
        "not on the letter yet. Proposed and dismissed findings are never included."
    ),
)
def refresh(engagement_id: uuid.UUID, db: DB, ctx: Writer) -> LetterOut:
    e = get_engagement(db, ctx, engagement_id)
    _guard(lambda: svc.refresh(db, e, ctx.user))
    db.commit()
    return letter_out(db, e)


@router.put(
    "/letter-points/{point_id}",
    response_model=LetterPointOut,
    summary="Edit a letter point",
    description="Recommendation, management response, owner and date, and whether it is included.",
)
def update_point(point_id: uuid.UUID, body: LetterPointIn, db: DB, ctx: Writer) -> LetterPointOut:
    p = get_owned_or_404(db, LetterPoint, point_id, ctx.org.id)
    e = get_engagement(db, ctx, p.engagement_id)
    _guard(lambda: svc.update_point(db, e, p, body, ctx.user))
    db.commit()
    return _point(p)


@router.post(
    "/engagements/{engagement_id}/letter/issue",
    response_model=LetterOut,
    summary="Issue the management letter",
    description="Freezes the included points as the next immutable letter version.",
)
def issue(engagement_id: uuid.UUID, db: DB, ctx: Decider) -> LetterOut:
    e = get_engagement(db, ctx, engagement_id)
    _guard(lambda: svc.issue(db, e, ctx.user))
    db.commit()
    return letter_out(db, e)


@router.get(
    "/engagements/{engagement_id}/letter/{version}/export",
    summary="Export an issued management letter",
    response_class=Response,
)
def export_letter(
    engagement_id: uuid.UUID,
    version: int,
    db: DB,
    ctx: Ctx,
    fmt: str = Query(alias="format", pattern="^(html|pdf)$"),
) -> Response:
    e = get_engagement(db, ctx, engagement_id)
    snap = db.scalar(
        select(LetterSnapshot).where(
            LetterSnapshot.engagement_id == e.id,
            LetterSnapshot.org_id == ctx.org.id,
            LetterSnapshot.version == version,
        )
    )
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    audit.record(
        db,
        org_id=ctx.org.id,
        actor_id=ctx.user.id,
        action="letter.exported",
        object_type="audit_engagement",
        object_id=e.id,
        meta={"version": version, "format": fmt},
    )
    db.commit()
    headers = {"Cache-Control": "private, no-store"}
    if fmt == "html":
        return Response(
            svc.render_html(snap.content), media_type="text/html; charset=utf-8", headers=headers
        )
    headers["Content-Disposition"] = (
        f'attachment; filename="saqient-management-letter-v{version}.pdf"'
    )
    return Response(svc.render_pdf(snap.content), media_type="application/pdf", headers=headers)
