"""Engine versions and the check configurations each one accepts.

``deterministic-1.0.0`` runs text checks only and its behaviour is frozen (golden
test). ``deterministic-1.1.0`` adds data checks over finance datasets and runs
text checks with the unchanged 1.0.0 code. New runs use ``ENGINE_VERSION``; a
run records the version it used, so earlier results stay explainable.
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
    DataCheckConfig,
    DateRuleCheck,
    DuplicateCheck,
    FieldFormatCheck,
    RatioCheck,
    ReconcileCheck,
    ThresholdCheck,
)

ENGINE_VERSION = "deterministic-1.1.0"

AnyCheckConfig = Annotated[
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

_text: TypeAdapter[CheckConfig] = TypeAdapter(CheckConfig)
_any: TypeAdapter[AnyCheckConfig] = TypeAdapter(AnyCheckConfig)

SUPPORTED = (TEXT_ENGINE_VERSION, ENGINE_VERSION)


def parse_check(
    raw: dict[str, Any], version: str = ENGINE_VERSION
) -> CheckConfig | DataCheckConfig:
    """Validate a check configuration for an engine version (ValidationError on failure)."""
    if version == TEXT_ENGINE_VERSION:
        return _text.validate_python(raw)
    if version == ENGINE_VERSION:
        return _any.validate_python(raw)
    raise ValueError(f"Unknown engine version {version!r}.")


def is_data_check(config: object) -> bool:
    return isinstance(config, DATA_CHECK_TYPES)
