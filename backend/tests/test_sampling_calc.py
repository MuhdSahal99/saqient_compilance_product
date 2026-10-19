"""Hand-checked sampling selection and projection (app/calc/sampling.py)."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from app.calc import sampling as smp

D = Decimal


def test_stream_is_sha256_counter_mode() -> None:
    s = smp.Stream("synthetic")
    first = int.from_bytes(hashlib.sha256(b"synthetic:0").digest()[:8], "big")
    second = int.from_bytes(hashlib.sha256(b"synthetic:1").digest()[:8], "big")
    assert s.below(1 << 32) == first % (1 << 32)
    assert s.below(1 << 32) == second % (1 << 32)
    with pytest.raises(smp.SamplingError):
        s.below(0)


def test_mus_systematic_selection_by_hand() -> None:
    # Total 1000, n = 4 -> interval 250.00. Start 100: points 100, 350, 600, 850.
    # Cumulative ranges: row 1 (0, 100], row 2 (100, 350], row 3 (350, 400], row 4 (400, 1000].
    rows = [(1, D(100)), (2, D(250)), (3, D(50)), (4, D(600))]
    interval = smp.mus_interval(D(1000), 4)
    assert interval == D("250.00")
    sel = smp.mus_select(rows, interval, D(100))
    assert sel.hits == {1: 1, 2: 1, 4: 2}
    # An item at least as large as the interval is always hit, whatever the start.
    for seed in ("a", "b", "c", "d", "e"):
        start = smp.mus_start(interval, smp.Stream(seed))
        assert D("0.01") <= start <= interval
        assert 4 in smp.mus_select(rows, interval, start).hits
    # 1000 / 3 = 333.333… -> 333.33 (half up)
    assert smp.mus_interval(D(1000), 3) == D("333.33")
    with pytest.raises(smp.SamplingError):
        smp.mus_interval(D(0), 3)


def test_random_and_stratified_selection() -> None:
    ids = list(range(1, 21))
    a = smp.random_select(ids, 5, smp.Stream("seed-1"))
    assert len(a) == len(set(a)) == 5 and set(a) <= set(ids)
    assert smp.random_select(ids, 5, smp.Stream("seed-1")) == a
    assert smp.random_select(ids, 20, smp.Stream("x")) == ids
    with pytest.raises(smp.SamplingError):
        smp.random_select(ids, 21, smp.Stream("x"))

    rows = [(1, D(50)), (2, D(80)), (3, D(90)), (4, D(500)), (5, D(700))]
    strata = [smp.Stratum(D(100), 1), smp.Stratum(None, None)]
    assert smp.strata_of(rows, strata) == [[1, 2, 3], [4, 5]]
    picked = smp.stratified_select(rows, strata, smp.Stream("s"))
    assert picked[4] == 1 and picked[5] == 1
    assert sum(1 for s in picked.values() if s == 0) == 1
    with pytest.raises(smp.SamplingError):
        smp.strata_of(rows, [smp.Stratum(D(100), 1), smp.Stratum(D(50), 1)])


def test_projections_by_hand() -> None:
    # MUS, interval 250: row 4 book 600 (>= interval) audited 540 -> actual 60;
    # row 1 book 100 audited 90 -> tainting 0.1 x 250 = 25.00; row 2 no exception. Total 85.00.
    items = [
        smp.TestedItem(1, D(100), D(90)),
        smp.TestedItem(2, D(250), D(250)),
        smp.TestedItem(4, D(600), D(540)),
    ]
    p = smp.project_mus(items, D(250))
    assert p.projected == D("85.00") and p.known == D(70) and p.untested == 0
    assert p.steps[-1]["value"] == "85.00"

    # Ratio: misstatement 50 / sample value 300 x population 3000 = 500.00; one untested.
    r = smp.project_ratio(
        [
            smp.TestedItem(1, D(100), D(100)),
            smp.TestedItem(2, D(200), D(150)),
            smp.TestedItem(3, D(10), None),
        ],
        D(3000),
    )
    assert r.projected == D("500.00") and r.untested == 1

    # Stratified: stratum 1 value 220, tested 80 -> 60: 20 / 80 x 220 = 55.00;
    # stratum 2 fully tested: 700 -> 650 = 50. Total 105.00.
    st = smp.project_stratified(
        [
            smp.TestedItem(2, D(80), D(60), 0),
            smp.TestedItem(4, D(500), D(500), 1),
            smp.TestedItem(5, D(700), D(650), 1),
        ],
        [D(220), D(1200)],
        [False, True],
    )
    assert st.projected == D("105.00") and st.known == D(70)


def test_population_hash_depends_on_rows_and_values() -> None:
    a = smp.population_hash([(1, D("10.00")), (2, D(5))])
    assert a == smp.population_hash([(1, D("10.00")), (2, D(5))])
    assert a != smp.population_hash([(1, D("10.01")), (2, D(5))])
