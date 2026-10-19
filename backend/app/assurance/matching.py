"""Bank-to-book matching (``recon-1.0.0``).

Both sides use "money in is positive": bank amount = credit − debit, ledger amount =
debit − credit for the bank's GL account. Passes run in order on items still unmatched:

1. ``reference``        same normalised reference, amount within tolerance; the closest
                        date wins, then the lowest row id
2. ``amount_date``      amount within tolerance and dates within the window; the smallest
                        amount difference wins, then the smallest date gap, then row id
3. ``reference_group``  several items on one side with one reference whose total is within
                        tolerance of a single item on the other side with that reference

Every tie-break is explicit, so the same inputs always give the same matches.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MATCHER_VERSION = "recon-1.0.0"


@dataclass(frozen=True)
class Item:
    row_id: int
    on: date
    amount: Decimal
    reference: str = ""


@dataclass(frozen=True)
class Match:
    method: str
    bank: tuple[int, ...]
    book: tuple[int, ...]


def norm_ref(ref: str | None) -> str:
    return "".join(ch for ch in (ref or "").casefold() if ch.isascii() and ch.isalnum())


def _pick(
    item: Item, pool: list[Item], tol: Decimal, window: int | None, same_ref: bool
) -> Item | None:
    best: tuple[Decimal, int, int] | None = None
    chosen = None
    ref = norm_ref(item.reference)
    for c in pool:
        diff = abs(c.amount - item.amount)
        gap = abs((c.on - item.on).days)
        if diff > tol or (window is not None and gap > window):
            continue
        if same_ref and (not ref or norm_ref(c.reference) != ref):
            continue
        key = (Decimal(gap), 0, c.row_id) if same_ref else (diff, gap, c.row_id)
        if best is None or key < best:
            best, chosen = key, c
    return chosen


def match(
    bank: list[Item],
    book: list[Item],
    tolerance: Decimal,
    window_days: int,
    exclude_bank: set[int] | frozenset[int] = frozenset(),
    exclude_book: set[int] | frozenset[int] = frozenset(),
) -> list[Match]:
    if tolerance < 0 or window_days < 0:
        raise ValueError("tolerance and window must not be negative")
    open_bank = sorted((b for b in bank if b.row_id not in exclude_bank), key=_order)
    open_book = sorted((b for b in book if b.row_id not in exclude_book), key=_order)
    out: list[Match] = []

    for method, window, same_ref in (
        ("reference", None, True),
        ("amount_date", window_days, False),
    ):
        for b in list(open_bank):
            c = _pick(b, open_book, tolerance, window, same_ref)
            if c is not None:
                out.append(Match(method, (b.row_id,), (c.row_id,)))
                open_bank.remove(b)
                open_book.remove(c)

    for many_side in ("book", "bank"):
        singles, many = (open_bank, open_book) if many_side == "book" else (open_book, open_bank)
        groups: dict[str, list[Item]] = defaultdict(list)
        for it in many:
            if r := norm_ref(it.reference):
                groups[r].append(it)
        for s in list(singles):
            g = groups.get(norm_ref(s.reference))
            if not g or len(g) < 2:
                continue
            if abs(sum((x.amount for x in g), Decimal(0)) - s.amount) <= tolerance:
                ids = tuple(sorted(x.row_id for x in g))
                pair = ((s.row_id,), ids) if many_side == "book" else (ids, (s.row_id,))
                out.append(Match("reference_group", *pair))
                singles.remove(s)
                for x in g:
                    many.remove(x)
                del groups[norm_ref(s.reference)]
    return out


def _order(i: Item) -> tuple[date, int]:
    return (i.on, i.row_id)


def bucket_labels(bounds: list[int]) -> list[str]:
    labels, lower = [], 0
    for b in bounds:
        labels.append(f"{lower}-{b}")
        lower = b + 1
    labels.append(f"{lower}+")
    return labels


def age_bucket(on: date, as_of: date, bounds: list[int]) -> tuple[int, str]:
    """Days outstanding at ``as_of`` and the bucket label (bounds are inclusive uppers)."""
    days = max((as_of - on).days, 0)
    labels = bucket_labels(bounds)
    for b, label in zip(bounds, labels, strict=False):
        if days <= b:
            return days, label
    return days, labels[-1]
