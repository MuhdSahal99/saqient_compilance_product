"""Benchmark: import a synthetic 100k-row general ledger (CSV) end to end in-process.

Measures what the worker does for a GL import: SHA-256 of the raw file, CSV
read, header mapping, typing every value, writing Parquet, and reading it
back. Synthetic data only.

    uv run python scripts/bench_gl_import.py [--rows 100000]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.datasets.build import BuildOptions, build_canonical, from_parquet, to_parquet  # noqa: E402
from app.datasets.readers import read_table  # noqa: E402
from app.datasets.schemas import suggest_mapping  # noqa: E402
from app.models import DatasetKind  # noqa: E402


def synthetic_gl(rows: int, seed: int = 7) -> bytes:
    rnd = random.Random(seed)  # noqa: S311 - synthetic benchmark data
    accounts = ["1100", "1200", "2000", "2100", "4000", "5000", "5100", "6000"]
    out = io.StringIO()
    out.write("Journal,Date,Account,Narration,Debit,Credit,Currency,Reference\n")
    start = date(2025, 1, 1)
    for i in range(0, rows, 2):
        amount = f"{rnd.randint(1, 5_000_000) / 100:.2f}"
        d = (start + timedelta(days=rnd.randint(0, 364))).isoformat()
        je = f"JE-{i // 2 + 1:07d}"
        a, b = rnd.sample(accounts, 2)
        out.write(f"{je},{d},{a},Synthetic entry {i},{amount},,AED,REF{i}\n")
        out.write(f"{je},{d},{b},Synthetic entry {i},,{amount},AED,REF{i}\n")
    return out.getvalue().encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    args = parser.parse_args()
    raw = synthetic_gl(args.rows)
    t0 = time.perf_counter()
    hashlib.sha256(raw).hexdigest()
    table = read_table(raw, "csv", 1_000_000)
    mapping = suggest_mapping(DatasetKind.GENERAL_LEDGER, list(table.frame.columns))
    t1 = time.perf_counter()
    result = build_canonical(
        DatasetKind.GENERAL_LEDGER, table.frame, mapping, BuildOptions(default_currency="AED")
    )
    assert result.frame is not None, result.errors[:3]
    data, _ = to_parquet(result.frame)
    t2 = time.perf_counter()
    back = from_parquet(data)
    t3 = time.perf_counter()
    assert back.height == args.rows
    print(f"rows={args.rows} csv_mb={len(raw) / 1e6:.1f} parquet_mb={len(data) / 1e6:.1f}")
    print(f"read+hash={t1 - t0:.2f}s build+parquet={t2 - t1:.2f}s reload={t3 - t2:.2f}s")
    print(f"total={t3 - t0:.2f}s (target < 60s)")
    print(f"debit total={result.totals['debit']} credit total={result.totals['credit']}")


if __name__ == "__main__":
    main()
