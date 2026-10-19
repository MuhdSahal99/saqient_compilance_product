"""Direct-tax workpapers: preparer inputs with evidence, computed lines, sign-off.

The formulas live in ``app.calc``; this module feeds them input lines and rules
from one published pack version (resolved on the period end), stores every
computed line with its steps and rule snapshots, and freezes the result at
sign-off. A signed-off paper is changed only by reopening it with a reason; the
next sign-off is version n+1.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import calc
from app.models import (
    AUDIT_WORKPAPER_KINDS,
    AuditEngagement,
    ChecklistState,
    DatasetVersion,
    Document,
    DocumentVersion,
    LegalEntity,
    LineSource,
    RulePackVersion,
    SourceBlock,
    TaxWorkpaper,
    User,
    WorkpaperKind,
    WorkpaperLine,
    WorkpaperSnapshot,
    WorkpaperStatus,
)
from app.schemas import EvidenceRefIn, TrialBalanceImportIn, WorkpaperIn, WorkpaperInputIn
from app.services import audit, rule_packs
from app.services.datasets import DatasetNotReady, load_frame

MAX_PERIOD_DAYS = 731
QUOTE_CHARS = 300


class WorkpaperError(ValueError):
    """Shown to the preparer as a 422."""


class WorkpaperConflict(WorkpaperError):
    """The workpaper's state does not allow the action (409)."""


@dataclass
class PackRules(calc.RuleSource):
    """Rules from one pack version effective on ``on``; remembers what was read."""

    db: Session
    org_id: uuid.UUID
    version_id: uuid.UUID
    on: date
    used: dict[str, rule_packs.ResolvedRule] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        if key not in self.used:
            try:
                self.used[key] = rule_packs.resolve(
                    self.db, self.org_id, self.version_id, key, self.on
                )
            except rule_packs.RuleNotFound as exc:
                raise calc.CalcError(str(exc)) from exc
        return self.used[key].value


def _now() -> datetime:
    return datetime.now(UTC)


def _require_draft(wp: TaxWorkpaper) -> None:
    if wp.status is not WorkpaperStatus.DRAFT:
        raise WorkpaperConflict("The workpaper is signed off. Reopen it with a reason first.")


def _published(db: Session, org_id: uuid.UUID, version_id: uuid.UUID) -> RulePackVersion:
    v = db.scalar(
        select(RulePackVersion).where(
            RulePackVersion.id == version_id, RulePackVersion.org_id == org_id
        )
    )
    if v is None:
        raise LookupError("Rule pack version not found.")
    if v.state is not ChecklistState.PUBLISHED:
        raise WorkpaperError("Use a published rule pack version.")
    return v


def create(
    db: Session,
    entity: LegalEntity,
    body: WorkpaperIn,
    actor: User,
    engagement: AuditEngagement | None = None,
) -> TaxWorkpaper:
    if body.kind.value not in calc.FORMULAS:
        raise WorkpaperError(f"Workpapers of kind '{body.kind.value}' are not available yet.")
    if (body.kind in AUDIT_WORKPAPER_KINDS) != (engagement is not None):
        raise WorkpaperError(
            "Audit workpapers are created from their engagement; tax workpapers are not."
        )
    if body.period_end < body.period_start:
        raise WorkpaperError("The period must end after it starts.")
    if (body.period_end - body.period_start).days > MAX_PERIOD_DAYS:
        raise WorkpaperError("A workpaper period can be at most two years.")
    version = _published(db, entity.org_id, body.rule_pack_version_id)
    wp = TaxWorkpaper(
        org_id=entity.org_id,
        entity_id=entity.id,
        kind=body.kind,
        title=body.title.strip(),
        period_start=body.period_start,
        period_end=body.period_end,
        currency=body.currency or entity.functional_currency,
        rule_pack_version_id=version.id,
        rules_prefix=body.rules_prefix,
        engagement_id=engagement.id if engagement else None,
        status=WorkpaperStatus.DRAFT,
        warnings=[],
        created_by_id=actor.id,
    )
    db.add(wp)
    db.flush()
    audit.record(
        db,
        org_id=wp.org_id,
        actor_id=actor.id,
        action="workpaper.created",
        object_type="tax_workpaper",
        object_id=wp.id,
        meta={"kind": wp.kind.value, "entity_id": str(entity.id)},
    )
    return wp


# ---------------------------------------------------------------- evidence


def resolve_evidence(db: Session, org_id: uuid.UUID, refs: list[EvidenceRefIn]) -> list[dict]:
    """Check each reference exists in this organisation and describe it for readers."""
    out: list[dict[str, Any]] = []
    for ref in refs:
        if ref.kind == "source_block":
            row = db.execute(
                select(SourceBlock, DocumentVersion.version_number, Document.title, Document.id)
                .join(DocumentVersion, DocumentVersion.id == SourceBlock.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(SourceBlock.id == ref.source_block_id, SourceBlock.org_id == org_id)
            ).first()
            if row is None:
                raise WorkpaperError("An evidence source block was not found.")
            b, vnum, title, doc_id = row
            out.append(
                {
                    "kind": "source_block",
                    "source_block_id": str(b.id),
                    "document_id": str(doc_id),
                    "document_title": title,
                    "document_version_id": str(b.document_version_id),
                    "document_version": vnum,
                    "ref": b.ref,
                    "page_number": b.page_number,
                    "paragraph_number": b.paragraph_number,
                    "quote": b.text[:QUOTE_CHARS],
                }
            )
            continue
        assert ref.dataset_version_id is not None
        try:
            v, frame = load_frame(db, ref.dataset_version_id, org_id)
        except DatasetNotReady as exc:
            raise WorkpaperError(
                "An evidence dataset version was not found or is not ready."
            ) from exc
        wanted = sorted(set(ref.row_ids))
        present = set(frame.filter(frame["row_id"].is_in(wanted))["row_id"].to_list())
        missing = [r for r in wanted if r not in present]
        if missing:
            raise WorkpaperError(f"Rows {missing[:5]} are not in that dataset version.")
        out.append(_dataset_ref(v, wanted))
    return out


def _dataset_ref(v: DatasetVersion, row_ids: list[int], **extra: Any) -> dict[str, Any]:
    return {
        "kind": "dataset_rows",
        "dataset_id": str(v.dataset_id),
        "dataset_name": v.dataset.name,
        "dataset_version_id": str(v.id),
        "version_number": v.version_number,
        "parquet_sha256": v.parquet_sha256,
        "row_ids": row_ids,
        **extra,
    }


# ---------------------------------------------------------------- inputs


def _invalidate(db: Session, wp: TaxWorkpaper) -> None:
    """Inputs changed: earlier computed lines no longer follow from them."""
    wp.lines[:] = [ln for ln in wp.lines if ln.source is LineSource.MANUAL]
    db.flush()  # delete them before new lines reuse their keys
    wp.computed_at = None
    wp.result_hash = None
    wp.calc_version = None
    wp.warnings = []
    wp.prepared_by = None
    wp.prepared_at = None


def _check_category(wp: TaxWorkpaper, category: str) -> None:
    allowed = calc.CATEGORIES.get(wp.kind.value, ("input",))
    if category not in allowed:
        raise WorkpaperError(f"Category must be one of: {', '.join(allowed)}.")


def put_input(
    db: Session, wp: TaxWorkpaper, key: str, body: WorkpaperInputIn, actor: User
) -> WorkpaperLine:
    _require_draft(wp)
    _check_category(wp, body.category)
    evidence = resolve_evidence(db, wp.org_id, body.evidence)
    line = next((ln for ln in wp.lines if ln.line_key == key), None)
    if line is not None and line.source is not LineSource.MANUAL:
        raise WorkpaperError("That key belongs to a computed line.")
    _invalidate(db, wp)
    if line is None:
        ordinal = max((ln.ordinal for ln in wp.lines), default=0) + 1
        line = WorkpaperLine(
            org_id=wp.org_id,
            source=LineSource.MANUAL,
            section="adjustment" if body.category != "input" else "input",
            line_key=key,
            ordinal=ordinal,
            created_by_id=actor.id,
        )
        wp.lines.append(line)
    line.section = "adjustment" if body.category != "input" else "input"
    line.category = body.category
    line.label = body.label.strip()
    line.amount = body.amount
    line.value = body.value.strip() if body.value is not None else None
    line.note = body.note
    line.evidence = evidence
    db.flush()
    audit.record(
        db,
        org_id=wp.org_id,
        actor_id=actor.id,
        action="workpaper.input_saved",
        object_type="tax_workpaper",
        object_id=wp.id,
        meta={"line_key": key, "category": body.category, "evidence_count": len(evidence)},
    )
    return line


def delete_input(db: Session, wp: TaxWorkpaper, key: str, actor: User) -> None:
    _require_draft(wp)
    line = next(
        (ln for ln in wp.lines if ln.line_key == key and ln.source is LineSource.MANUAL), None
    )
    if line is None:
        raise LookupError("Not found.")
    _invalidate(db, wp)
    wp.lines.remove(line)
    db.flush()
    audit.record(
        db,
        org_id=wp.org_id,
        actor_id=actor.id,
        action="workpaper.input_deleted",
        object_type="tax_workpaper",
        object_id=wp.id,
        meta={"line_key": key},
    )


def import_trial_balance(
    db: Session, wp: TaxWorkpaper, body: TrialBalanceImportIn, actor: User
) -> list[WorkpaperLine]:
    """Sum mapped trial balance accounts into input lines, citing the rows used."""
    _require_draft(wp)
    try:
        v, frame = load_frame(db, body.dataset_version_id, wp.org_id)
    except DatasetNotReady as exc:
        raise WorkpaperError("The dataset version was not found or is not ready.") from exc
    if v.dataset.kind.value != "trial_balance":
        raise WorkpaperError("Choose a trial balance dataset.")
    if "currency" in frame.columns:
        other = {c for c in frame["currency"].drop_nulls().unique().to_list() if c != wp.currency}
        if other:
            raise WorkpaperError(
                f"The trial balance has amounts in {', '.join(sorted(other))}; "
                f"the workpaper is in {wp.currency}."
            )
    seen: set[str] = set()
    for m in body.lines:
        _check_category(wp, m.category)
        dup = seen & set(m.account_codes)
        if dup:
            raise WorkpaperError(f"Account {sorted(dup)[0]} is mapped to more than one line.")
        seen |= set(m.account_codes)
    _invalidate(db, wp)
    saved: list[WorkpaperLine] = []
    for m in body.lines:
        rows = frame.filter(frame["account_code"].is_in(m.account_codes))
        if rows.height == 0:
            raise WorkpaperError(
                f"None of the accounts for '{m.line_key}' are in the trial balance."
            )
        total = sum(
            (Decimal(str(b)) for b in rows["balance"].to_list() if b is not None), Decimal(0)
        )
        amount = -total if m.sign == "credit" else total
        evidence = [
            _dataset_ref(
                v,
                sorted(rows["row_id"].to_list()),
                account_codes=sorted(m.account_codes),
                sign=m.sign,
            )
        ]
        line = put_input(
            db,
            wp,
            m.line_key,
            WorkpaperInputIn(
                category=m.category,
                label=m.label,
                amount=amount,
                note=f"From trial balance {v.dataset.name} v{v.version_number}",
            ),
            actor,
        )
        line.evidence = evidence
        saved.append(line)
    db.flush()
    return saved


# ---------------------------------------------------------------- compute


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute(db: Session, wp: TaxWorkpaper, actor: User) -> TaxWorkpaper:
    _require_draft(wp)
    manual = [ln for ln in wp.lines if ln.source is LineSource.MANUAL]
    inputs = calc.Inputs(
        lines=[
            calc.InputLine(ln.line_key, ln.category, ln.amount, ln.value, ln.label) for ln in manual
        ],
        period_start=wp.period_start,
        period_end=wp.period_end,
    )
    rules = PackRules(db, wp.org_id, wp.rule_pack_version_id, wp.period_end)
    try:
        outputs = calc.run(wp.kind.value, inputs, rules, wp.rules_prefix)
    except calc.CalcError as exc:
        raise WorkpaperError(str(exc)) from exc
    _invalidate(db, wp)
    snapshots = {k: r.snapshot() for k, r in rules.used.items()}
    base = max((ln.ordinal for ln in manual), default=0)
    for i, o in enumerate(outputs, start=1):
        wp.lines.append(
            WorkpaperLine(
                org_id=wp.org_id,
                source=LineSource.COMPUTED,
                section=o.section,
                line_key=f"calc:{o.key}",
                category="computed",
                label=o.label,
                ordinal=base + i,
                amount=o.amount,
                value=o.value,
                formula_id=o.formula_id,
                explanation=[s.as_dict() for s in o.steps],
                rule_snapshots=[snapshots[k] for k in o.rule_keys if k in snapshots],
                evidence=[],
                note="",
                created_by_id=actor.id,
            )
        )
    wp.warnings = sorted({w for r in rules.used.values() if (w := r.warning())})
    wp.calc_version = calc.CALC_VERSION
    wp.computed_at = _now()
    wp.result_hash = hashlib.sha256(
        _canonical(
            {
                "calc_version": calc.CALC_VERSION,
                "kind": wp.kind.value,
                "inputs": [
                    [ln.line_key, ln.category, ln.amount, ln.value, ln.evidence] for ln in manual
                ],
                "rules": snapshots,
                "outputs": [[o.key, o.formula_id, o.amount, o.value] for o in outputs],
            }
        ).encode()
    ).hexdigest()
    db.flush()
    audit.record(
        db,
        org_id=wp.org_id,
        actor_id=actor.id,
        action="workpaper.computed",
        object_type="tax_workpaper",
        object_id=wp.id,
        meta={
            "calc_version": calc.CALC_VERSION,
            "result_hash": wp.result_hash,
            "lines": len(outputs),
            "unverified_rules": len(wp.warnings),
        },
    )
    return wp


# ---------------------------------------------------------------- sign-off


def _line_content(ln: WorkpaperLine) -> dict[str, Any]:
    return {
        "source": ln.source.value,
        "section": ln.section,
        "line_key": ln.line_key,
        "category": ln.category,
        "label": ln.label,
        "amount": str(ln.amount) if ln.amount is not None else None,
        "value": ln.value,
        "formula_id": ln.formula_id,
        "explanation": ln.explanation,
        "rule_snapshots": ln.rule_snapshots,
        "evidence": ln.evidence,
        "note": ln.note,
    }


def content(wp: TaxWorkpaper) -> dict[str, Any]:
    return {
        "workpaper_id": str(wp.id),
        "kind": wp.kind.value,
        "title": wp.title,
        "entity": {"id": str(wp.entity_id), "name": wp.entity.name},
        "period_start": wp.period_start.isoformat(),
        "period_end": wp.period_end.isoformat(),
        "currency": wp.currency,
        "rule_pack_version_id": str(wp.rule_pack_version_id),
        "rules_prefix": wp.rules_prefix,
        "engagement_id": str(wp.engagement_id) if wp.engagement_id else None,
        "calc_version": wp.calc_version,
        "computed_at": wp.computed_at.isoformat() if wp.computed_at else None,
        "result_hash": wp.result_hash,
        "warnings": wp.warnings,
        "is_demo": wp.is_demo,
        "lines": [_line_content(ln) for ln in wp.lines],
    }


def snapshots(db: Session, wp: TaxWorkpaper) -> list[WorkpaperSnapshot]:
    return list(
        db.scalars(
            select(WorkpaperSnapshot)
            .where(WorkpaperSnapshot.workpaper_id == wp.id, WorkpaperSnapshot.org_id == wp.org_id)
            .order_by(WorkpaperSnapshot.version)
        )
    )


def prepare(db: Session, wp: TaxWorkpaper, actor: User) -> None:
    """Audit workpapers: the preparer marks the computed paper ready for review."""
    _require_draft(wp)
    if wp.kind not in AUDIT_WORKPAPER_KINDS:
        raise WorkpaperError("Only audit workpapers have a preparer step.")
    if wp.result_hash is None:
        raise WorkpaperError("Compute the workpaper before marking it prepared.")
    wp.prepared_by = actor
    wp.prepared_at = _now()
    db.flush()
    audit.record(
        db,
        org_id=wp.org_id,
        actor_id=actor.id,
        action="workpaper.prepared",
        object_type="tax_workpaper",
        object_id=wp.id,
        meta={"result_hash": wp.result_hash},
    )


def sign_off(db: Session, wp: TaxWorkpaper, actor: User) -> WorkpaperSnapshot:
    _require_draft(wp)
    if wp.result_hash is None:
        raise WorkpaperError("Compute the workpaper before signing it off.")
    if wp.kind in AUDIT_WORKPAPER_KINDS:
        if wp.prepared_by_id is None:
            raise WorkpaperError("A preparer must mark the workpaper prepared first.")
        if wp.prepared_by_id == actor.id:
            raise WorkpaperError("The reviewer must be someone other than the preparer.")
    version = (
        db.scalar(
            select(func.max(WorkpaperSnapshot.version)).where(
                WorkpaperSnapshot.workpaper_id == wp.id
            )
        )
        or 0
    ) + 1
    at = _now()
    snap = WorkpaperSnapshot(
        org_id=wp.org_id,
        workpaper_id=wp.id,
        version=version,
        content={
            **content(wp),
            "version": version,
            "signed_off_by": actor.full_name,
            "prepared_by": wp.prepared_by.full_name if wp.prepared_by else None,
            "prepared_at": wp.prepared_at.isoformat() if wp.prepared_at else None,
        },
        signed_off_by_id=actor.id,
        signed_off_at=at,
    )
    db.add(snap)
    wp.status = WorkpaperStatus.SIGNED_OFF
    db.flush()
    audit.record(
        db,
        org_id=wp.org_id,
        actor_id=actor.id,
        action="workpaper.signed_off",
        object_type="tax_workpaper",
        object_id=wp.id,
        meta={"version": version, "result_hash": wp.result_hash},
    )
    return snap


def reopen(db: Session, wp: TaxWorkpaper, reason: str, actor: User) -> None:
    if wp.status is not WorkpaperStatus.SIGNED_OFF:
        raise WorkpaperConflict("Only a signed-off workpaper can be reopened.")
    wp.status = WorkpaperStatus.DRAFT
    wp.prepared_by = None
    wp.prepared_at = None
    db.flush()
    audit.record(
        db,
        org_id=wp.org_id,
        actor_id=actor.id,
        action="workpaper.reopened",
        object_type="tax_workpaper",
        object_id=wp.id,
        meta={"reason": reason.strip()},
    )


def kinds() -> list[WorkpaperKind]:
    return [k for k in WorkpaperKind if k.value in calc.FORMULAS]


# ---------------------------------------------------------------- standalone checks


@dataclass
class Evaluation:
    outputs: list[calc.Output]
    rules: dict[str, dict[str, Any]]
    warnings: list[str]
    result_hash: str

    def overall(self) -> str | None:
        return next((o.value for o in self.outputs if o.key == "conditions"), None)

    def lines(self) -> list[dict[str, Any]]:
        return [
            {
                "key": o.key,
                "label": o.label,
                "section": o.section,
                "formula_id": o.formula_id,
                "amount": o.amount,
                "value": o.value,
                "explanation": [s.as_dict() for s in o.steps],
                "rule_snapshots": [self.rules[k] for k in o.rule_keys if k in self.rules],
            }
            for o in self.outputs
        ]


def evaluate(
    db: Session,
    org_id: uuid.UUID,
    version_id: uuid.UUID,
    prefix: str,
    on: date,
    kind: str,
    lines: list[calc.InputLine],
) -> Evaluation:
    """Run one formula outside a workpaper (loss transfers, group tests)."""
    _published(db, org_id, version_id)
    rules = PackRules(db, org_id, version_id, on)
    try:
        outputs = calc.run(kind, calc.Inputs(lines=lines, period_end=on), rules, prefix)
    except calc.CalcError as exc:
        raise WorkpaperError(str(exc)) from exc
    snaps = {k: r.snapshot() for k, r in rules.used.items()}
    digest = hashlib.sha256(
        _canonical(
            {
                "calc_version": calc.CALC_VERSION,
                "kind": kind,
                "inputs": [[i.key, i.category, i.amount, i.value] for i in lines],
                "rules": snaps,
                "outputs": [[o.key, o.formula_id, o.amount, o.value] for o in outputs],
            }
        ).encode()
    ).hexdigest()
    warnings = sorted({w for r in rules.used.values() if (w := r.warning())})
    return Evaluation(outputs, snaps, warnings, digest)
