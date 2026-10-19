"""Engine versions and the check configurations each one accepts.

``deterministic-1.0.0`` runs text checks only and its behaviour is frozen (golden
test). ``deterministic-1.1.0`` adds data checks over finance datasets and runs
text checks with the unchanged 1.0.0 code. ``deterministic-1.2.0`` adds
e-invoice, master data, readiness and VAT return checks, and lets checks take
their period from the review's tax period; 1.1.0 checks run unchanged.
``deterministic-1.3.0`` adds the withholding tax check; 1.2.0 checks run unchanged.
``deterministic-1.4.0`` adds journal entry tests; 1.3.0 checks run unchanged.
``deterministic-1.5.0`` adds segregation of duties; 1.4.0 checks run unchanged. New runs
use ``ENGINE_VERSION``; a run records the version it used, so earlier results stay explainable.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, TypeAdapter

from app.engine import (
    TEXT_ENGINE_VERSION,
    CheckConfig,
    ManualCheck,
    MetadataCheck,
    PatternCheck,
    PhraseGroupsCheck,
    ProhibitedTermsCheck,
    RequiredTextCheck,
)
from app.engine.data_checks import (
    DATA_CHECK_TYPES,
    DateRuleCheck,
    DuplicateCheck,
    FieldFormatCheck,
    RatioCheck,
    ReconcileCheck,
    ThresholdCheck,
)
from app.engine.einvoice_checks import (
    EInvoiceDeadlineCheck,
    EInvoiceValidateCheck,
    RejectionMatchCheck,
)
from app.engine.je_checks import JournalEntryCheck
from app.engine.master_data_checks import CompletenessCheck, PartyCrossCheck, TaxIdFormatCheck
from app.engine.sod_checks import SodConflictCheck
from app.engine.tax_checks import TAX_CHECK_TYPES
from app.engine.vat_checks import (
    BlockedInputCheck,
    ReverseChargeCheck,
    VatBoxReconcileCheck,
    VatGlReconcileCheck,
    ZeroRatedEvidenceCheck,
)
from app.engine.wht_checks import WhtRateCheck

DATA_ENGINE_VERSION = "deterministic-1.1.0"
ENGINE_V12 = "deterministic-1.2.0"
ENGINE_V13 = "deterministic-1.3.0"
ENGINE_V14 = "deterministic-1.4.0"
ENGINE_VERSION = "deterministic-1.5.0"

DataCheckConfig11 = Annotated[
    RequiredTextCheck
    | PhraseGroupsCheck
    | ProhibitedTermsCheck
    | PatternCheck
    | MetadataCheck
    | ManualCheck
    | ReconcileCheck
    | ThresholdCheck
    | DuplicateCheck
    | FieldFormatCheck
    | DateRuleCheck
    | RatioCheck,
    Field(discriminator="type"),
]

DataCheckConfig12 = Annotated[
    RequiredTextCheck
    | PhraseGroupsCheck
    | ProhibitedTermsCheck
    | PatternCheck
    | MetadataCheck
    | ManualCheck
    | ReconcileCheck
    | ThresholdCheck
    | DuplicateCheck
    | FieldFormatCheck
    | DateRuleCheck
    | RatioCheck
    | TaxIdFormatCheck
    | CompletenessCheck
    | PartyCrossCheck
    | EInvoiceValidateCheck
    | EInvoiceDeadlineCheck
    | RejectionMatchCheck
    | VatBoxReconcileCheck
    | VatGlReconcileCheck
    | ReverseChargeCheck
    | ZeroRatedEvidenceCheck
    | BlockedInputCheck,
    Field(discriminator="type"),
]

DataCheckConfig13 = Annotated[
    DataCheckConfig12 | WhtRateCheck,
    Field(discriminator="type"),
]

DataCheckConfig14 = Annotated[
    DataCheckConfig13 | JournalEntryCheck,
    Field(discriminator="type"),
]

AnyCheckConfig = Annotated[
    DataCheckConfig14 | SodConflictCheck,
    Field(discriminator="type"),
]

_text: TypeAdapter[CheckConfig] = TypeAdapter(CheckConfig)
_data11: TypeAdapter[DataCheckConfig11] = TypeAdapter(DataCheckConfig11)
_data12: TypeAdapter[DataCheckConfig12] = TypeAdapter(DataCheckConfig12)
_data13: TypeAdapter[DataCheckConfig13] = TypeAdapter(DataCheckConfig13)
_data14: TypeAdapter[DataCheckConfig14] = TypeAdapter(DataCheckConfig14)
_any: TypeAdapter[AnyCheckConfig] = TypeAdapter(AnyCheckConfig)

SUPPORTED = (
    TEXT_ENGINE_VERSION,
    DATA_ENGINE_VERSION,
    ENGINE_V12,
    ENGINE_V13,
    ENGINE_V14,
    ENGINE_VERSION,
)


def parse_check(raw: dict[str, Any], version: str = ENGINE_VERSION) -> Any:
    """Validate a check configuration for an engine version (ValidationError on failure)."""
    if version == TEXT_ENGINE_VERSION:
        return _text.validate_python(raw)
    if version == DATA_ENGINE_VERSION:
        return _data11.validate_python(raw)
    if version == ENGINE_V12:
        return _data12.validate_python(raw)
    if version == ENGINE_V13:
        return _data13.validate_python(raw)
    if version == ENGINE_V14:
        return _data14.validate_python(raw)
    if version == ENGINE_VERSION:
        return _any.validate_python(raw)
    raise ValueError(f"Unknown engine version {version!r}.")


def is_data_check(config: object) -> bool:
    return isinstance(config, (*DATA_CHECK_TYPES, *TAX_CHECK_TYPES))
