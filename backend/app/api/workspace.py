"""Dashboard, activity, members and AI status."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.ai import get_provider
from app.config import get_settings
from app.deps import DB, Admin, Ctx
from app.models import (
    AuditEvent,
    CheckResult,
    Document,
    DocumentVersion,
    Finding,
    FindingStatus,
    Job,
    JobStatus,
    Membership,
    Requirement,
    Review,
    ReviewRun,
    ReviewStatus,
    VersionStatus,
)
from app.schemas import AuditEventOut, AuditVerificationOut, MemberOut, Page
from app.services import audit
from app.services.ai_suggestions import FEATURE

router = APIRouter(tags=["workspace"])


@router.get("/dashboard")
def dashboard(ctx: Ctx, db: DB) -> dict[str, Any]:
    org = ctx.org_id
    live_docs = select(Document.id).where(Document.org_id == org, Document.deleted_at.is_(None))

    def count(stmt: Any) -> int:
        return int(db.scalar(stmt) or 0)

    processed = count(
        select(func.count(DocumentVersion.id)).where(
            DocumentVersion.org_id == org,
            DocumentVersion.status == VersionStatus.READY,
            DocumentVersion.document_id.in_(live_docs),
        )
    )
    failed_docs = count(
        select(func.count(DocumentVersion.id)).where(
            DocumentVersion.org_id == org,
            DocumentVersion.status == VersionStatus.FAILED,
            DocumentVersion.document_id.in_(live_docs),
        )
    )
    active_reviews = count(
        select(func.count(Review.id)).where(
            Review.org_id == org, Review.status != ReviewStatus.SIGNED_OFF
        )
    )
    by_status = dict(
        db.execute(
            select(Finding.status, func.count(Finding.id))
            .where(Finding.org_id == org)
            .group_by(Finding.status)
        ).all()
    )
    open_task = [FindingStatus.REMEDIATION_IN_PROGRESS, FindingStatus.READY_FOR_REREVIEW]
    open_tasks = count(
        select(func.count(Finding.id)).where(Finding.org_id == org, Finding.status.in_(open_task))
    )
    overdue = count(
        select(func.count(Finding.id)).where(
            Finding.org_id == org, Finding.status.in_(open_task), Finding.due_date < date.today()
        )
    )
    severity = dict(
        db.execute(
            select(Finding.severity, func.count(Finding.id))
            .where(Finding.org_id == org, Finding.status.notin_([FindingStatus.DISMISSED]))
            .group_by(Finding.severity)
        ).all()
    )
    job_failures = count(
        select(func.count(Job.id)).where(Job.org_id == org, Job.status == JobStatus.FAILED)
    )

    # Coverage: the proportion of checklist items reviewed, per active review. A
    # requirement counts as reviewed when its check result needs no attention, or its
    # finding has a reviewer decision.
    coverage = []
    reviews = (
        db.scalars(
            select(Review).where(Review.org_id == org).order_by(Review.created_at.desc()).limit(5)
        )
        .unique()
        .all()
    )
    for r in reviews:
        total = count(
            select(func.count(Requirement.id)).where(
                Requirement.checklist_version_id == r.checklist_version_id
            )
        )
        run_id = db.scalar(
            select(ReviewRun.id)
            .where(ReviewRun.review_id == r.id, ReviewRun.finished_at.is_not(None))
            .order_by(ReviewRun.created_at.desc())
            .limit(1)
        )
        clear = (
            count(
                select(func.count(CheckResult.id)).where(
                    CheckResult.run_id == run_id, CheckResult.needs_attention.is_(False)
                )
            )
            if run_id
            else 0
        )
        decided = count(
            select(func.count(Finding.id)).where(
                Finding.review_id == r.id,
                Finding.requirement_id.is_not(None),
                Finding.status.notin_([FindingStatus.PROPOSED, FindingStatus.IN_REVIEW]),
            )
        )
        coverage.append(
            {"review_id": str(r.id), "title": r.title, "reviewed": clear + decided, "total": total}
        )

    return {
        "documents_processed": processed,
        "documents_failed": failed_docs,
        "active_reviews": active_reviews,
        "findings_proposed": int(by_status.get(FindingStatus.PROPOSED, 0))
        + int(by_status.get(FindingStatus.IN_REVIEW, 0)),
        "findings_confirmed": sum(
            int(by_status.get(s, 0))
            for s in (
                FindingStatus.CONFIRMED,
                FindingStatus.REMEDIATION_IN_PROGRESS,
                FindingStatus.READY_FOR_REREVIEW,
                FindingStatus.RESOLVED,
            )
        ),
        "open_tasks": open_tasks,
        "overdue_tasks": overdue,
        "severity_distribution": {k.value: int(v) for k, v in severity.items()},
        "job_failures": job_failures,
        "coverage": coverage,
        "coverage_definition": "The proportion of checklist items reviewed.",
    }


@router.get("/audit-events", response_model=Page[AuditEventOut])
def audit_events(
    ctx: Ctx,
    db: DB,
    action: str | None = Query(default=None, max_length=80),
    object_type: str | None = Query(default=None, max_length=60),
    object_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Page[AuditEventOut]:
    stmt = select(AuditEvent).where(AuditEvent.org_id == ctx.org_id)
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action))
    if object_type:
        stmt = stmt.where(AuditEvent.object_type == object_type)
    if object_id:
        stmt = stmt.where(AuditEvent.object_id == object_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        db.scalars(
            stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.seq.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    return Page(
        items=[
            AuditEventOut(
                id=e.id,
                actor_name=e.actor.full_name if e.actor else None,
                action=e.action,
                object_type=e.object_type,
                object_id=e.object_id,
                meta=e.meta,
                created_at=e.created_at,
                seq=e.seq,
                hash=e.hash,
            )
            for e in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/audit-events/verify",
    response_model=AuditVerificationOut,
    summary="Verify the organisation's audit chain",
    description="Recomputes every audit event hash in order. Organisation admins only.",
)
def verify_audit_events(ctx: Admin, db: DB) -> AuditVerificationOut:
    result = audit.verify_chain(db, ctx.org_id)
    return AuditVerificationOut(**vars(result))


@router.get("/members", response_model=list[MemberOut])
def members(ctx: Ctx, db: DB) -> list[MemberOut]:
    rows = db.scalars(select(Membership).where(Membership.org_id == ctx.org_id)).unique().all()
    return sorted(
        [
            MemberOut(
                user_id=m.user_id,
                full_name=m.user.full_name,
                email=m.user.email,
                role=m.role,
                membership_id=m.id,
                joined_at=m.created_at,
            )
            for m in rows
        ],
        key=lambda m: m.full_name,
    )


@router.get("/ai/status")
def ai_status(ctx: Ctx) -> dict[str, Any]:
    s = get_settings()
    provider = get_provider(s)
    deployment = s.ai_enabled and provider.name != "disabled"
    enabled = deployment and ctx.org.ai_opt_in
    return {
        "enabled": enabled,
        "deployment_enabled": deployment,
        "org_opted_in": ctx.org.ai_opt_in,
        "provider": provider.name,
        "model": s.ai_model if s.ai_enabled else None,
        "available_features": [FEATURE] if enabled else [],
        "is_mock": enabled and provider.name == "mock",
        "note": (
            "AI suggestions are available. Each suggestion needs a reviewer's acceptance "
            "before it becomes a finding."
            if enabled
            else "AI is offered but this organisation has not opted in."
            if deployment
            else "AI is disabled. Reviews use deterministic checks and human decisions only."
        ),
    }
