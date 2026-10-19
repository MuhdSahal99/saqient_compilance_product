from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import DB, DECIDE_ROLES, Ctx, Decider, Writer, get_owned_or_404
from app.models import (
    ChecklistVersion,
    CheckResult,
    Comment,
    DatasetVersion,
    Document,
    DocumentVersion,
    EInvoiceBatch,
    EInvoiceFile,
    Finding,
    FindingStatus,
    LegalEntity,
    Membership,
    ReportSnapshot,
    Requirement,
    Review,
    ReviewEInvoice,
    ReviewRun,
    ReviewStatus,
    RulePackVersion,
    Severity,
    SourceBlock,
    TaxPeriod,
    User,
)
from app.schemas import (
    AssignmentIn,
    BulkAssignIn,
    CheckResultOut,
    CommentIn,
    CommentOut,
    DecisionIn,
    FindingOut,
    JobOut,
    ManualFindingIn,
    Page,
    RemediationIn,
    ReopenIn,
    ReportOut,
    ReviewCreateIn,
    ReviewDatasetOut,
    ReviewOut,
    ReviewRunOut,
)
from app.services import audit, reviews
from app.services.jobs import enqueue
from app.services.reports import render_csv, render_html, render_pdf

router = APIRouter(tags=["reviews"])

OPEN_TASK_STATUSES = [FindingStatus.REMEDIATION_IN_PROGRESS, FindingStatus.READY_FOR_REREVIEW]


def _review_out(db: Session, r: Review) -> ReviewOut:
    dv = r.document_version
    cv: ChecklistVersion = r.checklist_version
    doc = db.get(Document, dv.document_id) if dv else None
    rpv = db.get(RulePackVersion, r.rule_pack_version_id) if r.rule_pack_version_id else None
    counts = dict(
        db.execute(
            select(Finding.status, func.count(Finding.id))
            .where(Finding.review_id == r.id)
            .group_by(Finding.status)
        ).all()
    )
    run = db.scalar(
        select(ReviewRun)
        .where(ReviewRun.review_id == r.id)
        .order_by(ReviewRun.created_at.desc())
        .limit(1)
    )
    signer = db.get(User, r.signed_off_by_id) if r.signed_off_by_id else None
    return ReviewOut(
        id=r.id,
        title=r.title,
        status=r.status,
        is_demo=r.is_demo,
        created_at=r.created_at,
        signed_off_at=r.signed_off_at,
        signed_off_by_name=signer.full_name if signer else None,
        document_id=doc.id if doc else None,
        document_title=doc.title if doc else None,
        document_version_id=dv.id if dv else None,
        document_version_number=dv.version_number if dv else None,
        datasets=[
            ReviewDatasetOut(
                kind=link.kind,
                dataset_id=link.dataset_version.dataset_id,
                dataset_name=link.dataset_version.dataset.name,
                dataset_version_id=link.dataset_version_id,
                version_number=link.dataset_version.version_number,
                row_count=link.dataset_version.row_count,
            )
            for link in r.datasets
        ],
        rule_pack_version_id=r.rule_pack_version_id,
        rule_pack_name=rpv.rule_pack.name if rpv else None,
        rule_pack_version_number=rpv.version_number if rpv else None,
        as_of_date=r.as_of_date,
        entity_id=r.entity_id,
        entity_name=r.entity.name if r.entity else None,
        tax_period_id=r.tax_period_id,
        tax_period_start=r.tax_period.period_start if r.tax_period else None,
        tax_period_end=r.tax_period.period_end if r.tax_period else None,
        einvoice_count=db.scalar(
            select(func.count(ReviewEInvoice.id)).where(ReviewEInvoice.review_id == r.id)
        )
        or 0,
        checklist_id=cv.checklist_id,
        checklist_name=cv.checklist.name,
        checklist_version_id=cv.id,
        checklist_version_number=cv.version_number,
        checklist_kind=cv.checklist.kind,
        finding_counts={k.value: v for k, v in counts.items()},
        latest_run=ReviewRunOut(
            id=run.id,
            engine_version=run.engine_version,
            engine_mode=run.engine_mode,
            warnings=run.warnings,
            inputs_snapshot=run.inputs_snapshot or {},
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            job=JobOut.model_validate(run.job),
        )
        if run
        else None,
    )


def finding_out(f: Finding) -> FindingOut:
    open_states = (
        FindingStatus.CONFIRMED,
        FindingStatus.REMEDIATION_IN_PROGRESS,
        FindingStatus.READY_FOR_REREVIEW,
    )
    return FindingOut(
        id=f.id,
        review_id=f.review_id,
        review_title=f.review.title,
        review_status=f.review.status,
        requirement_id=f.requirement_id,
        requirement_code=f.requirement.code
        if f.requirement
        else (f.ai_suggestion.requirement.code if f.ai_suggestion else None),
        finding_key=f.finding_key,
        source_reference=f.requirement.source_reference if f.requirement else None,
        is_manual=f.is_manual,
        title=f.title,
        description=f.description,
        severity=f.severity,
        automated_outcome=f.automated_outcome,
        evidence=f.evidence,
        status=f.status,
        owner_id=f.owner_id,
        owner_name=f.owner.full_name if f.owner else None,
        due_date=f.due_date,
        is_overdue=bool(f.due_date and f.due_date < date.today() and f.status in open_states),
        decided_by_name=f.decided_by.full_name if f.decided_by else None,
        decided_at=f.decided_at,
        decision_rationale=f.decision_rationale,
        remediation_notes=f.remediation_notes,
        ai_suggestion_id=f.ai_suggestion_id,
        ai_provider=f.ai_suggestion.run.provider if f.ai_suggestion else None,
        ai_model=f.ai_suggestion.run.model if f.ai_suggestion else None,
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


def _bad(exc: Exception, code: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(code, str(exc))


# ---------------------------------------------------------------- reviews


@router.get("/reviews", response_model=Page[ReviewOut])
def list_reviews(
    ctx: Ctx,
    db: DB,
    status_filter: ReviewStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ReviewOut]:
    stmt = select(Review).where(Review.org_id == ctx.org_id)
    if status_filter:
        stmt = stmt.where(Review.status == status_filter)
    if q:
        stmt = stmt.where(Review.title.ilike(f"%{q.replace('%', r'\%')}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        db.scalars(
            stmt.order_by(Review.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        .unique()
        .all()
    )
    return Page(
        items=[_review_out(db, r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.post("/reviews", status_code=201, response_model=ReviewOut)
def create_review(body: ReviewCreateIn, ctx: Writer, db: DB) -> ReviewOut:
    dv = None
    if body.document_version_id is not None:
        dv = get_owned_or_404(db, DocumentVersion, body.document_version_id, ctx.org_id)
        doc = db.get(Document, dv.document_id)
        if doc is None or doc.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    cv = get_owned_or_404(db, ChecklistVersion, body.checklist_version_id, ctx.org_id)
    datasets = [
        get_owned_or_404(db, DatasetVersion, vid, ctx.org_id) for vid in body.dataset_version_ids
    ]
    rpv = (
        get_owned_or_404(db, RulePackVersion, body.rule_pack_version_id, ctx.org_id)
        if body.rule_pack_version_id
        else None
    )
    entity = (
        get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org_id) if body.entity_id else None
    )
    period = (
        get_owned_or_404(db, TaxPeriod, body.tax_period_id, ctx.org_id)
        if body.tax_period_id
        else None
    )
    files: dict[uuid.UUID, EInvoiceFile] = {}
    for bid in body.einvoice_batch_ids:
        batch = get_owned_or_404(db, EInvoiceBatch, bid, ctx.org_id)
        for f in db.scalars(
            select(EInvoiceFile).where(
                EInvoiceFile.org_id == ctx.org_id, EInvoiceFile.batch_id == batch.id
            )
        ):
            files[f.id] = f
    for fid in body.einvoice_file_ids:
        f = get_owned_or_404(db, EInvoiceFile, fid, ctx.org_id)
        files[f.id] = f
    try:
        review, job = reviews.create_review(
            db,
            org_id=ctx.org_id,
            user_id=ctx.user.id,
            title=body.title,
            document_version=dv,
            checklist_version=cv,
            dataset_versions=datasets,
            rule_pack_version=rpv,
            as_of_date=body.as_of_date,
            entity=entity,
            tax_period=period,
            einvoice_files=list(files.values()),
        )
    except reviews.ReviewError as exc:
        raise _bad(exc, status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    db.commit()
    enqueue(job)
    db.expire_all()  # the job may have run inline (eager mode)
    db.refresh(review)
    return _review_out(db, review)


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: uuid.UUID, ctx: Ctx, db: DB) -> ReviewOut:
    return _review_out(db, get_owned_or_404(db, Review, review_id, ctx.org_id))


@router.post("/reviews/{review_id}/runs", response_model=ReviewOut)
def rerun(review_id: uuid.UUID, ctx: Writer, db: DB) -> ReviewOut:
    review = get_owned_or_404(db, Review, review_id, ctx.org_id)
    try:
        job = reviews.start_run(db, review, ctx.user.id)
    except reviews.ReviewError as exc:
        raise _bad(exc) from exc
    db.commit()
    enqueue(job)
    db.expire_all()  # the job may have run inline (eager mode)
    db.refresh(review)
    return _review_out(db, review)


@router.get("/reviews/{review_id}/results", response_model=list[CheckResultOut])
def results(review_id: uuid.UUID, ctx: Ctx, db: DB) -> list[CheckResultOut]:
    review = get_owned_or_404(db, Review, review_id, ctx.org_id)
    run = db.scalar(
        select(ReviewRun)
        .where(ReviewRun.review_id == review.id, ReviewRun.finished_at.is_not(None))
        .order_by(ReviewRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return []
    rows = db.scalars(
        select(CheckResult)
        .join(Requirement)
        .where(CheckResult.run_id == run.id)
        .order_by(Requirement.ordinal)
    ).all()
    return [
        CheckResultOut(
            id=r.id,
            requirement_id=r.requirement_id,
            requirement_code=r.requirement.code,
            requirement_title=r.requirement.title,
            severity=r.requirement.severity,
            outcome=r.outcome,
            needs_attention=r.needs_attention,
            message=r.message,
            evidence=r.evidence,
            meta=r.meta or {},
            result_hash=r.result_hash,
        )
        for r in rows
    ]


@router.post("/reviews/{review_id}/signoff", response_model=ReportOut)
def sign_off(review_id: uuid.UUID, ctx: Decider, db: DB) -> ReportOut:
    review = get_owned_or_404(db, Review, review_id, ctx.org_id)
    try:
        snap = reviews.sign_off(db, review, ctx.user)
    except reviews.ReviewError as exc:
        raise _bad(exc) from exc
    db.commit()
    return _report_out(snap, review)


@router.post("/reviews/{review_id}/reopen", response_model=ReviewOut)
def reopen(review_id: uuid.UUID, body: ReopenIn, ctx: Decider, db: DB) -> ReviewOut:
    review = get_owned_or_404(db, Review, review_id, ctx.org_id)
    try:
        reviews.reopen(db, review, body.reason, ctx.user)
    except reviews.ReviewError as exc:
        raise _bad(exc) from exc
    db.commit()
    return _review_out(db, review)


# ---------------------------------------------------------------- findings


@router.get("/findings", response_model=Page[FindingOut])
def list_findings(
    ctx: Ctx,
    db: DB,
    review_id: uuid.UUID | None = None,
    status_filter: list[FindingStatus] | None = Query(default=None, alias="status"),
    severity: Severity | None = None,
    owner: str | None = Query(default=None, pattern="^(me|any|none)$"),
    overdue: bool = False,
    q: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="severity", pattern="^(severity|due_date|created_at|status)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Page[FindingOut]:
    stmt = select(Finding).where(Finding.org_id == ctx.org_id)
    if review_id:
        stmt = stmt.where(Finding.review_id == review_id)
    if status_filter:
        stmt = stmt.where(Finding.status.in_(status_filter))
    if severity:
        stmt = stmt.where(Finding.severity == severity)
    if owner == "me":
        stmt = stmt.where(Finding.owner_id == ctx.user.id)
    elif owner == "none":
        stmt = stmt.where(Finding.owner_id.is_(None))
    if overdue:
        stmt = stmt.where(Finding.due_date < date.today(), Finding.status.in_(OPEN_TASK_STATUSES))
    if q:
        stmt = stmt.where(Finding.title.ilike(f"%{q.replace('%', r'\%')}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sev_order = func.array_position(["critical", "high", "medium", "low"], Finding.severity)
    orders: dict[str, list[Any]] = {
        "severity": [sev_order, Finding.created_at],
        "due_date": [Finding.due_date.asc().nulls_last(), sev_order],
        "created_at": [Finding.created_at.desc()],
        "status": [Finding.status, sev_order],
    }
    order = orders[sort]
    rows = (
        db.scalars(stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size))
        .unique()
        .all()
    )
    return Page(items=[finding_out(f) for f in rows], total=total, page=page, page_size=page_size)


@router.get("/findings/{finding_id}", response_model=FindingOut)
def get_finding(finding_id: uuid.UUID, ctx: Ctx, db: DB) -> FindingOut:
    return finding_out(get_owned_or_404(db, Finding, finding_id, ctx.org_id))


@router.post("/findings/{finding_id}/decision", response_model=FindingOut)
def decide(finding_id: uuid.UUID, body: DecisionIn, ctx: Decider, db: DB) -> FindingOut:
    f = get_owned_or_404(db, Finding, finding_id, ctx.org_id)
    try:
        reviews.decide(db, f, body.decision, body.rationale, ctx.user)
    except reviews.ReviewError as exc:
        raise _bad(exc) from exc
    db.commit()
    db.refresh(f)
    return finding_out(f)


def _member(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> User:
    m = db.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )
    if m is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The owner must be a member of this organisation."
        )
    return m.user


@router.post("/findings/{finding_id}/assignment", response_model=FindingOut)
def assign(finding_id: uuid.UUID, body: AssignmentIn, ctx: Decider, db: DB) -> FindingOut:
    f = get_owned_or_404(db, Finding, finding_id, ctx.org_id)
    owner = _member(db, ctx.org_id, body.owner_id) if body.owner_id else None
    try:
        reviews.assign(db, f, owner, body.due_date, ctx.user)
    except reviews.ReviewError as exc:
        raise _bad(exc) from exc
    db.commit()
    db.refresh(f)
    return finding_out(f)


@router.post("/findings/bulk-assign", response_model=list[FindingOut])
def bulk_assign(body: BulkAssignIn, ctx: Decider, db: DB) -> list[FindingOut]:
    owner = _member(db, ctx.org_id, body.owner_id)
    found = (
        db.scalars(
            select(Finding).where(Finding.org_id == ctx.org_id, Finding.id.in_(body.finding_ids))
        )
        .unique()
        .all()
    )
    if len(found) != len(set(body.finding_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more findings were not found.")
    try:
        for f in found:
            reviews.assign(db, f, owner, body.due_date, ctx.user)
    except reviews.ReviewError as exc:
        db.rollback()
        raise _bad(exc) from exc
    db.commit()
    return [finding_out(f) for f in found]


@router.post("/findings/{finding_id}/remediation", response_model=FindingOut)
def remediation(finding_id: uuid.UUID, body: RemediationIn, ctx: Writer, db: DB) -> FindingOut:
    f = get_owned_or_404(db, Finding, finding_id, ctx.org_id)
    can_decide = ctx.role in DECIDE_ROLES
    if not can_decide and f.owner_id != ctx.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the assigned owner or a reviewer can update remediation.",
        )
    try:
        reviews.update_remediation(db, f, body.notes, body.status, ctx.user, can_decide)
    except reviews.ReviewError as exc:
        raise _bad(exc) from exc
    except PermissionError as exc:
        raise _bad(exc, status.HTTP_403_FORBIDDEN) from exc
    db.commit()
    db.refresh(f)
    return finding_out(f)


@router.post("/reviews/{review_id}/findings", status_code=201, response_model=FindingOut)
def manual_finding(review_id: uuid.UUID, body: ManualFindingIn, ctx: Writer, db: DB) -> FindingOut:
    review = get_owned_or_404(db, Review, review_id, ctx.org_id)
    if review.status == ReviewStatus.SIGNED_OFF:
        raise HTTPException(status.HTTP_409_CONFLICT, "Reopen the review to add findings.")
    if body.requirement_id:
        req = get_owned_or_404(db, Requirement, body.requirement_id, ctx.org_id)
        if req.checklist_version_id != review.checklist_version_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Requirement is not part of this review's checklist.",
            )
    evidence = []
    for bid in body.block_ids:
        b = get_owned_or_404(db, SourceBlock, bid, ctx.org_id)
        if (
            review.document_version_id is None
            or b.document_version_id != review.document_version_id
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Evidence must come from the reviewed document version.",
            )
        evidence.append(
            {
                "block_id": str(b.id),
                "ref": b.ref,
                "page_number": b.page_number,
                "paragraph_number": b.paragraph_number,
                "quote": b.text[:500],
                "context": b.text[:500],
                "highlight_start": 0,
                "highlight_end": min(len(b.text), 500),
            }
        )
    f = Finding(
        org_id=ctx.org_id,
        review_id=review.id,
        requirement_id=None,
        is_manual=True,
        title=body.title,
        description=body.description,
        severity=body.severity,
        evidence=evidence,
        status=FindingStatus.PROPOSED,
    )
    db.add(f)
    db.flush()
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="finding.manual_created",
        object_type="finding",
        object_id=f.id,
    )
    db.commit()
    db.refresh(f)
    return finding_out(f)


@router.get("/findings/{finding_id}/comments", response_model=list[CommentOut])
def list_comments(finding_id: uuid.UUID, ctx: Ctx, db: DB) -> list[CommentOut]:
    f = get_owned_or_404(db, Finding, finding_id, ctx.org_id)
    rows = db.scalars(
        select(Comment).where(Comment.finding_id == f.id).order_by(Comment.created_at)
    ).all()
    return [
        CommentOut(
            id=c.id,
            author_name=c.author.full_name if c.author else None,
            body=c.body,
            created_at=c.created_at,
        )
        for c in rows
    ]


@router.post("/findings/{finding_id}/comments", status_code=201, response_model=CommentOut)
def add_comment(finding_id: uuid.UUID, body: CommentIn, ctx: Writer, db: DB) -> CommentOut:
    f = get_owned_or_404(db, Finding, finding_id, ctx.org_id)
    c = Comment(org_id=ctx.org_id, finding_id=f.id, author_id=ctx.user.id, body=body.body)
    db.add(c)
    db.flush()
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="finding.commented",
        object_type="finding",
        object_id=f.id,
    )
    db.commit()
    return CommentOut(id=c.id, author_name=ctx.user.full_name, body=c.body, created_at=c.created_at)


# ---------------------------------------------------------------- reports


def _report_out(s: ReportSnapshot, review: Review) -> ReportOut:
    return ReportOut(
        id=s.id,
        review_id=review.id,
        review_title=review.title,
        version=s.version,
        signed_off_at=s.signed_off_at,
        signed_off_by_name=s.content.get("signed_off_by"),
        finding_count=len(s.content.get("findings", [])),
    )


@router.get("/reports", response_model=Page[ReportOut])
def list_reports(
    ctx: Ctx,
    db: DB,
    review_id: uuid.UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[ReportOut]:
    stmt = (
        select(ReportSnapshot, Review)
        .join(Review, Review.id == ReportSnapshot.review_id)
        .where(ReportSnapshot.org_id == ctx.org_id)
    )
    if review_id:
        stmt = stmt.where(ReportSnapshot.review_id == review_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        db.execute(
            stmt.order_by(ReportSnapshot.signed_off_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    return Page(
        items=[_report_out(s, r) for s, r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/reports/{report_id}/export")
def export_report(
    report_id: uuid.UUID,
    ctx: Ctx,
    db: DB,
    fmt: str = Query(alias="format", pattern="^(html|pdf|csv)$"),
) -> Response:
    snap = get_owned_or_404(db, ReportSnapshot, report_id, ctx.org_id)
    content = snap.content
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="report.exported",
        object_type="report",
        object_id=snap.id,
        meta={"format": fmt, "version": snap.version},
    )
    db.commit()
    stem = f"saqient-review-report-v{snap.version}"
    headers = {"Cache-Control": "private, no-store"}
    if fmt == "html":
        return Response(
            render_html(content),
            media_type="text/html; charset=utf-8",
            headers={
                **headers,
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            },
        )
    if fmt == "csv":
        headers["Content-Disposition"] = f'attachment; filename="{stem}.csv"'
        return Response(
            "﻿" + render_csv(content), media_type="text/csv; charset=utf-8", headers=headers
        )
    headers["Content-Disposition"] = f'attachment; filename="{stem}.pdf"'
    return Response(render_pdf(content), media_type="application/pdf", headers=headers)
