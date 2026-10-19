"""Audit samples over dataset versions (D5): selection, item testing, projection.

The selection is computed once and stored with its seed, parameters, algorithm
version and population hash; ``reproduce`` re-runs it from those records and
compares. Book values are the absolute amounts of the chosen column.
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc import sampling as smp
from app.deps import now
from app.engine.data_checks import field_type
from app.models import (
    AuditEngagement,
    AuditRisk,
    AuditSample,
    AuditSampleItem,
    SampleItemResult,
    SamplingMethod,
    User,
)
from app.schemas import SampleIn, SampleItemIn
from app.services import audit
from app.services.datasets import DatasetNotReady, load_frame
from app.services.engagements import EngagementError, require_open
from app.services.lead_schedules import materiality


def _population(
    db: Session, e: AuditEngagement, version_id: Any, column: str
) -> tuple[Any, list[tuple[int, Decimal]]]:
    try:
        v, frame = load_frame(db, version_id, e.org_id)
    except DatasetNotReady as exc:
        raise LookupError("dataset version") from exc
    if v.dataset.entity_id != e.entity_id:
        raise EngagementError("The dataset belongs to another entity.")
    if field_type(v.dataset.kind, column) != "amount" or column not in frame.columns:
        raise EngagementError(f"'{column}' is not an amount column of this dataset.")
    rows = [
        (int(rid), abs(Decimal(str(val))))
        for rid, val in zip(frame["row_id"].to_list(), frame[column].to_list(), strict=True)
        if val is not None and Decimal(str(val)) != 0
    ]
    if not rows:
        raise EngagementError("The population has no non-zero amounts.")
    return v, sorted(rows)


def _strata(params: dict[str, Any]) -> list[smp.Stratum]:
    return [
        smp.Stratum(Decimal(s["upper"]) if s["upper"] is not None else None, s["size"])
        for s in params["strata"]
    ]


def _select(
    method: SamplingMethod, rows: list[tuple[int, Decimal]], params: dict[str, Any], seed: str
) -> dict[int, tuple[int | None, int]]:
    """Row id → (stratum, hits). Fills params with derived values (interval, start)."""
    stream = smp.Stream(seed)
    if method is SamplingMethod.RANDOM:
        return {
            r: (None, 1) for r in smp.random_select([r for r, _ in rows], params["size"], stream)
        }
    if method is SamplingMethod.MONETARY_UNIT:
        total = sum((v for _, v in rows), Decimal(0))
        interval = smp.mus_interval(total, params["size"])
        start = smp.mus_start(interval, stream)
        params["interval"], params["start"] = str(interval), str(start)
        sel = smp.mus_select(rows, interval, start)
        return {r: (None, h) for r, h in sel.hits.items()}
    return {r: (s, 1) for r, s in smp.stratified_select(rows, _strata(params), stream).items()}


def create(db: Session, e: AuditEngagement, body: SampleIn, actor: User) -> AuditSample:
    require_open(e)
    if (
        body.risk_id is not None
        and db.scalar(
            select(AuditRisk.id).where(
                AuditRisk.id == body.risk_id, AuditRisk.engagement_id == e.id
            )
        )
        is None
    ):
        raise LookupError("risk")
    v, rows = _population(db, e, body.dataset_version_id, body.amount_column)
    params: dict[str, Any] = {
        "size": body.size,
        "strata": [
            {"upper": str(s.upper) if s.upper is not None else None, "size": s.size}
            for s in body.strata
        ],
    }
    seed = body.seed or secrets.token_hex(16)
    try:
        chosen = _select(body.method, rows, params, seed)
    except smp.SamplingError as exc:
        raise EngagementError(str(exc)) from exc
    values = dict(rows)
    sample = AuditSample(
        org_id=e.org_id,
        engagement_id=e.id,
        name=body.name.strip(),
        method=body.method,
        dataset_version_id=v.id,
        amount_column=body.amount_column,
        seed=seed,
        params=params,
        algorithm_version=smp.SAMPLING_VERSION,
        population_count=len(rows),
        population_value=sum(values.values(), Decimal(0)),
        population_sha256=smp.population_hash(rows),
        risk_id=body.risk_id,
        created_by_id=actor.id,
    )
    sample.items = [
        AuditSampleItem(
            org_id=e.org_id, row_id=rid, stratum=stratum, hits=hits, book_value=values[rid]
        )
        for rid, (stratum, hits) in sorted(chosen.items())
    ]
    db.add(sample)
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="sample.created",
        object_type="audit_sample",
        object_id=sample.id,
        meta={
            "engagement_id": str(e.id),
            "method": body.method.value,
            "dataset_version_id": str(v.id),
            "items": len(sample.items),
            "population_sha256": sample.population_sha256,
        },
    )
    return sample


def samples(db: Session, e: AuditEngagement) -> list[AuditSample]:
    return list(
        db.scalars(
            select(AuditSample)
            .where(AuditSample.org_id == e.org_id, AuditSample.engagement_id == e.id)
            .order_by(AuditSample.created_at)
        )
    )


def record_item(
    db: Session, e: AuditEngagement, s: AuditSample, row_id: int, body: SampleItemIn, actor: User
) -> AuditSampleItem:
    require_open(e)
    item = next((i for i in s.items if i.row_id == row_id), None)
    if item is None:
        raise LookupError("sample item")
    item.audited_value = body.audited_value
    item.result = (
        SampleItemResult.NO_EXCEPTION
        if body.audited_value == item.book_value
        else SampleItemResult.EXCEPTION
    )
    if item.result is SampleItemResult.EXCEPTION and not body.note.strip():
        raise EngagementError("Describe the exception in the note.")
    item.note = body.note
    item.tested_by_id, item.tested_at = actor.id, now()
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="sample.item_tested",
        object_type="audit_sample",
        object_id=s.id,
        meta={"row_id": row_id, "result": item.result.value},
    )
    return item


def conclude(db: Session, e: AuditEngagement, s: AuditSample, text: str, actor: User) -> None:
    require_open(e)
    if any(i.result is SampleItemResult.NOT_TESTED for i in s.items):
        raise EngagementError("Test every item before concluding.")
    s.conclusion = text.strip()
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="sample.concluded",
        object_type="audit_sample",
        object_id=s.id,
        meta={},
    )


def projection(db: Session, e: AuditEngagement, s: AuditSample) -> dict[str, Any]:
    items = [smp.TestedItem(i.row_id, i.book_value, i.audited_value, i.stratum) for i in s.items]
    if s.method is SamplingMethod.MONETARY_UNIT:
        p = smp.project_mus(items, Decimal(s.params["interval"]))
    elif s.method is SamplingMethod.RANDOM:
        p = smp.project_ratio(items, s.population_value)
    else:
        strata = _strata(s.params)
        # Stratum values are recomputed from the recorded population.
        _, rows = _population(db, e, s.dataset_version_id, s.amount_column)
        groups = smp.strata_of(rows, strata)
        values = dict(rows)
        p = smp.project_stratified(
            items,
            [sum((values[r] for r in g), Decimal(0)) for g in groups],
            [st.size is None for st in strata],
        )
    pm = (materiality(db, e) or {}).get("performance")
    return {
        "projected": p.projected,
        "known": p.known,
        "untested": p.untested,
        "steps": p.steps,
        "performance_materiality": pm,
        "exceeds_performance": (abs(p.projected) >= pm) if pm is not None else None,
    }


def reproduce(db: Session, e: AuditEngagement, s: AuditSample) -> dict[str, Any]:
    _, rows = _population(db, e, s.dataset_version_id, s.amount_column)
    unchanged = smp.population_hash(rows) == s.population_sha256
    params = {"size": s.params.get("size"), "strata": s.params.get("strata", [])}
    again = _select(s.method, rows, params, s.seed)
    stored = {i.row_id for i in s.items}
    diff = sorted(stored ^ set(again))
    return {
        "reproducible": unchanged and not diff,
        "population_unchanged": unchanged,
        "differences": diff,
    }
