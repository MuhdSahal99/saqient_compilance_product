"""Read-only accounting connectors (Phase E6). Off unless CONNECTORS_ENABLED=true."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app import connectors as conn
from app.api.assurance_common import name_of
from app.config import get_settings
from app.deps import DB, Admin, Ctx, Writer, get_owned_or_404
from app.models import Connector, ConnectorSync, DatasetVersion, LegalEntity
from app.schemas import (
    AuthorizeOut,
    ConnectorIn,
    ConnectorOut,
    ConnectorProviderOut,
    ConnectorStatusOut,
    ConnectorSyncIn,
    ConnectorSyncOut,
)
from app.services import connectors as svc
from app.services.jobs import enqueue

router = APIRouter(tags=["connectors"])
T = TypeVar("T")
SAFE_CONFIG = ("base_url", "database", "username", "organization_id", "organization_name")


def _guard(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except svc.ConnectorsOff as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except svc.ConnectorStateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def sync_out(db: DB, s: ConnectorSync) -> ConnectorSyncOut:
    v = db.get(DatasetVersion, s.dataset_version_id) if s.dataset_version_id else None
    return ConnectorSyncOut(
        id=s.id,
        kind=s.kind,
        status=s.status,
        rows=s.rows,
        sha256=s.sha256,
        dataset_version_id=s.dataset_version_id,
        dataset_version_status=v.status.value if v else None,
        message=s.message,
        requested_by_name=name_of(db, s.requested_by_id),
        created_at=s.created_at,
        finished_at=s.finished_at,
    )


def connector_out(db: DB, c: Connector) -> ConnectorOut:
    a = conn.adapter(c.provider)
    syncs = db.scalars(
        select(ConnectorSync)
        .where(ConnectorSync.connector_id == c.id, ConnectorSync.org_id == c.org_id)
        .order_by(ConnectorSync.created_at.desc())
        .limit(10)
    )
    return ConnectorOut(
        id=c.id,
        entity_id=c.entity_id,
        entity_name=c.entity.name,
        provider=c.provider,
        provider_label=a.label,
        auth=a.auth,
        name=c.name,
        status=c.status,
        scopes=c.scopes,
        config={k: c.config[k] for k in SAFE_CONFIG if k in c.config},
        has_credentials=c.secret_enc is not None,
        kinds=list(a.kinds),
        datasets={k: uuid.UUID(v) for k, v in c.datasets.items()},
        mapping_status=conn.MAPPING_STATUS,
        last_sync_at=c.last_sync_at,
        last_error=c.last_error,
        syncs=[sync_out(db, s) for s in syncs],
        created_at=c.created_at,
    )


def _get(db: DB, ctx: Ctx, cid: uuid.UUID) -> Connector:
    return get_owned_or_404(db, Connector, cid, ctx.org.id)


@router.get(
    "/connectors/status",
    response_model=ConnectorStatusOut,
    summary="Whether connectors are on, and which providers are configured",
)
def connector_status(ctx: Ctx) -> ConnectorStatusOut:
    return ConnectorStatusOut(
        enabled=get_settings().connectors_enabled,
        providers=[
            ConnectorProviderOut(
                provider=a.provider,
                label=a.label,
                auth=a.auth,
                kinds=list(a.kinds),
                scopes=list(a.scopes),
                configured=a.configured(),
                mapping_status=conn.MAPPING_STATUS,
            )
            for a in conn.adapters().values()
        ],
    )


@router.get("/connectors", response_model=list[ConnectorOut], summary="List connectors")
def list_connectors(db: DB, ctx: Ctx, entity_id: uuid.UUID | None = None) -> list[ConnectorOut]:
    stmt = select(Connector).where(Connector.org_id == ctx.org.id)
    if entity_id is not None:
        stmt = stmt.where(Connector.entity_id == entity_id)
    return [connector_out(db, c) for c in db.scalars(stmt.order_by(Connector.created_at))]


@router.post(
    "/connectors",
    response_model=ConnectorOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a connector",
    description="Org admins only. Odoo takes its address, database, user and API key here; "
    "Zoho Books is then authorised through its sign-in page.",
)
def create_connector(body: ConnectorIn, db: DB, ctx: Admin) -> ConnectorOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    config = body.config.model_dump(exclude_defaults=True) if body.config else {}
    c = _guard(
        lambda: svc.create(db, entity, body.provider, body.name, config, body.api_key, ctx.user)
    )
    db.commit()
    return connector_out(db, c)


@router.get(
    "/connectors/oauth/callback",
    summary="OAuth redirect target",
    description="The provider sends the browser here. The state is single-use, expires after "
    "10 minutes and must have been started by the same admin.",
    response_class=RedirectResponse,
)
def oauth_callback(
    db: DB,
    ctx: Admin,
    state: str = Query(min_length=10, max_length=200),
    code: str = Query(default="", max_length=2000),
    error: str = Query(default="", max_length=200),
) -> RedirectResponse:
    c = svc.find_by_state(db, ctx.org.id, state)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    result = "connected"
    try:
        if error or not code:
            raise svc.ConnectorStateError("The provider did not grant access.")
        svc.complete_oauth(db, c, code, ctx.user)
    except svc.ConnectorStateError:
        c.oauth_state_hash = c.oauth_verifier_enc = c.oauth_expires_at = None
        result = "failed"
    db.commit()
    base = get_settings().app_base_url.rstrip("/")
    query = urlencode({"connector": str(c.id), "result": result})
    return RedirectResponse(f"{base}/connectors?{query}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/connectors/{connector_id}", response_model=ConnectorOut, summary="Get a connector")
def get_connector(connector_id: uuid.UUID, db: DB, ctx: Ctx) -> ConnectorOut:
    return connector_out(db, _get(db, ctx, connector_id))


@router.post(
    "/connectors/{connector_id}/authorize",
    response_model=AuthorizeOut,
    summary="Start OAuth sign-in (read-only scopes, PKCE)",
)
def authorize(connector_id: uuid.UUID, db: DB, ctx: Admin) -> AuthorizeOut:
    c = _get(db, ctx, connector_id)
    url = _guard(lambda: svc.authorize(db, c, ctx.user))
    db.commit()
    return AuthorizeOut(url=url)


@router.post(
    "/connectors/{connector_id}/test",
    response_model=ConnectorOut,
    summary="Check API-key credentials",
)
def test_connector(connector_id: uuid.UUID, db: DB, ctx: Admin) -> ConnectorOut:
    c = _get(db, ctx, connector_id)
    try:
        _guard(lambda: svc.test(db, c, ctx.user))
    finally:
        db.commit()  # keep the error status and audit event
    return connector_out(db, c)


@router.post(
    "/connectors/{connector_id}/disconnect",
    response_model=ConnectorOut,
    summary="Delete stored credentials",
)
def disconnect(connector_id: uuid.UUID, db: DB, ctx: Admin) -> ConnectorOut:
    c = _get(db, ctx, connector_id)
    svc.disconnect(db, c, ctx.user)
    db.commit()
    return connector_out(db, c)


@router.post(
    "/connectors/{connector_id}/sync",
    response_model=ConnectorSyncOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pull one dataset kind",
    description="Runs as a background job. A new dataset version is added only when the "
    "content differs from the latest one.",
)
def sync(connector_id: uuid.UUID, body: ConnectorSyncIn, db: DB, ctx: Writer) -> ConnectorSyncOut:
    c = _get(db, ctx, connector_id)
    s, job = _guard(lambda: svc.request_sync(db, c, body.kind, ctx.user))
    db.commit()
    enqueue(job)
    db.expire_all()
    return sync_out(db, db.get(ConnectorSync, s.id) or s)
