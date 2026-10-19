"""Bank reconciliation (E1): auto-match, manual matches, ageing and the balance proof.

Bank lines are the statement version's rows in the period; book lines are the ledger
version's rows for the reconciliation's GL accounts in the period. Tolerance, date
window and ageing buckets are pack rules under ``rules_prefix``. Re-running the
auto-match replaces automatic matches and keeps manual ones.

Proof (both sides "money in is positive"):
  book closing  = book opening + book movement
  adjusted bank = bank closing + unmatched book lines   (in the books, not yet on the statement)
  adjusted book = book closing + unmatched bank lines   (on the statement, not yet booked)
  difference    = adjusted bank − adjusted book         (must be zero to sign off)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import polars as pl
from sqlalchemy.orm import Session

from app.assurance import matching as mt
from app.calc import CalcError
from app.deps import now
from app.models import (
    AssuranceObject,
    AssuranceStatus,
    BankReconciliation,
    DatasetKind,
    LegalEntity,
    ReconMatch,
    ReconMatchLine,
    ReconMethod,
    ReconSide,
    User,
)
from app.schemas import BankRecIn, BankRecUpdateIn, ManualMatchIn
from app.services import assurance as sign
from app.services import audit, rule_schemas
from app.services import tb as tbs
from app.services.assurance import AssuranceError
from app.services.datasets import DatasetNotReady, load_frame
from app.services.workpapers import PackRules, WorkpaperError, _published

ZERO = Decimal(0)
KIND = AssuranceObject.BANK_RECONCILIATION


@dataclass(frozen=True)
class Line:
    side: ReconSide
    row_id: int
    on: date
    amount: Decimal
    reference: str
    description: str


def _record(db: Session, r: BankReconciliation, actor: User, action: str, **meta: Any) -> None:
    audit.record(
        db,
        org_id=r.org_id,
        actor_id=actor.id,
        action=f"bank_reconciliation.{action}",
        object_type=KIND.value,
        object_id=r.id,
        meta=meta,
    )


def _apply(r: BankReconciliation, body: BankRecUpdateIn | BankRecIn) -> None:
    r.name, r.account_label = body.name.strip(), body.account_label.strip()
    r.gl_accounts = list(body.gl_accounts)
    r.bank_closing_balance, r.book_opening_balance = (
        body.bank_closing_balance,
        body.book_opening_balance,
    )


def create(db: Session, entity: LegalEntity, body: BankRecIn, actor: User) -> BankReconciliation:
    tbs.version(db, entity.org_id, body.statement_version_id, entity.id, DatasetKind.BANK_STATEMENT)
    tbs.version(db, entity.org_id, body.ledger_version_id, entity.id, DatasetKind.GENERAL_LEDGER)
    try:
        _published(db, entity.org_id, body.rule_pack_version_id)
    except WorkpaperError as exc:
        raise AssuranceError(str(exc)) from exc
    r = BankReconciliation(
        org_id=entity.org_id,
        entity_id=entity.id,
        period_start=body.period_start,
        period_end=body.period_end,
        currency=entity.functional_currency,
        statement_version_id=body.statement_version_id,
        ledger_version_id=body.ledger_version_id,
        rule_pack_version_id=body.rule_pack_version_id,
        rules_prefix=body.rules_prefix,
        created_by_id=actor.id,
    )
    _apply(r, body)
    db.add(r)
    db.flush()
    _record(db, r, actor, "created")
    auto_match(db, r, actor)
    return r


def update(db: Session, r: BankReconciliation, body: BankRecUpdateIn, actor: User) -> None:
    sign.changed(r)
    accounts_changed = set(body.gl_accounts) != set(r.gl_accounts)
    _apply(r, body)
    db.flush()
    _record(db, r, actor, "updated", accounts_changed=accounts_changed)
    if accounts_changed:
        r.matches.clear()
        db.flush()
        auto_match(db, r, actor)


# ---------------------------------------------------------------- lines and rules


def _frame(db: Session, r: BankReconciliation, vid: uuid.UUID) -> pl.DataFrame:
    try:
        return load_frame(db, vid, r.org_id)[1]
    except DatasetNotReady as exc:
        raise AssuranceError(str(exc)) from exc


def _text(v: Any) -> str:
    return "" if v is None else str(v)


def lines(db: Session, r: BankReconciliation) -> tuple[list[Line], list[Line], pl.DataFrame]:
    bank_df = _frame(db, r, r.statement_version_id)
    bank_in = bank_df.filter(pl.col("transaction_date").is_between(r.period_start, r.period_end))
    bank = [
        Line(
            ReconSide.BANK,
            int(x["row_id"]),
            x["transaction_date"],
            Decimal(str(x["amount"])),
            _text(x.get("reference")),
            _text(x.get("description")),
        )
        for x in bank_in.sort("row_id").to_dicts()
        if x.get("amount") is not None
    ]
    gl = _frame(db, r, r.ledger_version_id)
    gl = gl.filter(
        pl.col("account_code").cast(pl.String).is_in(r.gl_accounts)
        & pl.col("posting_date").is_between(r.period_start, r.period_end)
    )
    book = [
        Line(
            ReconSide.BOOK,
            int(x["row_id"]),
            x["posting_date"],
            Decimal(str(x["amount"])),
            _text(x.get("reference")) or _text(x.get("entry_id")),
            _text(x.get("description")),
        )
        for x in gl.sort("row_id").to_dicts()
        if x.get("amount") is not None
    ]
    return bank, book, bank_df


@dataclass
class Params:
    tolerance: Decimal
    window: int
    buckets: list[int]
    warnings: list[str]


def params(db: Session, r: BankReconciliation) -> Params:
    rules = PackRules(db, r.org_id, r.rule_pack_version_id, r.period_end)
    p = r.rules_prefix
    try:
        tol = Decimal(str(rules.get(f"{p}.amount_tolerance")))
        window = int(rules.get(f"{p}.date_window_days"))
        key = f"{p}.ageing_buckets"
        buckets = list(rule_schemas.typed(key, rules.get(key)))
    except (CalcError, rule_schemas.RuleShapeError, ValueError, TypeError) as exc:
        raise AssuranceError(f"The rule pack is missing a reconciliation rule: {exc}") from exc
    if tol < 0 or window < 0:
        raise AssuranceError("The tolerance and date window must not be negative.")
    warnings = sorted({w for u in rules.used.values() if (w := u.warning())})
    return Params(tol, window, buckets, warnings)


# ---------------------------------------------------------------- matching


def _matched(r: BankReconciliation, manual_only: bool = False) -> tuple[set[int], set[int]]:
    bank: set[int] = set()
    book: set[int] = set()
    for m in r.matches:
        if manual_only and m.method is not ReconMethod.MANUAL:
            continue
        for ln in m.lines:
            (bank if ln.side is ReconSide.BANK else book).add(ln.row_id)
    return bank, book


def _add_match(
    r: BankReconciliation,
    method: ReconMethod,
    chosen: list[Line],
    actor: User,
    reason: str = "",
) -> ReconMatch:
    m = ReconMatch(org_id=r.org_id, method=method, reason=reason, created_by_id=actor.id)
    m.lines = [
        ReconMatchLine(
            org_id=r.org_id,
            reconciliation_id=r.id,
            side=ln.side,
            row_id=ln.row_id,
            amount=ln.amount,
        )
        for ln in chosen
    ]
    r.matches.append(m)
    return m


def auto_match(db: Session, r: BankReconciliation, actor: User) -> int:
    sign.changed(r)
    p = params(db, r)
    bank, book, _ = lines(db, r)
    r.matches = [m for m in r.matches if m.method is ReconMethod.MANUAL]
    db.flush()
    keep_bank, keep_book = _matched(r)
    found = mt.match(
        [mt.Item(b.row_id, b.on, b.amount, b.reference) for b in bank],
        [mt.Item(b.row_id, b.on, b.amount, b.reference) for b in book],
        p.tolerance,
        p.window,
        keep_bank,
        keep_book,
    )
    by_bank = {b.row_id: b for b in bank}
    by_book = {b.row_id: b for b in book}
    for f in found:
        _add_match(
            r,
            ReconMethod(f.method),
            [by_bank[i] for i in f.bank] + [by_book[i] for i in f.book],
            actor,
        )
    r.matcher_version, r.matched_at, r.warnings = mt.MATCHER_VERSION, now(), p.warnings
    db.flush()
    _record(db, r, actor, "auto_matched", matches=len(found), version=mt.MATCHER_VERSION)
    return len(found)


def manual_match(
    db: Session, r: BankReconciliation, body: ManualMatchIn, actor: User
) -> ReconMatch:
    sign.changed(r)
    p = params(db, r)
    bank, book, _ = lines(db, r)
    by_bank = {b.row_id: b for b in bank}
    by_book = {b.row_id: b for b in book}
    if len(set(body.bank_row_ids)) != len(body.bank_row_ids) or len(set(body.book_row_ids)) != len(
        body.book_row_ids
    ):
        raise AssuranceError("List each line once.")
    missing = [i for i in body.bank_row_ids if i not in by_bank] + [
        i for i in body.book_row_ids if i not in by_book
    ]
    if missing:
        raise AssuranceError(f"Line(s) {missing} are not in this reconciliation.")
    used_bank, used_book = _matched(r)
    if set(body.bank_row_ids) & used_bank or set(body.book_row_ids) & used_book:
        raise AssuranceError("A chosen line is already matched. Remove that match first.")
    chosen = [by_bank[i] for i in body.bank_row_ids] + [by_book[i] for i in body.book_row_ids]
    diff = sum((ln.amount for ln in chosen if ln.side is ReconSide.BANK), ZERO) - sum(
        (ln.amount for ln in chosen if ln.side is ReconSide.BOOK), ZERO
    )
    if abs(diff) > p.tolerance:
        raise AssuranceError(
            f"The lines differ by {diff}, more than the tolerance of {p.tolerance}."
        )
    m = _add_match(r, ReconMethod.MANUAL, chosen, actor, body.reason.strip())
    db.flush()
    _record(
        db,
        r,
        actor,
        "matched",
        match_id=str(m.id),
        bank_rows=body.bank_row_ids,
        book_rows=body.book_row_ids,
    )
    return m


def unmatch(
    db: Session, r: BankReconciliation, match_id: uuid.UUID, reason: str, actor: User
) -> None:
    sign.changed(r)
    m = next((x for x in r.matches if x.id == match_id), None)
    if m is None:
        raise LookupError("match")
    if not reason.strip():
        raise AssuranceError("Give a reason for removing the match.")
    r.matches.remove(m)
    db.flush()
    _record(db, r, actor, "unmatched", match_id=str(match_id), method=m.method.value, reason=reason)


# ---------------------------------------------------------------- view and proof


def _bank_closing(r: BankReconciliation, df: pl.DataFrame) -> tuple[Decimal | None, str]:
    if r.bank_closing_balance is not None:
        return r.bank_closing_balance, "entered"
    if "balance" in df.columns:
        rows = (
            df.filter(
                (pl.col("transaction_date") <= r.period_end) & pl.col("balance").is_not_null()
            )
            .sort(["transaction_date", "row_id"])
            .select("balance")
            .to_series()
            .to_list()
        )
        if rows:
            return Decimal(str(rows[-1])), "statement"
    return None, "unknown"


def _total(m: ReconMatch, side: ReconSide) -> Decimal:
    return sum((ln.amount for ln in m.lines if ln.side is side), ZERO)


def view(db: Session, r: BankReconciliation) -> dict[str, Any]:
    p = params(db, r)
    bank, book, bank_df = lines(db, r)
    owner: dict[tuple[ReconSide, int], ReconMatch] = {}
    for rm in r.matches:
        for ml in rm.lines:
            owner[(ml.side, ml.row_id)] = rm
    items = []
    ageing: dict[tuple[ReconSide, str], list[Decimal]] = {}
    for it in bank + book:
        found = owner.get((it.side, it.row_id))
        age = bucket = None
        if found is None:
            age, bucket = mt.age_bucket(it.on, r.period_end, p.buckets)
            ageing.setdefault((it.side, bucket), []).append(it.amount)
        items.append(
            {
                "side": it.side,
                "row_id": it.row_id,
                "date": it.on,
                "amount": it.amount,
                "reference": it.reference,
                "description": it.description,
                "match_id": found.id if found else None,
                "method": found.method if found else None,
                "age_days": age,
                "bucket": bucket,
            }
        )
    unmatched_bank = sum(
        (ln.amount for ln in bank if (ReconSide.BANK, ln.row_id) not in owner), ZERO
    )
    unmatched_book = sum(
        (ln.amount for ln in book if (ReconSide.BOOK, ln.row_id) not in owner), ZERO
    )
    movement = sum((ln.amount for ln in book), ZERO)
    book_closing = r.book_opening_balance + movement
    bank_closing, source = _bank_closing(r, bank_df)
    adjusted_bank = None if bank_closing is None else bank_closing + unmatched_book
    adjusted_book = book_closing + unmatched_bank
    difference = None if adjusted_bank is None else adjusted_bank - adjusted_book
    steps = [
        {
            "label": "Book closing balance",
            "expression": f"{r.book_opening_balance} + {movement}",
            "value": str(book_closing),
        },
        {
            "label": "Adjusted bank balance",
            "expression": f"{bank_closing if bank_closing is not None else '?'} + {unmatched_book}",
            "value": str(adjusted_bank) if adjusted_bank is not None else "not determinable",
        },
        {
            "label": "Adjusted book balance",
            "expression": f"{book_closing} + {unmatched_bank}",
            "value": str(adjusted_book),
        },
        {
            "label": "Difference",
            "expression": "adjusted bank − adjusted book",
            "value": str(difference) if difference is not None else "not determinable",
        },
    ]
    labels = mt.bucket_labels(p.buckets)
    ageing_rows = [
        {"side": side, "bucket": b, "count": len(v), "total": sum(v, ZERO)}
        for side in (ReconSide.BANK, ReconSide.BOOK)
        for b in labels
        if (v := ageing.get((side, b)))
    ]
    matched_bank, matched_book = _matched(r)
    return {
        "parameters": {
            "amount_tolerance": str(p.tolerance),
            "date_window_days": p.window,
            "ageing_buckets": p.buckets,
            "matcher_version": mt.MATCHER_VERSION,
        },
        "warnings": p.warnings,
        "summary": {
            "bank_closing_balance": bank_closing,
            "bank_closing_source": source,
            "book_opening_balance": r.book_opening_balance,
            "book_movement": movement,
            "book_closing_balance": book_closing,
            "unmatched_bank_total": unmatched_bank,
            "unmatched_book_total": unmatched_book,
            "adjusted_bank": adjusted_bank,
            "adjusted_book": adjusted_book,
            "difference": difference,
            "bank_items": len(bank),
            "book_items": len(book),
            "matched_bank_items": len(matched_bank),
            "matched_book_items": len(matched_book),
            "ageing": ageing_rows,
            "steps": steps,
        },
        "items": items,
        "matches": [
            {
                "id": m.id,
                "method": m.method,
                "reason": m.reason,
                "bank_row_ids": [ln.row_id for ln in m.lines if ln.side is ReconSide.BANK],
                "book_row_ids": [ln.row_id for ln in m.lines if ln.side is ReconSide.BOOK],
                "bank_total": (
                    bt := sum((ln.amount for ln in m.lines if ln.side is ReconSide.BANK), ZERO)
                ),
                "book_total": (
                    kt := sum((ln.amount for ln in m.lines if ln.side is ReconSide.BOOK), ZERO)
                ),
                "difference": bt - kt,
                "created_by_id": m.created_by_id,
                "created_at": m.created_at,
            }
            for m in r.matches
        ],
    }


UNMATCHED_COLUMNS = ["Side", "Row", "Date", "Amount", "Reference", "Description", "Days", "Bucket"]
MATCH_COLUMNS = ["Method", "Bank rows", "Book rows", "Bank total", "Book total", "Reason"]


def _ids(ids: list[int]) -> str:
    return " ".join(map(str, ids))


def sign_off(db: Session, r: BankReconciliation, actor: User) -> Any:
    v = view(db, r)
    s = v["summary"]
    if s["difference"] is None:
        raise AssuranceError("Enter the statement closing balance before signing off.")
    if s["difference"] != 0:
        raise AssuranceError(f"The reconciliation does not prove: difference {s['difference']}.")
    unmatched = [i for i in v["items"] if i["match_id"] is None]
    content = {
        "title": f"Bank reconciliation — {r.name}",
        "subtitle": f"{r.entity.name} · {r.account_label} · {r.period_start} to {r.period_end}",
        "is_demo": r.is_demo,
        "warnings": v["warnings"],
        "meta": [
            ["Currency", r.currency],
            ["Statement dataset version", str(r.statement_version_id)],
            ["Ledger dataset version", str(r.ledger_version_id)],
            ["GL accounts", ", ".join(r.gl_accounts)],
            ["Matcher", r.matcher_version],
            ["Amount tolerance", v["parameters"]["amount_tolerance"]],
            ["Date window (days)", v["parameters"]["date_window_days"]],
            *[[st["label"], f"{st['expression']} = {st['value']}"] for st in s["steps"]],
        ],
        "sections": [
            {
                "title": "Unmatched items",
                "columns": [
                    "Side",
                    "Row",
                    "Date",
                    "Amount",
                    "Reference",
                    "Description",
                    "Days",
                    "Bucket",
                ],
                "rows": [
                    [
                        i["side"].value,
                        i["row_id"],
                        str(i["date"]),
                        str(i["amount"]),
                        i["reference"],
                        i["description"],
                        i["age_days"],
                        i["bucket"],
                    ]
                    for i in unmatched
                ],
            },
            {
                "title": "Ageing of unmatched items",
                "columns": ["Side", "Bucket", "Count", "Total"],
                "rows": [
                    [a["side"].value, a["bucket"], a["count"], str(a["total"])] for a in s["ageing"]
                ],
            },
            {
                "title": "Matches",
                "columns": [
                    "Method",
                    "Bank rows",
                    "Book rows",
                    "Bank total",
                    "Book total",
                    "Reason",
                ],
                "rows": [
                    [
                        m["method"].value,
                        " ".join(map(str, m["bank_row_ids"])),
                        " ".join(map(str, m["book_row_ids"])),
                        str(m["bank_total"]),
                        str(m["book_total"]),
                        m["reason"],
                    ]
                    for m in v["matches"]
                ],
            },
        ],
        "notes": [],
    }
    return sign.sign_off(db, r, KIND, content, actor)


def is_open(r: BankReconciliation) -> bool:
    return r.status is not AssuranceStatus.SIGNED_OFF
