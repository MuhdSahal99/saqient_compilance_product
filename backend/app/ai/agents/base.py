"""Agent framework: one agent = a model tier, a prompt and a strict JSON output schema.

``run_agent`` calls the provider for the agent's tier, parses the answer into the
agent's Pydantic schema and returns it with a step record (agent, model, model
version, tokens, duration, outcome). It never stores or logs prompts or answers.

The deterministic guards below run after every agent: model output is never trusted
to cite only what it was given, or to use only numbers that appear in the evidence.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app import ai
from app.config import AITier, Settings

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Agent(Generic[T]):
    name: str
    tier: AITier
    schema_name: str
    system: str
    output: type[T]
    max_tokens: int = 800

    def system_prompt(self) -> str:
        # The schema line lets the development mock answer in the right shape.
        return f"{self.system}\n\nOutput schema: {self.schema_name}"


@dataclass
class StepRecord:
    agent: str
    tier: str
    provider: str
    model: str
    model_version: str
    status: str  # ok | invalid_output | provider_error
    duration_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    note: str = ""


@dataclass
class AgentResult(Generic[T]):
    value: T | None
    step: StepRecord
    warnings: list[str] = field(default_factory=list)


def parse_json(text: str, schema: type[T]) -> T | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return schema.model_validate(json.loads(text[start : end + 1]))
    except (ValueError, PydanticValidationError):
        return None


def run_agent(settings: Settings, agent: Agent[T], prompt: str) -> AgentResult[T]:
    provider = ai.get_provider(settings, agent.tier)
    model = getattr(provider, "model", "") or provider.name
    started = time.monotonic()
    try:
        completion = provider.complete(agent.system_prompt(), prompt, max_tokens=agent.max_tokens)
    except ai.AIProviderError as exc:
        return AgentResult(
            None,
            StepRecord(
                agent.name,
                agent.tier,
                provider.name,
                model,
                "",
                "provider_error",
                _ms(started),
                note=str(exc)[:300],
            ),
        )
    value = parse_json(completion.text, agent.output)
    return AgentResult(
        value,
        StepRecord(
            agent.name,
            agent.tier,
            completion.provider,
            completion.model or model,
            completion.model_version or "",
            "ok" if value is not None else "invalid_output",
            _ms(started),
            completion.input_tokens,
            completion.output_tokens,
            "" if value is not None else "The answer did not match the expected JSON shape.",
        ),
    )


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


# ---------------------------------------------------------------- deterministic guards

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Small whole numbers (list positions, "two steps", months) are not treated as facts.
SMALL_NUMBER_LIMIT = 12


def _digits(text: str) -> str:
    # NFKC maps Arabic-Indic and other digit forms to ASCII.
    return "".join(
        str(unicodedata.digit(ch)) if ch.isdigit() else ch
        for ch in unicodedata.normalize("NFKC", text)
    )


def numbers_in(text: str) -> set[str]:
    """Numbers in ``text``, normalised: thousands separators and trailing decimal zeros
    dropped, so 1,000.50 and 1000.5000 compare equal."""
    found: set[str] = set()
    for raw in _NUMBER.findall(_digits(text)):
        n = raw.replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        found.add(n)
    return found


def ungrounded_numbers(draft: str, evidence: str) -> list[str]:
    """Numbers in a draft that appear nowhere in the evidence it was given."""
    allowed = numbers_in(evidence)
    out: list[str] = []
    for n in sorted(numbers_in(draft)):
        if n in allowed:
            continue
        if n.isdigit() and int(n) <= SMALL_NUMBER_LIMIT:
            continue
        out.append(n)
    return out


def known_ids(cited: list[str], allowed: set[str]) -> tuple[list[str], int]:
    """Keep cited ids that were in the input; return them and how many were dropped."""
    kept: list[str] = []
    for c in cited:
        c = c.strip()
        if c in allowed and c not in kept:
            kept.append(c)
    return kept, len([c for c in cited if c.strip() not in allowed])


def fence(label: str, text: str) -> str:
    """Wrap untrusted text so the prompt makes clear it is data, not instructions."""
    clean = text.replace("<<<", "‹‹‹").replace(">>>", "›››")
    return f"<<<{label}\n{clean}\n{label}>>>"
