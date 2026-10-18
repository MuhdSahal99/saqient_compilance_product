# ADR 0007 — Finance datasets as hashed raw files plus canonical Parquet

Status: accepted (2026-10-18)

## Decision
An imported trial balance, ledger, register or bank statement is stored twice
through the existing storage adapter: the raw upload (SHA-256 recorded) and,
once a user confirms the column mapping, a canonical Parquet file (SHA-256
recorded) with typed columns: `Decimal(20,4)` amounts, `Date` dates, a
currency on every row and a stable `row_id` (1-based data row in the source).
Each upload is a new `dataset_versions` row; nothing is overwritten.

Polars (MIT) reads CSV/XLSX and writes Parquet inside the Celery worker.
XLSX goes through calamine via `fastexcel`; formula cells and macros are
rejected by scanning the workbook XML. MT940 is parsed by a small in-repo
parser; CAMT.053 by `defusedxml` (no DTDs or entities). Invalid values fail
the build with row ids; nothing is rounded or guessed.

## Why
Polars handles the 100k-row acceptance target in well under a second, keeps
Decimal exact, and Parquet keeps the canonical rows compact and
reproducible: a check reads exactly the bytes whose hash is on record. DuckDB
was not needed for load → validate → write.

## Consequences
- Check findings can cite `dataset_version_id` + `row_id` + column values.
- Loading re-verifies the Parquet hash, so tampered storage is refused.
- Very large files are held in memory by the worker (row cap
  `DATASET_MAX_ROWS`, size cap `DATASET_MAX_UPLOAD_MB`).
