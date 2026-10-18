"""Shared handling for uploads refused by the malware scanner."""

from __future__ import annotations

import hashlib

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.deps import Context
from app.malware import MalwareFound, ScannerUnavailable
from app.services import audit


def scan_refusal(
    db: Session, ctx: Context, exc: MalwareFound | ScannerUnavailable, data: bytes, kind: str
) -> HTTPException:
    """Roll back the upload, audit an infected file, and return the HTTP error."""
    db.rollback()
    if isinstance(exc, ScannerUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    audit.record(
        db,
        org_id=ctx.org_id,
        actor_id=ctx.user.id,
        action="upload.rejected_malware",
        object_type=kind,
        meta={"signature": exc.signature, "sha256": hashlib.sha256(data).hexdigest()},
    )
    db.commit()
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
