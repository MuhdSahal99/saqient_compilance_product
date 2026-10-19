"""E-invoice store: upload XML or ZIP batches, hash and keep every file.

Saqient stores and checks invoices that were issued elsewhere. It never signs,
clears, reports or sends an invoice to any platform.
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.einvoice import ubl, xmlsafe
from app.malware import ensure_clean
from app.models import EInvoiceBatch, EInvoiceFile, LegalEntity, User
from app.services import audit
from app.storage import get_storage, new_storage_key

MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024


class EInvoiceUploadError(ValueError):
    """Message is safe to show."""


def _entries(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    if not data:
        raise EInvoiceUploadError("The file is empty.")
    lower = filename.lower()
    if lower.endswith(".xml"):
        return [(posixpath.basename(filename) or "invoice.xml", data)]
    if not lower.endswith(".zip"):
        raise EInvoiceUploadError("Upload an XML invoice or a ZIP of XML invoices.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise EInvoiceUploadError("The file is not a valid ZIP archive.") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise EInvoiceUploadError("The ZIP archive is empty.")
    if len(infos) > MAX_ZIP_ENTRIES:
        raise EInvoiceUploadError(f"The ZIP archive has more than {MAX_ZIP_ENTRIES} files.")
    if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED:
        raise EInvoiceUploadError("The ZIP archive is too large when unpacked.")
    out: list[tuple[str, bytes]] = []
    for info in infos:
        name = posixpath.normpath(info.filename.replace("\\", "/"))
        if name.startswith(("/", "../")) or name == ".." or ":" in name:
            raise EInvoiceUploadError("The ZIP archive contains an unsafe path.")
        if posixpath.basename(name).startswith("._") or name.startswith("__MACOSX/"):
            continue
        if not name.lower().endswith(".xml"):
            raise EInvoiceUploadError("The ZIP archive may only contain .xml files.")
        if info.file_size > xmlsafe.MAX_XML_BYTES:
            raise EInvoiceUploadError(f"{posixpath.basename(name)} is larger than 5 MB.")
        body = zf.read(info)
        if len(body) != info.file_size:
            raise EInvoiceUploadError("The ZIP archive is corrupt.")
        out.append((name, body))
    if not out:
        raise EInvoiceUploadError("The ZIP archive has no XML files.")
    return out


def create_batch(
    db: Session,
    *,
    entity: LegalEntity,
    name: str,
    filename: str,
    data: bytes,
    actor: User | None,
    is_demo: bool = False,
) -> EInvoiceBatch:
    """Store each XML once per entity (same SHA-256 = duplicate, skipped and counted).

    A file that is not acceptable XML is still stored and listed with its parse
    error, so a review can report it rather than the upload silently dropping it.
    """
    entries = _entries(filename, data)
    ensure_clean(data)
    batch = EInvoiceBatch(
        org_id=entity.org_id,
        entity_id=entity.id,
        name=name.strip()[:200],
        original_filename=filename[:255],
        raw_sha256=hashlib.sha256(data).hexdigest(),
        is_demo=is_demo,
        created_by_id=actor.id if actor else None,
    )
    db.add(batch)
    db.flush()
    known = set(
        db.scalars(
            select(EInvoiceFile.sha256).where(
                EInvoiceFile.org_id == entity.org_id, EInvoiceFile.entity_id == entity.id
            )
        )
    )
    storage = get_storage()
    for entry_name, body in entries:
        sha = hashlib.sha256(body).hexdigest()
        if sha in known:
            batch.duplicate_count += 1
            continue
        known.add(sha)
        f = EInvoiceFile(
            org_id=entity.org_id,
            batch_id=batch.id,
            entity_id=entity.id,
            filename=posixpath.basename(entry_name)[:255],
            size_bytes=len(body),
            sha256=sha,
            storage_key=new_storage_key(entity.org_id),
        )
        try:
            root = xmlsafe.parse_xml(body)
            h = ubl.header(root)
            if not h.document_type:
                f.parse_error = "The XML is not a UBL Invoice or CreditNote."
            f.document_type = h.document_type
            f.profile = h.profile
            f.invoice_number = ubl.clip(h.invoice_number)
            f.invoice_uuid = (h.invoice_uuid or "")[:100] or None
            f.issue_date = h.issue_date
            f.type_code = (h.type_code or "")[:20] or None
            f.icv = h.icv
            f.currency = h.currency
            f.payable_amount = h.payable_amount
            f.tax_amount = h.tax_amount
        except xmlsafe.UnsafeXML as exc:
            f.parse_error = str(exc)
        if f.parse_error:
            batch.failed_count += 1
        storage.put(f.storage_key, body)
        db.add(f)
        batch.file_count += 1
    db.flush()
    audit.record(
        db,
        org_id=entity.org_id,
        actor_id=actor.id if actor else None,
        action="einvoice.batch_uploaded",
        object_type="einvoice_batch",
        object_id=batch.id,
        meta={
            "entity_id": str(entity.id),
            "files": batch.file_count,
            "duplicates": batch.duplicate_count,
            "failed": batch.failed_count,
            "sha256": batch.raw_sha256,
        },
    )
    return batch


def read_file(f: EInvoiceFile) -> bytes:
    data = get_storage().get(f.storage_key)
    if hashlib.sha256(data).hexdigest() != f.sha256:
        raise EInvoiceUploadError("The stored invoice failed its integrity check.")
    return data
