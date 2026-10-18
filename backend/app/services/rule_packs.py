"""Rule packs: versioned tax/regulatory parameters held as data.

Values are stored as strings and parsed by their declared type, so rates and
thresholds are exact (Decimal), never floats. Only organisation admins can mark
a rule verified, and only when it has an official source URL and no open TODO.
Checks that use a draft rule carry an "unverified rule" warning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    ChecklistState,
    Rule,
    RulePack,
    RulePackVersion,
    RuleValueType,
    RuleVerification,
    User,
)
from app.schemas import RuleIn
from app.services import audit

UNVERIFIED_WARNING = "Unverified rule: {key} ({pack} v{version}) has not been verified by an admin."


class RuleValueError(ValueError):
    pass


def parse_value(value_type: RuleValueType, raw: str) -> Any:
    raw = raw.strip()
    try:
        if value_type is RuleValueType.DECIMAL:
            d = Decimal(raw)
            if not d.is_finite():
                raise RuleValueError("not a finite number")
            return d
        if value_type is RuleValueType.INTEGER:
            if not raw.lstrip("-").isdigit():
                raise RuleValueError("not an integer")
            return int(raw)
        if value_type is RuleValueType.BOOLEAN:
            if raw not in ("true", "false"):
                raise RuleValueError("use true or false")
            return raw == "true"
        if value_type is RuleValueType.DATE:
            return date.fromisoformat(raw)
        return raw
    except (InvalidOperation, ValueError) as exc:
        if isinstance(exc, RuleValueError):
            raise
        raise RuleValueError(f"not a valid {value_type.value}") from exc


def validate_rules(rules: list[RuleIn]) -> None:
    by_key: dict[str, list[RuleIn]] = {}
    for r in rules:
        try:
            parse_value(r.value_type, r.value)
        except RuleValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{r.rule_key}: {exc}."
            ) from exc
        if r.effective_to is not None and r.effective_to < r.effective_from:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{r.rule_key}: effective_to is before effective_from.",
            )
        by_key.setdefault(r.rule_key, []).append(r)
    for key, items in by_key.items():
        if len({i.value_type for i in items}) > 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key}: all periods need the same type."
            )
        items.sort(key=lambda i: i.effective_from)
        for a, b in zip(items, items[1:], strict=False):
            if a.effective_to is None or a.effective_to >= b.effective_from:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key}: effective periods overlap."
                )


def _identity(r: Rule) -> tuple[Any, ...]:
    return (
        r.rule_key,
        RuleValueType(r.value_type),
        r.value.strip(),
        r.unit,
        r.effective_from,
        r.effective_to,
        r.source_url,
    )


def replace_rules(db: Session, v: RulePackVersion, rules: list[RuleIn], actor: User) -> None:
    if v.state != ChecklistState.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Published rule pack versions are immutable.")
    validate_rules(rules)
    # A verification survives an edit only if nothing it vouched for changed.
    kept = {_identity(old): old for old in v.rules if old.verification_status.value == "verified"}
    carried: dict[tuple[Any, ...], tuple[uuid.UUID | None, datetime | None]] = {
        k: (o.verified_by_id, o.verified_at) for k, o in kept.items()
    }
    for old in list(v.rules):
        db.delete(old)
    db.flush()
    for r in rules:
        new = Rule(org_id=v.org_id, rule_pack_version_id=v.id, **r.model_dump())
        prior = carried.get(_identity(new))
        if prior and not new.todo.strip():
            new.verification_status = RuleVerification.VERIFIED
            new.verified_by_id, new.verified_at = prior
        db.add(new)
    audit.record(
        db,
        org_id=v.org_id,
        actor_id=actor.id,
        action="rule_pack.rules_replaced",
        object_type="rule_pack_version",
        object_id=v.id,
        meta={"rules": len(rules)},
    )


def create_pack(
    db: Session, org_id: uuid.UUID, name: str, jurisdiction: str, description: str, actor: User
) -> RulePack:
    pack = RulePack(
        org_id=org_id,
        name=name.strip(),
        jurisdiction=jurisdiction,
        description=description,
        is_synthetic=jurisdiction == "SYNTHETIC",
    )
    db.add(pack)
    db.flush()
    db.add(RulePackVersion(org_id=org_id, rule_pack_id=pack.id, version_number=1))
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor.id,
        action="rule_pack.created",
        object_type="rule_pack",
        object_id=pack.id,
        meta={"jurisdiction": jurisdiction},
    )
    return pack


def publish(db: Session, v: RulePackVersion, actor: User) -> None:
    if v.state != ChecklistState.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only drafts can be published.")
    if not v.rules:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A rule pack needs at least one rule."
        )
    for other in v.rule_pack.versions:
        if other.id != v.id and other.state == ChecklistState.PUBLISHED:
            other.state = ChecklistState.ARCHIVED
    v.state = ChecklistState.PUBLISHED
    v.published_at = datetime.now(UTC)
    v.published_by_id = actor.id
    audit.record(
        db,
        org_id=v.org_id,
        actor_id=actor.id,
        action="rule_pack.published",
        object_type="rule_pack_version",
        object_id=v.id,
        meta={"version": v.version_number},
    )


def new_draft(db: Session, pack: RulePack, actor: User) -> RulePackVersion:
    if any(v.state == ChecklistState.DRAFT for v in pack.versions):
        raise HTTPException(status.HTTP_409_CONFLICT, "A draft already exists for this rule pack.")
    base = pack.versions[-1]
    v = RulePackVersion(
        org_id=pack.org_id, rule_pack_id=pack.id, version_number=base.version_number + 1
    )
    db.add(v)
    db.flush()
    for r in base.rules:
        # Copied as-is, verification included; replace_rules drops it if the rule changes.
        db.add(
            Rule(
                org_id=pack.org_id,
                rule_pack_version_id=v.id,
                rule_key=r.rule_key,
                title=r.title,
                value_type=r.value_type,
                value=r.value,
                unit=r.unit,
                effective_from=r.effective_from,
                effective_to=r.effective_to,
                source_url=r.source_url,
                source_note=r.source_note,
                todo=r.todo,
                verification_status=r.verification_status,
                verified_by_id=r.verified_by_id,
                verified_at=r.verified_at,
            )
        )
    audit.record(
        db,
        org_id=pack.org_id,
        actor_id=actor.id,
        action="rule_pack.draft_created",
        object_type="rule_pack_version",
        object_id=v.id,
        meta={"version": v.version_number},
    )
    return v


def set_verification(db: Session, rule: Rule, verified: bool, actor: User) -> None:
    if verified:
        if not rule.source_url:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Add an official source URL before verifying this rule.",
            )
        if rule.todo.strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Resolve the open question (TODO) before verifying this rule.",
            )
        if rule.version.rule_pack.is_synthetic:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Synthetic demonstration rules cannot be verified.",
            )
        rule.verification_status = RuleVerification.VERIFIED
        rule.verified_by_id = actor.id
        rule.verified_at = datetime.now(UTC)
    else:
        rule.verification_status = RuleVerification.DRAFT
        rule.verified_by_id = None
        rule.verified_at = None
    audit.record(
        db,
        org_id=rule.org_id,
        actor_id=actor.id,
        action="rule.verified" if verified else "rule.unverified",
        object_type="rule",
        object_id=rule.id,
        meta={"rule_key": rule.rule_key, "version_id": str(rule.rule_pack_version_id)},
    )


@dataclass(frozen=True)
class ResolvedRule:
    """A rule value as used by a check, with everything needed to reproduce it."""

    rule_id: uuid.UUID
    rule_key: str
    value: Any
    raw_value: str
    value_type: RuleValueType
    unit: str
    rule_pack_version_id: uuid.UUID
    pack_name: str
    pack_version: int
    verification_status: RuleVerification
    effective_from: date
    effective_to: date | None

    @property
    def verified(self) -> bool:
        return self.verification_status is RuleVerification.VERIFIED

    def warning(self) -> str | None:
        if self.verified:
            return None
        return UNVERIFIED_WARNING.format(
            key=self.rule_key, pack=self.pack_name, version=self.pack_version
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "rule_id": str(self.rule_id),
            "rule_key": self.rule_key,
            "value": self.raw_value,
            "value_type": self.value_type.value,
            "unit": self.unit,
            "rule_pack_version_id": str(self.rule_pack_version_id),
            "pack_name": self.pack_name,
            "pack_version": self.pack_version,
            "verification_status": self.verification_status.value,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
        }


class RuleNotFound(LookupError):
    pass


def resolve(
    db: Session, org_id: uuid.UUID, version_id: uuid.UUID, rule_key: str, on: date
) -> ResolvedRule:
    """The rule in one pack version that is effective on ``on``. Tenant-scoped."""
    rule = db.scalar(
        select(Rule).where(
            Rule.org_id == org_id,
            Rule.rule_pack_version_id == version_id,
            Rule.rule_key == rule_key,
            Rule.effective_from <= on,
            or_(Rule.effective_to.is_(None), and_(Rule.effective_to >= on)),
        )
    )
    if rule is None:
        raise RuleNotFound(f"No rule '{rule_key}' effective on {on.isoformat()}.")
    v = rule.version
    return ResolvedRule(
        rule_id=rule.id,
        rule_key=rule.rule_key,
        value=parse_value(rule.value_type, rule.value),
        raw_value=rule.value,
        value_type=rule.value_type,
        unit=rule.unit,
        rule_pack_version_id=v.id,
        pack_name=v.rule_pack.name,
        pack_version=v.version_number,
        verification_status=rule.verification_status,
        effective_from=rule.effective_from,
        effective_to=rule.effective_to,
    )
