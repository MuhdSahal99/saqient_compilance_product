"""recon-1.0.0 matcher and ageing, hand-checked."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.assurance.matching import Item, age_bucket, bucket_labels, match, norm_ref

D = Decimal


def test_passes_in_order_with_tie_breaks() -> None:
    bank = [
        Item(1, date(2026, 1, 3), D("5000"), "INV-100"),
        Item(2, date(2026, 1, 10), D("800"), ""),
        Item(3, date(2026, 1, 15), D("3000"), "batch 9"),
        Item(4, date(2026, 1, 20), D("50"), ""),
    ]
    book = [
        Item(10, date(2026, 1, 2), D("5000"), "inv100"),
        Item(11, date(2026, 1, 9), D("800"), "X"),
        Item(12, date(2026, 1, 11), D("800"), "Y"),  # same gap as 11; lower row id wins
        Item(13, date(2026, 1, 14), D("1000"), "BATCH9"),
        Item(14, date(2026, 1, 14), D("2000"), "BATCH-9"),
        Item(15, date(2026, 1, 30), D("50"), ""),  # 10 days away: outside the window
    ]
    got = match(bank, book, D("0"), 3)
    assert [(m.method, m.bank, m.book) for m in got] == [
        ("reference", (1,), (10,)),
        ("amount_date", (2,), (11,)),
        ("reference_group", (3,), (13, 14)),
    ]


def test_tolerance_exclusions_and_many_bank_to_one_book() -> None:
    bank = [
        Item(1, date(2026, 1, 1), D("100.00"), "R1"),
        Item(2, date(2026, 1, 1), D("60.00"), "G"),
        Item(3, date(2026, 1, 2), D("40.01"), "G"),
    ]
    book = [Item(9, date(2026, 1, 1), D("100.02"), "R1"), Item(8, date(2026, 1, 5), D("100"), "G")]
    assert [(m.method, m.bank, m.book) for m in match(bank, book, D("0.01"), 0)] == [
        ("reference_group", (2, 3), (8,))
    ]
    got = match(bank, book, D("0.02"), 0, exclude_bank={2})
    assert [(m.method, m.bank, m.book) for m in got] == [("reference", (1,), (9,))]
    with pytest.raises(ValueError):
        match(bank, book, D("-1"), 0)


def test_ageing_and_refs() -> None:
    assert bucket_labels([30, 60, 90]) == ["0-30", "31-60", "61-90", "91+"]
    end = date(2026, 1, 31)
    assert age_bucket(date(2026, 1, 1), end, [30, 60, 90]) == (30, "0-30")
    assert age_bucket(date(2025, 12, 31), end, [30, 60, 90]) == (31, "31-60")
    assert age_bucket(date(2025, 11, 20), end, [30, 60, 90]) == (72, "61-90")
    assert age_bucket(date(2025, 6, 1), end, [30, 60, 90]) == (244, "91+")
    assert age_bucket(date(2026, 2, 5), end, [30]) == (0, "0-30")
    assert norm_ref(" Inv-100/A ") == "inv100a" and norm_ref(None) == ""
