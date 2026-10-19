"""Tax loss register, loss transfers and tax group membership history (Phase C3).

The register is a list of positive movements per entity; the balance is incurred
+ transferred in − used − transferred out − forfeited. A signed-off corporate tax
workpaper posts its loss incurred and losses used once. Transfers are checked
against the pack's conditions first; a result that is not met is refused, and a
met result is still a proposal recorded with its explanation for a reviewer.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import calc
from app.models import (
    LegalEntity,
    LineSource,
    LossEntryKind,
    TaxGroup,
    TaxGroupMembership,
    TaxLossEntry,
    TaxWorkpaper,
    User,
    WorkpaperKind,
    WorkpaperStatus,
)
from app.schemas import GroupTestIn, LossEntryIn, LossTransferIn, MembershipIn, WorkpaperInputIn
from app.services import audit
from app.services.workpapers import (
    Evaluation,
    WorkpaperError,
    evaluate,
    put_input,
    resolve_evidence,
)

ZERO = Decimal(0)
SIGN = {
    LossEntryKind.INCURRED: 1,
    LossEntryKind.TRANSFERRED_IN: 1,
    LossEntryKind.USED: -1,
    LossEntryKind.TRANSFERRED_OUT: -1,
    LossEntryKind.FORFEITED: -1,
}


class LossError(WorkpaperError):
    pass


def signed(e: TaxLossEntry) -> Decimal:
    return e.amount * SIGN[e.kind]


def entries(db: Session, entity: LegalEntity) -> list[TaxLossEntry]:
    return list(
        db.scalars(
            select(TaxLossEntry)
            .where(TaxLossEntry.org_id == entity.org_id, TaxLossEntry.entity_id == entity.id)
            .order_by(TaxLossEntry.period_end, TaxLossEntry.created_at)
        ).unique()
    )


def balance(db: Session, entity: LegalEntity, before: date | None = None) -> Decimal:
    """Balance of movements for periods ending before ``before`` (or all)."""
    return sum(
        (signed(e) for e in entries(db, entity) if before is None or e.period_end < before),
        ZERO,
    )


def _check_period(start: date, end: date) -> None:
    if end < start:
        raise LossError("The period must end after it starts.")


def _record(db: Session, e: TaxLossEntry, actor: User, action: str) -> None:
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action=action,
        object_type="tax_loss_entry",
        object_id=e.id,
        meta={"entity_id": str(e.entity_id), "kind": e.kind.value, "amount": str(e.amount)},
    )


def add_entry(db: Session, entity: LegalEntity, body: LossEntryIn, actor: User) -> TaxLossEntry:
    _check_period(body.period_start, body.period_end)
    kind = LossEntryKind(body.kind)
    if SIGN[kind] < 0 and body.amount > balance(db, entity):
        raise LossError("That is more than the entity's loss balance.")
    e = TaxLossEntry(
        org_id=entity.org_id,
        entity_id=entity.id,
        kind=kind,
        period_start=body.period_start,
        period_end=body.period_end,
        amount=body.amount,
        currency=entity.functional_currency,
        evidence=resolve_evidence(db, entity.org_id, body.evidence),
        note=body.note,
        explanation=[],
        rule_snapshots=[],
        created_by_id=actor.id,
    )
    db.add(e)
    db.flush()
    _record(db, e, actor, "tax_loss.recorded")
    return e


def _computed(wp: TaxWorkpaper, key: str) -> Decimal | None:
    ln = next(
        (x for x in wp.lines if x.source is LineSource.COMPUTED and x.line_key == f"calc:{key}"),
        None,
    )
    return ln.amount if ln else None


def post_workpaper(
    db: Session, wp: TaxWorkpaper, actor: User
) -> tuple[list[TaxLossEntry], list[str]]:
    """Post a signed-off CT workpaper's loss incurred and losses used (once each)."""
    if wp.kind is not WorkpaperKind.CORPORATE_TAX:
        raise LossError("Only corporate tax workpapers feed the loss register.")
    if wp.status is not WorkpaperStatus.SIGNED_OFF:
        raise LossError("Sign the workpaper off before posting it to the loss register.")
    before = _computed(wp, "taxable_income_before_losses")
    used = _computed(wp, "losses_used")
    if before is None or used is None:
        raise LossError("The workpaper has no computed loss lines.")
    entity = wp.entity
    warnings: list[str] = []
    bf_line = next((x for x in wp.lines if x.line_key == "losses_brought_forward"), None)
    bf = bf_line.amount if bf_line and bf_line.amount is not None else ZERO
    reg = balance(db, entity, before=wp.period_start)
    if bf != reg:
        warnings.append(
            f"Losses brought forward in the workpaper ({bf}) differ from the register "
            f"balance before the period ({reg})."
        )
    existing = set(db.scalars(select(TaxLossEntry.kind).where(TaxLossEntry.workpaper_id == wp.id)))
    created: list[TaxLossEntry] = []
    for kind, amount, step in (
        (LossEntryKind.INCURRED, -before if before < 0 else ZERO, "loss for the period"),
        (LossEntryKind.USED, used, "losses used against taxable income"),
    ):
        if amount <= 0 or kind in existing:
            continue
        line = (
            "calc:taxable_income_before_losses"
            if kind is LossEntryKind.INCURRED
            else ("calc:losses_used")
        )
        e = TaxLossEntry(
            org_id=wp.org_id,
            entity_id=wp.entity_id,
            kind=kind,
            period_start=wp.period_start,
            period_end=wp.period_end,
            amount=amount,
            currency=wp.currency,
            workpaper_id=wp.id,
            explanation=[
                {"label": f"From workpaper: {step}", "expression": line, "value": str(amount)}
            ],
            rule_snapshots=[],
            evidence=[
                {
                    "kind": "workpaper_line",
                    "workpaper_id": str(wp.id),
                    "workpaper_title": wp.title,
                    "line_key": line,
                    "result_hash": wp.result_hash,
                }
            ],
            note="",
            created_by_id=actor.id,
        )
        db.add(e)
        db.flush()
        _record(db, e, actor, "tax_loss.posted")
        created.append(e)
    return created, warnings


def transfer(
    db: Session,
    source: LegalEntity,
    target: LegalEntity,
    body: LossTransferIn,
    actor: User,
) -> tuple[list[TaxLossEntry], Evaluation]:
    _check_period(body.period_start, body.period_end)
    if source.id == target.id:
        raise LossError("Choose two different entities.")
    if source.functional_currency != target.functional_currency:
        raise LossError("Both entities must use the same currency.")
    available = balance(db, source)
    flag = lambda b: "true" if b else "false"  # noqa: E731
    lines = [
        calc.InputLine("amount", "input", body.amount, None, "Amount to transfer"),
        calc.InputLine("available_balance", "input", available, None, "Available losses"),
        calc.InputLine(
            "common_ownership", "input", body.common_ownership, None, "Common ownership"
        ),
        calc.InputLine(
            "same_business_continuity",
            "input",
            None,
            flag(body.same_business_continuity),
            "Ownership continuity",
        ),
        calc.InputLine("both_resident", "input", None, flag(body.both_resident), "Residence"),
    ]
    ev = evaluate(
        db,
        source.org_id,
        body.rule_pack_version_id,
        body.rules_prefix,
        body.period_end,
        "loss_transfer",
        lines,
    )
    if ev.overall() != "met":
        failed = [o.label for o in ev.outputs if o.section == "test" and o.value != "met"]
        raise LossError("The transfer does not meet: " + "; ".join(failed) + ".")
    evidence = resolve_evidence(db, source.org_id, body.evidence)
    tid = uuid.uuid4()
    explanation = [s for line in ev.lines() for s in line["explanation"]]
    snaps = list(ev.rules.values())
    made: list[TaxLossEntry] = []
    for entity, other, kind in (
        (source, target, LossEntryKind.TRANSFERRED_OUT),
        (target, source, LossEntryKind.TRANSFERRED_IN),
    ):
        e = TaxLossEntry(
            org_id=source.org_id,
            entity_id=entity.id,
            kind=kind,
            period_start=body.period_start,
            period_end=body.period_end,
            amount=body.amount,
            currency=entity.functional_currency,
            counterparty_entity_id=other.id,
            transfer_id=tid,
            explanation=explanation,
            rule_snapshots=snaps,
            evidence=evidence,
            note=body.note,
            created_by_id=actor.id,
        )
        db.add(e)
        db.flush()
        _record(db, e, actor, "tax_loss.transferred")
        made.append(e)
    return made, ev


def prefill_workpaper(db: Session, wp: TaxWorkpaper, actor: User) -> None:
    """Set a CT workpaper's losses brought forward from the register."""
    if wp.kind is not WorkpaperKind.CORPORATE_TAX:
        raise LossError("Only corporate tax workpapers take losses brought forward.")
    prior = [e for e in entries(db, wp.entity) if e.period_end < wp.period_start]
    amount = sum((signed(e) for e in prior), ZERO)
    line = put_input(
        db,
        wp,
        "losses_brought_forward",
        WorkpaperInputIn(label="Tax losses brought forward (register)", amount=amount),
        actor,
    )
    line.evidence = [
        {
            "kind": "loss_register",
            "entity_id": str(wp.entity_id),
            "before": wp.period_start.isoformat(),
            "entry_ids": [str(e.id) for e in prior],
            "balance": str(amount),
        }
    ]
    db.flush()


# ---------------------------------------------------------------- tax groups


def memberships(db: Session, group: TaxGroup) -> list[TaxGroupMembership]:
    return list(
        db.scalars(
            select(TaxGroupMembership)
            .where(
                TaxGroupMembership.org_id == group.org_id,
                TaxGroupMembership.tax_group_id == group.id,
            )
            .order_by(TaxGroupMembership.joined_on)
        ).unique()
    )


def _overlaps(start: date, end: date | None):  # type: ignore[no-untyped-def]
    far = date.max
    return and_(
        TaxGroupMembership.joined_on <= (end or far),
        or_(TaxGroupMembership.left_on.is_(None), TaxGroupMembership.left_on >= start),
    )


def add_membership(
    db: Session, group: TaxGroup, entity: LegalEntity, body: MembershipIn, actor: User
) -> TaxGroupMembership:
    if body.left_on is not None and body.left_on < body.joined_on:
        raise LossError("The membership must end after it starts.")
    clash = db.scalar(
        select(TaxGroupMembership.id).where(
            TaxGroupMembership.org_id == group.org_id,
            TaxGroupMembership.entity_id == entity.id,
            _overlaps(body.joined_on, body.left_on),
        )
    )
    if clash:
        raise LossError("The entity already belongs to a tax group for part of that time.")
    if body.is_parent and db.scalar(
        select(TaxGroupMembership.id).where(
            TaxGroupMembership.tax_group_id == group.id,
            TaxGroupMembership.is_parent.is_(True),
            _overlaps(body.joined_on, body.left_on),
        )
    ):
        raise LossError("The group already has a parent for part of that time.")
    m = TaxGroupMembership(
        org_id=group.org_id,
        tax_group_id=group.id,
        entity_id=entity.id,
        is_parent=body.is_parent,
        ownership_share=Decimal(1) if body.is_parent else body.ownership_share,
        joined_on=body.joined_on,
        left_on=body.left_on,
        evidence=resolve_evidence(db, group.org_id, body.evidence),
        note=body.note,
        created_by_id=actor.id,
    )
    db.add(m)
    db.flush()
    audit.record(
        db,
        org_id=group.org_id,
        actor_id=actor.id,
        action="tax_group.member_added",
        object_type="tax_group",
        object_id=group.id,
        meta={"entity_id": str(entity.id), "joined_on": body.joined_on.isoformat()},
    )
    return m


def end_membership(
    db: Session, m: TaxGroupMembership, left_on: date, note: str, actor: User
) -> None:
    if m.left_on is not None:
        raise LossError("That membership has already ended.")
    if left_on < m.joined_on:
        raise LossError("The membership must end after it starts.")
    m.left_on = left_on
    m.note = (m.note + "\n" if m.note else "") + note
    db.flush()
    audit.record(
        db,
        org_id=m.org_id,
        actor_id=actor.id,
        action="tax_group.member_left",
        object_type="tax_group",
        object_id=m.tax_group_id,
        meta={"entity_id": str(m.entity_id), "left_on": left_on.isoformat()},
    )


def group_test(db: Session, group: TaxGroup, body: GroupTestIn, actor: User) -> Evaluation:
    active = [
        m
        for m in memberships(db, group)
        if m.joined_on <= body.on and (m.left_on is None or m.left_on >= body.on)
    ]
    parent = next((m for m in active if m.is_parent), None)
    if parent is None:
        raise LossError("The group has no parent on that date.")
    pe = parent.entity
    lines: list[calc.InputLine] = []
    for i, m in enumerate((m for m in active if not m.is_parent), start=1):
        key = f"member_{i}"
        e = m.entity
        same = (e.fiscal_year_end_month, e.fiscal_year_end_day) == (
            pe.fiscal_year_end_month,
            pe.fiscal_year_end_day,
        )
        lines.append(calc.InputLine(key, "member", m.ownership_share, None, e.name))
        lines.append(
            calc.InputLine(
                f"{key}_same_year_end", "input", None, "true" if same else "false", e.name
            )
        )
    ev = evaluate(
        db,
        group.org_id,
        body.rule_pack_version_id,
        body.rules_prefix,
        body.on,
        "tax_group_test",
        lines,
    )
    audit.record(
        db,
        org_id=group.org_id,
        actor_id=actor.id,
        action="tax_group.tested",
        object_type="tax_group",
        object_id=group.id,
        meta={"on": body.on.isoformat(), "result_hash": ev.result_hash, "result": ev.overall()},
    )
    return ev
