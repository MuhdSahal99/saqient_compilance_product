"""AI provider abstraction. Disabled by default; not used by any user flow yet.

See docs/MODEL_INTEGRATION.md before enabling anything here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from app.config import ConfigError, Settings

MOCK_PREFIX = "[MOCK — not analysis] "


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


class Provider(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> Completion: ...


class DisabledProvider:
    name = "disabled"

    def complete(self, system: str, prompt: str) -> Completion:
        raise AIDisabledError("AI is disabled for this deployment.")


class MockProvider:
    """Development/test only. Output is visibly labelled and never presented as analysis."""

    name = "mock"

    def __init__(self, settings: Settings) -> None:
        if settings.app_env not in ("development", "test"):
            raise ConfigError("MockProvider is only available in development or test.")

    def complete(self, system: str, prompt: str) -> Completion:
        return Completion(MOCK_PREFIX + "This is placeholder text.", "mock", "mock", None)


class OpenAICompatibleProvider:
    """Chat-completions style adapter for an admin-configured, allowlisted endpoint.

    Not exercised against a real endpoint yet. Serving backends differ; verify the
    actual API before enabling (docs/MODEL_INTEGRATION.md).
    """

    def __init__(self, settings: Settings, name: str = "openai_compatible") -> None:
        self.name = name
        host = (urlparse(settings.ai_base_url).hostname or "").lower()
        if not settings.ai_base_url.startswith("https://") and host not in (
            "localhost",
            "127.0.0.1",
        ):
            raise ConfigError("AI_BASE_URL must use https (or localhost for self-hosted dev).")
        if not host or host not in settings.ai_allowed_host_list:
            raise ConfigError("AI_BASE_URL host is not in AI_ALLOWED_HOSTS.")
        if not settings.ai_model:
            raise ConfigError("AI_MODEL is required.")
        self._settings = settings

    def complete(self, system: str, prompt: str) -> Completion:  # pragma: no cover
        import httpx

        s = self._settings
        payload = {
            "model": s.ai_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt[: s.ai_max_input_chars]},
            ],
            "max_tokens": s.ai_max_output_tokens,
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {s.ai_api_key}"} if s.ai_api_key else {}
        try:
            # follow_redirects=False: never let the endpoint bounce us elsewhere.
            resp = httpx.post(
                s.ai_base_url.rstrip("/") + "/chat/completions",
                json=payload,
                headers=headers,
                timeout=s.ai_timeout_seconds,
                follow_redirects=False,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise AIProviderError(f"AI request failed ({type(exc).__name__}).") from exc
        return Completion(text, self.name, data.get("model", s.ai_model), data.get("id"))


def get_provider(settings: Settings) -> Provider:
    """Return the configured provider. Never falls back to another provider."""
    settings.validate_ai()
    if not settings.ai_enabled or settings.ai_provider == "disabled":
        return DisabledProvider()
    if settings.ai_provider == "mock":
        return MockProvider(settings)
    return OpenAICompatibleProvider(settings, name=settings.ai_provider)
