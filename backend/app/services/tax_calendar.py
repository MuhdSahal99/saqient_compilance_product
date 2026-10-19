"""Tax calendar: obligations per entity generated from rule pack data.

Frequencies, due-date offsets and e-invoicing milestones all come from the pack
(``<prefix>.obligations`` and optionally ``<prefix>.go_live_waves``); nothing here
encodes a jurisdiction's deadlines. Each obligation gets a task (ADR 0009) with an
owner and due date, which the daily reminder digest picks up.

Regenerating is idempotent: an obligation is keyed by (entity, obligation id,
period start); a done or cancelled one is never changed, an open one has its due
date updated if the pack now says otherwise.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.engine.einvoice_checks import go_live_for
from app.engine.tax_checks import EntityInfo
from app.models import (
    ChecklistState,
    LegalEntity,
    Membership,
    PeriodFrequency,
    Rule,
    RulePackVersion,
    Task,
    TaskSource,
    TaskStatus,
    TaxObligation,
    TaxPeriod,
    TaxType,
    User,
)
from app.services import audit
from app.services import rule_packs as packs
from app.services.rule_schemas import Obligation, RuleShapeError, typed

MAX_SPAN_DAYS = 3 * 366
CLOSED = (TaskStatus.DONE, TaskStatus.CANCELLED)


class CalendarError(ValueError):
    pass


# ---------------------------------------------------------------- date arithmetic


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def periods(
    frequency: str, basis: str, fy_end_month: int, start: date, end: date
) -> list[tuple[date, date]]:
    """Periods of a frequency whose end falls within [start, end].

    Calendar basis: months, quarters ending Mar/Jun/Sep/Dec, years ending Dec.
    Fiscal basis: quarters and years end on the entity's fiscal year-end month.
    """
    step = {"monthly": 1, "quarterly": 3, "annual": 12}[frequency]
    anchor = 12 if basis == "calendar" or frequency == "monthly" else fy_end_month
    out: list[tuple[date, date]] = []
    y, m = start.year - 1, anchor
    while (pe := month_end(y, m)) <= end:
        if pe >= start:
            out.append((add_months(date(y, m, 1), -(step - 1)), pe))
        m += step
        while m > 12:
            m, y = m - 12, y + 1
    return out


def due_date(ob: Obligation, period_end: date) -> tuple[date, str]:
    """Due date and the formula that produced it."""
    base = add_months(period_end, ob.months_after)
    if ob.day_of_month is not None:
        day = min(ob.day_of_month, calendar.monthrange(base.year, base.month)[1])
        return (
            base.replace(day=day),
            f"period end + {ob.months_after} month(s), day {ob.day_of_month} of that month",
        )
    days = ob.days_after or 0
    return (
        base + timedelta(days=days),
        f"period end + {ob.months_after} month(s) + {days} day(s)",
    )


# ---------------------------------------------------------------- generation


@dataclass
class GenerateResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    periods_created: int = 0
    warnings: list[str] = field(default_factory=list)
    obligations: list[TaxObligation] = field(default_factory=list)


@dataclass(frozen=True)
class _Planned:
    key: str
    label: str
    tax_type: str
    frequency: str | None
    period_start: date
    period_end: date
    due: date
    formula: str
    rule: packs.ResolvedRule


def _plan(
    db: Session,
    entity: LegalEntity,
    version: RulePackVersion,
    prefix: str,
    start: date,
    end: date,
    include_einvoicing: bool,
    waves_rule: str | None = None,
) -> list[_Planned]:
    org = entity.org_id
    key = f"{prefix}.obligations"
    planned: list[_Planned] = []
    # Every version of the rule overlapping the range; each covers its own dates.
    seen_rules: dict[uuid.UUID, packs.ResolvedRule] = {}
    for rule_from in db.scalars(
        select(Rule.effective_from).where(
            Rule.org_id == org,
            Rule.rule_pack_version_id == version.id,
            Rule.rule_key == key,
            Rule.effective_from <= end,
            or_(Rule.effective_to.is_(None), Rule.effective_to >= start),
        )
    ):
        seen = packs.resolve(db, org, version.id, key, max(start, rule_from))
        seen_rules.setdefault(seen.rule_id, seen)
    if not seen_rules:
        raise CalendarError(f"The rule pack has no '{key}' rule for {start} – {end}.")
    for rule in seen_rules.values():
        try:
            obligations: list[Obligation] = typed(key, rule.value)
        except RuleShapeError as exc:
            raise CalendarError(f"Rule '{key}': {exc}") from exc
        lo = max(start, rule.effective_from)
        hi = min(end, rule.effective_to) if rule.effective_to else end
        for ob in obligations:
            for ps, pe in periods(
                ob.frequency, ob.period_basis, entity.fiscal_year_end_month, lo, hi
            ):
                due, formula = due_date(ob, pe)
                planned.append(
                    _Planned(ob.id, ob.label, ob.tax_type, ob.frequency, ps, pe, due, formula, rule)
                )
    if include_einvoicing:
        wkey = waves_rule or f"{prefix}.go_live_waves"
        try:
            wrule = packs.resolve(db, org, version.id, wkey, end)
        except packs.RuleNotFound:
            wrule = None
        if wrule is not None:
            info = EntityInfo(
                id=str(entity.id),
                name=entity.name,
                country=entity.country,
                size_basis_amount=entity.size_basis_amount,
                size_basis_currency=entity.size_basis_currency,
                size_basis_year=entity.size_basis_year,
                go_live_override=entity.einvoice_go_live_override,
                go_live_note=entity.einvoice_go_live_note,
            )
            try:
                gl = go_live_for(info, typed(wkey, wrule.value))
            except ValueError as exc:
                raise CalendarError(str(exc)) from exc
            items = [("go_live", "E-invoicing go-live", gl.go_live)] + [
                (mid, label, d) for mid, label, d in gl.milestones
            ]
            for mid, label, d in items:
                if start <= d <= end:
                    planned.append(
                        _Planned(
                            f"einvoicing:{mid}",
                            label,
                            "einvoicing",
                            None,
                            d,
                            d,
                            d,
                            f"{gl.source}: {gl.wave or 'notified date'}",
                            wrule,
                        )
                    )
    return planned


def _ensure_period(
    db: Session, entity: LegalEntity, p: _Planned, result: GenerateResult
) -> TaxPeriod | None:
    if p.frequency is None or p.tax_type not in {t.value for t in TaxType}:
        return None
    tt = TaxType(p.tax_type)
    existing = db.scalar(
        select(TaxPeriod).where(
            TaxPeriod.org_id == entity.org_id,
            TaxPeriod.entity_id == entity.id,
            TaxPeriod.tax_type == tt,
            TaxPeriod.period_start <= p.period_end,
            TaxPeriod.period_end >= p.period_start,
        )
    )
    if existing is not None:
        if (existing.period_start, existing.period_end) == (p.period_start, p.period_end):
            return existing
        result.warnings.append(
            f"{p.label}: an existing {tt.value} period {existing.period_start} – "
            f"{existing.period_end} overlaps {p.period_start} – {p.period_end}; not linked."
        )
        return None
    tp = TaxPeriod(
        org_id=entity.org_id,
        entity_id=entity.id,
        tax_type=tt,
        frequency=PeriodFrequency(p.frequency),
        period_start=p.period_start,
        period_end=p.period_end,
    )
    db.add(tp)
    db.flush()
    result.periods_created += 1
    return tp


def generate(
    db: Session,
    *,
    entity: LegalEntity,
    version: RulePackVersion,
    prefix: str,
    start: date,
    end: date,
    actor: User,
    owner_id: uuid.UUID | None = None,
    include_einvoicing: bool = True,
    waves_rule: str | None = None,
) -> GenerateResult:
    if version.org_id != entity.org_id:
        raise CalendarError("Rule pack version not found.")
    if version.state != ChecklistState.PUBLISHED:
        raise CalendarError("Use a published rule pack version.")
    if end < start or (end - start).days > MAX_SPAN_DAYS:
        raise CalendarError("Choose a range of up to three years, with the end after the start.")
    if owner_id is not None and not db.scalar(
        select(Membership.id).where(
            Membership.org_id == entity.org_id, Membership.user_id == owner_id
        )
    ):
        raise CalendarError("The owner must be a member of this organisation.")
    result = GenerateResult()
    for p in _plan(db, entity, version, prefix, start, end, include_einvoicing, waves_rule):
        snapshot = p.rule.snapshot()
        if not p.rule.verified:
            w = p.rule.warning()
            if w and w not in result.warnings:
                result.warnings.append(w)
        ob = db.scalar(
            select(TaxObligation).where(
                and_(
                    TaxObligation.org_id == entity.org_id,
                    TaxObligation.entity_id == entity.id,
                    TaxObligation.obligation_key == p.key,
                    TaxObligation.period_start == p.period_start,
                )
            )
        )
        if ob is not None:
            closed = ob.task is not None and ob.task.status in CLOSED
            if closed or (ob.due_date == p.due and ob.rule_snapshot == snapshot):
                result.unchanged += 1
                result.obligations.append(ob)
                continue
            old = ob.due_date
            ob.due_date, ob.formula, ob.label = p.due, p.formula, p.label
            ob.rule_pack_version_id, ob.rule_snapshot = version.id, snapshot
            ob.rule_verified = p.rule.verified
            if ob.task is not None:
                ob.task.due_date = p.due
            audit.record(
                db,
                org_id=entity.org_id,
                actor_id=actor.id,
                action="tax_obligation.updated",
                object_type="tax_obligation",
                object_id=ob.id,
                meta={"due_date": [old.isoformat(), p.due.isoformat()]},
            )
            result.updated += 1
            result.obligations.append(ob)
            continue
        tp = _ensure_period(db, entity, p, result)
        ob = TaxObligation(
            org_id=entity.org_id,
            entity_id=entity.id,
            tax_period_id=tp.id if tp else None,
            obligation_key=p.key,
            label=p.label,
            tax_type=p.tax_type,
            period_start=p.period_start,
            period_end=p.period_end,
            due_date=p.due,
            rule_pack_version_id=version.id,
            rule_key=p.rule.rule_key,
            rule_snapshot=snapshot,
            formula=p.formula,
            rule_verified=p.rule.verified,
        )
        db.add(ob)
        db.flush()
        span = (
            p.period_start.isoformat()
            if p.period_start == p.period_end
            else f"{p.period_start.isoformat()} – {p.period_end.isoformat()}"
        )
        task = Task(
            org_id=entity.org_id,
            source_kind=TaskSource.TAX_OBLIGATION,
            source_id=ob.id,
            entity_id=entity.id,
            title=f"{entity.name}: {p.label} ({span})"[:300],
            owner_id=owner_id,
            due_date=p.due,
            created_by_id=actor.id,
        )
        db.add(task)
        db.flush()
        ob.task_id = task.id
        ob.task = task
        result.created += 1
        result.obligations.append(ob)
    audit.record(
        db,
        org_id=entity.org_id,
        actor_id=actor.id,
        action="tax_calendar.generated",
        object_type="legal_entity",
        object_id=entity.id,
        meta={
            "rule_pack_version_id": str(version.id),
            "prefix": prefix,
            "range": [start.isoformat(), end.isoformat()],
            "created": result.created,
            "updated": result.updated,
            "unchanged": result.unchanged,
        },
    )
    return result


# ---------------------------------------------------------------- tasks


def update_task(
    db: Session,
    task: Task,
    *,
    actor: User,
    status: TaskStatus | None = None,
    owner_id: uuid.UUID | None = None,
    clear_owner: bool = False,
    due_date: date | None = None,
    note: str | None = None,
) -> Task:
    changes: dict[str, Any] = {}
    if owner_id is not None:
        if not db.scalar(
            select(Membership.id).where(
                Membership.org_id == task.org_id, Membership.user_id == owner_id
            )
        ):
            raise CalendarError("The owner must be a member of this organisation.")
        changes["owner_id"] = str(owner_id)
        task.owner_id = owner_id
    elif clear_owner:
        changes["owner_id"] = None
        task.owner_id = None
    if due_date is not None and task.source_kind is not TaskSource.TAX_OBLIGATION:
        changes["due_date"] = due_date.isoformat()
        task.due_date = due_date
    elif due_date is not None:
        raise CalendarError("An obligation's due date comes from the rule pack.")
    if status is not None and status != task.status:
        if status in CLOSED and not (note or "").strip():
            raise CalendarError("Add a note (e.g. the filing reference) to close the task.")
        changes["status"] = [task.status.value, status.value]
        task.status = status
        if status in CLOSED:
            task.completed_by_id, task.completed_at = actor.id, datetime.now(UTC)
            task.completion_note = (note or "").strip()
        else:
            task.completed_by_id, task.completed_at, task.completion_note = None, None, ""
    audit.record(
        db,
        org_id=task.org_id,
        actor_id=actor.id,
        action="task.updated",
        object_type="task",
        object_id=task.id,
        meta=changes,
    )
    return task
