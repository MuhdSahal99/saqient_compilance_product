from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.extraction import ValidationError
from app.models import (
    Document,
    DocumentVersion,
    Job,
    JobKind,
    JobStatus,
    SourceBlock,
    VersionStatus,
)
from app.schemas import (
    DocumentDetailOut,
    DocumentOut,
    DocumentUpdateIn,
    DocumentVersionOut,
    JobOut,
    Page,
    SourceBlockOut,
)
from app.services import audit
from app.services.documents import DuplicateDocument, create_version, delete_document
from app.services.jobs import enqueue
from app.storage import StorageError, get_storage

router = APIRouter(tags=["documents"])


def _latest(doc: Document) -> DocumentVersion | None:
    return doc.versions[-1] if doc.versions else None


def _doc_out(doc: Document) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    latest = _latest(doc)
    out.latest_version = DocumentVersionOut.model_validate(latest) if latest else None
    out.version_count = len(doc.versions)
    out.created_by_name = doc.created_by.full_name if doc.created_by else None
    return out


def _latest_job(db: Session, version_id: uuid.UUID, org_id: uuid.UUID) -> Job | None:
    return db.scalar(
        select(Job)
        .where(Job.target_id == version_id, Job.org_id == org_id, Job.kind == JobKind.EXTRACT)
        .order_by(Job.created_at.desc())
        .limit(1)
    )


def _detail(db: Session, doc: Document) -> DocumentDetailOut:
    base = _doc_out(doc)
    latest = _latest(doc)
    job = _latest_job(db, latest.id, doc.org_id) if latest else None
    return DocumentDetailOut(
        **base.model_dump(),
        versions=[DocumentVersionOut.model_validate(v) for v in doc.versions],
        latest_job=JobOut.model_validate(job) if job else None,
    )


def _tags(raw: str) -> list[str]:
    tags = [t.strip()[:60] for t in raw.split(",") if t.strip()]
    if len(tags) > 20:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "At most 20 tags.")
    return tags


async def _read_limited(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file is larger than the {get_settings().max_upload_mb} MB limit.",
        )
    return data


def _duplicate_response(exc: DuplicateDocument) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": f"This file was already uploaded as “{exc.title}”.",
            "duplicate_document_id": str(exc.document_id),
        },
    )


@router.get("/documents", response_model=Page[DocumentOut])
def list_documents(
    ctx: Ctx,
    db: DB,
    q: str | None = Query(default=None, max_length=200),
    status_filter: VersionStatus | None = Query(default=None, alias="status"),
    document_type: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page[DocumentOut]:
    stmt = select(Document).where(Document.org_id == ctx.org_id, Document.deleted_at.is_(None))
    if q:
        like = f"%{q.replace('%', r'\%').replace('_', r'\_')}%"
        text_hit = exists().where(
            SourceBlock.org_id == ctx.org_id,
            SourceBlock.document_version_id == DocumentVersion.id,
            DocumentVersion.document_id == Document.id,
            SourceBlock.text.ilike(like),
        )
        stmt = stmt.where(
            or_(Document.title.ilike(like), Document.description.ilike(like), text_hit)
        )
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if status_filter:
        latest_no = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == Document.id)
            .scalar_subquery()
        )
        stmt = stmt.where(
            exists().where(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.version_number == latest_no,
                DocumentVersion.status == status_filter,
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    docs = (
        db.scalars(
            stmt.order_by(Document.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .unique()
        .all()
    )
    return Page(items=[_doc_out(d) for d in docs], total=total, page=page, page_size=page_size)


@router.post("/documents", status_code=201, response_model=DocumentDetailOut)
async def upload_document(
    ctx: Writer,
    db: DB,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    description: Annotated[str, Form(max_length=5000)] = "",
    document_type: Annotated[str, Form(min_length=1, max_length=80)] = "policy",
    tags: Annotated[str, Form(max_length=1300)] = "",
    allow_duplicate: Annotated[bool, Form()] = False,
) -> DocumentDetailOut | JSONResponse:
    data = await _read_limited(file)
    doc = Document(
        org_id=ctx.org_id,
        title=title.strip(),
        description=description.strip(),
        document_type=document_type.strip(),
        tags=_tags(tags),
        created_by_id=ctx.user.id,
    )
    db.add(doc)
    db.flush()
    try:
        _, job = create_version(
            db,
            org_id=ctx.org_id,
            user_id=ctx.user.id,
            document=doc,
            filename=file.filename or "upload",
            data=data,
            declared_mime=file.content_type or "",
            allow_duplicate=allow_duplicate,
        )
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DuplicateDocument as exc:
        db.rollback()
        return _duplicate_response(exc)
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="document.created",
        object_type="document",
        object_id=doc.id,
    )
    db.commit()
    enqueue(job)
    db.expire_all()  # the job may have run inline (eager mode)
    db.refresh(doc)
    return _detail(db, doc)


@router.get("/documents/{doc_id}", response_model=DocumentDetailOut)
def get_document(doc_id: uuid.UUID, ctx: Ctx, db: DB) -> DocumentDetailOut:
    doc = get_owned_or_404(db, Document, doc_id, ctx.org_id, deleted_at=None)
    return _detail(db, doc)


@router.patch("/documents/{doc_id}", response_model=DocumentDetailOut)
def update_document(
    doc_id: uuid.UUID, body: DocumentUpdateIn, ctx: Writer, db: DB
) -> DocumentDetailOut:
    doc = get_owned_or_404(db, Document, doc_id, ctx.org_id, deleted_at=None)
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(doc, key, value)
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="document.updated",
        object_type="document",
        object_id=doc.id,
        meta={"fields": sorted(changes)},
    )
    db.commit()
    return _detail(db, doc)


@router.post("/documents/{doc_id}/versions", status_code=201, response_model=DocumentDetailOut)
async def upload_version(
    doc_id: uuid.UUID,
    ctx: Writer,
    db: DB,
    file: Annotated[UploadFile, File()],
    allow_duplicate: Annotated[bool, Form()] = False,
) -> DocumentDetailOut | JSONResponse:
    doc = get_owned_or_404(db, Document, doc_id, ctx.org_id, deleted_at=None)
    data = await _read_limited(file)
    try:
        _, job = create_version(
            db,
            org_id=ctx.org_id,
            user_id=ctx.user.id,
            document=doc,
            filename=file.filename or "upload",
            data=data,
            declared_mime=file.content_type or "",
            allow_duplicate=allow_duplicate,
        )
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except DuplicateDocument as exc:
        db.rollback()
        return _duplicate_response(exc)
    db.commit()
    enqueue(job)
    db.expire_all()  # the job may have run inline (eager mode)
    db.refresh(doc)
    return _detail(db, doc)


@router.delete("/documents/{doc_id}", status_code=204)
def remove_document(doc_id: uuid.UUID, ctx: Decider, db: DB) -> None:
    doc = get_owned_or_404(db, Document, doc_id, ctx.org_id, deleted_at=None)
    try:
        delete_document(db, doc, ctx.user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()


@router.get("/document-versions/{version_id}/blocks", response_model=Page[SourceBlockOut])
def list_blocks(
    version_id: uuid.UUID,
    ctx: Ctx,
    db: DB,
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=500),
) -> Page[SourceBlockOut]:
    version = get_owned_or_404(db, DocumentVersion, version_id, ctx.org_id)
    stmt = select(SourceBlock).where(
        SourceBlock.document_version_id == version.id, SourceBlock.org_id == ctx.org_id
    )
    if q:
        stmt = stmt.where(SourceBlock.text.ilike(f"%{q.replace('%', r'\%')}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    blocks = db.scalars(
        stmt.order_by(SourceBlock.ordinal).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page(
        items=[SourceBlockOut.model_validate(b) for b in blocks],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/document-versions/{version_id}/download")
def download_version(version_id: uuid.UUID, ctx: Ctx, db: DB) -> Response:
    version = get_owned_or_404(db, DocumentVersion, version_id, ctx.org_id)
    doc = db.get(Document, version.document_id)
    if doc is None or doc.deleted_at is not None or not version.storage_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    try:
        data = get_storage().get(version.storage_key)
    except StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File is no longer available.") from exc
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="document.downloaded",
        object_type="document",
        object_id=doc.id,
        meta={"version": version.version_number},
    )
    db.commit()
    safe_name = "".join(c for c in version.original_filename if c.isalnum() or c in "._- ")
    return Response(
        content=data,
        media_type=version.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name or "document"}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/document-versions/{version_id}/retry", response_model=JobOut)
def retry_processing(version_id: uuid.UUID, ctx: Writer, db: DB) -> JobOut:
    version = get_owned_or_404(db, DocumentVersion, version_id, ctx.org_id)
    if version.status != VersionStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed processing can be retried.")
    version.status = VersionStatus.PENDING
    version.failure_message = None
    job = Job(
        org_id=ctx.org_id,
        kind=JobKind.EXTRACT,
        target_id=version.id,
        max_attempts=get_settings().job_max_attempts,
    )
    db.add(job)
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="document.retry",
        object_type="document",
        object_id=version.document_id,
    )
    db.commit()
    enqueue(job)
    db.expire_all()  # the job may have run inline (eager mode)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, ctx: Ctx, db: DB) -> JobOut:
    return JobOut.model_validate(get_owned_or_404(db, Job, job_id, ctx.org_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, ctx: Writer, db: DB) -> JobOut:
    job = get_owned_or_404(db, Job, job_id, ctx.org_id)
    if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only queued or running jobs can be cancelled."
        )
    job.cancel_requested = True
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="job.cancel_requested",
        object_type="job",
        object_id=job.id,
    )
    db.commit()
    return JobOut.model_validate(job)
