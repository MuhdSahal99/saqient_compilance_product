"""Transfer pricing register, documentation threshold check and disclosure export (C4)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Response, status

from app import calc
from app.api.workpapers import _bad
from app.deps import DB, Ctx, Writer, get_owned_or_404
from app.models import LegalEntity, RelatedParty, RelatedPartyTransaction
from app.schemas import (
    CalcLineOut,
    RelatedPartyIn,
    RelatedPartyOut,
    RPTransactionIn,
    RPTransactionOut,
    TPCheckIn,
    TPCheckOut,
)
from app.services import transfer_pricing as svc
from app.services.workpapers import WorkpaperError

router = APIRouter(tags=["transfer pricing"])


def txn_out(db: DB, t: RelatedPartyTransaction) -> RPTransactionOut:
    return RPTransactionOut(
        id=t.id,
        entity_id=t.entity_id,
        related_party_id=t.related_party_id,
        related_party_name=t.party.name,
        period_start=t.period_start,
        period_end=t.period_end,
        transaction_type=t.transaction_type,
        direction=t.direction,
        description=t.description,
        amount=t.amount,
        currency=t.currency,
        method=t.method,
        range_low=t.range_low,
        range_high=t.range_high,
        tested_value=t.tested_value,
        range_metric=t.range_metric,
        benchmark_documents=svc.documents(db, t.org_id, t.benchmark_document_ids),
        evidence=t.evidence,
        is_demo=t.is_demo,
    )


@router.get(
    "/entities/{entity_id}/related-parties",
    response_model=list[RelatedPartyOut],
    summary="List related parties",
)
def list_parties(entity_id: uuid.UUID, db: DB, ctx: Ctx) -> list[RelatedPartyOut]:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    return [RelatedPartyOut.model_validate(p) for p in svc.parties(db, e)]


@router.post(
    "/entities/{entity_id}/related-parties",
    response_model=RelatedPartyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a related party",
)
def add_party(entity_id: uuid.UUID, body: RelatedPartyIn, db: DB, ctx: Writer) -> RelatedPartyOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    try:
        p = svc.add_party(db, e, body, ctx.user)
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return RelatedPartyOut.model_validate(p)


@router.delete(
    "/related-parties/{party_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a related party with no transactions",
)
def delete_party(party_id: uuid.UUID, db: DB, ctx: Writer) -> Response:
    p = get_owned_or_404(db, RelatedParty, party_id, ctx.org.id)
    try:
        svc.delete_party(db, p, ctx.user)
    except WorkpaperError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/entities/{entity_id}/rp-transactions",
    response_model=list[RPTransactionOut],
    summary="List related-party transactions",
    description="Transactions whose own period lies inside the given dates.",
)
def list_txns(
    entity_id: uuid.UUID,
    db: DB,
    ctx: Ctx,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[RPTransactionOut]:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    return [txn_out(db, t) for t in svc.transactions(db, e, period_start, period_end)]


@router.post(
    "/entities/{entity_id}/rp-transactions",
    response_model=RPTransactionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a related-party transaction",
    description=(
        "Type, direction, amount and method, with an optional arm's length range and tested "
        "result, benchmarking documents and evidence."
    ),
)
def add_txn(entity_id: uuid.UUID, body: RPTransactionIn, db: DB, ctx: Writer) -> RPTransactionOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    party = get_owned_or_404(db, RelatedParty, body.related_party_id, ctx.org.id)
    try:
        t = svc.add_transaction(db, e, party, body, ctx.user)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return txn_out(db, t)


@router.delete(
    "/rp-transactions/{txn_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a related-party transaction",
)
def delete_txn(txn_id: uuid.UUID, db: DB, ctx: Writer) -> Response:
    t = get_owned_or_404(db, RelatedPartyTransaction, txn_id, ctx.org.id)
    svc.delete_transaction(db, t, ctx.user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/entities/{entity_id}/tp/check",
    response_model=TPCheckOut,
    summary="Check transfer pricing documentation thresholds",
    description=(
        "Master File, Local File and disclosure thresholds from the pack, plus arm's length "
        "range tests for transactions with a range. Indications for a reviewer to confirm."
    ),
)
def tp_check(entity_id: uuid.UUID, body: TPCheckIn, db: DB, ctx: Writer) -> TPCheckOut:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    try:
        ev, total, count = svc.check(db, e, body, ctx.user)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return TPCheckOut(
        currency=e.functional_currency,
        rp_total=total,
        transaction_count=count,
        calc_version=calc.CALC_VERSION,
        result_hash=ev.result_hash,
        lines=[CalcLineOut(**x) for x in ev.lines()],
        warnings=ev.warnings,
    )


@router.get(
    "/entities/{entity_id}/tp/disclosure.csv",
    summary="Export disclosure data (CSV)",
    description="Totals per related party, transaction type and direction for the period.",
    response_class=Response,
)
def disclosure(
    entity_id: uuid.UUID, period_start: date, period_end: date, db: DB, ctx: Ctx
) -> Response:
    e = get_owned_or_404(db, LegalEntity, entity_id, ctx.org.id)
    body = svc.disclosure_csv(db, e, period_start, period_end, ctx.user)
    db.commit()
    return Response(
        "﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="saqient-tp-disclosure-{period_end}.csv"',
        },
    )
