"""Shared pieces for Phase E routers: error mapping, sign-off state and exports."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.deps import Context
from app.models import AssuranceObject, SignOffMixin, User
from app.schemas import AssuranceVersionOut, SignOffOut
from app.services import assurance, audit

T = TypeVar("T")


def guard(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except assurance.AssuranceConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except assurance.AssuranceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc


def _name(db: Session, uid: uuid.UUID | None) -> str | None:
    u = db.get(User, uid) if uid else None
    return u.full_name if u else None


def name_of(db: Session, uid: uuid.UUID | None) -> str | None:
    return _name(db, uid)


def sign_off_out(db: Session, obj: SignOffMixin) -> SignOffOut:
    return SignOffOut(
        status=obj.status,
        version=obj.version,
        prepared_by_name=_name(db, obj.prepared_by_id),
        prepared_at=obj.prepared_at,
        signed_off_by_name=_name(db, obj.signed_off_by_id),
        signed_off_at=obj.signed_off_at,
        reopen_reason=obj.reopen_reason,
    )


def versions_out(
    db: Session, org_id: uuid.UUID, kind: AssuranceObject, oid: uuid.UUID
) -> list[AssuranceVersionOut]:
    return [
        AssuranceVersionOut(
            version=s.version,
            signed_by_name=_name(db, s.signed_by_id),
            signed_at=s.signed_at,
            sha256=s.sha256,
        )
        for s in assurance.snapshots(db, org_id, kind, oid)
    ]


def export(
    db: Session, ctx: Context, kind: AssuranceObject, oid: uuid.UUID, version: int, fmt: str
) -> Response:
    snap = assurance.snapshot(db, ctx.org.id, kind, oid, version)
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    audit.record(
        db,
        org_id=ctx.org.id,
        actor_id=ctx.user.id,
        action=f"{kind.value}.exported",
        object_type=kind.value,
        object_id=oid,
        meta={"version": version, "format": fmt},
    )
    db.commit()
    headers = {"Cache-Control": "private, no-store"}
    c: dict[str, Any] = snap.content
    if fmt == "html":
        return Response(
            assurance.render_html(c), media_type="text/html; charset=utf-8", headers=headers
        )
    stem = f"saqient-{kind.value.replace('_', '-')}-v{version}"
    if fmt == "csv":
        headers["Content-Disposition"] = f'attachment; filename="{stem}.csv"'
        return Response(
            assurance.render_csv(c), media_type="text/csv; charset=utf-8", headers=headers
        )
    headers["Content-Disposition"] = f'attachment; filename="{stem}.pdf"'
    return Response(assurance.render_pdf(c), media_type="application/pdf", headers=headers)
