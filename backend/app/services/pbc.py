"""PBC ("prepared by client") requests and the client portal (D8).

Staff raise requests on an engagement and assign each to a user with the ``client``
role. That user sees only the requests assigned to them, uploads files through the
normal validated document pipeline and submits; staff accept or reject with a note.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AuditEngagement,
    Document,
    Membership,
    PbcFile,
    PbcRequest,
    PbcStatus,
    Role,
    User,
)
from app.schemas import PbcRequestIn
from app.services import audit
from app.services.engagements import EngagementError, require_open


def _record(db: Session, r: PbcRequest, actor: User, action: str, **meta: object) -> None:
    audit.record(
        db,
        org_id=r.org_id,
        actor_id=actor.id,
        action=f"pbc.{action}",
        object_type="pbc_request",
        object_id=r.id,
        meta={"engagement_id": str(r.engagement_id), **meta},
    )


def _client(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> User:
    m = db.scalar(
        select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )
    if m is None:
        raise LookupError("user")
    if m.role is not Role.CLIENT:
        raise EngagementError("Assign requests to a user with the client role.")
    return m.user


def requests(db: Session, e: AuditEngagement) -> list[PbcRequest]:
    return list(
        db.scalars(
            select(PbcRequest)
            .where(PbcRequest.org_id == e.org_id, PbcRequest.engagement_id == e.id)
            .order_by(PbcRequest.ref)
        ).unique()
    )


def create(db: Session, e: AuditEngagement, body: PbcRequestIn, actor: User) -> PbcRequest:
    require_open(e)
    if db.scalar(
        select(PbcRequest.id).where(PbcRequest.engagement_id == e.id, PbcRequest.ref == body.ref)
    ):
        raise EngagementError(f"Request {body.ref} already exists.")
    if body.assignee_id is not None:
        _client(db, e.org_id, body.assignee_id)
    r = PbcRequest(
        org_id=e.org_id,
        engagement_id=e.id,
        ref=body.ref,
        title=body.title.strip(),
        description=body.description,
        due_date=body.due_date,
        assignee_id=body.assignee_id,
        created_by_id=actor.id,
    )
    db.add(r)
    db.flush()
    _record(db, r, actor, "created", assigned=body.assignee_id is not None)
    return r


def review(
    db: Session, e: AuditEngagement, r: PbcRequest, accept: bool, note: str, actor: User
) -> None:
    require_open(e)
    if r.status is not PbcStatus.SUBMITTED:
        raise EngagementError("Only a submitted request can be accepted or rejected.")
    if not accept and not note.strip():
        raise EngagementError("Say what is missing when rejecting a request.")
    r.status = PbcStatus.ACCEPTED if accept else PbcStatus.REJECTED
    r.review_note = note.strip()
    r.reviewed_by_id, r.reviewed_at = actor.id, now()
    db.flush()
    _record(db, r, actor, "reviewed", status=r.status.value)


# ---------------------------------------------------------------- portal (client role)


def mine(db: Session, user: User, org_id: uuid.UUID) -> list[PbcRequest]:
    return list(
        db.scalars(
            select(PbcRequest)
            .where(PbcRequest.org_id == org_id, PbcRequest.assignee_id == user.id)
            .order_by(PbcRequest.due_date.nulls_last(), PbcRequest.ref)
        ).unique()
    )


def get_mine(db: Session, user: User, org_id: uuid.UUID, request_id: uuid.UUID) -> PbcRequest:
    """A request assigned to this client user; anything else is reported as missing."""
    r = db.scalar(
        select(PbcRequest).where(
            PbcRequest.id == request_id,
            PbcRequest.org_id == org_id,
            PbcRequest.assignee_id == user.id,
        )
    )
    if r is None:
        raise LookupError("request")
    return r


def _open_for_client(db: Session, r: PbcRequest) -> None:
    e = db.get(AuditEngagement, r.engagement_id)
    if e is None or e.status.value == "closed":
        raise EngagementError("This request is closed.")
    if r.status not in (PbcStatus.REQUESTED, PbcStatus.REJECTED):
        raise EngagementError("This request has already been submitted.")


def attach(db: Session, r: PbcRequest, doc: Document, actor: User) -> None:
    _open_for_client(db, r)
    r.files.append(PbcFile(org_id=r.org_id, document_id=doc.id, uploaded_by_id=actor.id))
    db.flush()
    _record(db, r, actor, "file_uploaded", document_id=str(doc.id))


def submit(db: Session, r: PbcRequest, note: str, actor: User) -> None:
    _open_for_client(db, r)
    if not r.files:
        raise EngagementError("Upload at least one file before submitting.")
    r.status = PbcStatus.SUBMITTED
    r.client_note = note.strip()
    r.submitted_at = now()
    db.flush()
    _record(db, r, actor, "submitted", files=len(r.files))
