"""Trial balance helpers shared by Phase E reconciliations and flux review."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc import CalcError
from app.models import DatasetKind, DatasetVersion, Membership
from app.services import rule_schemas
from app.services.assurance import AssuranceError
from app.services.datasets import DatasetNotReady, load_frame
from app.services.workpapers import PackRules, WorkpaperError, _published

ZERO = Decimal(0)


@dataclass
class Account:
    code: str
    name: str = ""
    balance: Decimal = ZERO
    row_ids: list[int] = field(default_factory=list)


def version(
    db: Session, org_id: uuid.UUID, vid: uuid.UUID, entity_id: uuid.UUID, kind: DatasetKind
) -> DatasetVersion:
    v = db.scalar(
        select(DatasetVersion).where(DatasetVersion.id == vid, DatasetVersion.org_id == org_id)
    )
    if v is None:
        raise LookupError("dataset version")
    if v.dataset.kind is not kind:
        raise AssuranceError(f"Choose a {kind.value.replace('_', ' ')} dataset version.")
    if v.dataset.entity_id != entity_id:
        raise AssuranceError("The dataset belongs to another entity.")
    return v


def accounts(db: Session, org_id: uuid.UUID, vid: uuid.UUID) -> dict[str, Account]:
    """Every account in a trial balance version: summed balance, name and row ids."""
    try:
        _, frame = load_frame(db, vid, org_id)
    except DatasetNotReady as exc:
        raise AssuranceError(str(exc)) from exc
    out: dict[str, Account] = {}
    for r in frame.sort("row_id").to_dicts():
        code = str(r["account_code"]).strip()
        a = out.setdefault(code, Account(code))
        a.name = a.name or str(r.get("account_name") or "")
        a.balance += Decimal(str(r.get("balance") or 0))
        a.row_ids.append(int(r["row_id"]))
    return out


def published(db: Session, org_id: uuid.UUID, vid: uuid.UUID) -> None:
    try:
        _published(db, org_id, vid)
    except WorkpaperError as exc:
        raise AssuranceError(str(exc)) from exc


def require_member(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is not None and not db.scalar(
        select(Membership.id).where(Membership.org_id == org_id, Membership.user_id == user_id)
    ):
        raise AssuranceError("The owner must be a member of this organisation.")


class Rules:
    """Typed reads from one pack version under a prefix, with unverified-rule warnings."""

    def __init__(self, db: Session, org_id: uuid.UUID, vid: uuid.UUID, prefix: str, on: Any):
        self.prefix = prefix
        self.pack = PackRules(db, org_id, vid, on)

    def _get(self, name: str) -> Any:
        try:
            return self.pack.get(f"{self.prefix}.{name}")
        except CalcError as exc:
            raise AssuranceError(str(exc)) from exc

    def decimal(self, name: str, minimum: Decimal = ZERO) -> Decimal:
        try:
            v = Decimal(str(self._get(name)))
        except ArithmeticError as exc:
            raise AssuranceError(f"Rule '{self.prefix}.{name}' must be a number.") from exc
        if v < minimum:
            raise AssuranceError(f"Rule '{self.prefix}.{name}' must be at least {minimum}.")
        return v

    def integer(self, name: str) -> int:
        try:
            return int(self._get(name))
        except (TypeError, ValueError) as exc:
            raise AssuranceError(f"Rule '{self.prefix}.{name}' must be a whole number.") from exc

    def typed(self, name: str) -> Any:
        key = f"{self.prefix}.{name}"
        try:
            return rule_schemas.typed(key, self._get(name))
        except rule_schemas.RuleShapeError as exc:
            raise AssuranceError(f"Rule '{key}': {exc}") from exc

    @property
    def warnings(self) -> list[str]:
        return sorted({w for u in self.pack.used.values() if (w := u.warning())})


def over(value: Decimal, base: Decimal, abs_limit: Decimal, pct_limit: Decimal) -> bool:
    """True when |value| exceeds both the absolute limit and the share of |base|."""
    return abs(value) > abs_limit and abs(value) > pct_limit * abs(base)
