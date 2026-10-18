"""Finance datasets: upload, column mapping, canonical rows."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.uploads import scan_refusal
from app.config import get_settings
from app.datasets.readers import DatasetFileError
from app.datasets.schemas import SCHEMAS, MappingError
from app.deps import DB, Ctx, Writer, get_owned_or_404
from app.malware import MalwareFound, ScannerUnavailable
from app.models import Dataset, DatasetKind, DatasetVersion, Job, JobKind, LegalEntity
from app.schemas import (
    CanonicalFieldOut,
    DatasetDetailOut,
    DatasetKindOut,
    DatasetOut,
    DatasetRowsOut,
    DatasetVersionDetailOut,
    DatasetVersionOut,
    JobOut,
    MappingIn,
)
from app.services import datasets as svc
from app.services.jobs import enqueue

router = APIRouter(tags=["datasets"])
MAX_ROWS_PAGE = 200


def _out(ds: Dataset) -> DatasetOut:
    latest = ds.versions[-1] if ds.versions else None
    return DatasetOut(
        id=ds.id,
        entity_id=ds.entity_id,
        entity_name=ds.entity.name,
        kind=ds.kind,
        name=ds.name,
        period_start=ds.period_start,
        period_end=ds.period_end,
        is_demo=ds.is_demo,
        created_at=ds.created_at,
        latest_version=DatasetVersionOut.model_validate(latest) if latest else None,
    )


def _detail(ds: Dataset) -> DatasetDetailOut:
    return DatasetDetailOut(
        **_out(ds).model_dump(),
        versions=[DatasetVersionOut.model_validate(v) for v in ds.versions],
    )


def _latest_job(db: Session, v: DatasetVersion) -> Job | None:
    return db.scalar(
        select(Job)
        .where(
            Job.org_id == v.org_id,
            Job.target_id == v.id,
            Job.kind.in_([JobKind.DATASET_PARSE, JobKind.DATASET_BUILD]),
        )
        .order_by(desc(Job.created_at))
        .limit(1)
    )


def _version_detail(db: Session, v: DatasetVersion) -> DatasetVersionDetailOut:
    job = _latest_job(db, v)
    try:
        preview = svc.preview(v)
    except DatasetFileError:
        preview = []
    return DatasetVersionDetailOut(
        **DatasetVersionOut.model_validate(v).model_dump(),
        dataset_id=v.dataset_id,
        kind=v.dataset.kind,
        preview=preview,
        latest_job=JobOut.model_validate(job) if job else None,
    )


async def _read_limited(file: UploadFile) -> bytes:
    s = get_settings()
    data = await file.read(s.dataset_max_upload_bytes + 1)
    if len(data) > s.dataset_max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file is larger than the {s.dataset_max_upload_mb} MB limit.",
        )
    return data


def _duplicate(exc: svc.DuplicateDataset) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": f"This file was already imported into “{exc.name}”.",
            "duplicate_dataset_id": str(exc.dataset_id),
        },
    )


@router.get("/dataset-kinds", response_model=list[DatasetKindOut], summary="Canonical schemas")
def dataset_kinds(ctx: Ctx) -> list[DatasetKindOut]:
    return [
        DatasetKindOut(
            kind=k,
            fields=[
                CanonicalFieldOut(name=f.name, type=f.type, required=f.required) for f in s.fields
            ],
            require_any=[list(g) for g in s.require_any],
        )
        for k, s in SCHEMAS.items()
    ]


@router.get("/datasets", response_model=list[DatasetOut], summary="List datasets")
def list_datasets(
    ctx: Ctx, db: DB, entity_id: uuid.UUID | None = None, kind: DatasetKind | None = None
) -> list[DatasetOut]:
    stmt = select(Dataset).where(Dataset.org_id == ctx.org_id)
    if entity_id:
        stmt = stmt.where(Dataset.entity_id == entity_id)
    if kind:
        stmt = stmt.where(Dataset.kind == kind)
    rows = db.scalars(stmt.order_by(Dataset.created_at.desc())).unique().all()
    return [_out(d) for d in rows]


@router.post(
    "/datasets",
    status_code=201,
    response_model=DatasetDetailOut,
    summary="Import a finance dataset",
    description="Trial balance, general ledger, sales/purchase register (CSV or XLSX) or bank "
    "statement (CSV, XLSX, MT940, CAMT.053). The file is hashed and versioned; the column "
    "mapping is proposed from headers and must be confirmed. Analysts, reviewers, admins.",
)
async def create_dataset(
    ctx: Writer,
    db: DB,
    file: Annotated[UploadFile, File()],
    entity_id: Annotated[uuid.UUID, Form()],
    kind: Annotated[DatasetKind, Form()],
    name: Annotated[str, Form(min_length=1, max_length=200)],
    period_start: Annotated[date | None, Form()] = None,
    period_end: Annotated[date | None, Form()] = None,
    allow_duplicate: Annotated[bool, Form()] = False,
) -> DatasetDetailOut | JSONResponse:
    data = await _read_limited(file)
    entity = get_owned_or_404(db, LegalEntity, entity_id, ctx.org_id)
    try:
        ds = svc.create_dataset(
            db,
            org_id=ctx.org_id,
            entity=entity,
            kind=kind,
            name=name,
            period_start=period_start,
            period_end=period_end,
            actor=ctx.user,
        )
        _, job = svc.create_version(
            db,
            dataset=ds,
            filename=file.filename or "upload",
            declared_mime=file.content_type or "",
            data=data,
            actor=ctx.user,
            allow_duplicate=allow_duplicate,
        )
    except DatasetFileError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (MalwareFound, ScannerUnavailable) as exc:
        raise scan_refusal(db, ctx, exc, data, "dataset") from exc
    except svc.DuplicateDataset as exc:
        db.rollback()
        return _duplicate(exc)
    db.commit()
    enqueue(job)
    db.expire_all()
    db.refresh(ds)
    return _detail(ds)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetailOut, summary="Get a dataset")
def get_dataset(dataset_id: uuid.UUID, ctx: Ctx, db: DB) -> DatasetDetailOut:
    return _detail(get_owned_or_404(db, Dataset, dataset_id, ctx.org_id))


@router.post(
    "/datasets/{dataset_id}/versions",
    status_code=201,
    response_model=DatasetDetailOut,
    summary="Upload a new version of a dataset",
)
async def upload_version(
    dataset_id: uuid.UUID,
    ctx: Writer,
    db: DB,
    file: Annotated[UploadFile, File()],
    allow_duplicate: Annotated[bool, Form()] = False,
) -> DatasetDetailOut | JSONResponse:
    data = await _read_limited(file)
    ds = get_owned_or_404(db, Dataset, dataset_id, ctx.org_id)
    try:
        _, job = svc.create_version(
            db,
            dataset=ds,
            filename=file.filename or "upload",
            declared_mime=file.content_type or "",
            data=data,
            actor=ctx.user,
            allow_duplicate=allow_duplicate,
        )
    except DatasetFileError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (MalwareFound, ScannerUnavailable) as exc:
        raise scan_refusal(db, ctx, exc, data, "dataset") from exc
    except svc.DuplicateDataset as exc:
        db.rollback()
        return _duplicate(exc)
    db.commit()
    enqueue(job)
    db.expire_all()
    db.refresh(ds)
    return _detail(ds)


@router.get(
    "/dataset-versions/{version_id}",
    response_model=DatasetVersionDetailOut,
    summary="Get a dataset version with preview and mapping",
)
def get_version(version_id: uuid.UUID, ctx: Ctx, db: DB) -> DatasetVersionDetailOut:
    return _version_detail(db, get_owned_or_404(db, DatasetVersion, version_id, ctx.org_id))


@router.put(
    "/dataset-versions/{version_id}/mapping",
    response_model=DatasetVersionDetailOut,
    summary="Confirm the column mapping and build the canonical dataset",
    description="Every required field must be mapped. Invalid values fail the build with "
    "their row ids; nothing is rounded or guessed.",
)
def confirm_mapping(
    version_id: uuid.UUID, body: MappingIn, ctx: Writer, db: DB
) -> DatasetVersionDetailOut:
    v = get_owned_or_404(db, DatasetVersion, version_id, ctx.org_id)
    try:
        job = svc.confirm_mapping(
            db,
            v,
            body.mapping,
            date_format=body.date_format,
            decimal_separator=body.decimal_separator,
            actor=ctx.user,
        )
    except (DatasetFileError, MappingError) as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.commit()
    enqueue(job)
    db.expire_all()
    return _version_detail(db, get_owned_or_404(db, DatasetVersion, version_id, ctx.org_id))


def _jsonable(value: Any) -> Any:
    return value if value is None or isinstance(value, (str, int, bool)) else str(value)


@router.get(
    "/dataset-versions/{version_id}/rows",
    response_model=DatasetRowsOut,
    summary="Read canonical rows",
    description="Page through rows, or fetch specific rows by id (evidence links).",
)
def get_rows(
    version_id: uuid.UUID,
    ctx: Ctx,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=MAX_ROWS_PAGE),
    row_ids: str | None = Query(default=None, max_length=4000, description="Comma-separated."),
) -> DatasetRowsOut:
    get_owned_or_404(db, DatasetVersion, version_id, ctx.org_id)
    try:
        _, frame = svc.load_frame(db, version_id, ctx.org_id)
    except svc.DatasetNotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if row_ids:
        try:
            ids = [int(x) for x in row_ids.split(",") if x.strip()][:MAX_ROWS_PAGE]
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid row ids.") from exc
        page = frame.filter(frame["row_id"].is_in(ids))
    else:
        page = frame.slice(offset, limit)
    rows = [{k: _jsonable(v) for k, v in r.items()} for r in page.iter_rows(named=True)]
    return DatasetRowsOut(
        version_id=version_id, columns=frame.columns, rows=rows, total=frame.height
    )
