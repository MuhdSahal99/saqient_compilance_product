"""Flux analysis (E2): current against prior trial balance per account.

A change needs an explanation when it exceeds both the pack's absolute limit
(``flux_abs``) and its share of the prior balance (``flux_pct``). Sign-off needs every
such account explained.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AssuranceObject,
    DatasetKind,
    FluxExplanation,
    FluxReview,
    LegalEntity,
    User,
)
from app.schemas import FluxExplainIn, FluxIn
from app.services import assurance as sign
from app.services import audit
from app.services import tb as tbs
from app.services.assurance import AssuranceError

ZERO = Decimal(0)
SHARE = Decimal("0.0001")
KIND = AssuranceObject.FLUX


def create(db: Session, entity: LegalEntity, body: FluxIn, actor: User) -> FluxReview:
    for vid in (body.cy_tb_version_id, body.py_tb_version_id):
        tbs.version(db, entity.org_id, vid, entity.id, DatasetKind.TRIAL_BALANCE)
    tbs.published(db, entity.org_id, body.rule_pack_version_id)
    r = FluxReview(
        org_id=entity.org_id,
        entity_id=entity.id,
        name=body.name.strip(),
        as_of=body.as_of,
        currency=entity.functional_currency,
        cy_tb_version_id=body.cy_tb_version_id,
        py_tb_version_id=body.py_tb_version_id,
        rule_pack_version_id=body.rule_pack_version_id,
        rules_prefix=body.rules_prefix,
        created_by_id=actor.id,
    )
    db.add(r)
    db.flush()
    _record(db, r, actor, "created")
    view(db, r)  # fails early on missing rules or unreadable data
    return r


def _record(db: Session, r: FluxReview, actor: User, action: str, **meta: Any) -> None:
    audit.record(
        db,
        org_id=r.org_id,
        actor_id=actor.id,
        action=f"flux.{action}",
        object_type=KIND.value,
        object_id=r.id,
        meta=meta,
    )


def view(db: Session, r: FluxReview) -> dict[str, Any]:
    rules = tbs.Rules(db, r.org_id, r.rule_pack_version_id, r.rules_prefix, r.as_of)
    abs_limit, pct = rules.decimal("flux_abs"), rules.decimal("flux_pct")
    cy = tbs.accounts(db, r.org_id, r.cy_tb_version_id)
    py = tbs.accounts(db, r.org_id, r.py_tb_version_id)
    notes = {e.account_code: e for e in r.explanations}
    lines = []
    for code in sorted(set(cy) | set(py)):
        a, b = cy.get(code), py.get(code)
        cur, pri = (a.balance if a else ZERO), (b.balance if b else ZERO)
        change = cur - pri
        e = notes.get(code)
        lines.append(
            {
                "account_code": code,
                "account_name": (a.name if a else "") or (b.name if b else ""),
                "current": cur,
                "prior": pri,
                "change": change,
                "change_pct": (change / abs(pri)).quantize(SHARE, ROUND_HALF_UP) if pri else None,
                "exceeds": tbs.over(change, pri, abs_limit, pct),
                "explanation": e.explanation if e else "",
                "explained_by_id": e.explained_by_id if e else None,
                "cy_row_ids": a.row_ids if a else [],
                "py_row_ids": b.row_ids if b else [],
            }
        )
    exceeding = [ln for ln in lines if ln["exceeds"]]
    return {
        "threshold_abs": abs_limit,
        "threshold_pct": pct,
        "lines": lines,
        "exceeding": len(exceeding),
        "unexplained": sum(1 for ln in exceeding if not ln["explanation"]),
        "warnings": rules.warnings,
    }


def explain(db: Session, r: FluxReview, body: FluxExplainIn, actor: User) -> None:
    sign.changed(r)
    code, text = body.account_code.strip(), body.explanation.strip()
    if code not in {ln["account_code"] for ln in view(db, r)["lines"]}:
        raise AssuranceError(f"Account {code} is in neither trial balance.")
    e = next((x for x in r.explanations if x.account_code == code), None)
    if not text:
        if e is not None:
            r.explanations.remove(e)
    elif e is None:
        r.explanations.append(
            FluxExplanation(
                org_id=r.org_id,
                account_code=code,
                explanation=text,
                explained_by_id=actor.id,
                explained_at=now(),
            )
        )
    else:
        e.explanation, e.explained_by_id, e.explained_at = text, actor.id, now()
    db.flush()
    _record(db, r, actor, "explained", account_code=code, cleared=not text)


def sign_off(db: Session, r: FluxReview, actor: User) -> Any:
    v = view(db, r)
    if v["unexplained"]:
        raise AssuranceError(f"Explain the {v['unexplained']} account(s) over the threshold first.")
    content = {
        "title": f"Flux analysis — {r.name}",
        "subtitle": f"{r.entity.name} · as of {r.as_of} · {r.currency}",
        "is_demo": r.is_demo,
        "warnings": v["warnings"],
        "meta": [
            ["Current trial balance version", str(r.cy_tb_version_id)],
            ["Prior trial balance version", str(r.py_tb_version_id)],
            [
                "Explanation threshold",
                f"|change| > {v['threshold_abs']} and |change| > {v['threshold_pct']} × |prior|",
            ],
            ["Accounts over threshold", v["exceeding"]],
        ],
        "sections": [
            {
                "title": "Accounts",
                "columns": ["Account", "Name", "Current", "Prior", "Change", "Change %", "Over"]
                + ["Explanation"],
                "rows": [
                    [ln["account_code"], ln["account_name"], str(ln["current"]), str(ln["prior"])]
                    + [
                        str(ln["change"]),
                        str(ln["change_pct"]) if ln["change_pct"] is not None else None,
                    ]
                    + ["yes" if ln["exceeds"] else "", ln["explanation"]]
                    for ln in v["lines"]
                ],
            }
        ],
        "notes": [],
    }
    return sign.sign_off(db, r, KIND, content, actor)
