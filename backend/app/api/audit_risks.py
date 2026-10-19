"""Risk register, audit procedures and audit programmes (Phase D4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.api.engagements import _guard, get_engagement
from app.deps import DB, Ctx, Writer, get_owned_or_404
from app.models import AuditProcedure, AuditRisk, Review
from app.schemas import (
    CoverageOut,
    ProcedureIn,
    ProcedureOut,
    ProcedureStatusIn,
    ProgrammeIn,
    ReviewOut,
    RiskIn,
    RiskOut,
)
from app.services import audit_risks as svc

router = APIRouter(tags=["audit risks and procedures"])


def _risk_out(r: AuditRisk, pairs: list[tuple[uuid.UUID, uuid.UUID]]) -> RiskOut:
    return RiskOut(
        id=r.id,
        ref=r.ref,
        title=r.title,
        description=r.description,
        lead_code=r.lead_code,
        assertions=r.assertions,
        inherent_risk=r.inherent_risk,
        significant=r.significant,
        fraud=r.fraud,
        response=r.response,
        procedure_ids=[p for rid, p in pairs if rid == r.id],
    )


def _proc_out(p: AuditProcedure, pairs: list[tuple[uuid.UUID, uuid.UUID]]) -> ProcedureOut:
    return ProcedureOut(
        id=p.id,
        title=p.title,
        description=p.description,
        requirement_id=p.requirement_id,
        requirement_code=p.requirement.code if p.requirement else None,
        review_id=p.review_id,
        assignee_id=p.assignee_id,
        assignee_name=p.assignee.full_name if p.assignee else None,
        status=p.status,
        conclusion=p.conclusion,
        completed_at=p.completed_at,
        risk_ids=[rid for rid, pid in pairs if pid == p.id],
    )


@router.get(
    "/engagements/{engagement_id}/risks",
    response_model=list[RiskOut],
    summary="List the risk register",
)
def list_risks(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[RiskOut]:
    e = get_engagement(db, ctx, engagement_id)
    pairs = svc.links(db, e)
    return [_risk_out(r, pairs) for r in svc.risks(db, e)]


@router.post(
    "/engagements/{engagement_id}/risks",
    response_model=RiskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a risk",
    description="A risk of material misstatement for an FS area and one or more assertions.",
)
def add_risk(engagement_id: uuid.UUID, body: RiskIn, db: DB, ctx: Writer) -> RiskOut:
    e = get_engagement(db, ctx, engagement_id)
    r = _guard(lambda: svc.save_risk(db, e, body, ctx.user))
    db.commit()
    return _risk_out(r, svc.links(db, e))


@router.put("/risks/{risk_id}", response_model=RiskOut, summary="Update a risk")
def update_risk(risk_id: uuid.UUID, body: RiskIn, db: DB, ctx: Writer) -> RiskOut:
    r = get_owned_or_404(db, AuditRisk, risk_id, ctx.org.id)
    e = get_engagement(db, ctx, r.engagement_id)
    _guard(lambda: svc.save_risk(db, e, body, ctx.user, r))
    db.commit()
    return _risk_out(r, svc.links(db, e))


@router.delete("/risks/{risk_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a risk")
def delete_risk(risk_id: uuid.UUID, db: DB, ctx: Writer) -> Response:
    r = get_owned_or_404(db, AuditRisk, risk_id, ctx.org.id)
    e = get_engagement(db, ctx, r.engagement_id)
    _guard(lambda: svc.delete_risk(db, e, r, ctx.user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/engagements/{engagement_id}/procedures",
    response_model=list[ProcedureOut],
    summary="List audit procedures",
)
def list_procedures(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[ProcedureOut]:
    e = get_engagement(db, ctx, engagement_id)
    pairs = svc.links(db, e)
    return [_proc_out(p, pairs) for p in svc.procedures(db, e)]


@router.post(
    "/engagements/{engagement_id}/procedures",
    response_model=ProcedureOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an audit procedure",
    description="Links to the risks it responds to, and optionally a programme requirement.",
)
def add_procedure(engagement_id: uuid.UUID, body: ProcedureIn, db: DB, ctx: Writer) -> ProcedureOut:
    e = get_engagement(db, ctx, engagement_id)
    p = _guard(lambda: svc.save_procedure(db, e, body, ctx.user))
    db.commit()
    return _proc_out(p, svc.links(db, e))


@router.put("/procedures/{procedure_id}", response_model=ProcedureOut, summary="Update a procedure")
def update_procedure(
    procedure_id: uuid.UUID, body: ProcedureIn, db: DB, ctx: Writer
) -> ProcedureOut:
    p = get_owned_or_404(db, AuditProcedure, procedure_id, ctx.org.id)
    e = get_engagement(db, ctx, p.engagement_id)
    _guard(lambda: svc.save_procedure(db, e, body, ctx.user, p))
    db.commit()
    return _proc_out(p, svc.links(db, e))


@router.post(
    "/procedures/{procedure_id}/status",
    response_model=ProcedureOut,
    summary="Change a procedure's status",
    description="Marking a procedure done needs a written conclusion.",
)
def procedure_status(
    procedure_id: uuid.UUID, body: ProcedureStatusIn, db: DB, ctx: Writer
) -> ProcedureOut:
    p = get_owned_or_404(db, AuditProcedure, procedure_id, ctx.org.id)
    e = get_engagement(db, ctx, p.engagement_id)
    _guard(lambda: svc.set_procedure_status(db, e, p, body, ctx.user))
    db.commit()
    return _proc_out(p, svc.links(db, e))


@router.post(
    "/engagements/{engagement_id}/programme",
    response_model=list[ProcedureOut],
    summary="Apply an audit programme",
    description=(
        "Creates one procedure per requirement of a published audit programme checklist "
        "version; requirements already planned are skipped."
    ),
)
def apply_programme(
    engagement_id: uuid.UUID, body: ProgrammeIn, db: DB, ctx: Writer
) -> list[ProcedureOut]:
    e = get_engagement(db, ctx, engagement_id)
    _guard(lambda: svc.apply_programme(db, e, body.checklist_version_id, ctx.user))
    db.commit()
    pairs = svc.links(db, e)
    return [_proc_out(p, pairs) for p in svc.procedures(db, e)]


@router.get(
    "/engagements/{engagement_id}/risk-coverage",
    response_model=CoverageOut,
    summary="Risk coverage",
    description=(
        "Procedures per risk, risks with none, significant or fraud risks without a "
        "completed procedure, and procedures answering no risk."
    ),
)
def risk_coverage(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> CoverageOut:
    e = get_engagement(db, ctx, engagement_id)
    return CoverageOut.model_validate(svc.coverage(db, e))


@router.post(
    "/engagements/{engagement_id}/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Link a review to the engagement",
    description="Its findings then count as engagement findings (e.g. for the management letter).",
)
def link_review(engagement_id: uuid.UUID, review_id: uuid.UUID, db: DB, ctx: Writer) -> Response:
    e = get_engagement(db, ctx, engagement_id)
    rv = get_owned_or_404(db, Review, review_id, ctx.org.id)
    _guard(lambda: svc.link_review(db, e, rv, ctx.user))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/engagements/{engagement_id}/reviews",
    response_model=list[ReviewOut],
    summary="List the engagement's reviews",
)
def list_reviews(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[ReviewOut]:
    from app.api.reviews import _review_out as review_out

    e = get_engagement(db, ctx, engagement_id)
    rows = db.scalars(
        select(Review)
        .where(Review.org_id == ctx.org.id, Review.engagement_id == e.id)
        .order_by(Review.created_at)
    ).unique()
    return [review_out(db, r) for r in rows]
