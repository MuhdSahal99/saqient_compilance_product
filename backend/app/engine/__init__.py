"""Deterministic review engine.

No AI and no arbitrary code: each requirement has a validated declarative
check configuration. A text match is not proof of compliance, and the absence
of a match is not automatically a violation — outcomes go to human review.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.engine.patterns import PatternError, compile_pattern
from app.models import CheckOutcome

# Text checks are frozen at 1.0.0 (pinned by tests/fixtures/engine/golden_*.json).
# app/engine/versions.py maps engine versions to the check types they accept.
TEXT_ENGINE_VERSION = "deterministic-1.0.0"
MAX_TERMS = 25
MAX_TERM_LENGTH = 200
MAX_EVIDENCE = 5

Term = Annotated[str, Field(min_length=1, max_length=MAX_TERM_LENGTH)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_sensitive: bool = False


class RequiredTextCheck(_Base):
    """At least one (match='any') or every (match='all') phrase must appear."""

    type: Literal["required_text"]
    phrases: list[Term] = Field(min_length=1, max_length=MAX_TERMS)
    match: Literal["any", "all"] = "any"


class PhraseGroupsCheck(_Base):
    """Every group must be satisfied by at least one of its phrases."""

    type: Literal["phrase_groups"]
    groups: list[list[Term]] = Field(min_length=1, max_length=10)

    @field_validator("groups")
    @classmethod
    def _non_empty(cls, v: list[list[str]]) -> list[list[str]]:
        if any(len(g) == 0 or len(g) > MAX_TERMS for g in v):
            raise ValueError(f"each group needs 1-{MAX_TERMS} phrases")
        return v


class ProhibitedTermsCheck(_Base):
    """None of the terms should appear. A match needs attention."""

    type: Literal["prohibited_terms"]
    terms: list[Term] = Field(min_length=1, max_length=MAX_TERMS)


class PatternCheck(_Base):
    """Restricted pattern syntax (engine/patterns.py). Raw regex is not accepted."""

    type: Literal["pattern"]
    pattern: str = Field(min_length=1, max_length=200)
    expect: Literal["present", "absent"] = "present"

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            compile_pattern(v)
        except PatternError as exc:
            raise ValueError(str(exc)) from exc
        return v


class MetadataCheck(_Base):
    """Checks explicit document metadata, not document text."""

    type: Literal["metadata"]
    field: Literal["document_type", "tags", "description", "title"]
    equals: str | None = Field(default=None, max_length=200)
    required: bool = True


class ManualCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["manual"]


CheckConfig = Annotated[
    RequiredTextCheck
    | PhraseGroupsCheck
    | ProhibitedTermsCheck
    | PatternCheck
    | MetadataCheck
    | ManualCheck,
    Field(discriminator="type"),
]
_adapter: TypeAdapter[CheckConfig] = TypeAdapter(CheckConfig)


def parse_config(raw: dict[str, Any]) -> CheckConfig:
    return _adapter.validate_python(raw)


class BlockLike(Protocol):
    @property
    def id(self) -> Any: ...
    @property
    def ref(self) -> str: ...
    @property
    def text(self) -> str: ...
    @property
    def page_number(self) -> int | None: ...
    @property
    def paragraph_number(self) -> int | None: ...


@dataclass
class DocumentContext:
    title: str
    description: str
    document_type: str
    tags: list[str]
    blocks: Sequence[BlockLike]


@dataclass
class CheckEvaluation:
    outcome: CheckOutcome
    needs_attention: bool
    message: str
    evidence: list[dict[str, Any]] = field(default_factory=list)


def normalise(text: str, case_sensitive: bool = False) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = " ".join(text.split())
    return text if case_sensitive else text.casefold()


def _evidence(block: BlockLike, start: int, end: int, original: str) -> dict[str, Any]:
    lo = max(0, start - 80)
    hi = min(len(original), end + 80)
    return {
        "block_id": str(block.id),
        "ref": block.ref,
        "page_number": block.page_number,
        "paragraph_number": block.paragraph_number,
        "quote": original[start:end],
        "context": original[lo:hi],
        "highlight_start": start - lo,
        "highlight_end": end - lo,
    }


def _find_phrase(
    phrase: str, blocks: Sequence[BlockLike], case_sensitive: bool
) -> list[dict[str, Any]]:
    """Find a phrase in blocks; evidence offsets refer to whitespace-normalised text."""
    needle = normalise(phrase, case_sensitive)
    hits: list[dict[str, Any]] = []
    for block in blocks:
        shown = " ".join(unicodedata.normalize("NFKC", block.text).split())
        hay = shown if case_sensitive else shown.casefold()
        idx = hay.find(needle)
        if idx >= 0 and len(hay) == len(shown):
            hits.append(_evidence(block, idx, idx + len(needle), shown))
        elif idx >= 0:
            # casefold changed length (rare scripts); cite the whole block
            hits.append(_evidence(block, 0, len(shown), shown))
        if len(hits) >= MAX_EVIDENCE:
            break
    return hits


def evaluate(config: CheckConfig, doc: DocumentContext) -> CheckEvaluation:
    O = CheckOutcome  # noqa: N806, E741
    if isinstance(config, ManualCheck):
        return CheckEvaluation(O.NEEDS_HUMAN_REVIEW, True, "Manual review required.")

    if isinstance(config, RequiredTextCheck):
        found: dict[str, list[dict[str, Any]]] = {
            p: _find_phrase(p, doc.blocks, config.case_sensitive) for p in config.phrases
        }
        present = [p for p, ev in found.items() if ev]
        missing = [p for p, ev in found.items() if not ev]
        evidence = [e for ev in found.values() for e in ev][:MAX_EVIDENCE]
        ok = bool(present) if config.match == "any" else not missing
        if ok:
            return CheckEvaluation(O.MATCH_FOUND, False, f"Found: {', '.join(present)}.", evidence)
        msg = (
            "None of the expected phrases were found."
            if config.match == "any"
            else f"Missing phrase(s): {', '.join(missing)}."
        )
        return CheckEvaluation(O.NO_MATCH_FOUND, True, msg, evidence)

    if isinstance(config, PhraseGroupsCheck):
        evidence = []
        unsatisfied: list[int] = []
        for i, group in enumerate(config.groups, start=1):
            group_hits = [
                e for p in group for e in _find_phrase(p, doc.blocks, config.case_sensitive)
            ]
            if group_hits:
                evidence.extend(group_hits[:2])
            else:
                unsatisfied.append(i)
        if not unsatisfied:
            return CheckEvaluation(
                O.MATCH_FOUND, False, "All phrase groups found.", evidence[:MAX_EVIDENCE]
            )
        return CheckEvaluation(
            O.NO_MATCH_FOUND,
            True,
            f"No phrase found for group(s) {', '.join(map(str, unsatisfied))}.",
            evidence[:MAX_EVIDENCE],
        )

    if isinstance(config, ProhibitedTermsCheck):
        evidence = []
        hit_terms = []
        for term in config.terms:
            hits = _find_phrase(term, doc.blocks, config.case_sensitive)
            if hits:
                hit_terms.append(term)
                evidence.extend(hits)
        if hit_terms:
            return CheckEvaluation(
                O.MATCH_FOUND,
                True,
                f"Prohibited term(s) present: {', '.join(hit_terms)}.",
                evidence[:MAX_EVIDENCE],
            )
        return CheckEvaluation(O.NO_MATCH_FOUND, False, "No prohibited terms found.")

    if isinstance(config, PatternCheck):
        rx = compile_pattern(config.pattern, config.case_sensitive)
        evidence = []
        for block in doc.blocks:
            shown = " ".join(unicodedata.normalize("NFKC", block.text).split())
            m = rx.search(shown)
            if m:
                evidence.append(_evidence(block, m.start(), m.end(), shown))
                if len(evidence) >= MAX_EVIDENCE:
                    break
        if config.expect == "present":
            if evidence:
                return CheckEvaluation(O.MATCH_FOUND, False, "Pattern found.", evidence)
            return CheckEvaluation(O.NO_MATCH_FOUND, True, "Pattern not found.")
        if evidence:
            return CheckEvaluation(
                O.MATCH_FOUND, True, "Pattern found where it should be absent.", evidence
            )
        return CheckEvaluation(O.NO_MATCH_FOUND, False, "Pattern not found, as expected.")

    if isinstance(config, MetadataCheck):
        value: Any = getattr(doc, config.field)
        if config.field == "tags":
            has_value = bool(value)
            is_match = config.equals is None or config.equals.casefold() in {
                t.casefold() for t in value
            }
        else:
            has_value = bool(str(value or "").strip())
            is_match = config.equals is None or str(value).casefold() == config.equals.casefold()
        if has_value and is_match:
            return CheckEvaluation(O.MATCH_FOUND, False, f"Metadata '{config.field}' satisfied.")
        expected = f" (expected '{config.equals}')" if config.equals else ""
        return CheckEvaluation(
            O.NO_MATCH_FOUND,
            config.required,
            f"Metadata '{config.field}' not satisfied{expected}.",
        )

    raise AssertionError("unreachable")  # pragma: no cover
