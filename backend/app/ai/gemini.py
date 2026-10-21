"""Gemini Developer API adapter (``generateContent``).

The key is read from settings (GEMINI_API_KEY), sent only in the ``x-goog-api-key``
header to the fixed Google host, and never logged. Prompts and responses are not
logged either; failures carry the error class and HTTP status only.

On the free tier Google may use prompts to improve its products, so the free tier is
for synthetic data only (docs/MODEL_INTEGRATION.md).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.ai.types import AIProviderError, Completion
from app.config import GEMINI_HOST, AITier, ConfigError, Settings

RETRY_STATUSES = {429, 500, 502, 503, 504}
# Gemini counts thinking tokens against maxOutputTokens; leave room for them.
THINKING_HEADROOM = {"reasoning": 4096, "fast": 1024}
THINKING_LEVEL = {"reasoning": "medium", "fast": "low"}


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        tier: AITier = "fast",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not settings.gemini_key:
            raise ConfigError("AI_PROVIDER=gemini requires GEMINI_API_KEY.")
        if not settings.gemini_base_url.startswith(f"https://{GEMINI_HOST}/"):
            raise ConfigError(f"GEMINI_BASE_URL must be on https://{GEMINI_HOST}/.")
        self.tier: AITier = tier
        self.model = settings.ai_model_for(tier)
        self._settings = settings
        self._transport = transport
        self._sleep = time.sleep

    def _body(self, system: str, prompt: str, max_tokens: int | None) -> dict[str, Any]:
        s = self._settings
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt[: s.ai_max_input_chars]}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": (max_tokens or s.ai_max_output_tokens)
                + THINKING_HEADROOM[self.tier],
                "thinkingConfig": {"thinkingLevel": THINKING_LEVEL[self.tier]},
            },
        }

    def complete(self, system: str, prompt: str, *, max_tokens: int | None = None) -> Completion:
        s = self._settings
        url = f"{s.gemini_base_url.rstrip('/')}/models/{self.model}:generateContent"
        headers = {"x-goog-api-key": s.gemini_key, "Content-Type": "application/json"}
        body = self._body(system, prompt, max_tokens)
        attempts = max(1, s.ai_max_retries + 1)
        with httpx.Client(
            transport=self._transport, timeout=s.ai_timeout_seconds, follow_redirects=False
        ) as client:
            for attempt in range(attempts):
                try:
                    resp = client.post(url, json=body, headers=headers)
                except httpx.HTTPError as exc:
                    if attempt + 1 < attempts:
                        self._sleep(2**attempt)
                        continue
                    raise AIProviderError(f"Gemini request failed ({type(exc).__name__}).") from exc
                if resp.status_code in RETRY_STATUSES and attempt + 1 < attempts:
                    self._sleep(_retry_after(resp) or 2**attempt)
                    continue
                if resp.status_code != 200:
                    raise AIProviderError(f"Gemini request failed (HTTP {resp.status_code}).")
                return self._parse(resp)
        raise AIProviderError("Gemini request failed.")  # pragma: no cover

    def _parse(self, resp: httpx.Response) -> Completion:
        try:
            data = resp.json()
            candidate = data["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("Gemini returned an unreadable response.") from exc
        # Thought summaries (if any) are not part of the answer.
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text:
            reason = str(candidate.get("finishReason", "unknown"))[:40]
            raise AIProviderError(f"Gemini returned no text (finish reason {reason}).")
        usage = data.get("usageMetadata") or {}
        return Completion(
            text=text,
            provider=self.name,
            model=self.model,
            model_version=str(data.get("modelVersion") or self.model)[:200],
            input_tokens=_int(usage.get("promptTokenCount")),
            output_tokens=_int(usage.get("candidatesTokenCount")),
        )


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after", "")
    try:
        return min(30.0, float(raw))
    except ValueError:
        return None
