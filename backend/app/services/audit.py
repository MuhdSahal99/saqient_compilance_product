from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent

# Keys that must never appear in audit metadata.
_FORBIDDEN_KEYS = {"text", "content", "password", "token", "csrf", "body"}


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
    safe = {k: v for k, v in (meta or {}).items() if k not in _FORBIDDEN_KEYS}
    event = AuditEvent(
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        meta=safe,
    )
    db.add(event)
    return event
