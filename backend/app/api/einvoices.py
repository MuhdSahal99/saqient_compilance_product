"""E-invoice batches and files (upload, list, download). Validation runs in reviews."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.uploads import scan_refusal
from app.config import get_settings
from app.deps import DB, Ctx, Writer, get_owned_or_404
from app.malware import MalwareFound, ScannerUnavailable
from app.models import EInvoiceBatch, EInvoiceFile, LegalEntity
from app.schemas import EInvoiceBatchDetailOut, EInvoiceBatchOut, EInvoiceFileOut
from app.services import einvoices as svc

router = APIRouter(tags=["e-invoices"])


def _batch_out(b: EInvoiceBatch) -> EInvoiceBatchOut:
    out = EInvoiceBatchOut.model_validate(b)
    out.entity_name = b.entity.name
    return out


def _detail(db: DB, b: EInvoiceBatch) -> EInvoiceBatchDetailOut:
    files = db.scalars(
        select(EInvoiceFile)
        .where(EInvoiceFile.org_id == b.org_id, EInvoiceFile.batch_id == b.id)
        .order_by(EInvoiceFile.filename, EInvoiceFile.sha256)
    ).all()
    return EInvoiceBatchDetailOut(
        **_batch_out(b).model_dump(), files=[EInvoiceFileOut.model_validate(f) for f in files]
    )


@router.post(
    "/einvoice-batches",
    response_model=EInvoiceBatchDetailOut,
    status_code=201,
    summary="Upload e-invoices (one XML or a ZIP of XML files)",
    description="Files are parsed safely (no DTDs or entities), hashed and stored for one "
    "entity; a file already stored for the entity is skipped. Nothing is sent to any "
    "e-invoicing platform. Validate the files by creating a review. Analysts and above.",
)
async def upload_batch(
    ctx: Writer,
    db: DB,
    file: Annotated[UploadFile, File()],
    entity_id: Annotated[uuid.UUID, Form()],
    name: Annotated[str, Form(min_length=1, max_length=200)],
) -> EInvoiceBatchDetailOut:
    limit = get_settings().dataset_max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is too large.")
    entity = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    try:
        batch = svc.create_batch(
            db,
            entity=entity,
            name=name,
            filename=file.filename or "invoice.xml",
            data=data,
            actor=ctx.user,
        )
    except svc.EInvoiceUploadError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (MalwareFound, ScannerUnavailable) as exc:
        raise scan_refusal(db, ctx, exc, data, "einvoice_batch") from exc
    db.commit()
    db.refresh(batch)
    return _detail(db, batch)


@router.get("/einvoice-batches", response_model=list[EInvoiceBatchOut], summary="List batches")
def list_batches(ctx: Ctx, db: DB, entity_id: uuid.UUID | None = None) -> list[EInvoiceBatchOut]:
    stmt = select(EInvoiceBatch).where(EInvoiceBatch.org_id == ctx.org_id)
    if entity_id:
        stmt = stmt.where(EInvoiceBatch.entity_id == entity_id)
    rows = db.scalars(stmt.order_by(EInvoiceBatch.created_at.desc())).unique().all()
    return [_batch_out(b) for b in rows]


@router.get(
    "/einvoice-batches/{batch_id}",
    response_model=EInvoiceBatchDetailOut,
    summary="Get a batch with its files",
)
def get_batch(batch_id: uuid.UUID, ctx: Ctx, db: DB) -> EInvoiceBatchDetailOut:
    return _detail(db, get_owned_or_404(db, EInvoiceBatch, batch_id, ctx.org_id))


@router.get("/einvoice-files/{file_id}", response_model=EInvoiceFileOut, summary="Get a file")
def get_file(file_id: uuid.UUID, ctx: Ctx, db: DB) -> EInvoiceFileOut:
    return EInvoiceFileOut.model_validate(get_owned_or_404(db, EInvoiceFile, file_id, ctx.org_id))


@router.get(
    "/einvoice-files/{file_id}/download",
    summary="Download the stored XML",
    description="The bytes as uploaded; their SHA-256 is re-checked first.",
    response_class=Response,
)
def download_file(file_id: uuid.UUID, ctx: Ctx, db: DB) -> Response:
    f = get_owned_or_404(db, EInvoiceFile, file_id, ctx.org_id)
    try:
        data = svc.read_file(f)
    except svc.EInvoiceUploadError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    safe = "".join(c for c in f.filename if c.isalnum() or c in "._-") or "invoice.xml"
    return Response(
        data,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
