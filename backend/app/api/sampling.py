"""Reproducible audit sampling (Phase D5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.engagements import _guard, get_engagement
from app.deps import DB, Ctx, Writer, get_owned_or_404
from app.models import AuditSample
from app.schemas import (
    ProjectionOut,
    ReproduceOut,
    SampleConclusionIn,
    SampleIn,
    SampleItemIn,
    SampleItemOut,
    SampleOut,
    SampleSummaryOut,
)
from app.services import sampling as svc

router = APIRouter(tags=["audit sampling"])


def _summary(s: AuditSample) -> dict[str, object]:
    return {
        "id": s.id,
        "name": s.name,
        "method": s.method,
        "dataset_version_id": s.dataset_version_id,
        "amount_column": s.amount_column,
        "seed": s.seed,
        "params": s.params,
        "algorithm_version": s.algorithm_version,
        "population_count": s.population_count,
        "population_value": s.population_value,
        "population_sha256": s.population_sha256,
        "risk_id": s.risk_id,
        "conclusion": s.conclusion,
        "item_count": len(s.items),
        "created_at": s.created_at,
    }


def sample_out(db: DB, ctx: Ctx, s: AuditSample) -> SampleOut:
    e = get_engagement(db, ctx, s.engagement_id)
    return SampleOut(
        **_summary(s),
        items=[SampleItemOut.model_validate(i) for i in s.items],
        projection=ProjectionOut.model_validate(_guard(lambda: svc.projection(db, e, s))),
    )


@router.get(
    "/engagements/{engagement_id}/samples",
    response_model=list[SampleSummaryOut],
    summary="List samples",
)
def list_samples(engagement_id: uuid.UUID, db: DB, ctx: Ctx) -> list[SampleSummaryOut]:
    e = get_engagement(db, ctx, engagement_id)
    return [SampleSummaryOut(**_summary(s)) for s in svc.samples(db, e)]


@router.post(
    "/engagements/{engagement_id}/samples",
    response_model=SampleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Select a sample",
    description=(
        "Monetary unit (systematic, random start), simple random, or stratified selection "
        "over an amount column of a dataset version. The seed, parameters, algorithm "
        "version and a SHA-256 of the population are recorded so the sample reproduces."
    ),
)
def create_sample(engagement_id: uuid.UUID, body: SampleIn, db: DB, ctx: Writer) -> SampleOut:
    e = get_engagement(db, ctx, engagement_id)
    s = _guard(lambda: svc.create(db, e, body, ctx.user))
    db.commit()
    return sample_out(db, ctx, s)


@router.get("/samples/{sample_id}", response_model=SampleOut, summary="Get a sample")
def read_sample(sample_id: uuid.UUID, db: DB, ctx: Ctx) -> SampleOut:
    return sample_out(db, ctx, get_owned_or_404(db, AuditSample, sample_id, ctx.org.id))


@router.put(
    "/samples/{sample_id}/items/{row_id}",
    response_model=SampleOut,
    summary="Record a sample item's audited value",
    description="A difference from the book value is an exception and needs a note.",
)
def record_item(
    sample_id: uuid.UUID, row_id: int, body: SampleItemIn, db: DB, ctx: Writer
) -> SampleOut:
    s = get_owned_or_404(db, AuditSample, sample_id, ctx.org.id)
    e = get_engagement(db, ctx, s.engagement_id)
    _guard(lambda: svc.record_item(db, e, s, row_id, body, ctx.user))
    db.commit()
    return sample_out(db, ctx, s)


@router.post(
    "/samples/{sample_id}/conclusion",
    response_model=SampleOut,
    summary="Conclude a sample",
    description="Every item must be tested first.",
)
def conclude(sample_id: uuid.UUID, body: SampleConclusionIn, db: DB, ctx: Writer) -> SampleOut:
    s = get_owned_or_404(db, AuditSample, sample_id, ctx.org.id)
    e = get_engagement(db, ctx, s.engagement_id)
    _guard(lambda: svc.conclude(db, e, s, body.conclusion, ctx.user))
    db.commit()
    return sample_out(db, ctx, s)


@router.get(
    "/samples/{sample_id}/reproduce",
    response_model=ReproduceOut,
    summary="Re-run a sample's selection",
    description="Re-selects from the recorded seed and parameters and compares the result.",
)
def reproduce(sample_id: uuid.UUID, db: DB, ctx: Ctx) -> ReproduceOut:
    s = get_owned_or_404(db, AuditSample, sample_id, ctx.org.id)
    e = get_engagement(db, ctx, s.engagement_id)
    return ReproduceOut.model_validate(_guard(lambda: svc.reproduce(db, e, s)))
