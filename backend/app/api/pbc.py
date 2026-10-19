"""PBC request list (staff) and the restricted client portal (Phase D8).

Portal routes live under ``/portal`` and accept only the ``client`` role; every other
route refuses that role centrally (``app.deps.current_context``). A client sees only
requests assigned to them; any other id is reported as missing.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.api.documents import _duplicate_response, _read_limited
from app.api.engagements import _guard, get_engagement
from app.api.uploads import scan_refusal
from app.deps import DB, Ctx, PortalCtx, Writer, get_owned_or_404
from app.extraction import ValidationError
from app.malware import MalwareFound, ScannerUnavailable
from app.models import Document, PbcRequest
from app.schemas import PbcRequestIn, PbcRequestOut, PbcReviewIn, PbcStaffOut, PbcSubmitIn
from app.services import audit
from app.services import pbc as svc
from app.services.documents import DuplicateDocument, create_version
from app.services.jobs import enqueue

router = APIRouter(tags=["PBC requests and client portal"])


def _base(r: PbcRequest) -> dict[str, object]:
    return {
        "id": r.id,
        "ref": r.ref,
        "title": r.title,
        "description": r.description,
        "due_date": r.due_date,
        "status": r.status,
        "client_note": r.client_note,
        "review_note": r.review_note,
        "submitted_at": r.submitted_at,
        "files": [
            {"document_id": f.document_id, "title": f.document.title, "uploaded_at": f.created_at}
            for f in r.files
        ],
    }


def staff_out(r: PbcRequest) -> PbcStaffOut:
    return PbcStaffOut(
        **_base(r),
        assignee_id=r.assignee_id,
        assignee_name=r.assignee.full_name if r.assignee else None,
        overdue=r.due_date is not None
        and r.due_date < date.today()
        and r.status.value in ("requested", "rejected"),
    )


@router.get(
    "/engagements/{engagement_id}/pbc",
    response_model=list[PbcStaffOut],
    summary="List PBC requests",
)
def list_requests(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[PbcStaffOut]:
    e = get_engagement(db, ctx, engagement_id)
    return [staff_out(r) for r in svc.requests(db, e)]


@router.post(
    "/engagements/{engagement_id}/pbc",
    response_model=PbcStaffOut,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a PBC request",
    description="Optionally assigned to a user with the client role, who answers it in the portal.",
)
def create_request(
    engagement_id: uuid.UUID, body: PbcRequestIn, db: DB, ctx: Writer
) -> PbcStaffOut:
    e = get_engagement(db, ctx, engagement_id)
    r = _guard(lambda: svc.create(db, e, body, ctx.user))
    db.commit()
    return staff_out(r)


@router.post(
    "/pbc/{request_id}/review",
    response_model=PbcStaffOut,
    summary="Accept or reject a submitted request",
    description="Rejecting needs a note saying what is missing; the client can then resubmit.",
)
def review_request(request_id: uuid.UUID, body: PbcReviewIn, db: DB, ctx: Writer) -> PbcStaffOut:
    r = get_owned_or_404(db, PbcRequest, request_id, ctx.org.id)
    e = get_engagement(db, ctx, r.engagement_id)
    _guard(lambda: svc.review(db, e, r, body.status == "accepted", body.note, ctx.user))
    db.commit()
    return staff_out(r)


# ---------------------------------------------------------------- portal


def _mine(db: DB, ctx: PortalCtx, request_id: uuid.UUID) -> PbcRequest:
    try:
        return svc.get_mine(db, ctx.user, ctx.org.id, request_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc


@router.get(
    "/portal/requests",
    response_model=list[PbcRequestOut],
    summary="My requests (client portal)",
)
def portal_list(db: DB, ctx: PortalCtx) -> list[PbcRequestOut]:
    return [PbcRequestOut(**_base(r)) for r in svc.mine(db, ctx.user, ctx.org.id)]


@router.get(
    "/portal/requests/{request_id}",
    response_model=PbcRequestOut,
    summary="One of my requests (client portal)",
)
def portal_get(request_id: uuid.UUID, db: DB, ctx: PortalCtx) -> PbcRequestOut:
    return PbcRequestOut(**_base(_mine(db, ctx, request_id)))


@router.post(
    "/portal/requests/{request_id}/files",
    response_model=PbcRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file for a request (client portal)",
    description="Checked like any document upload: type, size, signature and malware scan.",
)
async def portal_upload(
    request_id: uuid.UUID,
    db: DB,
    ctx: PortalCtx,
    file: Annotated[UploadFile, File()],
) -> PbcRequestOut | JSONResponse:
    r = _mine(db, ctx, request_id)
    _guard(lambda: svc._open_for_client(db, r))
    data = await _read_limited(file)
    doc = Document(
        org_id=ctx.org_id,
        title=f"{r.ref} {file.filename or 'upload'}"[:300],
        description=f"Uploaded by the client for PBC request {r.ref}.",
        document_type="pbc",
        tags=["pbc"],
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
            allow_duplicate=False,
        )
    except ValidationError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (MalwareFound, ScannerUnavailable) as exc:
        raise scan_refusal(db, ctx, exc, data, "document") from exc
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
        meta={"pbc_request_id": str(r.id)},
    )
    svc.attach(db, r, doc, ctx.user)
    db.commit()
    enqueue(job)
    db.expire_all()
    return PbcRequestOut(**_base(_mine(db, ctx, request_id)))


@router.post(
    "/portal/requests/{request_id}/submit",
    response_model=PbcRequestOut,
    summary="Submit a request (client portal)",
)
def portal_submit(
    request_id: uuid.UUID, body: PbcSubmitIn, db: DB, ctx: PortalCtx
) -> PbcRequestOut:
    r = _mine(db, ctx, request_id)
    _guard(lambda: svc.submit(db, r, body.note, ctx.user))
    db.commit()
    return PbcRequestOut(**_base(r))
