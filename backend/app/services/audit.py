"""Hash-chained, append-only audit log.

Each organisation has its own chain (events without an organisation, such as
failed sign-ins, share one more chain). Every event stores its position
(``seq``), the previous event's hash and its own hash over a canonical JSON
form of its fields. Editing, reordering or removing an event breaks the chain
from that point, and ``verify_chain`` reports where. A database trigger
rejects UPDATE on the table. Removing the newest events cannot be detected
from the table alone; keep the ``head_hash`` that verification returns if you
need that guarantee.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent

# Keys that must never appear in audit metadata.
_FORBIDDEN_KEYS = {"text", "content", "password", "token", "csrf", "body"}

HASH_VERSION = "v1"
GENESIS_HASH = "0" * 64
_GLOBAL_LOCK_KEY = 0x5A51E47  # chain for events without an organisation


def _lock_key(org_id: uuid.UUID | None) -> int:
    if org_id is None:
        return _GLOBAL_LOCK_KEY
    # Signed 64-bit key for pg_advisory_xact_lock.
    return int.from_bytes(org_id.bytes[:8], "big", signed=True)


def canonical_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through JSON so the stored value hashes the same after loading."""
    loaded: dict[str, Any] = json.loads(json.dumps(meta, default=str, sort_keys=True))
    return loaded


def compute_hash(
    *,
    event_id: uuid.UUID,
    org_id: uuid.UUID | None,
    seq: int,
    actor_id: uuid.UUID | None,
    action: str,
    object_type: str,
    object_id: uuid.UUID | None,
    meta: dict[str, Any],
    created_at: datetime,
    prev_hash: str,
) -> str:
    payload = {
        "v": HASH_VERSION,
        "id": str(event_id),
        "org_id": str(org_id) if org_id else None,
        "seq": seq,
        "actor_id": str(actor_id) if actor_id else None,
        "action": action,
        "object_type": object_type,
        "object_id": str(object_id) if object_id else None,
        "meta": meta,
        "created_at": created_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "prev_hash": prev_hash,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_hash(e: AuditEvent) -> str:
    return compute_hash(
        event_id=e.id,
        org_id=e.org_id,
        seq=e.seq,
        actor_id=e.actor_id,
        action=e.action,
        object_type=e.object_type,
        object_id=e.object_id,
        meta=e.meta,
        created_at=e.created_at,
        prev_hash=e.prev_hash,
    )


def record(
    db: Session,
    *,
    org_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    object_type: str,
    object_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditEvent:
    safe = canonical_meta({k: v for k, v in (meta or {}).items() if k not in _FORBIDDEN_KEYS})
    # Serialise appends per chain until this transaction ends.
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _lock_key(org_id)})
    last = db.execute(
        select(AuditEvent.seq, AuditEvent.hash)
        .where(AuditEvent.org_id.is_not_distinct_from(org_id))
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    ).first()
    seq, prev_hash = (last[0] + 1, last[1]) if last else (1, GENESIS_HASH)
    event = AuditEvent(
        id=uuid.uuid4(),
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        meta=safe,
        created_at=datetime.now(UTC),
        seq=seq,
        prev_hash=prev_hash,
    )
    event.hash = _event_hash(event)
    db.add(event)
    db.flush()
    return event


@dataclass
class ChainVerification:
    ok: bool
    checked: int
    head_seq: int | None
    head_hash: str | None
    first_broken_seq: int | None = None
    reason: str | None = None


def verify_chain(db: Session, org_id: uuid.UUID | None, batch: int = 1000) -> ChainVerification:
    """Recompute every hash in one chain, oldest first."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    head: AuditEvent | None = None
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.org_id.is_not_distinct_from(org_id))
        .order_by(AuditEvent.seq)
        .execution_options(yield_per=batch)
    )
    for e in db.scalars(stmt):
        checked += 1
        reason = None
        if e.seq != expected_seq:
            reason = f"expected event {expected_seq}, found {e.seq} (missing or reordered events)"
        elif e.prev_hash != expected_prev:
            reason = "previous-hash link does not match"
        elif _event_hash(e) != e.hash:
            reason = "event content does not match its hash"
        if reason:
            return ChainVerification(False, checked, e.seq, e.hash, e.seq, reason)
        expected_prev = e.hash
        expected_seq += 1
        head = e
    return ChainVerification(True, checked, head.seq if head else None, head.hash if head else None)
