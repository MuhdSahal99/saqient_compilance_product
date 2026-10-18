"""Direct-tax workpapers (Phase C): inputs with evidence, explainable computed lines."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, status
from sqlalchemy import select

from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.models import LegalEntity, TaxWorkpaper, WorkpaperKind, WorkpaperSnapshot
from app.schemas import (
    KEY_PATTERN,
    ReasonIn,
    TrialBalanceImportIn,
    WorkpaperIn,
    WorkpaperInputIn,
    WorkpaperLineOut,
    WorkpaperOut,
    WorkpaperSnapshotOut,
    WorkpaperSummaryOut,
)
from app.services import workpapers as svc

router = APIRouter(tags=["tax workpapers"])

LineKey = Annotated[str, Path(pattern=KEY_PATTERN)]


def _summary(wp: TaxWorkpaper) -> dict[str, Any]:
    return {
        "id": wp.id,
        "entity_id": wp.entity_id,
        "entity_name": wp.entity.name,
        "kind": wp.kind,
        "title": wp.title,
        "period_start": wp.period_start,
        "period_end": wp.period_end,
        "currency": wp.currency,
        "status": wp.status,
        "computed_at": wp.computed_at,
        "is_demo": wp.is_demo,
        "created_at": wp.created_at,
    }


def workpaper_out(db: DB, wp: TaxWorkpaper) -> WorkpaperOut:
    snaps = svc.snapshots(db, wp)
    return WorkpaperOut(
        **_summary(wp),
        rule_pack_version_id=wp.rule_pack_version_id,
        rules_prefix=wp.rules_prefix,
        calc_version=wp.calc_version,
        result_hash=wp.result_hash,
        warnings=wp.warnings,
        lines=[
            WorkpaperLineOut.model_validate(ln, from_attributes=True)
            for ln in sorted(wp.lines, key=lambda x: x.ordinal)
        ],
        snapshots=[
            WorkpaperSnapshotOut(
                version=s.version,
                signed_off_by_name=s.content.get("signed_off_by"),
                signed_off_at=s.signed_off_at,
                result_hash=s.content.get("result_hash"),
            )
            for s in snaps
        ],
    )


def _bad(exc: svc.WorkpaperError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(exc, svc.WorkpaperConflict)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, str(exc))


def _get(db: DB, ctx: Ctx, workpaper_id: uuid.UUID) -> TaxWorkpaper:
    return get_owned_or_404(db, TaxWorkpaper, workpaper_id, ctx.org.id)


@router.get(
    "/workpapers",
    response_model=list[WorkpaperSummaryOut],
    summary="List tax workpapers",
    description="Workpapers of this organisation, newest first.",
)
def list_workpapers(
    db: DB,
    ctx: Ctx,
    entity_id: uuid.UUID | None = None,
    kind: WorkpaperKind | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[WorkpaperSummaryOut]:
    stmt = select(TaxWorkpaper).where(TaxWorkpaper.org_id == ctx.org.id)
    if entity_id:
        stmt = stmt.where(TaxWorkpaper.entity_id == entity_id)
    if kind:
        stmt = stmt.where(TaxWorkpaper.kind == kind)
    rows = db.scalars(stmt.order_by(TaxWorkpaper.created_at.desc()).limit(limit)).unique()
    return [WorkpaperSummaryOut(**_summary(wp)) for wp in rows]


@router.post(
    "/workpapers",
    response_model=WorkpaperOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tax workpaper",
    description=(
        "Starts a draft workpaper for one entity and period, reading rules from one "
        "published rule pack version under the given prefix."
    ),
)
def create_workpaper(body: WorkpaperIn, db: DB, ctx: Writer) -> WorkpaperOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    try:
        wp = svc.create(db, entity, body, ctx.user)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except svc.WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.get(
    "/workpapers/{workpaper_id}",
    response_model=WorkpaperOut,
    summary="Get a tax workpaper",
    description="Input and computed lines with steps, rule snapshots and evidence.",
)
def get_workpaper(workpaper_id: uuid.UUID, db: DB, ctx: Ctx) -> WorkpaperOut:
    return workpaper_out(db, _get(db, ctx, workpaper_id))


@router.put(
    "/workpapers/{workpaper_id}/inputs/{line_key}",
    response_model=WorkpaperOut,
    summary="Save an input line",
    description=(
        "Creates or replaces one preparer input (an amount or a flag) with its evidence. "
        "Clears computed lines until the workpaper is computed again."
    ),
)
def put_input(
    workpaper_id: uuid.UUID, line_key: LineKey, body: WorkpaperInputIn, db: DB, ctx: Writer
) -> WorkpaperOut:
    wp = _get(db, ctx, workpaper_id)
    try:
        svc.put_input(db, wp, line_key, body, ctx.user)
    except svc.WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.delete(
    "/workpapers/{workpaper_id}/inputs/{line_key}",
    response_model=WorkpaperOut,
    summary="Delete an input line",
)
def delete_input(workpaper_id: uuid.UUID, line_key: LineKey, db: DB, ctx: Writer) -> WorkpaperOut:
    wp = _get(db, ctx, workpaper_id)
    try:
        svc.delete_input(db, wp, line_key, ctx.user)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.") from exc
    except svc.WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.post(
    "/workpapers/{workpaper_id}/import-trial-balance",
    response_model=WorkpaperOut,
    summary="Import inputs from a trial balance",
    description=(
        "Sums the balances of the mapped accounts of a trial balance dataset version into "
        "input lines; each line cites the dataset version and rows used."
    ),
)
def import_trial_balance(
    workpaper_id: uuid.UUID, body: TrialBalanceImportIn, db: DB, ctx: Writer
) -> WorkpaperOut:
    wp = _get(db, ctx, workpaper_id)
    try:
        svc.import_trial_balance(db, wp, body, ctx.user)
    except svc.WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.post(
    "/workpapers/{workpaper_id}/compute",
    response_model=WorkpaperOut,
    summary="Compute a workpaper",
    description=(
        "Runs the workpaper's formula over its inputs and the pack rules effective on the "
        "period end. Results are proposals for a qualified reviewer."
    ),
)
def compute(workpaper_id: uuid.UUID, db: DB, ctx: Writer) -> WorkpaperOut:
    wp = _get(db, ctx, workpaper_id)
    try:
        svc.compute(db, wp, ctx.user)
    except svc.WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.post(
    "/workpapers/{workpaper_id}/sign-off",
    response_model=WorkpaperOut,
    summary="Sign off a workpaper",
    description="Freezes the computed workpaper as an immutable snapshot version.",
)
def sign_off(workpaper_id: uuid.UUID, db: DB, ctx: Decider) -> WorkpaperOut:
    wp = _get(db, ctx, workpaper_id)
    try:
        svc.sign_off(db, wp, ctx.user)
    except svc.WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.post(
    "/workpapers/{workpaper_id}/reopen",
    response_model=WorkpaperOut,
    summary="Reopen a signed-off workpaper",
    description="Needs a reason; the next sign-off creates the next snapshot version.",
)
def reopen(workpaper_id: uuid.UUID, body: ReasonIn, db: DB, ctx: Decider) -> WorkpaperOut:
    wp = _get(db, ctx, workpaper_id)
    try:
        svc.reopen(db, wp, body.reason, ctx.user)
    except svc.WorkpaperError as exc:
        raise _bad(exc) from exc
    db.commit()
    return workpaper_out(db, wp)


@router.get(
    "/workpapers/{workpaper_id}/snapshots/{version}",
    summary="Get a signed-off snapshot",
    description="The frozen content of one sign-off version.",
)
def get_snapshot(workpaper_id: uuid.UUID, version: int, db: DB, ctx: Ctx) -> dict[str, Any]:
    wp = _get(db, ctx, workpaper_id)
    snap = db.scalar(
        select(WorkpaperSnapshot).where(
            WorkpaperSnapshot.workpaper_id == wp.id,
            WorkpaperSnapshot.org_id == ctx.org.id,
            WorkpaperSnapshot.version == version,
        )
    )
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return snap.content
