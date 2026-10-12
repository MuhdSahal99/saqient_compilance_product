from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.reviews import finding_out
from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.models import AISuggestion, AISuggestionRun, Review
from app.schemas import (
    AIDecisionIn,
    AISuggestionOut,
    AISuggestionRunOut,
    AISuggestionsOut,
    FindingOut,
    JobOut,
)
from app.services import ai_suggestions as svc
from app.services.jobs import enqueue

router = APIRouter(tags=["ai"])


def _run_out(run: AISuggestionRun) -> AISuggestionRunOut:
    return AISuggestionRunOut(
        id=run.id,
        provider=run.provider,
        model=run.model,
        is_mock=run.provider == "mock",
        prompt_version=run.prompt_version,
        warnings=run.warnings,
        created_at=run.created_at,
        finished_at=run.finished_at,
        job=JobOut.model_validate(run.job),
    )


def _suggestion_out(s: AISuggestion) -> AISuggestionOut:
    return AISuggestionOut(
        id=s.id,
        requirement_id=s.requirement_id,
        requirement_code=s.requirement.code,
        requirement_title=s.requirement.title,
        severity=s.requirement.severity,
        assessment=s.assessment,
        summary=s.summary,
        evidence=s.evidence,
        rejected_citations=s.rejected_citations,
        status=s.status,
        decided_by_name=s.decided_by.full_name if s.decided_by else None,
        decided_at=s.decided_at,
        decision_note=s.decision_note,
        finding_id=s.finding_id,
    )


def _latest(db: DB, review: Review) -> AISuggestionsOut:
    run = db.scalar(
        select(AISuggestionRun)
        .where(AISuggestionRun.review_id == review.id, AISuggestionRun.org_id == review.org_id)
        .order_by(AISuggestionRun.created_at.desc())
        .limit(1)
    )
    rows: list[AISuggestion] = []
    if run is not None:
        rows = sorted(
            db.scalars(select(AISuggestion).where(AISuggestion.run_id == run.id)).unique(),
            key=lambda s: s.requirement.ordinal,
        )
    return AISuggestionsOut(
        available=svc.feature_available(),
        run=_run_out(run) if run else None,
        suggestions=[_suggestion_out(s) for s in rows],
    )


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("/reviews/{review_id}/ai-suggestions", response_model=AISuggestionsOut)
def list_suggestions(review_id: uuid.UUID, ctx: Ctx, db: DB) -> AISuggestionsOut:
    return _latest(db, get_owned_or_404(db, Review, review_id, ctx.org_id))


@router.post("/reviews/{review_id}/ai-suggestions", response_model=AISuggestionsOut)
def request_suggestions(review_id: uuid.UUID, ctx: Writer, db: DB) -> AISuggestionsOut:
    review = get_owned_or_404(db, Review, review_id, ctx.org_id)
    try:
        job = svc.request_suggestions(db, review, ctx.user)
    except svc.AIError as exc:
        raise _bad(exc) from exc
    db.commit()
    enqueue(job)
    db.expire_all()  # the job may have run inline (eager mode)
    return _latest(db, review)


@router.post("/ai-suggestions/{suggestion_id}/accept", response_model=FindingOut)
def accept(suggestion_id: uuid.UUID, body: AIDecisionIn, ctx: Decider, db: DB) -> FindingOut:
    sug = get_owned_or_404(db, AISuggestion, suggestion_id, ctx.org_id)
    review = get_owned_or_404(db, Review, sug.review_id, ctx.org_id)
    try:
        finding = svc.accept(db, sug, review, ctx.user, body.note)
    except svc.AIError as exc:
        raise _bad(exc) from exc
    db.commit()
    db.refresh(finding)
    return finding_out(finding)


@router.post("/ai-suggestions/{suggestion_id}/reject", response_model=AISuggestionOut)
def reject(suggestion_id: uuid.UUID, body: AIDecisionIn, ctx: Decider, db: DB) -> AISuggestionOut:
    sug = get_owned_or_404(db, AISuggestion, suggestion_id, ctx.org_id)
    review = get_owned_or_404(db, Review, sug.review_id, ctx.org_id)
    try:
        svc.reject(db, sug, review, ctx.user, body.note)
    except svc.AIError as exc:
        raise _bad(exc) from exc
    db.commit()
    db.refresh(sug)
    return _suggestion_out(sug)
