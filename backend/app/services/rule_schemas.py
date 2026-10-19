"""Shapes of structured (``json``) rule values, by rule-key family.

A ``json`` rule holds a list or table (a VAT return box layout, a list of
mandatory invoice fields, a go-live wave table). The values are regulatory data
entered by people; this module only fixes their *shape*, so a check can rely on
it. Numbers inside JSON are parsed as Decimal, never float.

Families are matched by rule-key suffix (the last dotted segment), e.g. any key
ending in ``.mandatory_fields``. Keys whose suffix is not registered may hold
any JSON object or array.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

MAX_JSON_BYTES = 64 * 1024

Text = Annotated[str, Field(min_length=1, max_length=300)]
Code = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.\-]+$")]
# Restricted XPath: absolute or relative steps of prefixed names, optional [n] or
# [prefix:Name='literal'] predicates. Evaluated by lxml, never built from user text.
XPath = Annotated[
    str,
    Field(
        min_length=1,
        max_length=400,
        pattern=r"^(/{0,2}[A-Za-z][\w\-]*:[A-Za-z][\w\-]*"
        r"(\[(\d+|[A-Za-z][\w\-]*:[A-Za-z][\w\-]*='[^'\[\]]{0,80}')\])?)"
        r"(/{1,2}[A-Za-z][\w\-]*:[A-Za-z][\w\-]*"
        r"(\[(\d+|[A-Za-z][\w\-]*:[A-Za-z][\w\-]*='[^'\[\]]{0,80}')\])?|/@[A-Za-z][\w\-]*)*$",
    ),
]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MandatoryField(_M):
    id: Code
    label: Text
    xpath: XPath
    min: int = Field(default=1, ge=0, le=1000)
    max: int | None = Field(default=None, ge=1, le=100000)
    # Only required on these invoice type codes / subtypes when given.
    when_type: list[Code] | None = None


class CodeList(_M):
    id: Code
    label: Text
    xpath: XPath
    allowed: list[Annotated[str, Field(max_length=40)]] = Field(min_length=1, max_length=500)


class TaxIdFormat(_M):
    """A tax registration number shape: digits only, fixed length, fixed prefix/suffix."""

    length: int = Field(ge=1, le=40)
    digits_only: bool = True
    prefix: Annotated[str, Field(max_length=10)] = ""
    suffix: Annotated[str, Field(max_length=10)] = ""


class GoLiveWave(_M):
    """One wave of an e-invoicing rollout: entities whose size basis is in range."""

    label: Text
    min_revenue: Decimal | None = None
    max_revenue: Decimal | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    go_live: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    # Optional preparation milestone (e.g. ASP appointment) before go-live.
    milestones: list[Milestone] = Field(default_factory=list, max_length=10)


class Milestone(_M):
    id: Code
    label: Text
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


Treatment = Literal[
    "standard",
    "zero_rated",
    "zero_rated_export",
    "exempt",
    "out_of_scope",
    "reverse_charge",
    "import",
]


class BoxDefinition(_M):
    """One VAT return box and the formula that recomputes it from the registers."""

    code: Code
    label: Text
    register: Literal["sales_register", "purchase_register"]
    treatments: list[Treatment] = Field(min_length=1, max_length=7)
    measure: Literal["net_amount", "tax_amount", "recoverable_tax"]
    # Optional split, e.g. by emirate: only rows whose field equals the value.
    filter_field: Literal["place_of_supply", "customer_country", "tax_code"] | None = None
    filter_value: Annotated[str, Field(max_length=40)] | None = None
    # Reverse charge: the same purchase rows count once as output and once as input.
    sign: Literal[1, -1] = 1


class BoxLayout(_M):
    boxes: list[BoxDefinition] = Field(min_length=1, max_length=60)
    # Boxes that sum others (e.g. total output tax) — checked as box arithmetic.
    totals: list[BoxTotal] = Field(default_factory=list, max_length=20)
    # Return boxes whose tax amounts are compared with the GL VAT accounts.
    output_tax_boxes: list[Code] = Field(default_factory=list, max_length=40)
    input_tax_boxes: list[Code] = Field(default_factory=list, max_length=40)


class BoxTotal(_M):
    code: Code
    label: Text
    plus: list[Code] = Field(min_length=1, max_length=40)
    minus: list[Code] = Field(default_factory=list, max_length=40)
    column: Literal["amount", "tax_amount"] = "tax_amount"


class Obligation(_M):
    """A recurring filing obligation and how its due date is derived from a period."""

    id: Code
    label: Text
    tax_type: Literal["vat", "corporate_tax", "zakat", "wht", "einvoicing", "other"]
    frequency: Literal["monthly", "quarterly", "annual"]
    # Due date = period end + months_after months, then day_of_month (or + days_after days).
    months_after: int = Field(default=0, ge=0, le=24)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    days_after: int | None = Field(default=None, ge=0, le=730)
    # Quarters follow the entity's fiscal year unless the pack says calendar.
    period_basis: Literal["fiscal", "calendar"] = "calendar"


class RateBand(_M):
    """Income from ``lower`` up to ``upper`` (open-ended if null) is taxed at ``rate`` (0–1)."""

    lower: Decimal = Field(ge=0)
    upper: Decimal | None = None
    rate: Decimal = Field(ge=0, le=1)


def _bands(v: list[RateBand]) -> list[RateBand]:
    prev: Decimal | None = Decimal(0)
    for b in v:
        if prev is None or b.lower != prev:
            raise ValueError("bands must start at 0 and be contiguous (lower = previous upper)")
        if b.upper is not None and b.upper <= b.lower:
            raise ValueError("each band's upper must be above its lower")
        prev = b.upper
    if prev is not None:
        raise ValueError("the last band must be open-ended (upper null)")
    return v


def _ascending(v: list[int]) -> list[int]:
    if any(b <= a for a, b in zip(v, v[1:], strict=False)):
        raise ValueError("bounds must increase")
    return v


class ShareRange(_M):
    low: Decimal = Field(ge=0, le=1)
    high: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _order(self) -> ShareRange:
        if self.high < self.low:
            raise ValueError("high must not be below low")
        return self


SodCode = Annotated[str, Field(min_length=1, max_length=120)]


class SodConflict(_M):
    """Two sets of role or permission codes that one user should not hold together."""

    id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,40}$")
    a: list[SodCode] = Field(min_length=1, max_length=100)
    b: list[SodCode] = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _disjoint(self) -> SodConflict:
        a = {" ".join(x.split()).casefold() for x in self.a}
        if a & {" ".join(x.split()).casefold() for x in self.b}:
            raise ValueError("a code cannot be on both sides of a conflict")
        return self


def _unique_ids(v: list[SodConflict]) -> list[SodConflict]:
    ids = [c.id for c in v]
    if len(ids) != len(set(ids)):
        raise ValueError("conflict ids must be unique")
    return v


class BenfordBands(_M):
    """Mean absolute deviation upper bounds; above ``marginal`` is nonconformity."""

    close: Decimal = Field(gt=0, le=1)
    acceptable: Decimal = Field(gt=0, le=1)
    marginal: Decimal = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _order(self) -> BenfordBands:
        if not self.close < self.acceptable < self.marginal:
            raise ValueError("bands must increase: close < acceptable < marginal")
        return self


GoLiveWave.model_rebuild()
BoxLayout.model_rebuild()

FAMILIES: dict[str, TypeAdapter[Any]] = {
    "mandatory_fields": TypeAdapter(list[MandatoryField]),
    "code_lists": TypeAdapter(list[CodeList]),
    "tax_id_formats": TypeAdapter(dict[Annotated[str, Field(pattern=r"^[A-Z]{2}$")], TaxIdFormat]),
    "go_live_waves": TypeAdapter(list[GoLiveWave]),
    "box_layout": TypeAdapter(BoxLayout),
    "obligations": TypeAdapter(list[Obligation]),
    "codes": TypeAdapter(list[Annotated[str, Field(max_length=80)]]),
    # Withholding rate per payment type code (a share between 0 and 1).
    "wht_rates": TypeAdapter(
        dict[
            Annotated[str, Field(pattern=r"^[a-z0-9_]{1,60}$")],
            Annotated[Decimal, Field(ge=0, le=1)],
        ]
    ),
    "rate_bands": TypeAdapter(
        Annotated[list[RateBand], Field(min_length=1, max_length=20), AfterValidator(_bands)]
    ),
    "materiality_share_ranges": TypeAdapter(
        dict[Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")], ShareRange]
    ),
    "weekend_days": TypeAdapter(
        Annotated[list[Annotated[int, Field(ge=1, le=7)]], Field(max_length=3)]
    ),
    "holidays": TypeAdapter(Annotated[list[date], Field(max_length=400)]),
    "benford_mad_bands": TypeAdapter(BenfordBands),
    # Inclusive upper bounds in days, ascending (e.g. [30, 60, 90] → 0-30, 31-60, 61-90, 91+).
    "ageing_buckets": TypeAdapter(
        Annotated[
            list[Annotated[int, Field(ge=1, le=3650)]],
            Field(min_length=1, max_length=10),
            AfterValidator(_ascending),
        ]
    ),
    "sod_conflicts": TypeAdapter(
        Annotated[
            list[SodConflict], Field(min_length=1, max_length=500), AfterValidator(_unique_ids)
        ]
    ),
    "required_fields": TypeAdapter(
        dict[Annotated[str, Field(pattern=r"^([A-Z]{2}|\*)$")], list[Code]]
    ),
}


class RuleShapeError(ValueError):
    pass


def family(rule_key: str) -> str:
    return rule_key.rsplit(".", 1)[-1]


def load_json(raw: str) -> Any:
    if len(raw.encode()) > MAX_JSON_BYTES:
        raise RuleShapeError(f"larger than {MAX_JSON_BYTES // 1024} KB")
    try:
        value = json.loads(raw, parse_float=Decimal)
    except ValueError as exc:
        raise RuleShapeError("not valid JSON") from exc
    if not isinstance(value, (dict, list)):
        raise RuleShapeError("JSON rules must be an object or an array")
    return value


def validate_shape(rule_key: str, value: Any) -> Any:
    """Validate a parsed JSON value against its family; returns the typed value."""
    adapter = FAMILIES.get(family(rule_key))
    if adapter is None:
        return value
    try:
        return adapter.validate_python(value)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise RuleShapeError(f"{where or 'value'}: {first['msg']}") from exc


def typed(rule_key: str, value: Any) -> Any:
    """The family model for an already-validated JSON value (used by checks)."""
    return validate_shape(rule_key, value)
