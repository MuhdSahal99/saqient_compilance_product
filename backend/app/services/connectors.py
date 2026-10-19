"""Connector lifecycle and syncs (Phase E6).

Secrets (OAuth tokens, API keys, the PKCE verifier) are stored only as
``crypto.encrypt_field`` ciphertext bound to the organisation, and never returned,
logged or written to audit metadata. A sync is a job: it re-checks the connector's
organisation, pulls one dataset kind, writes a canonical CSV, and adds a dataset
version only when the content hash differs from the latest one (idempotent).
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import connectors as conn
from app.config import get_settings
from app.crypto import decrypt_field, encrypt_field
from app.models import (
    Connector,
    ConnectorProvider,
    ConnectorStatus,
    ConnectorSync,
    ConnectorSyncStatus,
    Dataset,
    DatasetKind,
    DatasetVersion,
    Job,
    JobKind,
    LegalEntity,
    User,
)
from app.services import audit
from app.services import datasets as dsvc
from app.services.jobs import Checkpoint, PermanentJobError, handler

logger = logging.getLogger("saqient.connectors")
STATE_TTL = timedelta(minutes=10)
SECRET_FIELD = "connector_secret"  # noqa: S105 - a field label, not a secret
VERIFIER_FIELD = "connector_pkce"


class ConnectorStateError(ValueError):
    """Shown to the user as a 409 or 422."""


class ConnectorsOff(ConnectorStateError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def require_enabled() -> None:
    if not get_settings().connectors_enabled:
        raise ConnectorsOff("Connectors are turned off for this installation.")


def _record(db: Session, c: Connector, actor: User | None, action: str, **meta: Any) -> None:
    audit.record(
        db,
        org_id=c.org_id,
        actor_id=actor.id if actor else None,
        action=action,
        object_type="connector",
        object_id=c.id,
        meta=meta,
    )


def _secret(c: Connector) -> dict[str, Any]:
    if not c.secret_enc:
        raise conn.ConnectorError("This connector has no credentials yet.")
    value: dict[str, Any] = json.loads(
        decrypt_field(c.secret_enc, org_id=c.org_id, field=SECRET_FIELD)
    )
    return value


def _store_secret(c: Connector, value: dict[str, Any]) -> None:
    c.secret_enc = encrypt_field(json.dumps(value), org_id=c.org_id, field=SECRET_FIELD)


def redirect_uri() -> str:
    return f"{get_settings().app_base_url.rstrip('/')}/api/connectors/oauth/callback"


def create(
    db: Session,
    entity: LegalEntity,
    provider: ConnectorProvider,
    name: str,
    config: dict[str, Any],
    api_key: str | None,
    actor: User,
) -> Connector:
    require_enabled()
    a = conn.adapter(provider)
    if not a.configured():
        raise ConnectorStateError(f"{a.label} is not configured for this installation.")
    clean: dict[str, Any] = {}
    if provider is ConnectorProvider.ODOO:
        from app.connectors.odoo import check_base_url

        try:
            clean["base_url"] = check_base_url(str(config.get("base_url", "")))
        except conn.ConnectorError as exc:
            raise ConnectorStateError(str(exc)) from exc
        for k in ("database", "username"):
            v = str(config.get(k, "")).strip()
            if not v or len(v) > 200:
                raise ConnectorStateError(f"Odoo needs a {k}.")
            clean[k] = v
        if not api_key:
            raise ConnectorStateError("Odoo needs an API key.")
    elif api_key or config:
        raise ConnectorStateError(f"{a.label} is connected through its sign-in page.")
    c = Connector(
        org_id=entity.org_id,
        entity_id=entity.id,
        provider=provider,
        name=name.strip(),
        scopes=list(a.scopes),
        config=clean,
        created_by_id=actor.id,
    )
    db.add(c)
    db.flush()
    if api_key:
        _store_secret(c, {"api_key": api_key})
    _record(db, c, actor, "connector.created", provider=provider.value)
    return c


def authorize(db: Session, c: Connector, actor: User) -> str:
    require_enabled()
    a = conn.adapter(c.provider)
    if a.auth != "oauth":
        raise ConnectorStateError(f"{a.label} does not use a sign-in page.")
    if not a.configured():
        raise ConnectorStateError(f"{a.label} is not configured for this installation.")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    c.oauth_state_hash = hashlib.sha256(state.encode()).hexdigest()
    c.oauth_verifier_enc = encrypt_field(verifier, org_id=c.org_id, field=VERIFIER_FIELD)
    c.oauth_expires_at = _now() + STATE_TTL
    c.oauth_started_by_id = actor.id
    db.flush()
    _record(db, c, actor, "connector.authorize_started")
    return a.authorize_url(state, challenge.decode().rstrip("="), redirect_uri())


def find_by_state(db: Session, org_id: uuid.UUID, state: str) -> Connector | None:
    digest = hashlib.sha256(state.encode()).hexdigest()
    return db.scalar(
        select(Connector).where(Connector.org_id == org_id, Connector.oauth_state_hash == digest)
    )


def complete_oauth(db: Session, c: Connector, code: str, actor: User) -> None:
    """Exchange the code. The state was matched by the caller; it is single-use."""
    require_enabled()
    expires, verifier_enc, starter = c.oauth_expires_at, c.oauth_verifier_enc, c.oauth_started_by_id
    c.oauth_state_hash = c.oauth_verifier_enc = c.oauth_expires_at = None
    c.oauth_started_by_id = None
    if expires is None or expires < _now() or verifier_enc is None or starter != actor.id:
        db.flush()
        raise ConnectorStateError("The sign-in link expired. Start again.")
    verifier = decrypt_field(verifier_enc, org_id=c.org_id, field=VERIFIER_FIELD)
    a = conn.adapter(c.provider)
    try:
        with conn.Http() as http:
            secret = a.exchange(http, code, verifier, redirect_uri())
            c.config = a.connect(http, secret, dict(c.config))
    except conn.ConnectorError as exc:
        c.status, c.last_error = ConnectorStatus.ERROR, str(exc)
        _record(db, c, actor, "connector.connect_failed", error=type(exc).__name__)
        db.flush()
        raise ConnectorStateError(str(exc)) from exc
    _store_secret(c, secret)
    c.status, c.last_error = ConnectorStatus.CONNECTED, ""
    db.flush()
    _record(db, c, actor, "connector.connected")


def test(db: Session, c: Connector, actor: User) -> None:
    """Check API-key credentials (Odoo) and store what the provider returns."""
    require_enabled()
    a = conn.adapter(c.provider)
    if a.auth != "api_key":
        raise ConnectorStateError(f"{a.label} is connected through its sign-in page.")
    try:
        with conn.Http() as http:
            c.config = a.connect(http, _secret(c), dict(c.config))
    except conn.ConnectorError as exc:
        c.status, c.last_error = ConnectorStatus.ERROR, str(exc)
        _record(db, c, actor, "connector.connect_failed", error=type(exc).__name__)
        db.flush()
        raise ConnectorStateError(str(exc)) from exc
    c.status, c.last_error = ConnectorStatus.CONNECTED, ""
    db.flush()
    _record(db, c, actor, "connector.connected")


def disconnect(db: Session, c: Connector, actor: User) -> None:
    c.secret_enc = None
    c.oauth_state_hash = c.oauth_verifier_enc = c.oauth_expires_at = None
    c.status = ConnectorStatus.DISCONNECTED
    db.flush()
    _record(db, c, actor, "connector.disconnected")


def request_sync(
    db: Session, c: Connector, kind: DatasetKind, actor: User
) -> tuple[ConnectorSync, Job]:
    require_enabled()
    if c.status is not ConnectorStatus.CONNECTED:
        raise ConnectorStateError("Connect the account before syncing.")
    if kind not in conn.adapter(c.provider).kinds:
        raise ConnectorStateError(f"This connector does not supply {kind.value.replace('_', ' ')}.")
    busy = db.scalar(
        select(ConnectorSync.id).where(
            ConnectorSync.connector_id == c.id, ConnectorSync.status == ConnectorSyncStatus.QUEUED
        )
    )
    if busy is not None:
        raise ConnectorStateError("A sync for this connector is already running.")
    s = ConnectorSync(org_id=c.org_id, connector_id=c.id, kind=kind, requested_by_id=actor.id)
    db.add(s)
    db.flush()
    job = Job(
        org_id=c.org_id,
        kind=JobKind.CONNECTOR_SYNC,
        target_id=s.id,
        max_attempts=get_settings().job_max_attempts,
    )
    db.add(job)
    _record(db, c, actor, "connector.sync_requested", kind=kind.value)
    return s, job


def to_csv(result: conn.FetchResult) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(result.columns)
    for r in result.rows:
        w.writerow([r.get(c, "") for c in result.columns])
    return buf.getvalue().encode("utf-8")


def _dataset(db: Session, c: Connector, kind: DatasetKind, actor: User) -> Dataset:
    did = c.datasets.get(kind.value)
    if did:
        ds = db.scalar(
            select(Dataset).where(Dataset.id == uuid.UUID(did), Dataset.org_id == c.org_id)
        )
        if ds is not None:
            return ds
    ds = dsvc.create_dataset(
        db,
        org_id=c.org_id,
        entity=c.entity,
        kind=kind,
        name=f"{c.name} · {kind.value.replace('_', ' ')}"[:200],
        period_start=None,
        period_end=None,
        actor=actor,
    )
    c.datasets = {**c.datasets, kind.value: str(ds.id)}
    return ds


def _finish(db: Session, s: ConnectorSync, status: ConnectorSyncStatus, message: str = "") -> None:
    s.status, s.message, s.finished_at = status, message, _now()


@handler(JobKind.CONNECTOR_SYNC)
def run_sync(db: Session, job: Job, checkpoint: Checkpoint) -> None:
    s = db.scalar(
        select(ConnectorSync).where(
            ConnectorSync.id == job.target_id, ConnectorSync.org_id == job.org_id
        )
    )
    if s is None:
        raise PermanentJobError("The sync no longer exists.")
    c = db.scalar(
        select(Connector).where(Connector.id == s.connector_id, Connector.org_id == job.org_id)
    )
    actor = db.get(User, s.requested_by_id) if s.requested_by_id else None
    if c is None or actor is None:
        _finish(db, s, ConnectorSyncStatus.FAILED, "The connector or the requester was removed.")
        db.commit()
        raise PermanentJobError("The connector or the requester was removed.")
    a = conn.adapter(c.provider)
    try:
        if not get_settings().connectors_enabled:
            raise conn.ConnectorError("Connectors are turned off for this installation.")
        secret = _secret(c)
        with conn.Http() as http:
            expires = secret.get("expires_at")
            if (
                a.auth == "oauth"
                and expires
                and datetime.fromisoformat(expires) <= _now() + timedelta(minutes=2)
            ):
                secret = a.refresh(http, secret)
                _store_secret(c, secret)
            checkpoint(20)
            result = a.fetch(http, s.kind, secret, dict(c.config))
            requests = http.requests
        if not result.rows:
            raise conn.ConnectorError("The provider returned no records for this kind.")
    except conn.ConnectorError as exc:
        if isinstance(exc, conn.ConnectorAuthError):
            c.status = ConnectorStatus.ERROR
        c.last_error = str(exc)
        _finish(db, s, ConnectorSyncStatus.FAILED, str(exc))
        _record(db, c, actor, "connector.sync_failed", kind=s.kind.value, error=type(exc).__name__)
        db.commit()
        logger.info(
            "connector sync failed", extra={"sync_id": str(s.id), "error": type(exc).__name__}
        )
        raise PermanentJobError(str(exc)) from exc
    checkpoint(60)
    data = to_csv(result)
    digest = hashlib.sha256(data).hexdigest()
    s.rows, s.sha256 = len(result.rows), digest
    ds = _dataset(db, c, s.kind, actor)
    latest = db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == ds.id)
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    )
    c.last_sync_at, c.last_error = _now(), ""
    if latest is not None and latest.raw_sha256 == digest:
        s.dataset_version_id = latest.id
        _finish(db, s, ConnectorSyncStatus.UNCHANGED, "Same content as the latest version.")
        _record(db, c, actor, "connector.sync_unchanged", kind=s.kind.value, sha256=digest)
        db.commit()
        return
    v = dsvc.store_version(
        db,
        dataset=ds,
        filename=f"{c.provider.value}-{s.kind.value}.csv",
        declared_mime="text/csv",
        data=data,
        actor=actor,
        allow_duplicate=True,
    )
    s.dataset_version_id = v.id
    _finish(db, s, ConnectorSyncStatus.SUCCEEDED)
    _record(
        db,
        c,
        actor,
        "connector.synced",
        kind=s.kind.value,
        rows=s.rows,
        sha256=digest,
        requests=requests,
    )
    db.commit()
    dsvc.build_from_canonical_csv(db, v, data, actor)
    logger.info("connector synced", extra={"sync_id": str(s.id), "rows": s.rows})
