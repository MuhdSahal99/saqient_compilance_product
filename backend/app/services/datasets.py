"""Finance dataset import: hashed raw file -> validated mapping -> canonical Parquet."""

from __future__ import annotations

import hashlib
import logging
import uuid
import warnings
from datetime import UTC, date, datetime

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.datasets.build import BuildOptions, build_canonical, from_parquet, to_parquet
from app.datasets.readers import DatasetFileError, RawTable, detect_format, read_table
from app.datasets.schemas import suggest_mapping, validate_mapping
from app.models import (
    Dataset,
    DatasetKind,
    DatasetStatus,
    DatasetVersion,
    Job,
    JobKind,
    LegalEntity,
    User,
)
from app.services import audit
from app.services.jobs import Checkpoint, PermanentJobError, handler, on_unsuccessful
from app.storage import get_storage, new_storage_key

logger = logging.getLogger("saqient.datasets")
PREVIEW_ROWS = 5

# calamine returns Arrow data; Polars warns about a future API change we do not rely on.
warnings.filterwarnings("ignore", message="from_arrow", category=FutureWarning)


class DuplicateDataset(Exception):
    def __init__(self, dataset_id: uuid.UUID, name: str) -> None:
        self.dataset_id = dataset_id
        self.name = name


def _safe_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable())[:255]
    return base or "upload"


def find_duplicate(db: Session, org_id: uuid.UUID, sha256: str) -> Dataset | None:
    return db.scalar(
        select(Dataset)
        .join(DatasetVersion, DatasetVersion.dataset_id == Dataset.id)
        .where(Dataset.org_id == org_id, DatasetVersion.raw_sha256 == sha256)
        .limit(1)
    )


def create_dataset(
    db: Session,
    *,
    org_id: uuid.UUID,
    entity: LegalEntity,
    kind: DatasetKind,
    name: str,
    period_start: date | None,
    period_end: date | None,
    actor: User,
) -> Dataset:
    if period_start and period_end and period_end < period_start:
        raise DatasetFileError("The period ends before it starts.")
    ds = Dataset(
        org_id=org_id,
        entity_id=entity.id,
        kind=kind,
        name=name.strip(),
        period_start=period_start,
        period_end=period_end,
        created_by_id=actor.id,
    )
    db.add(ds)
    db.flush()
    audit.record(
        db,
        org_id=org_id,
        actor_id=actor.id,
        action="dataset.created",
        object_type="dataset",
        object_id=ds.id,
        meta={"kind": kind.value, "entity_id": str(entity.id)},
    )
    return ds


def create_version(
    db: Session,
    *,
    dataset: Dataset,
    filename: str,
    declared_mime: str,
    data: bytes,
    actor: User,
    allow_duplicate: bool,
) -> tuple[DatasetVersion, Job]:
    settings = get_settings()
    if len(data) > settings.dataset_max_upload_bytes:
        raise DatasetFileError(
            f"The file is larger than the {settings.dataset_max_upload_mb} MB limit."
        )
    fmt = detect_format(filename, declared_mime, data, dataset.kind.value)
    sha256 = hashlib.sha256(data).hexdigest()
    if not allow_duplicate:
        dup = find_duplicate(db, dataset.org_id, sha256)
        if dup is not None:
            raise DuplicateDataset(dup.id, dup.name)
    key = new_storage_key(dataset.org_id)
    get_storage().put(key, data)
    next_no = (
        db.scalar(
            select(func.max(DatasetVersion.version_number)).where(
                DatasetVersion.dataset_id == dataset.id
            )
        )
        or 0
    ) + 1
    version = DatasetVersion(
        org_id=dataset.org_id,
        dataset_id=dataset.id,
        version_number=next_no,
        original_filename=_safe_filename(filename),
        file_format=fmt,
        size_bytes=len(data),
        raw_sha256=sha256,
        raw_storage_key=key,
        uploaded_by_id=actor.id,
    )
    db.add(version)
    db.flush()
    job = Job(
        org_id=dataset.org_id,
        kind=JobKind.DATASET_PARSE,
        target_id=version.id,
        max_attempts=settings.job_max_attempts,
    )
    db.add(job)
    audit.record(
        db,
        org_id=dataset.org_id,
        actor_id=actor.id,
        action="dataset.version_uploaded",
        object_type="dataset",
        object_id=dataset.id,
        meta={"version": next_no, "format": fmt, "size_bytes": len(data), "sha256": sha256},
    )
    return version, job


def _load_version(db: Session, job: Job) -> DatasetVersion:
    v = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == job.target_id, DatasetVersion.org_id == job.org_id
        )
    )
    if v is None:
        raise PermanentJobError("The dataset version no longer exists.")
    return v


def _read_raw(v: DatasetVersion) -> RawTable:
    data = get_storage().get(v.raw_storage_key)
    if hashlib.sha256(data).hexdigest() != v.raw_sha256:
        raise PermanentJobError("The stored file does not match its recorded hash.")
    try:
        return read_table(data, v.file_format, get_settings().dataset_max_rows)
    except DatasetFileError as exc:
        raise PermanentJobError(str(exc)) from exc


@handler(JobKind.DATASET_PARSE)
def parse_version(db: Session, job: Job, checkpoint: Checkpoint) -> None:
    v = _load_version(db, job)
    v.status = DatasetStatus.PARSING
    db.commit()
    checkpoint(10)
    table = _read_raw(v)
    v.source_columns = list(table.frame.columns)
    v.source_row_count = table.frame.height
    v.column_mapping = table.fixed_mapping or suggest_mapping(v.dataset.kind, v.source_columns)
    v.status = DatasetStatus.NEEDS_MAPPING
    db.commit()
    if table.fixed_mapping is not None:
        # Bank formats have a fixed mapping; build straight away.
        checkpoint(50)
        _build(db, v, table)


def preview(v: DatasetVersion, rows: int = PREVIEW_ROWS) -> list[dict[str, str | None]]:
    """First rows of the raw file as text, read on demand (not stored)."""
    if v.status in (DatasetStatus.PENDING, DatasetStatus.PARSING) or not v.source_columns:
        return []
    table = read_table(get_storage().get(v.raw_storage_key), v.file_format, 10**9)
    return table.frame.head(rows).to_dicts()


def confirm_mapping(
    db: Session,
    v: DatasetVersion,
    mapping: dict[str, str],
    *,
    date_format: str,
    decimal_separator: str,
    actor: User,
) -> Job:
    if v.status not in (DatasetStatus.NEEDS_MAPPING, DatasetStatus.FAILED) or not v.source_columns:
        raise DatasetFileError("This version is not waiting for a column mapping.")
    if v.file_format in ("mt940", "camt053"):
        raise DatasetFileError("Bank statement formats use a fixed mapping.")
    validate_mapping(v.dataset.kind, mapping, v.source_columns)
    v.column_mapping = dict(mapping)
    v.parse_options = {"date_format": date_format, "decimal_separator": decimal_separator}
    v.mapping_confirmed_by_id = actor.id
    v.mapping_confirmed_at = datetime.now(UTC)
    v.status = DatasetStatus.PROCESSING
    v.failure_message = None
    v.errors = []
    v.error_count = 0
    job = Job(
        org_id=v.org_id,
        kind=JobKind.DATASET_BUILD,
        target_id=v.id,
        max_attempts=get_settings().job_max_attempts,
    )
    db.add(job)
    audit.record(
        db,
        org_id=v.org_id,
        actor_id=actor.id,
        action="dataset.mapping_confirmed",
        object_type="dataset_version",
        object_id=v.id,
        meta={"fields": sorted(mapping), "date_format": date_format},
    )
    return job


@handler(JobKind.DATASET_BUILD)
def build_version(db: Session, job: Job, checkpoint: Checkpoint) -> None:
    v = _load_version(db, job)
    checkpoint(10)
    _build(db, v, _read_raw(v))


def _build(db: Session, v: DatasetVersion, table: RawTable) -> None:
    opts = BuildOptions(
        default_currency=v.dataset.entity.functional_currency,
        date_format=v.parse_options.get("date_format", "%Y-%m-%d"),
        decimal_separator=v.parse_options.get("decimal_separator", "."),
    )
    result = build_canonical(v.dataset.kind, table.frame, v.column_mapping, opts)
    if result.frame is None:
        v.status = DatasetStatus.FAILED
        v.errors = result.errors
        v.error_count = result.error_count
        v.failure_message = (
            f"{result.error_count} value(s) could not be read. Fix the file or the mapping."
        )
        audit.record(
            db,
            org_id=v.org_id,
            actor_id=None,
            action="dataset.build_failed",
            object_type="dataset_version",
            object_id=v.id,
            meta={"error_count": result.error_count},
        )
        db.commit()
        return
    data, digest = to_parquet(result.frame)
    key = new_storage_key(v.org_id)
    get_storage().put(key, data)
    v.parquet_storage_key = key
    v.parquet_sha256 = digest
    v.row_count = result.frame.height
    v.derived_fields = result.derived_fields
    v.totals = result.totals
    v.status = DatasetStatus.READY
    v.processed_at = datetime.now(UTC)
    audit.record(
        db,
        org_id=v.org_id,
        actor_id=None,
        action="dataset.version_ready",
        object_type="dataset_version",
        object_id=v.id,
        meta={"rows": v.row_count, "parquet_sha256": digest},
    )
    db.commit()
    logger.info("dataset built", extra={"version_id": str(v.id), "rows": v.row_count})


def _mark_failed(db: Session, job: Job) -> None:
    v = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == job.target_id, DatasetVersion.org_id == job.org_id
        )
    )
    if v is not None and v.status not in (DatasetStatus.READY, DatasetStatus.FAILED):
        v.status = DatasetStatus.FAILED
        v.failure_message = job.error or "Processing failed."


on_unsuccessful(JobKind.DATASET_PARSE)(_mark_failed)
on_unsuccessful(JobKind.DATASET_BUILD)(_mark_failed)


class DatasetNotReady(RuntimeError):
    pass


def load_frame(
    db: Session, version_id: uuid.UUID, org_id: uuid.UUID
) -> tuple[DatasetVersion, pl.DataFrame]:
    """Load a ready version's canonical rows, re-checking tenant and integrity."""
    v = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.id == version_id, DatasetVersion.org_id == org_id
        )
    )
    if v is None or v.status != DatasetStatus.READY or v.parquet_storage_key is None:
        raise DatasetNotReady("The dataset version is not ready.")
    data = get_storage().get(v.parquet_storage_key)
    if hashlib.sha256(data).hexdigest() != v.parquet_sha256:
        raise DatasetNotReady("The stored dataset does not match its recorded hash.")
    return v, from_parquet(data)
