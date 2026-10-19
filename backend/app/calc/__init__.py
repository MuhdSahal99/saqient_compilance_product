"""Explainable, versioned tax calculations (Phase C).

A formula takes a workpaper's input lines and a rule reader and returns computed
lines, each with the steps that produced it. All arithmetic is Decimal; rounding
follows the pack's ``<prefix>.amount_decimals`` and ``<prefix>.rounding_mode``.
Rates, thresholds and shares come only from the rule pack. A result is a proposal
for a qualified person; nothing here decides that an entity qualifies for anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Any

CALC_VERSION = "calc-1.0.0"

ZERO = Decimal(0)


class CalcError(ValueError):
    """The inputs or rules cannot produce a result (shown to the preparer)."""


@dataclass(frozen=True)
class InputLine:
    key: str
    category: str
    amount: Decimal | None
    value: str | None
    label: str


@dataclass
class Step:
    label: str
    expression: str
    value: str

    def as_dict(self) -> dict[str, str]:
        return {"label": self.label, "expression": self.expression, "value": self.value}


@dataclass
class Output:
    key: str
    label: str
    section: str
    formula_id: str
    amount: Decimal | None = None
    value: str | None = None
    steps: list[Step] = field(default_factory=list)
    rule_keys: list[str] = field(default_factory=list)


class RuleSource:
    """What a formula may read: typed rule values for the workpaper's period."""

    def get(self, key: str) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def decimal(self, key: str) -> Decimal:
        v = self.get(key)
        try:
            return Decimal(str(v))
        except Exception as exc:  # noqa: BLE001 - any bad value is a rule error
            raise CalcError(f"Rule '{key}' must be a number.") from exc


@dataclass
class Inputs:
    lines: list[InputLine]
    period_start: date | None = None
    period_end: date | None = None

    def amount(self, key: str, required: bool = False) -> Decimal:
        for ln in self.lines:
            if ln.key == key:
                if ln.amount is None:
                    break
                return ln.amount
        if required:
            raise CalcError(f"Enter the input '{key}'.")
        return ZERO

    def has(self, key: str) -> bool:
        return any(ln.key == key for ln in self.lines)

    def flag(self, key: str) -> bool | None:
        for ln in self.lines:
            if ln.key == key and ln.value is not None:
                v = ln.value.strip().lower()
                if v in ("true", "yes", "1"):
                    return True
                if v in ("false", "no", "0"):
                    return False
        return None

    def by_category(self, category: str) -> list[InputLine]:
        return [ln for ln in self.lines if ln.category == category and ln.amount is not None]


class Rounder:
    def __init__(self, rules: RuleSource, prefix: str) -> None:
        decimals = int(rules.decimal(f"{prefix}.amount_decimals"))
        mode = str(rules.get(f"{prefix}.rounding_mode")).lower()
        if mode not in ("half_up", "half_even"):
            raise CalcError(f"Rule '{prefix}.rounding_mode' must be half_up or half_even.")
        self.quantum = Decimal(1).scaleb(-decimals)
        self.mode = ROUND_HALF_UP if mode == "half_up" else ROUND_HALF_EVEN

    def __call__(self, v: Decimal) -> Decimal:
        return v.quantize(self.quantum, rounding=self.mode)


def fmt(v: Decimal) -> str:
    return format(v, "f")


Formula = Callable[[Inputs, RuleSource, str], list[Output]]
FORMULAS: dict[str, Formula] = {}
# Input categories a preparer may use per workpaper kind ('input' = a named input).
CATEGORIES: dict[str, tuple[str, ...]] = {}


def formula(kind: str, categories: tuple[str, ...] = ()) -> Callable[[Formula], Formula]:
    def register(fn: Formula) -> Formula:
        FORMULAS[kind] = fn
        CATEGORIES[kind] = ("input", *categories)
        return fn

    return register


def run(kind: str, inputs: Inputs, rules: RuleSource, prefix: str) -> list[Output]:
    fn = FORMULAS.get(kind)
    if fn is None:
        raise CalcError(f"No calculation for workpaper kind '{kind}'.")
    return fn(inputs, rules, prefix)


from app.calc import audit as _audit  # noqa: E402,F401
from app.calc import corporate_tax as _ct  # noqa: E402,F401  (registers formulas)
from app.calc import losses as _losses  # noqa: E402,F401
from app.calc import pillar_two as _p2  # noqa: E402,F401
from app.calc import transfer_pricing as _tp  # noqa: E402,F401
from app.calc import zakat as _zakat  # noqa: E402,F401
