"""Load a review's e-invoice files into the engine context (hash re-checked)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.einvoice import xmlsafe
from app.engine.data_checks import DataContext
from app.engine.einvoice_checks import InvoiceSet, LoadedInvoice
from app.models import Review, ReviewEInvoice
from app.services.einvoices import EInvoiceUploadError, read_file
from app.services.jobs import PermanentJobError


def attach(
    db: Session, review: Review, org_id: uuid.UUID, ctx: DataContext, inputs: dict[str, Any]
) -> None:
    links = list(
        db.scalars(
            select(ReviewEInvoice).where(
                ReviewEInvoice.review_id == review.id, ReviewEInvoice.org_id == org_id
            )
        )
    )
    if not links:
        return
    loaded: list[LoadedInvoice] = []
    for link in links:
        f = link.file
        if f.org_id != org_id:
            raise PermanentJobError("An e-invoice of this review is not available.")
        try:
            data = read_file(f)
        except EInvoiceUploadError as exc:
            raise PermanentJobError(str(exc)) from exc
        root, error = None, f.parse_error
        if error is None:
            try:
                root = xmlsafe.parse_xml(data)
            except xmlsafe.UnsafeXML as exc:
                error = str(exc)
        loaded.append(
            LoadedInvoice(
                file_id=str(f.id),
                filename=f.filename,
                sha256=f.sha256,
                invoice_number=f.invoice_number,
                invoice_uuid=f.invoice_uuid,
                icv=f.icv,
                raw=data,
                root=root,
                parse_error=error,
            )
        )
    loaded.sort(key=lambda i: (i.filename, i.sha256))
    ctx.einvoices = InvoiceSet(loaded)
    inputs["einvoices"] = [
        {"file_id": i.file_id, "filename": i.filename, "sha256": i.sha256} for i in loaded
    ]
