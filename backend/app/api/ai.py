from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.reviews import finding_out
from app.config import get_settings
from app.deps import DB, Admin, Ctx, Decider, Writer, get_owned_or_404
from app.models import (
    AISuggestion,
    AISuggestionRun,
    AITask,
    AITaskKind,
    DocumentVersion,
    Finding,
    LetterPoint,
    Organization,
    Review,
)
from app.schemas import (
    AIAgentOut,
    AIDecisionIn,
    AISettingsIn,
    AISettingsOut,
    AISuggestionOut,
    AISuggestionRunOut,
    AISuggestionsOut,
    AITaskIn,
    AITaskOut,
    AITaskStepOut,
    FindingOut,
    JobOut,
)
from app.services import ai_suggestions as svc
from app.services import ai_tasks as tasks
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
        available=svc.org_enabled(db.get(Organization, review.org_id)),
        run=_run_out(run) if run else None,
        suggestions=[_suggestion_out(s) for s in rows],
    )


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


def _settings_out(ctx: Ctx) -> AISettingsOut:
    s = get_settings()
    available = svc.feature_available()
    return AISettingsOut(
        deployment_available=available,
        provider=s.ai_provider if available else "disabled",
        model=(s.ai_model_for("fast") or s.ai_provider) if available else None,
        is_mock=available and s.ai_provider == "mock",
        opted_in=ctx.org.ai_opt_in,
        opted_in_at=ctx.org.ai_opt_in_at,
    )


@router.get(
    "/org/ai-settings",
    response_model=AISettingsOut,
    summary="Organisation AI settings",
    description="Whether the deployment offers AI suggestions and whether this "
    "organisation opted in. Both must hold before any document text goes to a model.",
)
def get_ai_settings(ctx: Ctx) -> AISettingsOut:
    return _settings_out(ctx)


@router.put(
    "/org/ai-settings",
    response_model=AISettingsOut,
    summary="Opt the organisation in or out of AI suggestions",
    description="Org admins only. Opting in is refused while the deployment has no AI "
    "provider. Suggestions still need a reviewer's acceptance to become findings.",
)
def put_ai_settings(body: AISettingsIn, ctx: Admin, db: DB) -> AISettingsOut:
    if body.opted_in and not svc.feature_available():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "AI suggestions are not enabled for this deployment."
        )
    svc.set_opt_in(db, ctx.org, body.opted_in, ctx.user)
    db.commit()
    db.refresh(ctx.org)
    return _settings_out(ctx)


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


# ---------------------------------------------------------------- multi-agent tasks

_SUBJECT_MODELS: dict[AITaskKind, type[DocumentVersion | Finding | LetterPoint]] = {
    AITaskKind.CONTRACT_TAX: DocumentVersion,
    AITaskKind.FINDING_EXPLAIN: Finding,
    AITaskKind.LETTER_DRAFT: LetterPoint,
}


def _task_out(t: AITask) -> AITaskOut:
    return AITaskOut(
        id=t.id,
        kind=t.kind,
        subject_type=t.subject_type,
        subject_id=t.subject_id,
        question=t.question,
        language=t.language,
        status=t.status,
        provider=t.provider,
        is_mock=t.provider == "mock",
        prompt_version=t.prompt_version,
        output=t.output,
        warnings=t.warnings,
        error=t.error,
        requested_by_name=t.requested_by.full_name if t.requested_by else None,
        decided_by_name=t.decided_by.full_name if t.decided_by else None,
        decided_at=t.decided_at,
        decision_note=t.decision_note,
        created_at=t.created_at,
        finished_at=t.finished_at,
        steps=[AITaskStepOut.model_validate(s) for s in t.steps],
        job=JobOut.model_validate(t.job),
    )


@router.get(
    "/ai/agents",
    response_model=list[AIAgentOut],
    summary="AI agents and their models",
    description="The agents, the model tier each uses and the configured model. "
    "Empty unless the deployment has an AI provider and the organisation opted in.",
)
def list_agents(ctx: Ctx) -> list[AIAgentOut]:
    if not tasks.org_enabled(ctx.org):
        return []
    return [AIAgentOut(**a) for a in tasks.agent_catalogue(get_settings())]


@router.post(
    "/ai/tasks",
    response_model=AITaskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Run an AI task",
    description="Starts a multi-agent task: contract VAT and related-party scan, a finding "
    "explanation, management letter wording, or a question answered from verified content "
    "only. The output is a draft that a reviewer accepts or dismisses. Needs the deployment "
    "provider and the organisation's opt-in.",
)
def create_task(body: AITaskIn, ctx: Writer, db: DB) -> AITaskOut:
    subject: object = ctx.org
    if body.kind is not AITaskKind.PACK_QA:
        if body.subject_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "subject_id is required.")
        subject = get_owned_or_404(db, _SUBJECT_MODELS[body.kind], body.subject_id, ctx.org_id)
    try:
        task = tasks.request_task(
            db, ctx.org, body.kind, subject, ctx.user, body.question, body.language
        )
    except tasks.AITaskError as exc:
        raise _bad(exc) from exc
    db.commit()
    job = task.job
    enqueue(job)
    db.expire_all()  # the job may have run inline (eager mode)
    return _task_out(get_owned_or_404(db, AITask, task.id, ctx.org_id))


@router.get(
    "/ai/tasks",
    response_model=list[AITaskOut],
    summary="List AI tasks",
    description="Most recent first; filter by kind and subject.",
)
def list_tasks(
    ctx: Ctx,
    db: DB,
    kind: AITaskKind | None = None,
    subject_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AITaskOut]:
    q = select(AITask).where(AITask.org_id == ctx.org_id)
    if kind is not None:
        q = q.where(AITask.kind == kind)
    if subject_id is not None:
        q = q.where(AITask.subject_id == subject_id)
    rows = db.scalars(q.order_by(AITask.created_at.desc()).limit(limit)).unique()
    return [_task_out(t) for t in rows]


@router.get("/ai/tasks/{task_id}", response_model=AITaskOut, summary="Get an AI task")
def get_task(task_id: uuid.UUID, ctx: Ctx, db: DB) -> AITaskOut:
    return _task_out(get_owned_or_404(db, AITask, task_id, ctx.org_id))


@router.post(
    "/ai/tasks/{task_id}/accept",
    response_model=AITaskOut,
    summary="Accept an AI draft",
    description="Reviewers and admins. Accepting letter wording copies the recommendation "
    "into the letter point while the engagement is open; other drafts are only marked "
    "accepted. Audited with the models used.",
)
def accept_task(task_id: uuid.UUID, body: AIDecisionIn, ctx: Decider, db: DB) -> AITaskOut:
    task = get_owned_or_404(db, AITask, task_id, ctx.org_id)
    try:
        tasks.accept(db, task, ctx.user, body.note)
    except tasks.AITaskError as exc:
        raise _bad(exc) from exc
    db.commit()
    db.refresh(task)
    return _task_out(task)


@router.post(
    "/ai/tasks/{task_id}/dismiss",
    response_model=AITaskOut,
    summary="Dismiss an AI draft",
)
def dismiss_task(task_id: uuid.UUID, body: AIDecisionIn, ctx: Decider, db: DB) -> AITaskOut:
    task = get_owned_or_404(db, AITask, task_id, ctx.org_id)
    try:
        tasks.dismiss(db, task, ctx.user, body.note)
    except tasks.AITaskError as exc:
        raise _bad(exc) from exc
    db.commit()
    db.refresh(task)
    return _task_out(task)
