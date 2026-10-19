"""Balance-sheet account and intercompany reconciliations (E2).

An account reconciliation compares the trial balance balance of one account at one
date with supporting items. The variance needs an explanation when it exceeds both the
pack's absolute limit (``variance_abs``) and its share of the balance (``variance_pct``).
An intercompany reconciliation sums each entity's intercompany accounts; the two
balances should net to zero, and a difference above ``intercompany_abs`` needs an
explanation. Both entities must report in the same currency (no translation here).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccountReconciliation,
    AssuranceObject,
    DatasetKind,
    Document,
    IntercompanyReconciliation,
    LegalEntity,
    ReconSupportItem,
    User,
)
from app.schemas import AccountRecIn, AccountRecUpdateIn, IntercompanyIn
from app.services import assurance as sign
from app.services import audit
from app.services import tb as tbs
from app.services.assurance import AssuranceError

ZERO = Decimal(0)
ACCOUNT = AssuranceObject.ACCOUNT_RECONCILIATION
IC = AssuranceObject.INTERCOMPANY


def _record(
    db: Session, obj: Any, kind: AssuranceObject, actor: User, action: str, **m: Any
) -> None:
    audit.record(
        db,
        org_id=obj.org_id,
        actor_id=actor.id,
        action=f"{kind.value}.{action}",
        object_type=kind.value,
        object_id=obj.id,
        meta=m,
    )


# ---------------------------------------------------------------- account reconciliations


def create(
    db: Session, entity: LegalEntity, body: AccountRecIn, actor: User
) -> list[AccountReconciliation]:
    tbs.version(db, entity.org_id, body.tb_version_id, entity.id, DatasetKind.TRIAL_BALANCE)
    tbs.published(db, entity.org_id, body.rule_pack_version_id)
    tbs.require_member(db, entity.org_id, body.owner_id)
    accts = tbs.accounts(db, entity.org_id, body.tb_version_id)
    codes = list(dict.fromkeys(c.strip() for c in body.account_codes))
    missing = [c for c in codes if c not in accts]
    if missing:
        raise AssuranceError(f"Account(s) {', '.join(missing)} are not in the trial balance.")
    have = set(
        db.scalars(
            select(AccountReconciliation.account_code).where(
                AccountReconciliation.tb_version_id == body.tb_version_id,
                AccountReconciliation.account_code.in_(codes),
            )
        )
    )
    if have:
        raise AssuranceError(
            f"Already reconciled on this trial balance: {', '.join(sorted(have))}."
        )
    out = []
    for c in codes:
        a = accts[c]
        r = AccountReconciliation(
            org_id=entity.org_id,
            entity_id=entity.id,
            tb_version_id=body.tb_version_id,
            as_of=body.as_of,
            account_code=c,
            account_name=a.name[:300],
            currency=entity.functional_currency,
            tb_balance=a.balance,
            tb_row_ids=a.row_ids,
            rule_pack_version_id=body.rule_pack_version_id,
            rules_prefix=body.rules_prefix,
            owner_id=body.owner_id,
            created_by_id=actor.id,
        )
        db.add(r)
        db.flush()
        _record(db, r, ACCOUNT, actor, "created", account_code=c)
        out.append(r)
    return out


def update(db: Session, r: AccountReconciliation, body: AccountRecUpdateIn, actor: User) -> None:
    sign.changed(r)
    tbs.require_member(db, r.org_id, body.owner_id)
    for it in body.items:
        if it.document_id is not None and (
            db.scalar(
                select(Document.id).where(
                    Document.id == it.document_id, Document.org_id == r.org_id
                )
            )
            is None
        ):
            raise LookupError("document")
    r.items = [
        ReconSupportItem(
            org_id=r.org_id,
            ordinal=i,
            description=it.description.strip(),
            amount=it.amount,
            document_id=it.document_id,
            note=it.note.strip(),
        )
        for i, it in enumerate(body.items)
    ]
    r.explanation, r.owner_id = body.explanation.strip(), body.owner_id
    db.flush()
    _record(db, r, ACCOUNT, actor, "updated", items=len(body.items))


def supported(r: AccountReconciliation) -> Decimal:
    return sum((i.amount for i in r.items), ZERO)


def check(db: Session, r: AccountReconciliation) -> tuple[dict[str, Any], list[str]]:
    rules = tbs.Rules(db, r.org_id, r.rule_pack_version_id, r.rules_prefix, r.as_of)
    abs_limit = rules.decimal("variance_abs")
    pct = rules.decimal("variance_pct")
    sup = supported(r)
    variance = r.tb_balance - sup
    exceeds = tbs.over(variance, r.tb_balance, abs_limit, pct)
    steps = [
        {
            "label": "Supported total",
            "expression": " + ".join(str(i.amount) for i in r.items) or "none",
            "value": str(sup),
        },
        {
            "label": "Variance",
            "expression": f"{r.tb_balance} − {sup}",
            "value": str(variance),
        },
        {
            "label": "Explanation threshold",
            "expression": f"|{variance}| > {abs_limit} and |{variance}| > {pct} × |{r.tb_balance}|",
            "value": "exceeded" if exceeds else "within",
        },
    ]
    return (
        {
            "variance": variance,
            "threshold_abs": abs_limit,
            "threshold_pct": pct,
            "exceeds": exceeds,
            "explanation_required": exceeds and not r.explanation,
            "steps": steps,
        },
        rules.warnings,
    )


def _owner_name(db: Session, r: AccountReconciliation) -> str | None:
    u = db.get(User, r.owner_id) if r.owner_id else None
    return u.full_name if u else None


def sign_off(db: Session, r: AccountReconciliation, actor: User) -> Any:
    c, warnings = check(db, r)
    if c["exceeds"] and not r.explanation:
        raise AssuranceError("Explain the variance before signing off.")
    titles = {
        i.document_id: d.title
        for i in r.items
        if i.document_id and (d := db.get(Document, i.document_id))
    }
    content = {
        "title": f"Account reconciliation — {r.account_code} {r.account_name}".strip(),
        "subtitle": f"{r.entity.name} · as of {r.as_of} · {r.currency}",
        "is_demo": r.is_demo,
        "warnings": warnings,
        "meta": [
            ["Trial balance version", str(r.tb_version_id)],
            ["Trial balance rows", " ".join(map(str, r.tb_row_ids))],
            ["Trial balance balance", str(r.tb_balance)],
            ["Owner", _owner_name(db, r)],
            *[[s["label"], f"{s['expression']} = {s['value']}"] for s in c["steps"]],
            ["Explanation", r.explanation or None],
        ],
        "sections": [
            {
                "title": "Supporting items",
                "columns": ["Description", "Amount", "Evidence", "Note"],
                "rows": [
                    [
                        i.description,
                        str(i.amount),
                        titles.get(i.document_id) if i.document_id else None,
                    ]
                    + [i.note]
                    for i in r.items
                ],
            }
        ],
        "notes": [],
    }
    return sign.sign_off(db, r, ACCOUNT, content, actor)


# ---------------------------------------------------------------- intercompany


def _side(db: Session, org_id: Any, vid: Any, codes: list[str]) -> tuple[Decimal, list[int]]:
    accts = tbs.accounts(db, org_id, vid)
    missing = [c for c in codes if c not in accts]
    if missing:
        raise AssuranceError(f"Account(s) {', '.join(missing)} are not in the trial balance.")
    return (
        sum((accts[c].balance for c in codes), ZERO),
        sorted(i for c in codes for i in accts[c].row_ids),
    )


def create_ic(
    db: Session, a: LegalEntity, b: LegalEntity, body: IntercompanyIn, actor: User
) -> IntercompanyReconciliation:
    if a.functional_currency != b.functional_currency:
        raise AssuranceError(
            "Both entities must report in the same currency; translation is not supported."
        )
    tbs.version(db, a.org_id, body.tb_a_version_id, a.id, DatasetKind.TRIAL_BALANCE)
    tbs.version(db, a.org_id, body.tb_b_version_id, b.id, DatasetKind.TRIAL_BALANCE)
    tbs.published(db, a.org_id, body.rule_pack_version_id)
    _side(db, a.org_id, body.tb_a_version_id, body.accounts_a)
    _side(db, a.org_id, body.tb_b_version_id, body.accounts_b)
    r = IntercompanyReconciliation(
        org_id=a.org_id,
        name=body.name.strip(),
        as_of=body.as_of,
        currency=a.functional_currency,
        entity_a_id=a.id,
        tb_a_version_id=body.tb_a_version_id,
        accounts_a=list(dict.fromkeys(body.accounts_a)),
        entity_b_id=b.id,
        tb_b_version_id=body.tb_b_version_id,
        accounts_b=list(dict.fromkeys(body.accounts_b)),
        rule_pack_version_id=body.rule_pack_version_id,
        rules_prefix=body.rules_prefix,
        created_by_id=actor.id,
    )
    db.add(r)
    db.flush()
    _record(db, r, IC, actor, "created")
    return r


def explain_ic(db: Session, r: IntercompanyReconciliation, text: str, actor: User) -> None:
    sign.changed(r)
    r.explanation = text.strip()
    db.flush()
    _record(db, r, IC, actor, "explained")


def ic_view(db: Session, r: IntercompanyReconciliation) -> dict[str, Any]:
    rules = tbs.Rules(db, r.org_id, r.rule_pack_version_id, r.rules_prefix, r.as_of)
    limit = rules.decimal("intercompany_abs")
    bal_a, rows_a = _side(db, r.org_id, r.tb_a_version_id, r.accounts_a)
    bal_b, rows_b = _side(db, r.org_id, r.tb_b_version_id, r.accounts_b)
    diff = bal_a + bal_b
    return {
        "side_a": {
            "entity_id": r.entity_a_id,
            "entity_name": r.entity_a.name,
            "tb_version_id": r.tb_a_version_id,
            "accounts": r.accounts_a,
            "balance": bal_a,
            "row_ids": rows_a,
        },
        "side_b": {
            "entity_id": r.entity_b_id,
            "entity_name": r.entity_b.name,
            "tb_version_id": r.tb_b_version_id,
            "accounts": r.accounts_b,
            "balance": bal_b,
            "row_ids": rows_b,
        },
        "difference": diff,
        "threshold": limit,
        "exceeds": abs(diff) > limit,
        "steps": [
            {"label": "Difference", "expression": f"{bal_a} + {bal_b}", "value": str(diff)},
            {
                "label": "Explanation threshold",
                "expression": f"|{diff}| > {limit}",
                "value": "exceeded" if abs(diff) > limit else "within",
            },
        ],
        "warnings": rules.warnings,
    }


def sign_off_ic(db: Session, r: IntercompanyReconciliation, actor: User) -> Any:
    v = ic_view(db, r)
    if v["exceeds"] and not r.explanation:
        raise AssuranceError("Explain the difference before signing off.")
    content = {
        "title": f"Intercompany reconciliation — {r.name}",
        "subtitle": f"{r.entity_a.name} and {r.entity_b.name} · as of {r.as_of} · {r.currency}",
        "is_demo": r.is_demo,
        "warnings": v["warnings"],
        "meta": [
            *[[s["label"], f"{s['expression']} = {s['value']}"] for s in v["steps"]],
            ["Explanation", r.explanation or None],
        ],
        "sections": [
            {
                "title": "Balances",
                "columns": ["Entity", "Trial balance version", "Accounts", "Rows", "Balance"],
                "rows": [
                    [
                        s["entity_name"],
                        str(s["tb_version_id"]),
                        ", ".join(s["accounts"]),
                        " ".join(map(str, s["row_ids"])),
                        str(s["balance"]),
                    ]
                    for s in (v["side_a"], v["side_b"])
                ],
            }
        ],
        "notes": [],
    }
    return sign.sign_off(db, r, IC, content, actor)
