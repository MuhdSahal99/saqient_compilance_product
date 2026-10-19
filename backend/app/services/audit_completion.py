"""Confirmations and the adjustments schedule with the SUD (D7).

Confirmation status moves planned → sent → responded or no_response → closed; each
step records its date or amount, and closing needs a conclusion. Adjustments must
balance; their effect on profit and net assets follows the account → lead schedule
mapping (income and expense sections affect profit; the rest affect net assets).
Passing an adjustment (leaving it unbooked) needs a reason and a reviewer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AdjustmentLine,
    AdjustmentStatus,
    AuditAdjustment,
    AuditConfirmation,
    AuditEngagement,
    ConfirmationStatus,
    Document,
    Finding,
    FsSection,
    User,
)
from app.schemas import AdjustmentDecisionIn, AdjustmentIn, ConfirmationIn, ConfirmationUpdateIn
from app.services import audit
from app.services.engagements import EngagementError, require_open
from app.services.lead_schedules import mappings, materiality, schedules

ZERO = Decimal(0)
PROFIT_SECTIONS = {FsSection.INCOME, FsSection.EXPENSE}
NEXT: dict[ConfirmationStatus, set[ConfirmationStatus]] = {
    ConfirmationStatus.PLANNED: {ConfirmationStatus.SENT},
    ConfirmationStatus.SENT: {ConfirmationStatus.RESPONDED, ConfirmationStatus.NO_RESPONSE},
    ConfirmationStatus.RESPONDED: {ConfirmationStatus.CLOSED},
    ConfirmationStatus.NO_RESPONSE: {ConfirmationStatus.CLOSED, ConfirmationStatus.RESPONDED},
    ConfirmationStatus.CLOSED: set(),
}


def _record(
    db: Session, e: AuditEngagement, actor: User, action: str, obj: str, oid: uuid.UUID, **meta: Any
) -> None:
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action=action,
        object_type=obj,
        object_id=oid,
        meta={"engagement_id": str(e.id), **meta},
    )


# ---------------------------------------------------------------- confirmations


def confirmations(db: Session, e: AuditEngagement) -> list[AuditConfirmation]:
    return list(
        db.scalars(
            select(AuditConfirmation)
            .where(AuditConfirmation.org_id == e.org_id, AuditConfirmation.engagement_id == e.id)
            .order_by(AuditConfirmation.type, AuditConfirmation.counterparty)
        )
    )


def add_confirmation(
    db: Session, e: AuditEngagement, body: ConfirmationIn, actor: User
) -> AuditConfirmation:
    require_open(e)
    c = AuditConfirmation(
        org_id=e.org_id,
        engagement_id=e.id,
        type=body.type,
        counterparty=body.counterparty.strip(),
        reference=body.reference.strip(),
        book_amount=body.book_amount,
        currency=e.currency,
        created_by_id=actor.id,
    )
    db.add(c)
    db.flush()
    _record(db, e, actor, "confirmation.created", "audit_confirmation", c.id, type=body.type.value)
    return c


def update_confirmation(
    db: Session, e: AuditEngagement, c: AuditConfirmation, body: ConfirmationUpdateIn, actor: User
) -> None:
    require_open(e)
    if body.status not in NEXT[c.status]:
        raise EngagementError(
            f"A confirmation that is {c.status.value.replace('_', ' ')} cannot move to "
            f"{body.status.value.replace('_', ' ')}."
        )
    if body.status is ConfirmationStatus.SENT:
        if body.sent_on is None:
            raise EngagementError("Give the date the request was sent.")
        c.sent_on = body.sent_on
    elif body.status is ConfirmationStatus.RESPONDED:
        if body.responded_on is None or body.confirmed_amount is None:
            raise EngagementError("Give the response date and the confirmed amount.")
        if c.sent_on and body.responded_on < c.sent_on:
            raise EngagementError("The response cannot be dated before the request was sent.")
        if body.response_document_id is not None:
            doc = db.scalar(
                select(Document.id).where(
                    Document.id == body.response_document_id, Document.org_id == e.org_id
                )
            )
            if doc is None:
                raise LookupError("document")
        c.responded_on, c.confirmed_amount = body.responded_on, body.confirmed_amount
        c.response_document_id = body.response_document_id
    elif body.status is ConfirmationStatus.CLOSED:
        if not body.conclusion.strip():
            raise EngagementError("Record the conclusion (including any alternative procedures).")
        c.conclusion = body.conclusion.strip()
    previous = c.status
    c.status = body.status
    db.flush()
    _record(
        db,
        e,
        actor,
        "confirmation.status_changed",
        "audit_confirmation",
        c.id,
        **{"from": previous.value, "to": body.status.value},
    )


def difference(c: AuditConfirmation) -> Decimal | None:
    return None if c.confirmed_amount is None else c.book_amount - c.confirmed_amount


# ---------------------------------------------------------------- adjustments


def adjustments(db: Session, e: AuditEngagement) -> list[AuditAdjustment]:
    return list(
        db.scalars(
            select(AuditAdjustment)
            .where(AuditAdjustment.org_id == e.org_id, AuditAdjustment.engagement_id == e.id)
            .order_by(AuditAdjustment.ref)
        ).unique()
    )


def save_adjustment(
    db: Session,
    e: AuditEngagement,
    body: AdjustmentIn,
    actor: User,
    adj: AuditAdjustment | None = None,
) -> AuditAdjustment:
    require_open(e)
    if adj is not None and adj.status is not AdjustmentStatus.PROPOSED:
        raise EngagementError("Only a proposed adjustment can be changed.")
    debits = sum((ln.debit for ln in body.lines), ZERO)
    credits = sum((ln.credit for ln in body.lines), ZERO)
    if debits != credits:
        raise EngagementError(
            f"The adjustment does not balance: debits {debits}, credits {credits}."
        )
    clash = db.scalar(
        select(AuditAdjustment.id).where(
            AuditAdjustment.engagement_id == e.id,
            AuditAdjustment.ref == body.ref,
            AuditAdjustment.id != (adj.id if adj else uuid.uuid4()),
        )
    )
    if clash:
        raise EngagementError(f"Adjustment {body.ref} already exists.")
    if (
        body.finding_id is not None
        and db.scalar(
            select(Finding.id).where(Finding.id == body.finding_id, Finding.org_id == e.org_id)
        )
        is None
    ):
        raise LookupError("finding")
    created = adj is None
    a = adj or AuditAdjustment(org_id=e.org_id, engagement_id=e.id, created_by_id=actor.id)
    a.ref, a.description, a.finding_id = body.ref, body.description.strip(), body.finding_id
    a.lines = [
        AdjustmentLine(
            org_id=e.org_id,
            ordinal=i,
            account_code=ln.account_code.strip(),
            debit=ln.debit,
            credit=ln.credit,
        )
        for i, ln in enumerate(body.lines)
    ]
    db.add(a)
    db.flush()
    _record(
        db,
        e,
        actor,
        "adjustment.created" if created else "adjustment.updated",
        "audit_adjustment",
        a.id,
        ref=a.ref,
        total=str(debits),
    )
    return a


def decide_adjustment(
    db: Session,
    e: AuditEngagement,
    a: AuditAdjustment,
    body: AdjustmentDecisionIn,
    actor: User,
    can_decide: bool,
) -> None:
    require_open(e)
    reason = body.reason.strip()
    if body.status is a.status:
        raise EngagementError("The adjustment already has that status.")
    if body.status is AdjustmentStatus.PASSED:
        if not can_decide:
            raise PermissionError("Only a reviewer or admin can pass an adjustment.")
        if not reason:
            raise EngagementError("Passing an adjustment needs a reason.")
    if body.status is AdjustmentStatus.PROPOSED and not reason:
        raise EngagementError("Reopening an adjustment needs a reason.")
    previous = a.status
    a.status, a.reason = body.status, reason or a.reason
    a.decided_by_id, a.decided_at = actor.id, now()
    db.flush()
    _record(
        db,
        e,
        actor,
        "adjustment.status_changed",
        "audit_adjustment",
        a.id,
        **{"from": previous.value, "to": body.status.value, "reason": reason},
    )


def effects(db: Session, e: AuditEngagement) -> dict[str, tuple[str, FsSection]]:
    """Account code → (lead code, section) from the engagement's mapping."""
    by_code = {s.code: s.section for s in schedules(db, e)}
    return {acct: (lead, by_code[lead]) for acct, lead in mappings(db, e)}


def adjustment_view(a: AuditAdjustment, eff: dict[str, tuple[str, FsSection]]) -> dict[str, Any]:
    profit = net_assets = ZERO
    unmapped: list[str] = []
    lines = []
    for ln in a.lines:
        lead, section = eff.get(ln.account_code, (None, None))
        net = ln.debit - ln.credit
        if section is None:
            unmapped.append(ln.account_code)
        elif section in PROFIT_SECTIONS:
            profit -= net  # a debit to income or expense reduces profit
        elif section is not FsSection.EQUITY:
            net_assets += net
        lines.append(
            {
                "account_code": ln.account_code,
                "debit": ln.debit,
                "credit": ln.credit,
                "lead_code": lead,
                "section": section,
            }
        )
    return {
        "id": a.id,
        "ref": a.ref,
        "description": a.description,
        "status": a.status,
        "reason": a.reason,
        "finding_id": a.finding_id,
        "lines": lines,
        "profit_effect": profit,
        "net_assets_effect": net_assets,
        "unmapped_accounts": sorted(set(unmapped)),
    }


def sud(db: Session, e: AuditEngagement) -> dict[str, Any]:
    eff = effects(db, e)
    passed = [
        adjustment_view(a, eff) for a in adjustments(db, e) if a.status is AdjustmentStatus.PASSED
    ]
    profit = sum((a["profit_effect"] for a in passed), ZERO)
    net_assets = sum((a["net_assets_effect"] for a in passed), ZERO)
    mat = materiality(db, e)
    steps = [
        {
            "label": "Profit effect of passed adjustments",
            "expression": " + ".join(f"{a['ref']} {a['profit_effect']}" for a in passed) or "none",
            "value": str(profit),
        },
        {
            "label": "Net assets effect of passed adjustments",
            "expression": " + ".join(f"{a['ref']} {a['net_assets_effect']}" for a in passed)
            or "none",
            "value": str(net_assets),
        },
    ]
    trivial: list[str] = []
    verdict = "not_determinable"
    if mat and mat.get("overall") is not None:
        overall = mat["overall"]
        largest = max(abs(profit), abs(net_assets))
        verdict = "at_or_above" if largest >= overall else "below"
        steps.append(
            {
                "label": "Larger effect against overall materiality",
                "expression": f"max(|{profit}|, |{net_assets}|) = {largest} vs {overall}",
                "value": verdict,
            }
        )
        if mat.get("trivial") is not None:
            t = mat["trivial"]
            trivial = [
                a["ref"]
                for a in passed
                if max(abs(a["profit_effect"]), abs(a["net_assets_effect"])) <= t
            ]
            steps.append(
                {
                    "label": "Clearly trivial items",
                    "expression": f"effect ≤ {t}",
                    "value": ", ".join(trivial) or "none",
                }
            )
    return {
        "adjustments": passed,
        "profit_effect": profit,
        "net_assets_effect": net_assets,
        "materiality": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in mat.items()}
        if mat
        else None,
        "clearly_trivial": trivial,
        "total_vs_overall": verdict,
        "steps": steps,
    }
