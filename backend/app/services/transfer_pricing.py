"""Transfer pricing register, documentation threshold check and disclosure export (C4).

Benchmarking studies are ordinary documents (uploaded and extracted through the
document pipeline) linked to transactions by id. Amounts are in the entity's
functional currency so totals can be compared with pack thresholds.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import calc
from app.models import (
    Document,
    LegalEntity,
    RelatedParty,
    RelatedPartyTransaction,
    User,
)
from app.schemas import RelatedPartyIn, RPTransactionIn, TPCheckIn
from app.services import audit
from app.services.reports import csv_safe
from app.services.workpapers import Evaluation, WorkpaperError, evaluate, resolve_evidence


class TPError(WorkpaperError):
    pass


def parties(db: Session, entity: LegalEntity) -> list[RelatedParty]:
    return list(
        db.scalars(
            select(RelatedParty)
            .where(RelatedParty.org_id == entity.org_id, RelatedParty.entity_id == entity.id)
            .order_by(RelatedParty.name)
        )
    )


def add_party(db: Session, entity: LegalEntity, body: RelatedPartyIn, actor: User) -> RelatedParty:
    name = body.name.strip()
    if any(p.name == name for p in parties(db, entity)):
        raise TPError("A related party with that name already exists for this entity.")
    p = RelatedParty(
        org_id=entity.org_id,
        entity_id=entity.id,
        name=name,
        relation=body.relation,
        jurisdiction=body.jurisdiction,
        note=body.note,
    )
    db.add(p)
    db.flush()
    audit.record(
        db,
        org_id=entity.org_id,
        actor_id=actor.id,
        action="related_party.created",
        object_type="related_party",
        object_id=p.id,
        meta={"entity_id": str(entity.id), "relation": body.relation.value},
    )
    return p


def delete_party(db: Session, p: RelatedParty, actor: User) -> None:
    if db.scalar(
        select(RelatedPartyTransaction.id).where(RelatedPartyTransaction.related_party_id == p.id)
    ):
        raise TPError("Delete the party's transactions first.")
    audit.record(
        db,
        org_id=p.org_id,
        actor_id=actor.id,
        action="related_party.deleted",
        object_type="related_party",
        object_id=p.id,
        meta={"entity_id": str(p.entity_id)},
    )
    db.delete(p)
    db.flush()


def transactions(
    db: Session, entity: LegalEntity, start: date | None = None, end: date | None = None
) -> list[RelatedPartyTransaction]:
    stmt = select(RelatedPartyTransaction).where(
        RelatedPartyTransaction.org_id == entity.org_id,
        RelatedPartyTransaction.entity_id == entity.id,
    )
    # A transaction belongs to a period when its own period lies inside it.
    if start:
        stmt = stmt.where(RelatedPartyTransaction.period_start >= start)
    if end:
        stmt = stmt.where(RelatedPartyTransaction.period_end <= end)
    return list(
        db.scalars(
            stmt.order_by(RelatedPartyTransaction.period_start, RelatedPartyTransaction.created_at)
        ).unique()
    )


def documents(db: Session, org_id: uuid.UUID, ids: list[str]) -> list[dict[str, str]]:
    if not ids:
        return []
    rows = db.execute(
        select(Document.id, Document.title).where(
            Document.org_id == org_id, Document.id.in_([uuid.UUID(i) for i in ids])
        )
    ).all()
    titles = {str(i): t for i, t in rows}
    return [{"id": i, "title": titles[i]} for i in ids if i in titles]


def add_transaction(
    db: Session, entity: LegalEntity, party: RelatedParty, body: RPTransactionIn, actor: User
) -> RelatedPartyTransaction:
    if party.entity_id != entity.id:
        raise LookupError("Not found.")
    if body.period_end < body.period_start:
        raise TPError("The period must end after it starts.")
    currency = body.currency or entity.functional_currency
    if currency != entity.functional_currency:
        raise TPError(f"Enter amounts in the entity's currency ({entity.functional_currency}).")
    doc_ids = [str(i) for i in dict.fromkeys(body.benchmark_document_ids)]
    if len(documents(db, entity.org_id, doc_ids)) != len(doc_ids):
        raise TPError("A benchmarking document was not found.")
    t = RelatedPartyTransaction(
        org_id=entity.org_id,
        entity_id=entity.id,
        related_party_id=party.id,
        period_start=body.period_start,
        period_end=body.period_end,
        transaction_type=body.transaction_type,
        direction=body.direction,
        description=body.description,
        amount=body.amount,
        currency=currency,
        method=body.method,
        range_low=body.range_low,
        range_high=body.range_high,
        tested_value=body.tested_value,
        range_metric=body.range_metric,
        benchmark_document_ids=doc_ids,
        evidence=resolve_evidence(db, entity.org_id, body.evidence),
        created_by_id=actor.id,
    )
    db.add(t)
    db.flush()
    audit.record(
        db,
        org_id=entity.org_id,
        actor_id=actor.id,
        action="rp_transaction.created",
        object_type="rp_transaction",
        object_id=t.id,
        meta={"entity_id": str(entity.id), "type": body.transaction_type.value},
    )
    return t


def delete_transaction(db: Session, t: RelatedPartyTransaction, actor: User) -> None:
    audit.record(
        db,
        org_id=t.org_id,
        actor_id=actor.id,
        action="rp_transaction.deleted",
        object_type="rp_transaction",
        object_id=t.id,
        meta={"entity_id": str(t.entity_id)},
    )
    db.delete(t)
    db.flush()


def check(
    db: Session, entity: LegalEntity, body: TPCheckIn, actor: User
) -> tuple[Evaluation, Decimal, int]:
    if body.period_end < body.period_start:
        raise TPError("The period must end after it starts.")
    txns = transactions(db, entity, body.period_start, body.period_end)
    total = sum((t.amount for t in txns), Decimal(0))
    lines = [
        calc.InputLine("entity_revenue", "input", body.entity_revenue, None, "Entity revenue"),
        calc.InputLine("rp_total", "input", total, None, "Related-party transactions"),
    ]
    if body.in_mne_group is not None:
        lines.append(
            calc.InputLine(
                "in_mne_group", "input", None, str(body.in_mne_group).lower(), "In an MNE group"
            )
        )
    if body.group_revenue is not None:
        lines.append(
            calc.InputLine("group_revenue", "input", body.group_revenue, None, "Group revenue")
        )
    for i, t in enumerate(txns, start=1):
        if t.range_low is None or t.range_high is None or t.tested_value is None:
            continue
        key = f"{t.party.name[:40]} {t.transaction_type.value} #{i}"
        for part, v in (("low", t.range_low), ("high", t.range_high), ("tested", t.tested_value)):
            lines.append(calc.InputLine(f"{key}.{part}", "range", v, None, key))
    ev = evaluate(
        db,
        entity.org_id,
        body.rule_pack_version_id,
        body.rules_prefix,
        body.period_end,
        "tp_documentation",
        lines,
    )
    audit.record(
        db,
        org_id=entity.org_id,
        actor_id=actor.id,
        action="tp.checked",
        object_type="legal_entity",
        object_id=entity.id,
        meta={"result_hash": ev.result_hash, "transactions": len(txns)},
    )
    return ev, total, len(txns)


DISCLOSURE_HEADER = [
    "Related party",
    "Relationship",
    "Jurisdiction",
    "Transaction type",
    "Direction",
    "Method",
    "Transactions",
    "Total amount",
    "Currency",
]


def disclosure_csv(db: Session, entity: LegalEntity, start: date, end: date, actor: User) -> str:
    """Totals per party, type and direction for the period, for a disclosure form."""
    groups: dict[tuple[str, ...], list[RelatedPartyTransaction]] = {}
    for t in transactions(db, entity, start, end):
        k: tuple[str, ...] = (
            t.party.name,
            t.party.relation.value,
            t.party.jurisdiction,
            t.transaction_type.value,
            t.direction,
            t.method.value,
            t.currency,
        )
        groups.setdefault(k, []).append(t)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(DISCLOSURE_HEADER)
    for k, txns in sorted(groups.items()):
        total = sum((t.amount for t in txns), Decimal(0))
        w.writerow([csv_safe(v) for v in (*k[:6], len(txns), format(total, "f"), k[6])])
    audit.record(
        db,
        org_id=entity.org_id,
        actor_id=actor.id,
        action="tp.disclosure_exported",
        object_type="legal_entity",
        object_id=entity.id,
        meta={
            "rows": len(groups),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        },
    )
    return buf.getvalue()
