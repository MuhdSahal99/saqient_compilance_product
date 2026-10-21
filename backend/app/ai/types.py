"""Types shared by the AI providers and agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AIDisabledError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    model_version: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None


class Provider(Protocol):
    name: str

    def complete(
        self, system: str, prompt: str, *, max_tokens: int | None = None
    ) -> Completion: ...
