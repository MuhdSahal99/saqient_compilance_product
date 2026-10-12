"""AI provider abstraction. Disabled by default.

Used only by AI-suggested findings (app/services/ai_suggestions.py), which a
reviewer must accept before anything becomes a finding.

See docs/MODEL_INTEGRATION.md before enabling anything here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
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
        """Return a fixed, labelled answer in the suggestion JSON shape.

        It quotes the first few words of the first numbered block in the prompt,
        so the citation check runs against real stored text. It reads nothing
        else and makes no judgement about the document.
        """
        citations = []
        match = _MOCK_BLOCK.search(prompt)
        if match:
            words = match.group(2).split()[:8]
            citations.append({"block": match.group(1), "quote": " ".join(words)})
        body = {
            "assessment": "unclear",
            "summary": MOCK_PREFIX
            + "Placeholder produced by the mock provider for testing the workflow.",
            "citations": citations,
        }
        return Completion(MOCK_PREFIX + json.dumps(body), "mock", "mock", None)


_MOCK_BLOCK = re.compile(r"^\[(B\d+)\] (.+)$", re.MULTILINE)


class OpenAICompatibleProvider:
    """Chat-completions style adapter for an admin-configured, allowlisted endpoint.

    Not exercised against a real endpoint yet. Serving backends differ; verify the
    actual API before enabling (docs/MODEL_INTEGRATION.md).
    """

    def __init__(self, settings: Settings, name: str = "openai_compatible") -> None:
        self.name = name
        host = (urlparse(settings.ai_base_url).hostname or "").lower()
        if (
            not settings.ai_base_url.startswith("https://")
            and host not in ("localhost", "127.0.0.1")
            and not (settings.ai_allow_insecure_http and settings.ai_base_url.startswith("http://"))
        ):
            raise ConfigError(
                "AI_BASE_URL must use https (or http on a private network with "
                "AI_ALLOW_INSECURE_HTTP=true)."
            )
        if not host or host not in settings.ai_allowed_host_list:
            raise ConfigError("AI_BASE_URL host is not in AI_ALLOWED_HOSTS.")
        if not settings.ai_model:
            raise ConfigError("AI_MODEL is required.")
        if settings.ai_auth == "google" and settings.ai_api_key:
            raise ConfigError("Leave AI_API_KEY empty when AI_AUTH=google.")
        self._settings = settings
        self._google = GoogleToken() if settings.ai_auth == "google" else None

    def _headers(self) -> dict[str, str]:
        if self._google is not None:
            return {"Authorization": f"Bearer {self._google.get()}"}
        key = self._settings.ai_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

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
        try:
            headers = self._headers()
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


class GoogleToken:
    """Short-lived Google Cloud access token for Vertex AI, refreshed when it expires.

    Uses Application Default Credentials: on Google Cloud the attached service
    account, elsewhere the key file in GOOGLE_APPLICATION_CREDENTIALS. Needs the
    optional ``vertex`` extra (``uv sync --extra vertex``). Tokens are never logged.
    """

    SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)

    def __init__(self) -> None:
        self._credentials: Any = None

    def get(self) -> str:
        try:
            import google.auth
            import google.auth.transport.requests
        except ImportError as exc:
            raise AIProviderError("AI_AUTH=google needs the 'vertex' extra installed.") from exc
        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=list(self.SCOPES))
        if not self._credentials.valid:
            self._credentials.refresh(google.auth.transport.requests.Request())
        return str(self._credentials.token)


def get_provider(settings: Settings) -> Provider:
    """Return the configured provider. Never falls back to another provider."""
    settings.validate_ai()
    if not settings.ai_enabled or settings.ai_provider == "disabled":
        return DisabledProvider()
    if settings.ai_provider == "mock":
        return MockProvider(settings)
    return OpenAICompatibleProvider(settings, name=settings.ai_provider)
