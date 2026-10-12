# Model integration (disabled)

AI is **off**. No user flow calls a model. This document describes the
abstraction that exists and the process required before any model is enabled.

## What exists in code (`backend/app/ai/`)

| Component | Status |
|---|---|
| `DisabledProvider` | Default. Every call raises `AIDisabledError`; callers degrade gracefully. |
| `MockProvider` | Only constructible when `APP_ENV` is `development` or `test`. Output is prefixed `[MOCK — not analysis]`. |
| `OpenAICompatibleProvider` | Chat-completions adapter. Refuses base URLs not in `AI_ALLOWED_HOSTS`. Not exercised against a real endpoint. |
| Jais / Falcon | Reserved values `AI_PROVIDER=jais` / `falcon`. They map to the OpenAI-compatible adapter **only** if `AI_SERVING_INTERFACE_VERIFIED=true`; otherwise startup fails. Placeholders do not mean hosting is configured. |
| `citations.validate_citations` | Validates returned block ids exist in the caller's org and quotes match stored text after normalisation. Tested, including prompt-injection fixtures. |

`GET /api/ai/status` reports `{enabled: false, provider: "disabled"}` by default.

## Configuration

```
AI_ENABLED=false
AI_PROVIDER=disabled          # disabled | mock | openai_compatible | jais | falcon
AI_BASE_URL=
AI_MODEL=
AI_API_KEY=                   # backend only, never sent to the browser
AI_TIMEOUT_SECONDS=30
AI_MAX_INPUT_CHARS=12000
AI_MAX_OUTPUT_TOKENS=800
AI_ALLOWED_HOSTS=             # comma-separated hostnames an admin approved
AI_SERVING_INTERFACE_VERIFIED=false
```

Rules: no user-supplied URLs; no automatic fallback to another provider; AI
failure never breaks deterministic review; sending document text externally
requires `AI_ENABLED=true` plus an allowlisted host; generated suggestions
must record provider, model and version and require human acceptance.

## Citation validation

1. Every cited block id must exist and belong to the requesting organisation.
2. Quotes must appear in the block text after normalisation: Unicode NFKC,
   Arabic tatweel and diacritics removed, whitespace collapsed, case-folded.
3. Invalid citations are returned as `unsupported` and never shown as evidence.
4. Passing validation proves only that the quote exists, not that any legal
   interpretation is correct.
5. Document text is untrusted: instructions inside documents ("ignore previous
   instructions", "reveal other tenants' data") must have no effect. Fixtures
   live in `backend/tests/fixtures/prompt_injection/`.

## Future model evaluation process (before any paid GPU use)

1. Choose an exact model and revision (e.g. a specific Jais or Falcon checkpoint).
2. Verify licence and acceptable-use conditions for commercial use.
3. Verify the serving backend's real API (vLLM, TGI, etc.); do not assume
   OpenAI compatibility.
4. Estimate memory: weights (params × bytes/param), KV cache
   (layers × 2 × hidden × context × batch × bytes), plus runtime overhead.
5. Benchmark latency and quality on synthetic Arabic and English documents.
6. Test grounding (citation validation pass rate) and refusal behaviour,
   including prompt-injection fixtures.
7. Estimate actual cost in the chosen cloud region from current price pages.
8. Get explicit human approval before deploying any paid GPU resource.
