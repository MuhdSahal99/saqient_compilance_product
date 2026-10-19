"""Trial balance → lead schedules with prior-year comparison (D2), and audit workpapers.

An engagement names a current and (optionally) a prior-year trial balance version of
its entity. Accounts are mapped to lead schedules; the report sums the mapped
balances and lists every account no schedule picks up, so nothing drops silently.
A lead schedule workpaper freezes those sums with row-level evidence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.audit import LEAD_KEY
from app.models import (
    AccountMapping,
    AuditEngagement,
    DatasetVersion,
    FsSection,
    LeadSchedule,
    TaxWorkpaper,
    User,
    WorkpaperKind,
)
from app.schemas import (
    AccountMappingsIn,
    AuditWorkpaperIn,
    EngagementSetupIn,
    LeadSchedulesIn,
    WorkpaperIn,
    WorkpaperInputIn,
)
from app.services import audit, workpapers
from app.services.datasets import DatasetNotReady, load_frame
from app.services.engagements import EngagementError, require_open
from app.services.workpapers import _dataset_ref, _published

ZERO = Decimal(0)
SHARE = Decimal("0.0001")
YEAR_LABEL = {"cy": "current year", "py": "prior year"}


def _change(movement: Decimal, prior: Decimal) -> Decimal | None:
    return (movement / abs(prior)).quantize(SHARE, ROUND_HALF_UP) if prior else None


def _record(db: Session, e: AuditEngagement, actor: User, action: str, **meta: Any) -> None:
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action=f"engagement.{action}",
        object_type="audit_engagement",
        object_id=e.id,
        meta=meta,
    )


def _tb(db: Session, e: AuditEngagement, version_id: uuid.UUID) -> DatasetVersion:
    try:
        v, frame = load_frame(db, version_id, e.org_id)
    except DatasetNotReady as exc:
        raise LookupError("dataset version") from exc
    if v.dataset.kind.value != "trial_balance":
        raise EngagementError("Choose a trial balance dataset version.")
    if v.dataset.entity_id != e.entity_id:
        raise EngagementError("The trial balance belongs to another entity.")
    if "currency" in frame.columns:
        other = {c for c in frame["currency"].drop_nulls().unique().to_list() if c != e.currency}
        if other:
            raise EngagementError(
                f"The trial balance has amounts in {', '.join(sorted(other))}; "
                f"the engagement is in {e.currency}."
            )
    return v


def set_up(db: Session, e: AuditEngagement, body: EngagementSetupIn, actor: User) -> None:
    require_open(e)
    if body.cy_tb_version_id and body.cy_tb_version_id == body.py_tb_version_id:
        raise EngagementError("The current and prior-year trial balances must differ.")
    for vid in (body.cy_tb_version_id, body.py_tb_version_id):
        if vid is not None:
            _tb(db, e, vid)
    if body.rule_pack_version_id is not None:
        try:
            _published(db, e.org_id, body.rule_pack_version_id)
        except workpapers.WorkpaperError as exc:
            raise EngagementError(str(exc)) from exc
    e.cy_tb_version_id = body.cy_tb_version_id
    e.py_tb_version_id = body.py_tb_version_id
    e.rule_pack_version_id = body.rule_pack_version_id
    e.rules_prefix = body.rules_prefix
    db.flush()
    _record(
        db,
        e,
        actor,
        "set_up",
        cy_tb_version_id=str(body.cy_tb_version_id) if body.cy_tb_version_id else None,
        py_tb_version_id=str(body.py_tb_version_id) if body.py_tb_version_id else None,
        rule_pack_version_id=str(body.rule_pack_version_id) if body.rule_pack_version_id else None,
    )


def schedules(db: Session, e: AuditEngagement) -> list[LeadSchedule]:
    return list(
        db.scalars(
            select(LeadSchedule)
            .where(LeadSchedule.org_id == e.org_id, LeadSchedule.engagement_id == e.id)
            .order_by(LeadSchedule.ordinal, LeadSchedule.code)
        )
    )


def mappings(db: Session, e: AuditEngagement) -> list[tuple[str, str]]:
    rows = db.execute(
        select(AccountMapping.account_code, LeadSchedule.code)
        .join(LeadSchedule, LeadSchedule.id == AccountMapping.lead_schedule_id)
        .where(AccountMapping.org_id == e.org_id, AccountMapping.engagement_id == e.id)
        .order_by(AccountMapping.account_code)
    )
    return [(a, c) for a, c in rows]


def replace_schedules(db: Session, e: AuditEngagement, body: LeadSchedulesIn, actor: User) -> None:
    require_open(e)
    codes = [s.code.upper() for s in body.schedules]
    if len(set(codes)) != len(codes):
        raise EngagementError("Lead schedule codes must be unique.")
    existing = {s.code: s for s in schedules(db, e)}
    in_use = {c for _, c in mappings(db, e)}
    dropped = sorted((set(existing) - set(codes)) & in_use)
    if dropped:
        raise EngagementError(f"Lead schedule {dropped[0]} still has mapped accounts.")
    for code in set(existing) - set(codes):
        db.delete(existing[code])
    for i, s in enumerate(body.schedules):
        code = s.code.upper()
        row = existing.get(code) or LeadSchedule(org_id=e.org_id, engagement_id=e.id, code=code)
        row.name, row.section, row.ordinal = s.name.strip(), s.section, i
        db.add(row)
    db.flush()
    _record(db, e, actor, "lead_schedules_set", count=len(codes))


def replace_mappings(db: Session, e: AuditEngagement, body: AccountMappingsIn, actor: User) -> None:
    require_open(e)
    by_code = {s.code: s for s in schedules(db, e)}
    seen: set[str] = set()
    for m in body.mappings:
        acct = m.account_code.strip()
        if acct in seen:
            raise EngagementError(f"Account {acct} is mapped more than once.")
        seen.add(acct)
        if m.lead_code.upper() not in by_code:
            raise EngagementError(f"There is no lead schedule {m.lead_code.upper()}.")
    for old in db.scalars(
        select(AccountMapping).where(
            AccountMapping.org_id == e.org_id, AccountMapping.engagement_id == e.id
        )
    ):
        db.delete(old)
    db.flush()
    for m in body.mappings:
        db.add(
            AccountMapping(
                org_id=e.org_id,
                engagement_id=e.id,
                account_code=m.account_code.strip(),
                lead_schedule_id=by_code[m.lead_code.upper()].id,
            )
        )
    db.flush()
    _record(db, e, actor, "account_mappings_set", count=len(body.mappings))


@dataclass
class _Acct:
    name: str | None = None
    cy: Decimal = ZERO
    py: Decimal = ZERO
    cy_rows: list[int] = field(default_factory=list)
    py_rows: list[int] = field(default_factory=list)


def _balances(frame: pl.DataFrame) -> dict[str, tuple[Decimal, str | None, list[int]]]:
    out: dict[str, tuple[Decimal, str | None, list[int]]] = {}
    names = "account_name" in frame.columns
    for r in frame.iter_rows(named=True):
        code = str(r["account_code"]).strip()
        bal = Decimal(str(r["balance"])) if r.get("balance") is not None else ZERO
        total, name, rows = out.get(code, (ZERO, None, []))
        out[code] = (
            total + bal,
            name or (r["account_name"] if names else None),
            [*rows, r["row_id"]],
        )
    return out


def _ref(v: DatasetVersion | None) -> dict[str, Any] | None:
    if v is None:
        return None
    return {"id": v.id, "dataset_name": v.dataset.name, "version_number": v.version_number}


def report(db: Session, e: AuditEngagement) -> dict[str, Any]:
    if e.cy_tb_version_id is None:
        raise EngagementError("Choose the current-year trial balance first.")
    accts: dict[str, _Acct] = {}
    versions: dict[str, DatasetVersion | None] = {"cy": None, "py": None}
    for side, vid in (("cy", e.cy_tb_version_id), ("py", e.py_tb_version_id)):
        if vid is None:
            continue
        try:
            v, frame = load_frame(db, vid, e.org_id)
        except DatasetNotReady as exc:
            raise EngagementError("A chosen trial balance is no longer available.") from exc
        versions[side] = v
        for code, (bal, name, rows) in _balances(frame).items():
            a = accts.setdefault(code, _Acct())
            a.name = a.name or name
            setattr(a, side, bal)
            setattr(a, f"{side}_rows", sorted(rows))

    def acct_out(code: str, a: _Acct) -> dict[str, Any]:
        mv = a.cy - a.py
        return {
            "account_code": code,
            "account_name": a.name,
            "cy": a.cy,
            "py": a.py,
            "movement": mv,
            "change_share": _change(mv, a.py),
            "cy_row_ids": a.cy_rows,
            "py_row_ids": a.py_rows,
        }

    mapped = dict(mappings(db, e))
    lines = []
    for s in schedules(db, e):
        codes = sorted(c for c, lead in mapped.items() if lead == s.code and c in accts)
        cy = sum((accts[c].cy for c in codes), ZERO)
        py = sum((accts[c].py for c in codes), ZERO)
        lines.append(
            {
                "code": s.code,
                "name": s.name,
                "section": s.section,
                "cy": cy,
                "py": py,
                "movement": cy - py,
                "change_share": _change(cy - py, py),
                "accounts": [acct_out(c, accts[c]) for c in codes],
            }
        )
    return {
        "currency": e.currency,
        "current": _ref(versions["cy"]),
        "prior": _ref(versions["py"]),
        "schedules": lines,
        "unmapped": [acct_out(c, a) for c, a in sorted(accts.items()) if c not in mapped],
        "missing_accounts": sorted(c for c in mapped if c not in accts),
        "cy_net": sum((a.cy for a in accts.values()), ZERO),
        "py_net": sum((a.py for a in accts.values()), ZERO),
    }


# ---------------------------------------------------------------- audit workpapers


def create_workpaper(
    db: Session, e: AuditEngagement, body: AuditWorkpaperIn, actor: User
) -> TaxWorkpaper:
    require_open(e)
    if e.rule_pack_version_id is None or e.rules_prefix is None:
        raise EngagementError("Choose the engagement's audit rule pack first.")
    wp = workpapers.create(
        db,
        e.entity,
        WorkpaperIn(
            entity_id=e.entity_id,
            kind=WorkpaperKind(body.kind),
            title=body.title,
            period_start=e.period_start,
            period_end=e.period_end,
            rule_pack_version_id=e.rule_pack_version_id,
            rules_prefix=e.rules_prefix,
            currency=e.currency,
        ),
        actor,
        engagement=e,
    )
    if wp.kind is WorkpaperKind.LEAD_SCHEDULE:
        load_lead_balances(db, e, wp, actor)
    elif wp.kind is WorkpaperKind.FS_DRAFT:
        load_fs_balances(db, e, wp, actor)
    return wp


def load_fs_balances(db: Session, e: AuditEngagement, wp: TaxWorkpaper, actor: User) -> None:
    """Replace an FS draft's face lines with the lead schedules by section, then compute."""
    rep = report(db, e)
    if not rep["schedules"]:
        raise EngagementError("Set up lead schedules and account mappings first.")
    for ln in [x for x in wp.lines if x.line_key.startswith("fs_")]:
        workpapers.delete_input(db, wp, ln.line_key, actor)
    cy_v = db.get(DatasetVersion, e.cy_tb_version_id) if e.cy_tb_version_id else None
    py_v = db.get(DatasetVersion, e.py_tb_version_id) if e.py_tb_version_id else None
    for s in rep["schedules"]:
        code, section = s["code"].lower(), FsSection(s["section"]).value
        for side, v, category in (("cy", cy_v, "current_year"), ("py", py_v, "prior_year")):
            if v is None:
                continue
            rows = sorted(r for a in s["accounts"] for r in a[f"{side}_row_ids"])
            line = workpapers.put_input(
                db,
                wp,
                f"fs_{section}_{code}_{side}",
                WorkpaperInputIn(
                    category=category,
                    label=f"{s['code']} {s['name']} ({YEAR_LABEL[side]})",
                    amount=s[side],
                    note=f"From trial balance {v.dataset.name} v{v.version_number}",
                ),
                actor,
            )
            line.evidence = [
                _dataset_ref(
                    v,
                    rows,
                    account_codes=sorted(a["account_code"] for a in s["accounts"]),
                    lead_code=s["code"],
                )
            ]
    db.flush()
    workpapers.compute(db, wp, actor)


def load_lead_balances(db: Session, e: AuditEngagement, wp: TaxWorkpaper, actor: User) -> None:
    """Replace a lead schedule workpaper's balances with the current report, then compute."""
    rep = report(db, e)
    if not rep["schedules"]:
        raise EngagementError("Set up lead schedules and account mappings first.")
    for ln in [x for x in wp.lines if LEAD_KEY.match(x.line_key)]:
        workpapers.delete_input(db, wp, ln.line_key, actor)
    cy_v = db.get(DatasetVersion, e.cy_tb_version_id) if e.cy_tb_version_id else None
    py_v = db.get(DatasetVersion, e.py_tb_version_id) if e.py_tb_version_id else None
    for s in rep["schedules"]:
        code = s["code"].lower()
        for side, v, category in (("cy", cy_v, "current_year"), ("py", py_v, "prior_year")):
            if v is None:
                continue
            rows = sorted(r for a in s["accounts"] for r in a[f"{side}_row_ids"])
            line = workpapers.put_input(
                db,
                wp,
                f"lead_{code}_{side}",
                WorkpaperInputIn(
                    category=category,
                    label=f"{s['code']} {s['name']} ({YEAR_LABEL[side]})",
                    amount=s[side],
                    note=f"From trial balance {v.dataset.name} v{v.version_number}",
                ),
                actor,
            )
            line.evidence = [
                _dataset_ref(
                    v,
                    rows,
                    account_codes=sorted(a["account_code"] for a in s["accounts"]),
                    lead_code=s["code"],
                )
            ]
    db.flush()
    workpapers.compute(db, wp, actor)


def materiality(db: Session, e: AuditEngagement) -> dict[str, Any] | None:
    """Amounts from the latest signed-off materiality workpaper of the engagement."""
    from app.models import WorkpaperSnapshot

    snap = db.scalar(
        select(WorkpaperSnapshot)
        .join(TaxWorkpaper, TaxWorkpaper.id == WorkpaperSnapshot.workpaper_id)
        .where(
            TaxWorkpaper.org_id == e.org_id,
            TaxWorkpaper.engagement_id == e.id,
            TaxWorkpaper.kind == WorkpaperKind.MATERIALITY,
        )
        .order_by(WorkpaperSnapshot.signed_off_at.desc())
        .limit(1)
    )
    if snap is None:
        return None
    amounts = {
        ln["line_key"].removeprefix("calc:"): Decimal(str(ln["amount"]))
        for ln in snap.content["lines"]
        if ln.get("source") == "computed" and ln.get("amount") is not None
    }
    return {
        "workpaper_id": str(snap.workpaper_id),
        "version": snap.version,
        "overall": amounts.get("overall"),
        "performance": amounts.get("performance"),
        "trivial": amounts.get("trivial"),
    }
