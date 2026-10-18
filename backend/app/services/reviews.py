from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.engine import CheckEvaluation, DocumentContext, evaluate
from app.engine.data_checks import (
    DataContext,
    FindingGroup,
    LoadedDataset,
    datasets_used,
    evaluate_data,
)
from app.engine.tax_checks import EntityInfo
from app.engine.versions import ENGINE_VERSION, is_data_check, parse_check
from app.models import (
    ChecklistState,
    ChecklistVersion,
    CheckOutcome,
    CheckResult,
    DatasetKind,
    DatasetStatus,
    DatasetVersion,
    Document,
    DocumentVersion,
    EInvoiceFile,
    Finding,
    FindingStatus,
    Job,
    JobKind,
    JobStatus,
    LegalEntity,
    ReportSnapshot,
    Requirement,
    Review,
    ReviewDataset,
    ReviewEInvoice,
    ReviewRun,
    ReviewStatus,
    RulePackVersion,
    SourceBlock,
    TaxPeriod,
    User,
    VersionStatus,
)
from app.services import audit, einvoice_inputs, rule_packs, tax_setup
from app.services.datasets import DatasetNotReady, load_frame
from app.services.jobs import Checkpoint, PermanentJobError, handler, on_unsuccessful

logger = logging.getLogger("saqient.reviews")

DISCLAIMER = (
    "This report records a human-reviewed document review supported by deterministic text "
    "checks. It is not legal advice and does not certify legal or regulatory compliance. A text "
    "match is not proof of compliance, and the absence of a match is not automatically a "
    "violation. Findings reflect reviewer decisions on the document and checklist versions "
    "listed."
)

AI_DISABLED_LIMITATION = "AI analysis was disabled for this review."
AI_USED_LIMITATION = (
    "Some findings started as AI suggestions. A reviewer accepted each one; the model, "
    "provider and version are recorded per finding. AI output can be wrong and quotes were "
    "checked only for matching stored text, not for meaning."
)
AI_MOCK_LIMITATION = (
    "Some findings came from the mock AI provider used for testing. They are placeholders, "
    "not analysis."
)

DATA_LIMITATION = (
    "Data checks test the uploaded dataset versions as mapped by a user; they do not verify "
    "that the data is complete or matches the accounting system. An exception is something "
    "to look at, not a conclusion."
)

OCR_LIMITATION = (
    "Some pages had no text layer and were read with OCR. OCR text can contain recognition "
    "errors, and quotes from those pages were matched against the OCR text, not the page image."
)

LIMITATIONS = [
    "Deterministic checks match text only; they do not interpret meaning or context.",
    "Content in images or scanned pages was not reviewed; no OCR was used for this document.",
    "Checklist content is only as accurate as its sources; see each requirement's source "
    "and verification status.",
]


class ReviewError(Exception):
    """Business-rule violation; message is safe to show users."""


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- create & run


def create_review(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    document_version: DocumentVersion | None,
    checklist_version: ChecklistVersion,
    dataset_versions: list[DatasetVersion] | None = None,
    rule_pack_version: RulePackVersion | None = None,
    as_of_date: date | None = None,
    entity: LegalEntity | None = None,
    tax_period: TaxPeriod | None = None,
    einvoice_files: list[EInvoiceFile] | None = None,
) -> tuple[Review, Job]:
    dataset_versions = dataset_versions or []
    einvoice_files = einvoice_files or []
    if tax_period is not None:
        if entity is None:
            entity = tax_period.entity
        elif tax_period.entity_id != entity.id:
            raise ReviewError("The tax period belongs to a different entity.")
    if entity is None and einvoice_files:
        entity = db.get(LegalEntity, einvoice_files[0].entity_id)
    if entity is not None and any(v.dataset.entity_id != entity.id for v in dataset_versions):
        raise ReviewError("Every dataset must belong to the entity under review.")
    if entity is not None and any(f.entity_id != entity.id for f in einvoice_files):
        raise ReviewError("Every e-invoice must belong to the entity under review.")
    if document_version is None and not dataset_versions and not einvoice_files and not entity:
        raise ReviewError("Choose a document, datasets, e-invoices or an entity.")
    if document_version is not None and document_version.status != VersionStatus.READY:
        raise ReviewError("The document has not finished processing.")
    if checklist_version.state != ChecklistState.PUBLISHED:
        raise ReviewError("Only published checklist versions can be used for a review.")
    if rule_pack_version is not None and rule_pack_version.state != ChecklistState.PUBLISHED:
        raise ReviewError("Only published rule pack versions can be used for a review.")
    kinds = [v.dataset.kind for v in dataset_versions]
    if len(kinds) != len(set(kinds)):
        raise ReviewError("Use one dataset version per dataset kind.")
    if any(v.status != DatasetStatus.READY for v in dataset_versions):
        raise ReviewError("Every dataset version must be ready (mapping confirmed and built).")
    doc = db.get(Document, document_version.document_id) if document_version else None
    review = Review(
        org_id=org_id,
        title=title,
        document_version_id=document_version.id if document_version else None,
        checklist_version_id=checklist_version.id,
        rule_pack_version_id=rule_pack_version.id if rule_pack_version else None,
        as_of_date=as_of_date,
        entity_id=entity.id if entity else None,
        tax_period_id=tax_period.id if tax_period else None,
        status=ReviewStatus.DRAFT,
        is_demo=bool(doc and doc.is_demo) or any(v.dataset.is_demo for v in dataset_versions),
        created_by_id=user_id,
    )
    db.add(review)
    db.flush()
    for v in dataset_versions:
        db.add(
            ReviewDataset(
                org_id=org_id, review_id=review.id, kind=v.dataset.kind, dataset_version_id=v.id
            )
        )
    for f in {f.id: f for f in einvoice_files}.values():
        db.add(ReviewEInvoice(org_id=org_id, review_id=review.id, file_id=f.id))
    db.flush()
    audit.record(
        db,
        org_id=org_id,
        actor_id=user_id,
        action="review.created",
        object_type="review",
        object_id=review.id,
        meta={
            "checklist_version": checklist_version.version_number,
            "document_version": document_version.version_number if document_version else None,
            "dataset_version_ids": [str(v.id) for v in dataset_versions],
            "rule_pack_version": rule_pack_version.version_number if rule_pack_version else None,
            "entity_id": str(entity.id) if entity else None,
            "tax_period_id": str(tax_period.id) if tax_period else None,
            "einvoice_files": len(einvoice_files),
        },
    )
    job = start_run(db, review, user_id)
    return review, job


def start_run(db: Session, review: Review, user_id: uuid.UUID | None) -> Job:
    if review.status == ReviewStatus.SIGNED_OFF:
        raise ReviewError("Reopen the review before running checks again.")
    active = db.scalar(
        select(Job)
        .join(ReviewRun, ReviewRun.job_id == Job.id)
        .where(
            ReviewRun.review_id == review.id,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    )
    if active is not None:
        raise ReviewError("A check run is already in progress for this review.")
    job = Job(
        org_id=review.org_id,
        kind=JobKind.REVIEW_RUN,
        target_id=uuid.uuid4(),
        max_attempts=get_settings().job_max_attempts,
    )
    db.add(job)
    db.flush()
    run = ReviewRun(
        org_id=review.org_id,
        review_id=review.id,
        job_id=job.id,
        document_version_id=review.document_version_id,
        checklist_version_id=review.checklist_version_id,
        engine_version=ENGINE_VERSION,
        engine_mode="deterministic (AI disabled)",
    )
    db.add(run)
    db.flush()
    job.target_id = run.id
    review.status = ReviewStatus.RUNNING
    audit.record(
        db,
        org_id=review.org_id,
        actor_id=user_id,
        action="review.run_started",
        object_type="review",
        object_id=review.id,
        meta={"run_id": str(run.id)},
    )
    return job


def _attention_title(req: Requirement, ev: CheckEvaluation) -> str:
    prefix = {
        CheckOutcome.NO_MATCH_FOUND: "Expected content not found",
        CheckOutcome.MATCH_FOUND: "Flagged content found",
        CheckOutcome.NEEDS_HUMAN_REVIEW: "Needs human review",
        CheckOutcome.PROCESSING_ERROR: "Check could not be completed",
        CheckOutcome.EXCEPTIONS_FOUND: "Data exceptions found",
        CheckOutcome.NOT_APPLICABLE: "Check could not run",
    }.get(ev.outcome, "Review")
    return f"{prefix}: {req.title}"[:300]


def result_hash(ev: CheckEvaluation, meta: dict[str, Any]) -> str:
    """SHA-256 over the canonical result. Same inputs and engine version, same hash."""
    body = {
        "outcome": ev.outcome.value,
        "needs_attention": ev.needs_attention,
        "message": ev.message,
        "evidence": ev.evidence,
        "meta": meta,
    }
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _data_context(
    db: Session, review: Review, org_id: uuid.UUID
) -> tuple[DataContext, dict[str, Any]]:
    """Load the review's dataset versions and build the rule resolver and as-of date."""
    loaded: dict[DatasetKind, LoadedDataset] = {}
    described: list[dict[str, Any]] = []
    for link in review.datasets:
        try:
            v, frame = load_frame(db, link.dataset_version_id, org_id)
        except DatasetNotReady as exc:
            raise PermanentJobError(str(exc)) from exc
        ds = v.dataset
        loaded[link.kind] = LoadedDataset(
            version_id=str(v.id),
            version_number=v.version_number,
            kind=link.kind,
            frame=frame,
            period_start=ds.period_start,
            period_end=ds.period_end,
        )
        described.append(
            {
                "kind": link.kind.value,
                "dataset_id": str(ds.id),
                "dataset_name": ds.name,
                "dataset_version_id": str(v.id),
                "version_number": v.version_number,
                "parquet_sha256": v.parquet_sha256,
                "raw_sha256": v.raw_sha256,
                "row_count": v.row_count,
                "period_start": ds.period_start.isoformat() if ds.period_start else None,
                "period_end": ds.period_end.isoformat() if ds.period_end else None,
            }
        )
    ends = [d.period_end for d in loaded.values() if d.period_end]
    if review.as_of_date:
        as_of, source = review.as_of_date, "review"
    elif ends:
        as_of, source = max(ends), "dataset_period_end"
    else:
        as_of, source = date.today(), "run_date"
    pack_id = review.rule_pack_version_id

    def resolve_rule(key: str) -> rule_packs.ResolvedRule:
        if pack_id is None:
            raise rule_packs.RuleNotFound(
                f"This check needs rule '{key}', but the review has no rule pack."
            )
        return rule_packs.resolve(db, org_id, pack_id, key, as_of)

    def resolve_file(key: str) -> rule_packs.ResolvedFile:
        if pack_id is None:
            raise rule_packs.RuleNotFound(
                f"This check needs rule pack file '{key}', but the review has no rule pack."
            )
        return rule_packs.resolve_file(db, org_id, pack_id, key)

    period = (
        (review.tax_period.period_start, review.tax_period.period_end)
        if review.tax_period
        else None
    )
    entity = _entity_info(db, review, org_id)
    inputs: dict[str, Any] = {
        "datasets": described,
        "rule_pack_version_id": str(pack_id) if pack_id else None,
        "as_of_date": as_of.isoformat(),
        "as_of_source": source,
        "tax_period": [period[0].isoformat(), period[1].isoformat()] if period else None,
        "entity": entity.snapshot() if entity else None,
    }
    ctx = DataContext(
        datasets=loaded,
        resolve_rule=resolve_rule,
        as_of=as_of,
        period=period,
        entity=entity,
        resolve_file=resolve_file,
    )
    einvoice_inputs.attach(db, review, org_id, ctx, inputs)
    return ctx, inputs


def _entity_info(db: Session, review: Review, org_id: uuid.UUID) -> EntityInfo | None:
    e = review.entity
    if e is None:
        return None
    if e.org_id != org_id:
        raise PermanentJobError("The review's entity is not available.")
    codes, accounts = tax_setup.vat_setup(db, org_id, e.id)
    by_role: dict[str, list[str]] = {}
    for a in accounts:
        by_role.setdefault(a.role.value, []).append(a.account_code)
    return EntityInfo(
        id=str(e.id),
        name=e.name,
        country=e.country,
        size_basis_amount=e.size_basis_amount,
        size_basis_currency=e.size_basis_currency,
        size_basis_year=e.size_basis_year,
        go_live_override=e.einvoice_go_live_override,
        go_live_note=e.einvoice_go_live_note or "",
        tax_codes={
            (c.register.value, c.tax_code): (c.treatment.value, c.recoverable) for c in codes
        },
        tax_accounts={k: tuple(sorted(v)) for k, v in by_role.items()},
    )


@handler(JobKind.REVIEW_RUN)
def execute_run(db: Session, job: Job, checkpoint: Checkpoint) -> None:
    run = db.scalar(
        select(ReviewRun).where(ReviewRun.id == job.target_id, ReviewRun.org_id == job.org_id)
    )
    if run is None:
        raise PermanentJobError("The review run no longer exists.")
    review = run.review
    version: DocumentVersion | None = None
    doc_ctx: DocumentContext | None = None
    if run.document_version_id is not None:
        version = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == run.document_version_id,
                DocumentVersion.org_id == job.org_id,
            )
        )
        if version is None or version.status != VersionStatus.READY:
            raise PermanentJobError("The document version is not available for review.")
        document = db.get(Document, version.document_id)
        assert document is not None and document.org_id == job.org_id
        blocks = list(
            db.scalars(
                select(SourceBlock)
                .where(SourceBlock.document_version_id == version.id)
                .order_by(SourceBlock.ordinal)
            )
        )
        doc_ctx = DocumentContext(
            title=document.title,
            description=document.description,
            document_type=document.document_type,
            tags=list(document.tags or []),
            blocks=blocks,
        )
    requirements = list(
        db.scalars(
            select(Requirement)
            .where(
                Requirement.checklist_version_id == run.checklist_version_id,
                Requirement.org_id == job.org_id,
            )
            .order_by(Requirement.ordinal)
        )
    )
    data_ctx, inputs = _data_context(db, review, job.org_id)
    inputs["document_version_id"] = str(version.id) if version else None
    inputs["document_sha256"] = version.sha256 if version else None
    started = _now()
    warnings: list[str] = list(version.extraction_warnings or []) if version else []
    evaluations: list[tuple[Requirement, CheckEvaluation, dict[str, Any], list[FindingGroup]]] = []
    snapshot: list[dict[str, Any]] = []
    total = max(1, len(requirements))
    for i, req in enumerate(requirements):
        checkpoint(int(100 * i / total))  # raises JobCancelled if requested
        snapshot.append(
            {"requirement_id": str(req.id), "code": req.code, "check_config": req.check_config}
        )
        meta: dict[str, Any] = {}
        groups: list[FindingGroup] = []
        try:
            config = parse_check(req.check_config, run.engine_version)
        except (PydanticValidationError, ValueError) as exc:
            logger.warning(
                "invalid check config",
                extra={"requirement_id": str(req.id), "error_class": type(exc).__name__},
            )
            ev = CheckEvaluation(
                CheckOutcome.PROCESSING_ERROR,
                True,
                "The check configuration is invalid; review manually.",
            )
            warnings.append(f"{req.code}: check configuration invalid.")
        else:
            if is_data_check(config):
                missing = sorted(
                    k.value for k in datasets_used(config) if k not in data_ctx.datasets
                )
                if missing:
                    ev = CheckEvaluation(
                        CheckOutcome.NOT_APPLICABLE,
                        False,
                        f"Not run: this review has no {', '.join(missing)} dataset.",
                    )
                else:
                    dev = evaluate_data(config, data_ctx)
                    ev = CheckEvaluation(
                        dev.outcome, dev.needs_attention, dev.message, dev.evidence
                    )
                    meta = dev.meta
                    groups = dev.groups
                    for w in dev.meta.get("warnings", []):
                        if f"{req.code}: {w}" not in warnings:
                            warnings.append(f"{req.code}: {w}")
            elif doc_ctx is None:
                ev = CheckEvaluation(
                    CheckOutcome.NOT_APPLICABLE, False, "Not run: this review has no document."
                )
            else:
                ev = evaluate(config, doc_ctx)
        evaluations.append((req, ev, meta, groups))
    checkpoint(95)

    # Write everything in one transaction. Unique constraints back this up.
    existing_results = set(
        db.scalars(select(CheckResult.requirement_id).where(CheckResult.run_id == run.id))
    )
    existing_findings = set(
        db.execute(
            select(Finding.requirement_id, Finding.finding_key).where(
                Finding.review_id == review.id, Finding.requirement_id.is_not(None)
            )
        ).tuples()
    )
    for req, ev, meta, groups in evaluations:
        if req.id in existing_results:
            continue
        result = CheckResult(
            org_id=job.org_id,
            run_id=run.id,
            requirement_id=req.id,
            outcome=ev.outcome,
            needs_attention=ev.needs_attention,
            message=ev.message,
            evidence=ev.evidence,
            meta=meta,
            result_hash=result_hash(ev, meta),
        )
        db.add(result)
        db.flush()
        if not ev.needs_attention:
            continue
        # A check may raise one finding per group (e.g. per failed invoice rule).
        planned = (
            [(g.key, f"{g.title}: {req.title}"[:300], g.message, g.evidence) for g in groups]
            if groups
            else [("", _attention_title(req, ev), ev.message, ev.evidence)]
        )
        for key, title, message, evidence in planned:
            if (req.id, key) in existing_findings:
                continue
            db.add(
                Finding(
                    org_id=job.org_id,
                    review_id=review.id,
                    requirement_id=req.id,
                    finding_key=key[:200],
                    check_result_id=result.id,
                    title=title,
                    description=f"{message} {req.description}".strip()[:5000],
                    severity=req.severity,
                    automated_outcome=ev.outcome,
                    evidence=evidence,
                    status=FindingStatus.PROPOSED,
                )
            )
    run.config_snapshot = snapshot
    run.inputs_snapshot = inputs
    run.warnings = warnings
    run.started_at = started
    run.finished_at = _now()
    review.status = ReviewStatus.IN_REVIEW
    db.commit()


@on_unsuccessful(JobKind.REVIEW_RUN)
def _run_unsuccessful(db: Session, job: Job) -> None:
    run = db.get(ReviewRun, job.target_id)
    if run is not None and run.org_id == job.org_id and run.review.status == ReviewStatus.RUNNING:
        has_findings = db.scalar(
            select(func.count(Finding.id)).where(Finding.review_id == run.review_id)
        )
        run.review.status = ReviewStatus.IN_REVIEW if has_findings else ReviewStatus.DRAFT


# ---------------------------------------------------------------- findings workflow

DECIDABLE = {
    FindingStatus.PROPOSED,
    FindingStatus.IN_REVIEW,
    FindingStatus.CONFIRMED,
    FindingStatus.DISMISSED,
    FindingStatus.ACCEPTED_RISK,
}
OPEN_FOR_DECISION = {FindingStatus.PROPOSED, FindingStatus.IN_REVIEW}


def _ensure_not_signed_off(review: Review) -> None:
    if review.status == ReviewStatus.SIGNED_OFF:
        raise ReviewError("This review is signed off. Reopen it with a reason to change decisions.")


def decide(db: Session, finding: Finding, decision: str, rationale: str, actor: User) -> None:
    _ensure_not_signed_off(finding.review)
    if finding.status not in DECIDABLE:
        raise ReviewError("This finding is in remediation; its decision can't be changed now.")
    target = FindingStatus(decision)
    rationale = rationale.strip()
    if target in (FindingStatus.DISMISSED, FindingStatus.ACCEPTED_RISK) and len(rationale) < 5:
        raise ReviewError("A rationale is required to dismiss a finding or accept the risk.")
    previous = finding.status
    finding.status = target
    finding.decision_rationale = rationale
    finding.decided_by_id = actor.id
    finding.decided_at = _now()
    audit.record(
        db,
        org_id=finding.org_id,
        actor_id=actor.id,
        action="finding.decided",
        object_type="finding",
        object_id=finding.id,
        meta={"from": previous.value, "to": target.value},
    )


def assign(
    db: Session, finding: Finding, owner: User | None, due: date | None, actor: User
) -> None:
    if finding.status in OPEN_FOR_DECISION | {FindingStatus.DISMISSED}:
        raise ReviewError("Confirm the finding before assigning remediation.")
    finding.owner_id = owner.id if owner else None
    finding.due_date = due
    if owner is not None and finding.status == FindingStatus.CONFIRMED:
        finding.status = FindingStatus.REMEDIATION_IN_PROGRESS
    audit.record(
        db,
        org_id=finding.org_id,
        actor_id=actor.id,
        action="finding.assigned",
        object_type="finding",
        object_id=finding.id,
        meta={
            "owner_id": str(owner.id) if owner else None,
            "due_date": due.isoformat() if due else None,
        },
    )


REMEDIATION_TRANSITIONS: dict[FindingStatus, set[FindingStatus]] = {
    FindingStatus.REMEDIATION_IN_PROGRESS: {FindingStatus.READY_FOR_REREVIEW},
    FindingStatus.READY_FOR_REREVIEW: {
        FindingStatus.RESOLVED,
        FindingStatus.REMEDIATION_IN_PROGRESS,
    },
}


def update_remediation(
    db: Session, finding: Finding, notes: str, status: str | None, actor: User, can_decide: bool
) -> None:
    if finding.status not in REMEDIATION_TRANSITIONS and status is not None:
        raise ReviewError("This finding is not in remediation.")
    if status is not None:
        target = FindingStatus(status)
        if target != finding.status:
            if target not in REMEDIATION_TRANSITIONS.get(finding.status, set()):
                raise ReviewError(f"Cannot move from {finding.status.value} to {target.value}.")
            if target == FindingStatus.RESOLVED and not can_decide:
                raise PermissionError("Only reviewers can resolve findings.")
            if finding.status == FindingStatus.READY_FOR_REREVIEW and not can_decide:
                raise PermissionError("Only reviewers can re-review remediation.")
            audit.record(
                db,
                org_id=finding.org_id,
                actor_id=actor.id,
                action="finding.remediation_status",
                object_type="finding",
                object_id=finding.id,
                meta={"from": finding.status.value, "to": target.value},
            )
            finding.status = target
    finding.remediation_notes = notes


# ---------------------------------------------------------------- sign-off


def _user_name(db: Session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    u = db.get(User, user_id)
    return u.full_name if u else None


def _rule_pack_scope(db: Session, review: Review) -> dict[str, Any] | None:
    if review.rule_pack_version_id is None:
        return None
    v = db.get(RulePackVersion, review.rule_pack_version_id)
    if v is None:
        return None
    return {
        "name": v.rule_pack.name,
        "jurisdiction": v.rule_pack.jurisdiction,
        "version": v.version_number,
        "is_synthetic": v.rule_pack.is_synthetic,
    }


def _report_evidence(e: dict[str, Any]) -> dict[str, Any]:
    if e.get("type") == "dataset_rows":
        return {
            "type": "dataset_rows",
            "dataset_kind": e.get("dataset_kind"),
            "version_number": e.get("version_number"),
            "label": e.get("label"),
            "row_ids": e.get("row_ids", []),
            "row_count": e.get("row_count"),
            "columns": e.get("columns", []),
            "rows": e.get("rows", [])[:20],
            "detail": e.get("detail", {}),
        }
    return {
        "ref": e.get("ref"),
        "page_number": e.get("page_number"),
        "paragraph_number": e.get("paragraph_number"),
        "quote": e.get("quote"),
    }


def build_snapshot(
    db: Session, review: Review, signer: User, signed_at: datetime, version: int
) -> dict[str, Any]:
    dv = review.document_version
    cv = review.checklist_version
    doc = db.get(Document, dv.document_id) if dv else None
    run = db.scalar(
        select(ReviewRun)
        .where(ReviewRun.review_id == review.id)
        .order_by(ReviewRun.created_at.desc())
        .limit(1)
    )
    findings = list(
        db.scalars(
            select(Finding).where(Finding.review_id == review.id).order_by(Finding.created_at)
        )
    )
    results = (
        list(db.scalars(select(CheckResult).where(CheckResult.run_id == run.id))) if run else []
    )
    req_count = (
        db.scalar(
            select(func.count(Requirement.id)).where(Requirement.checklist_version_id == cv.id)
        )
        or 0
    )
    from app.models import Organization

    ai_findings = [f for f in findings if f.ai_suggestion is not None]
    limitations = list(LIMITATIONS)
    if dv is not None and db.scalar(
        select(SourceBlock.id)
        .where(SourceBlock.document_version_id == dv.id, SourceBlock.is_ocr.is_(True))
        .limit(1)
    ):
        limitations[1] = OCR_LIMITATION
    if review.datasets:
        limitations.insert(1, DATA_LIMITATION)
    if not ai_findings:
        limitations.insert(2, AI_DISABLED_LIMITATION)
    else:
        limitations.insert(2, AI_USED_LIMITATION)
        if any(f.ai_suggestion and f.ai_suggestion.run.provider == "mock" for f in ai_findings):
            limitations.insert(3, AI_MOCK_LIMITATION)

    org = db.get(Organization, review.org_id)
    return {
        "report_version": version,
        "organization": org.name if org else "",
        "organization_is_demo": bool(org and org.is_demo),
        "review": {"id": str(review.id), "title": review.title, "is_demo": review.is_demo},
        "scope": {
            "document_title": doc.title if doc else None,
            "document_type": doc.document_type if doc else None,
            "document_version": dv.version_number if dv else None,
            "original_filename": dv.original_filename if dv else None,
            "file_format": dv.file_format if dv else None,
            "sha256": dv.sha256 if dv else None,
            "page_count": dv.page_count if dv else None,
            "datasets": list((run.inputs_snapshot or {}).get("datasets", [])) if run else [],
            "rule_pack": _rule_pack_scope(db, review),
            "as_of_date": (run.inputs_snapshot or {}).get("as_of_date") if run else None,
            "checklist_name": cv.checklist.name,
            "checklist_kind": cv.checklist.kind.value,
            "checklist_version": cv.version_number,
            "checklist_disclaimer": cv.disclaimer,
            "requirement_count": req_count,
        },
        "engine": {
            "version": run.engine_version if run else None,
            "mode": run.engine_mode if run else "none",
            "run_started_at": run.started_at.isoformat() if run and run.started_at else None,
            "run_finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
            "ai_enabled": bool(ai_findings),
        },
        "extraction_warnings": list(dv.extraction_warnings or []) if dv else [],
        "run_warnings": list(run.warnings or []) if run else [],
        "check_results": [
            {
                "code": r.requirement.code,
                "title": r.requirement.title,
                "outcome": r.outcome.value,
                "message": r.message,
            }
            for r in sorted(results, key=lambda r: r.requirement.ordinal)
        ],
        "findings": [
            {
                "id": str(f.id),
                "requirement_code": f.requirement.code
                if f.requirement
                else (f.ai_suggestion.requirement.code if f.ai_suggestion else None),
                "source_reference": f.requirement.source_reference if f.requirement else None,
                "title": f.title,
                "description": f.description,
                "severity": f.severity.value,
                "automated_outcome": f.automated_outcome.value if f.automated_outcome else None,
                "status": f.status.value,
                "decision_rationale": f.decision_rationale,
                "decided_by": _user_name(db, f.decided_by_id),
                "decided_at": f.decided_at.isoformat() if f.decided_at else None,
                "owner": _user_name(db, f.owner_id),
                "due_date": f.due_date.isoformat() if f.due_date else None,
                "remediation_notes": f.remediation_notes,
                "is_manual": f.is_manual,
                "ai_suggestion": {
                    "provider": f.ai_suggestion.run.provider,
                    "model": f.ai_suggestion.run.model,
                    "prompt_version": f.ai_suggestion.run.prompt_version,
                }
                if f.ai_suggestion
                else None,
                "evidence": [_report_evidence(e) for e in f.evidence],
            }
            for f in findings
        ],
        "signed_off_by": signer.full_name,
        "signed_off_at": signed_at.isoformat(),
        "limitations": limitations,
        "disclaimer": DISCLAIMER,
    }


def sign_off(db: Session, review: Review, signer: User) -> ReportSnapshot:
    if review.status == ReviewStatus.SIGNED_OFF:
        raise ReviewError("This review is already signed off.")
    if review.status != ReviewStatus.IN_REVIEW:
        raise ReviewError("Checks must finish before sign-off.")
    undecided = db.scalar(
        select(func.count(Finding.id)).where(
            Finding.review_id == review.id, Finding.status.in_(list(OPEN_FOR_DECISION))
        )
    )
    if undecided:
        raise ReviewError(f"{undecided} finding(s) still need a reviewer decision.")
    version = (
        db.scalar(
            select(func.max(ReportSnapshot.version)).where(ReportSnapshot.review_id == review.id)
        )
        or 0
    ) + 1
    signed_at = _now()
    snap = ReportSnapshot(
        org_id=review.org_id,
        review_id=review.id,
        version=version,
        content=build_snapshot(db, review, signer, signed_at, version),
        signed_off_by_id=signer.id,
        signed_off_at=signed_at,
    )
    db.add(snap)
    review.status = ReviewStatus.SIGNED_OFF
    review.signed_off_by_id = signer.id
    review.signed_off_at = signed_at
    db.flush()
    audit.record(
        db,
        org_id=review.org_id,
        actor_id=signer.id,
        action="review.signed_off",
        object_type="review",
        object_id=review.id,
        meta={"report_version": version, "report_id": str(snap.id)},
    )
    return snap


def reopen(db: Session, review: Review, reason: str, actor: User) -> None:
    if review.status != ReviewStatus.SIGNED_OFF:
        raise ReviewError("Only signed-off reviews can be reopened.")
    review.status = ReviewStatus.IN_REVIEW
    review.signed_off_at = None
    review.signed_off_by_id = None
    audit.record(
        db,
        org_id=review.org_id,
        actor_id=actor.id,
        action="review.reopened",
        object_type="review",
        object_id=review.id,
        meta={"reason": reason[:2000]},
    )
