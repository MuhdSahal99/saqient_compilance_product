"""Balance-sheet account and intercompany reconciliations (Phase E2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.assurance_common import export, guard, name_of, sign_off_out, versions_out
from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.models import (
    AccountReconciliation,
    AssuranceObject,
    Document,
    IntercompanyReconciliation,
    LegalEntity,
)
from app.schemas import (
    AccountRecIn,
    AccountRecListOut,
    AccountRecOut,
    AccountRecUpdateIn,
    ExplanationIn,
    IntercompanyIn,
    IntercompanyOut,
    ReasonIn,
    SupportItemOut,
)
from app.services import account_recs as svc
from app.services import assurance

router = APIRouter(tags=["account reconciliations"])
ACCOUNT = AssuranceObject.ACCOUNT_RECONCILIATION
IC = AssuranceObject.INTERCOMPANY


def _get(db: DB, ctx: Ctx, rec_id: uuid.UUID) -> AccountReconciliation:
    return get_owned_or_404(db, AccountReconciliation, rec_id, ctx.org.id)


def _list(db: DB, r: AccountReconciliation) -> dict[str, object]:
    sup = svc.supported(r)
    c, _ = guard(lambda: svc.check(db, r))
    return {
        "id": r.id,
        "entity_id": r.entity_id,
        "entity_name": r.entity.name,
        "as_of": r.as_of,
        "account_code": r.account_code,
        "account_name": r.account_name,
        "currency": r.currency,
        "tb_balance": r.tb_balance,
        "supported": sup,
        "variance": r.tb_balance - sup,
        "exceeds": c["exceeds"],
        "owner_name": name_of(db, r.owner_id),
        "status": r.status,
        "version": r.version,
        "is_demo": r.is_demo,
    }


def rec_out(db: DB, r: AccountReconciliation) -> AccountRecOut:
    c, warnings = guard(lambda: svc.check(db, r))
    return AccountRecOut(
        **_list(db, r),
        tb_version_id=r.tb_version_id,
        tb_row_ids=r.tb_row_ids,
        rule_pack_version_id=r.rule_pack_version_id,
        rules_prefix=r.rules_prefix,
        explanation=r.explanation,
        owner_id=r.owner_id,
        items=[
            SupportItemOut(
                description=i.description,
                amount=i.amount,
                document_id=i.document_id,
                document_title=(
                    d.title if i.document_id and (d := db.get(Document, i.document_id)) else None
                ),
                note=i.note,
            )
            for i in r.items
        ],
        check=c,
        warnings=warnings,
        sign_off=sign_off_out(db, r),
        versions=versions_out(db, r.org_id, ACCOUNT, r.id),
    )


@router.get(
    "/account-reconciliations",
    response_model=list[AccountRecListOut],
    summary="List account reconciliations",
    description="Filter by entity or as-of date. Variances are recomputed from current items.",
)
def list_recs(
    db: DB, ctx: Ctx, entity_id: uuid.UUID | None = None, as_of: str | None = None
) -> list[AccountRecListOut]:
    stmt = select(AccountReconciliation).where(AccountReconciliation.org_id == ctx.org.id)
    if entity_id:
        stmt = stmt.where(AccountReconciliation.entity_id == entity_id)
    if as_of:
        stmt = stmt.where(AccountReconciliation.as_of == as_of)
    rows = db.scalars(
        stmt.order_by(AccountReconciliation.as_of.desc(), AccountReconciliation.account_code).limit(
            1000
        )
    ).unique()
    return [AccountRecListOut(**_list(db, r)) for r in rows]


@router.post(
    "/account-reconciliations",
    response_model=list[AccountRecOut],
    status_code=status.HTTP_201_CREATED,
    summary="Start account reconciliations",
    description="One per account, with the balance taken from the trial balance version.",
)
def create_recs(body: AccountRecIn, db: DB, ctx: Writer) -> list[AccountRecOut]:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    recs = guard(lambda: svc.create(db, entity, body, ctx.user))
    db.commit()
    return [rec_out(db, r) for r in recs]


@router.get(
    "/account-reconciliations/{rec_id}",
    response_model=AccountRecOut,
    summary="Get an account reconciliation",
)
def get_rec(rec_id: uuid.UUID, db: DB, ctx: Ctx) -> AccountRecOut:
    return rec_out(db, _get(db, ctx, rec_id))


@router.put(
    "/account-reconciliations/{rec_id}",
    response_model=AccountRecOut,
    summary="Replace supporting items and the explanation",
)
def update_rec(rec_id: uuid.UUID, body: AccountRecUpdateIn, db: DB, ctx: Writer) -> AccountRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: svc.update(db, r, body, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/account-reconciliations/{rec_id}/prepare",
    response_model=AccountRecOut,
    summary="Mark prepared",
)
def prepare(rec_id: uuid.UUID, db: DB, ctx: Writer) -> AccountRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: assurance.prepare(db, r, ACCOUNT, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/account-reconciliations/{rec_id}/sign-off",
    response_model=AccountRecOut,
    summary="Sign off",
    description=(
        "By a reviewer or admin other than the preparer. A variance over the threshold "
        "needs an explanation."
    ),
)
def sign_off(rec_id: uuid.UUID, db: DB, ctx: Decider) -> AccountRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: svc.sign_off(db, r, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.post(
    "/account-reconciliations/{rec_id}/reopen", response_model=AccountRecOut, summary="Reopen"
)
def reopen(rec_id: uuid.UUID, body: ReasonIn, db: DB, ctx: Decider) -> AccountRecOut:
    r = _get(db, ctx, rec_id)
    guard(lambda: assurance.reopen(db, r, ACCOUNT, body.reason, ctx.user))
    db.commit()
    return rec_out(db, r)


@router.get(
    "/account-reconciliations/{rec_id}/versions/{version}/export",
    summary="Export a signed-off account reconciliation",
    response_class=Response,
)
def export_rec(
    rec_id: uuid.UUID,
    version: int,
    db: DB,
    ctx: Ctx,
    fmt: str = Query(alias="format", pattern="^(html|pdf|csv)$"),
) -> Response:
    r = _get(db, ctx, rec_id)
    return export(db, ctx, ACCOUNT, r.id, version, fmt)


# ---------------------------------------------------------------- intercompany


def _ic(db: DB, ctx: Ctx, rec_id: uuid.UUID) -> IntercompanyReconciliation:
    return get_owned_or_404(db, IntercompanyReconciliation, rec_id, ctx.org.id)


def ic_out(db: DB, r: IntercompanyReconciliation) -> IntercompanyOut:
    v = guard(lambda: svc.ic_view(db, r))
    return IntercompanyOut(
        id=r.id,
        name=r.name,
        as_of=r.as_of,
        currency=r.currency,
        explanation=r.explanation,
        rule_pack_version_id=r.rule_pack_version_id,
        rules_prefix=r.rules_prefix,
        is_demo=r.is_demo,
        sign_off=sign_off_out(db, r),
        versions=versions_out(db, r.org_id, IC, r.id),
        **v,
    )


@router.get(
    "/intercompany-reconciliations",
    response_model=list[IntercompanyOut],
    summary="List intercompany reconciliations",
)
def list_ic(db: DB, ctx: Ctx) -> list[IntercompanyOut]:
    rows = db.scalars(
        select(IntercompanyReconciliation)
        .where(IntercompanyReconciliation.org_id == ctx.org.id)
        .order_by(IntercompanyReconciliation.as_of.desc())
        .limit(200)
    ).unique()
    return [ic_out(db, r) for r in rows]


@router.post(
    "/intercompany-reconciliations",
    response_model=IntercompanyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an intercompany reconciliation",
    description="Each entity's intercompany accounts; the two balances should net to zero.",
)
def create_ic(body: IntercompanyIn, db: DB, ctx: Writer) -> IntercompanyOut:
    a = get_owned_or_404(db, LegalEntity, body.entity_a_id, ctx.org.id)
    b = get_owned_or_404(db, LegalEntity, body.entity_b_id, ctx.org.id)
    r = guard(lambda: svc.create_ic(db, a, b, body, ctx.user))
    db.commit()
    return ic_out(db, r)


@router.get(
    "/intercompany-reconciliations/{rec_id}",
    response_model=IntercompanyOut,
    summary="Get an intercompany reconciliation",
)
def get_ic(rec_id: uuid.UUID, db: DB, ctx: Ctx) -> IntercompanyOut:
    return ic_out(db, _ic(db, ctx, rec_id))


@router.put(
    "/intercompany-reconciliations/{rec_id}/explanation",
    response_model=IntercompanyOut,
    summary="Explain the difference",
)
def explain_ic(rec_id: uuid.UUID, body: ExplanationIn, db: DB, ctx: Writer) -> IntercompanyOut:
    r = _ic(db, ctx, rec_id)
    guard(lambda: svc.explain_ic(db, r, body.explanation, ctx.user))
    db.commit()
    return ic_out(db, r)


@router.post(
    "/intercompany-reconciliations/{rec_id}/prepare",
    response_model=IntercompanyOut,
    summary="Mark prepared",
)
def prepare_ic(rec_id: uuid.UUID, db: DB, ctx: Writer) -> IntercompanyOut:
    r = _ic(db, ctx, rec_id)
    guard(lambda: assurance.prepare(db, r, IC, ctx.user))
    db.commit()
    return ic_out(db, r)


@router.post(
    "/intercompany-reconciliations/{rec_id}/sign-off",
    response_model=IntercompanyOut,
    summary="Sign off",
)
def sign_off_ic(rec_id: uuid.UUID, db: DB, ctx: Decider) -> IntercompanyOut:
    r = _ic(db, ctx, rec_id)
    guard(lambda: svc.sign_off_ic(db, r, ctx.user))
    db.commit()
    return ic_out(db, r)


@router.post(
    "/intercompany-reconciliations/{rec_id}/reopen",
    response_model=IntercompanyOut,
    summary="Reopen",
)
def reopen_ic(rec_id: uuid.UUID, body: ReasonIn, db: DB, ctx: Decider) -> IntercompanyOut:
    r = _ic(db, ctx, rec_id)
    guard(lambda: assurance.reopen(db, r, IC, body.reason, ctx.user))
    db.commit()
    return ic_out(db, r)


@router.get(
    "/intercompany-reconciliations/{rec_id}/versions/{version}/export",
    summary="Export a signed-off intercompany reconciliation",
    response_class=Response,
)
def export_ic(
    rec_id: uuid.UUID,
    version: int,
    db: DB,
    ctx: Ctx,
    fmt: str = Query(alias="format", pattern="^(html|pdf|csv)$"),
) -> Response:
    r = _ic(db, ctx, rec_id)
    return export(db, ctx, IC, r.id, version, fmt)
