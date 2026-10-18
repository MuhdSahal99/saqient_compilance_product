from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import malware
from app.config import get_settings
from app.extraction import (
    ExtractionError,
    OcrOptions,
    ValidationError,
    detect_format,
    extract,
)
from app.extraction.ocr import get_ocr
from app.models import (
    Document,
    DocumentVersion,
    Job,
    JobKind,
    Review,
    SourceBlock,
    VersionStatus,
)
from app.services import audit
from app.services.jobs import Checkpoint, PermanentJobError, handler, on_unsuccessful
from app.storage import get_storage, new_storage_key

logger = logging.getLogger("saqient.documents")

MIME_BY_FORMAT = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
}


class DuplicateDocument(Exception):
    def __init__(self, document_id: uuid.UUID, title: str) -> None:
        self.document_id = document_id
        self.title = title


def _safe_filename(name: str) -> str:
    # Metadata only; strip any path components and control characters.
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable())[:255]
    return base or "upload"


def find_duplicate(db: Session, org_id: uuid.UUID, sha256: str) -> Document | None:
    return db.scalar(
        select(Document)
        .join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(
            Document.org_id == org_id,
            Document.deleted_at.is_(None),
            DocumentVersion.sha256 == sha256,
        )
        .limit(1)
    )


def create_version(
    db: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    document: Document,
    filename: str,
    declared_mime: str,
    data: bytes,
    allow_duplicate: bool,
) -> tuple[DocumentVersion, Job]:
    settings = get_settings()
    if len(data) > settings.max_upload_bytes:
        raise ValidationError(f"The file is larger than the {settings.max_upload_mb} MB limit.")
    file_format = detect_format(filename, declared_mime, data)
    malware.ensure_clean(data)  # before anything is stored
    sha256 = hashlib.sha256(data).hexdigest()
    if not allow_duplicate:
        dup = find_duplicate(db, org_id, sha256)
        if dup is not None:
            raise DuplicateDocument(dup.id, dup.title)

    key = new_storage_key(org_id)
    get_storage().put(key, data)
    next_no = (
        db.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document.id
            )
        )
        or 0
    ) + 1
    version = DocumentVersion(
        org_id=org_id,
        document_id=document.id,
        version_number=next_no,
        original_filename=_safe_filename(filename),
        file_format=file_format,
        mime_type=MIME_BY_FORMAT[file_format],
        size_bytes=len(data),
        sha256=sha256,
        storage_key=key,
        status=VersionStatus.PENDING,
        uploaded_by_id=user_id,
    )
    db.add(version)
    db.flush()
    job = Job(
        org_id=org_id,
        kind=JobKind.EXTRACT,
        target_id=version.id,
        max_attempts=settings.job_max_attempts,
    )
    db.add(job)
    audit.record(
        db,
        org_id=org_id,
        actor_id=user_id,
        action="document.version_uploaded",
        object_type="document",
        object_id=document.id,
        meta={"version": next_no, "format": file_format, "size_bytes": len(data)},
    )
    return version, job


@handler(JobKind.EXTRACT)
def process_version(db: Session, job: Job, checkpoint: Checkpoint) -> None:
    settings = get_settings()
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == job.target_id, DocumentVersion.org_id == job.org_id
        )
    )
    if version is None or version.storage_key is None:
        raise PermanentJobError("The document version no longer exists.")
    version.status = VersionStatus.PROCESSING
    db.commit()
    checkpoint(10)

    data = get_storage().get(version.storage_key)
    engine = get_ocr(settings)
    ocr = OcrOptions(engine, settings.ocr_dpi, settings.ocr_max_pages) if engine else None
    try:
        result = extract(
            version.file_format, data, settings.max_pdf_pages, settings.max_extracted_chars, ocr
        )
    except ExtractionError as exc:
        raise PermanentJobError(str(exc)) from exc
    checkpoint(70)

    # Idempotent: replace any blocks from an earlier partial attempt in one transaction.
    db.execute(delete(SourceBlock).where(SourceBlock.document_version_id == version.id))
    db.add_all(
        SourceBlock(
            org_id=version.org_id,
            document_version_id=version.id,
            ordinal=i,
            ref=b.ref,
            page_number=b.page_number,
            paragraph_number=b.paragraph_number,
            section_heading=b.section_heading,
            text=b.text,
            is_ocr=b.is_ocr,
            ocr_confidence=b.ocr_confidence,
        )
        for i, b in enumerate(result.blocks)
    )
    version.status = VersionStatus.READY
    version.page_count = result.page_count
    version.block_count = len(result.blocks)
    version.extraction_warnings = result.warnings
    version.failure_message = None
    version.processed_at = datetime.now(UTC)
    db.commit()
    logger.info(
        "document version extracted",
        extra={"version_id": str(version.id), "blocks": len(result.blocks)},
    )


@on_unsuccessful(JobKind.EXTRACT)
def _mark_version_failed(db: Session, job: Job) -> None:
    version = db.get(DocumentVersion, job.target_id)
    if version is not None and version.org_id == job.org_id:
        version.status = VersionStatus.FAILED
        version.failure_message = job.error or "Processing was cancelled."


def delete_document(db: Session, document: Document, actor_id: uuid.UUID) -> None:
    """Delete stored files and extracted text; keep a metadata tombstone for the audit trail.

    Documents used by a review cannot be deleted, so review evidence stays intact.
    """
    version_ids = [v.id for v in document.versions]
    in_use = (
        db.scalar(select(func.count(Review.id)).where(Review.document_version_id.in_(version_ids)))
        if version_ids
        else 0
    )
    if in_use:
        raise ValueError(
            f"This document is used by {in_use} review(s). Delete or archive those reviews first."
        )
    storage = get_storage()
    for v in document.versions:
        if v.storage_key:
            storage.delete(v.storage_key)
            v.storage_key = None
    if version_ids:
        db.execute(delete(SourceBlock).where(SourceBlock.document_version_id.in_(version_ids)))
    document.deleted_at = datetime.now(UTC)
    audit.record(
        db,
        org_id=document.org_id,
        actor_id=actor_id,
        action="document.deleted",
        object_type="document",
        object_id=document.id,
        meta={"versions": len(version_ids)},
    )
