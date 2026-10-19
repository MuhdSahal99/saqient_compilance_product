"""Reproducible audit sampling (D5): monetary unit, simple random and stratified.

Randomness comes from SHA-256 in counter mode over a recorded seed, not from
Python's ``random`` module, so a sample re-selects identically on any Python
version or machine. Selection works on (row_id, book value) pairs sorted by row id;
the population hash fixes exactly which rows and values were sampled from.

Projection is explained step by step. Upper misstatement limits need reliability
factors, which are professional tables, so they are not computed here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

SAMPLING_VERSION = "sampling-1.0.0"
CENT = Decimal("0.01")
ZERO = Decimal(0)


class SamplingError(ValueError):
    pass


class Stream:
    """Deterministic integers from SHA-256(seed:counter)."""

    def __init__(self, seed: str) -> None:
        self.seed = seed
        self.counter = 0

    def _u64(self) -> int:
        digest = hashlib.sha256(f"{self.seed}:{self.counter}".encode()).digest()
        self.counter += 1
        return int.from_bytes(digest[:8], "big")

    def below(self, k: int) -> int:
        """Uniform integer in [0, k), by rejection (no modulo bias)."""
        if k <= 0:
            raise SamplingError("empty range")
        limit = (1 << 64) - ((1 << 64) % k)
        while True:
            v = self._u64()
            if v < limit:
                return v % k


def population_hash(rows: list[tuple[int, Decimal]]) -> str:
    h = hashlib.sha256()
    for rid, value in rows:
        h.update(f"{rid}:{format(value, 'f')}\n".encode())
    return h.hexdigest()


def random_select(row_ids: list[int], n: int, stream: Stream) -> list[int]:
    """n distinct rows by a partial Fisher–Yates shuffle of the sorted ids."""
    ids = sorted(row_ids)
    if n > len(ids):
        raise SamplingError(f"The sample size {n} is larger than the population ({len(ids)}).")
    for i in range(n):
        j = i + stream.below(len(ids) - i)
        ids[i], ids[j] = ids[j], ids[i]
    return sorted(ids[:n])


@dataclass
class MusSelection:
    interval: Decimal
    start: Decimal
    hits: dict[int, int] = field(default_factory=dict)  # row id → selection points hit


def mus_interval(total: Decimal, n: int) -> Decimal:
    if n <= 0:
        raise SamplingError("The sample size must be at least 1.")
    if total <= 0:
        raise SamplingError("The population has no monetary value to sample.")
    return (total / n).quantize(CENT, ROUND_HALF_UP)


def mus_start(interval: Decimal, stream: Stream) -> Decimal:
    """A random start in [0.01, interval], in cents."""
    cents = int(interval / CENT)
    return (Decimal(stream.below(cents)) + 1) * CENT


def mus_select(rows: list[tuple[int, Decimal]], interval: Decimal, start: Decimal) -> MusSelection:
    """Systematic selection: points start, start + interval, … over cumulative |value|.

    Rows are taken in row id order. An item at least as large as the interval is
    always hit, possibly more than once.
    """
    sel = MusSelection(interval=interval, start=start)
    point = start
    cumulative = ZERO
    for rid, value in sorted(rows):
        upper = cumulative + abs(value)
        while point <= upper and abs(value) > 0:
            sel.hits[rid] = sel.hits.get(rid, 0) + 1
            point += interval
        cumulative = upper
    return sel


@dataclass(frozen=True)
class Stratum:
    upper: Decimal | None  # |value| up to and including; None = no upper bound
    size: int | None  # None = test every item


def strata_of(rows: list[tuple[int, Decimal]], strata: list[Stratum]) -> list[list[int]]:
    bounds = [s.upper for s in strata]
    if any(b is None for b in bounds[:-1]) or bounds[-1] is not None:
        raise SamplingError("Only the last stratum is open-ended, and it must be.")
    uppers = [b for b in bounds if b is not None]
    if uppers != sorted(uppers) or len(set(uppers)) != len(uppers):
        raise SamplingError("Stratum upper bounds must increase.")
    groups: list[list[int]] = [[] for _ in strata]
    for rid, value in sorted(rows):
        a = abs(value)
        idx = next(i for i, b in enumerate(bounds) if b is None or a <= b)
        groups[idx].append(rid)
    return groups


def stratified_select(
    rows: list[tuple[int, Decimal]], strata: list[Stratum], stream: Stream
) -> dict[int, int]:
    """Row id → stratum index; random within each stratum, every item where size is None."""
    out: dict[int, int] = {}
    for idx, (s, ids) in enumerate(zip(strata, strata_of(rows, strata), strict=True)):
        chosen = ids if s.size is None else random_select(ids, s.size, stream)
        for rid in chosen:
            out[rid] = idx
    return out


# ---------------------------------------------------------------- projection


@dataclass
class TestedItem:
    row_id: int
    book: Decimal
    audited: Decimal | None  # None = not tested yet
    stratum: int | None = None


@dataclass
class Projection:
    projected: Decimal
    known: Decimal  # misstatement found in the sample
    untested: int
    steps: list[dict[str, str]]


def _f(v: Decimal) -> str:
    return format(v, "f")


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, ROUND_HALF_UP)


def _step(label: str, expression: str, value: str) -> dict[str, str]:
    return {"label": label, "expression": expression, "value": value}


def project_mus(items: list[TestedItem], interval: Decimal) -> Projection:
    """Tainting × interval for items below the interval; actual for the rest."""
    steps, total, known = [], ZERO, ZERO
    for it in sorted(items, key=lambda x: x.row_id):
        if it.audited is None:
            continue
        mis = it.book - it.audited
        if mis == 0:
            continue
        known += mis
        if abs(it.book) >= interval:
            total += mis
            steps.append(
                _step(f"Row {it.row_id} (≥ interval)", f"{_f(it.book)} − {_f(it.audited)}", _f(mis))
            )
        else:
            taint = mis / it.book
            p = _q(taint * interval)
            total += p
            steps.append(
                _step(
                    f"Row {it.row_id} tainting × interval",
                    f"({_f(it.book)} − {_f(it.audited)}) ÷ {_f(it.book)} × {_f(interval)}",
                    _f(p),
                )
            )
    untested = sum(1 for it in items if it.audited is None)
    steps.append(_step("Projected misstatement", "sum of the above", _f(_q(total))))
    return Projection(_q(total), known, untested, steps)


def _ratio(
    items: list[TestedItem], pop_value: Decimal, label: str
) -> tuple[Decimal, Decimal, dict[str, str]]:
    tested = [it for it in items if it.audited is not None]
    book = sum((abs(it.book) for it in tested), ZERO)
    mis = sum((it.book - it.audited for it in tested if it.audited is not None), ZERO)
    if book == 0:
        return ZERO, mis, _step(label, "no tested value", "0")
    p = _q(mis / book * pop_value)
    return (
        p,
        mis,
        _step(label, f"{_f(mis)} ÷ {_f(book)} × {_f(pop_value)}", _f(p)),
    )


def project_ratio(items: list[TestedItem], pop_value: Decimal) -> Projection:
    p, mis, step = _ratio(items, pop_value, "Sample misstatement ÷ sample value × population value")
    untested = sum(1 for it in items if it.audited is None)
    return Projection(p, mis, untested, [step])


def project_stratified(
    items: list[TestedItem], strata_values: list[Decimal], fully_tested: list[bool]
) -> Projection:
    steps, total, known = [], ZERO, ZERO
    for idx, value in enumerate(strata_values):
        mine = [it for it in items if it.stratum == idx]
        if fully_tested[idx]:
            mis = sum((it.book - it.audited for it in mine if it.audited is not None), ZERO)
            total += mis
            known += mis
            steps.append(_step(f"Stratum {idx + 1} (all items)", "actual misstatement", _f(mis)))
        else:
            p, mis, step = _ratio(mine, value, f"Stratum {idx + 1} ratio projection")
            total += p
            known += mis
            steps.append(step)
    untested = sum(1 for it in items if it.audited is None)
    steps.append(_step("Projected misstatement", "sum of strata", _f(_q(total))))
    return Projection(_q(total), known, untested, steps)
