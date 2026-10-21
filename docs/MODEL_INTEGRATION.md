# Model integration (off by default)

AI is **off** by default. When an administrator turns it on, two features can use a
model: **AI suggestions** on a review, and the **multi-agent AI tasks** below. The
whole application works with no model at all.

## Gemini (recommended for now)

```
AI_ENABLED=true
AI_PROVIDER=gemini
GEMINI_API_KEY=<your key from Google AI Studio>      # never commit it
# optional: AI_MODEL_REASONING=gemini-3.8-flash  AI_MODEL_FAST=gemini-3.5-flash-lite
```

Then restart (`docker compose up -d`), sign in as an org admin, and turn AI on under
Settings. Defaults (checked 2026-10-21 on ai.google.dev): `gemini-3.8-flash` for the
reasoning tier and `gemini-3.5-flash-lite` for the fast tier; both are stable, have a
free tier and have no announced shutdown. `gemini-4-argon` is the flagship but paid
only. Model names change; check the Gemini models and deprecations pages when you
upgrade.

**Free tier warning.** On Gemini's free tier Google may use prompts and responses to
improve its products. Use the free tier with synthetic/demo data only. Real client
documents need a paid (billing-enabled) key and a review of where data is processed,
or a self-hosted model (Falcon/Jais below).

Smoke test after setting the key (one synthetic call per tier, no organisation data):

```
docker compose exec api python -m app.ai.smoke
```

## Multi-agent AI tasks

Each task runs as a background job through several agents (`app/ai/agents/`):

| Task | Agents (tier) | Grounding |
|---|---|---|
| Contract VAT and related-party scan (document) | contract analyst (reasoning) → checking agent (fast) | Every item needs a quote that matches stored block text; cues from a fixed list |
| Plain-language explanation (finding) | finding explainer (fast) → checking agent | Only the finding and its evidence; English and Arabic; stray numbers flagged |
| Letter wording (letter point) | letter drafter (reasoning) → checking agent | Confirmed findings only; stray numbers flagged |
| Question on verified content | router (fast) → answerer (reasoning) → checking agent | Only verified rules and verified-source requirements; ids checked; refuses when nothing verified fits |

After each agent the app checks quotes, cited ids and numbers deterministically; the
checking agent then reads the draft against the evidence. Every task records each
agent call (agent, tier, model, model version, tokens, duration). A reviewer accepts or
dismisses each draft; accepting letter wording copies it into the letter point.

## AI suggestions on a review

1. A writer (analyst, reviewer or admin) clicks *Get AI suggestions* on a review.
2. An `ai_suggest` background job sends one request per checklist requirement:
   the requirement plus the most related document blocks (by shared words, within
   `AI_MAX_INPUT_CHARS`). Blocks are labelled `B1`, `B2`... and fenced as
   untrusted text. The model must answer with strict JSON:
   `{"assessment": "addressed|not_addressed|unclear", "summary": "...", "citations": [{"block": "B3", "quote": "..."}]}`.
3. Each quote goes through `validate_citations`, restricted to the reviewed
   document version. Only matching quotes are kept, and the evidence shown is cut
   from the stored block text, never from model output. Dropped quotes are counted.
   An unreadable answer is stored as `invalid_output` with no evidence.
4. A reviewer (reviewer or admin) accepts a *possible gap* (`not_addressed` or
   `unclear`), which creates a **proposed** finding that still needs a normal
   decision, or dismisses it. Both are audited.
5. Each run records provider, model, prompt version, document version and
   checklist version. Signed-off reports show which findings started as AI
   suggestions and from which model, and the limitations section says so.
6. If the provider fails, the job retries and then fails with a safe message.
   The review, its findings and sign-off are unaffected.

Prompts, responses and document text are never logged; logs carry ids and counts.

### Trying it without a GPU

In development, `AI_ENABLED=true AI_PROVIDER=mock` turns on the mock provider. It
returns a fixed answer labelled `[MOCK — not analysis]` that quotes the first
words of the first block, so the whole pipeline (job, citation checks, accept and
dismiss, reports) runs on a laptop or in CI. Production refuses to start with the
mock, and every screen and report that shows mock output labels it as such.

## What exists in code (`backend/app/ai/`)

| Component | Status |
|---|---|
| `DisabledProvider` | Default. Every call raises `AIDisabledError`; callers degrade gracefully. |
| `MockProvider` | Only constructible when `APP_ENV` is `development` or `test`. Output is prefixed `[MOCK — not analysis]`. |
| `OpenAICompatibleProvider` | Chat-completions adapter (`POST {AI_BASE_URL}/chat/completions`, temperature 0). Refuses base URLs not in `AI_ALLOWED_HOSTS`, and plain http unless `AI_ALLOW_INSECURE_HTTP=true`. **Not yet exercised against a real model server.** |
| Jais / Falcon | Reserved values `AI_PROVIDER=jais` / `falcon`. They map to the OpenAI-compatible adapter **only** if `AI_SERVING_INTERFACE_VERIFIED=true`; otherwise startup fails. Placeholders do not mean hosting is configured. |
| `citations.validate_citations` | Validates returned block ids exist in the caller's org and quotes match stored text after normalisation. Tested, including prompt-injection fixtures. |

`GET /api/ai/status` reports `{enabled: false, provider: "disabled", available_features: []}`
by default, and `available_features: ["review_suggestions"]` when a provider is on.

## Configuration

```
AI_ENABLED=false
AI_PROVIDER=disabled          # disabled | mock | gemini | openai_compatible | jais | falcon
AI_BASE_URL=
AI_MODEL=
AI_API_KEY=                   # backend only, never sent to the browser
AI_AUTH=api_key               # api_key | google (short-lived tokens) | google_api_key
AI_TIMEOUT_SECONDS=30
AI_MAX_INPUT_CHARS=12000
AI_MAX_OUTPUT_TOKENS=800
AI_ALLOWED_HOSTS=             # comma-separated hostnames an admin approved
AI_ALLOW_INSECURE_HTTP=false  # http only to an allowlisted host on a private network
AI_SERVING_INTERFACE_VERIFIED=false
AI_MODEL_REASONING=           # agent tiers; empty = AI_MODEL (or the Gemini defaults)
AI_MODEL_FAST=
AI_MAX_RETRIES=2
GEMINI_API_KEY=               # AI_PROVIDER=gemini; AI_API_KEY also accepted
```

Groq and OpenRouter use `AI_PROVIDER=openai_compatible` with their base URL in
`AI_BASE_URL` and host in `AI_ALLOWED_HOSTS`. Falcon on SageMaker can use the same
adapter behind an OpenAI-compatible gateway once its serving API is verified.

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

## Self-hosting Jais or Falcon with vLLM (optional, not started by default)

`docker-compose.yml` has an `inference` service under the `ai` profile, using the
pinned image `vllm/vllm-openai:v0.31.0` (vLLM is Apache-2.0; the image is free,
the GPU machine is not). It never starts with a plain `docker compose up`, publishes
no port, and needs an NVIDIA GPU host.

Only after steps 1 to 8 above are done and approved:

```
INFERENCE_MODEL=<exact model id and revision, licence checked>
AI_MODEL=local-model
AI_ENABLED=true
AI_PROVIDER=jais                 # or falcon
AI_BASE_URL=http://inference:8000/v1
AI_ALLOWED_HOSTS=inference
AI_ALLOW_INSECURE_HTTP=true      # compose network only
AI_SERVING_INTERFACE_VERIFIED=true   # only after checking the server's real API
docker compose --profile ai up -d
```

Nothing in this repository has been run against a real Jais or Falcon model yet.
Quality, latency, Arabic handling and citation pass rates are unknown until
step 5 and step 6 are done on synthetic documents.

## Using a model deployed on Google Cloud Vertex AI

A Model Garden page is a catalogue entry. A model is only callable after it is
deployed to a Vertex AI endpoint, which runs on a GPU machine billed while it is
up. Get approval before deploying (step 8), and pick a Middle East region if
client documents must stay in the region.

The app signs in with short-lived Google tokens instead of a fixed key:

```
AI_AUTH=google                   # install with: uv sync --extra vertex
                                 # (Docker: build with --build-arg EXTRAS=vertex)
GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/vertex-sa.json   # not needed on Google Cloud
AI_PROVIDER=falcon
AI_MODEL=<served model name>
AI_BASE_URL=https://<REGION>-aiplatform.googleapis.com/v1/projects/<PROJECT>/locations/<REGION>/endpoints/<ENDPOINT_ID>
AI_ALLOWED_HOSTS=<REGION>-aiplatform.googleapis.com
AI_SERVING_INTERFACE_VERIFIED=true   # only after a test call proves the route below works
```

If you have a Google Cloud API key instead of a service account, set
`AI_AUTH=google_api_key` and put the key in `AI_API_KEY`; it is sent as the
`x-goog-api-key` header. Google accepts API keys only for some Vertex AI
endpoints, so confirm with a test call. Restrict the key to the Vertex AI API.

The adapter posts to `AI_BASE_URL + "/chat/completions"`. Whether a given
deployment answers on that route depends on the serving container Google uses
for it; check it with one test call before setting
`AI_SERVING_INTERFACE_VERIFIED=true`. The service account needs only the
*Vertex AI User* role. Its key file is a secret: keep it out of the repository,
chat and logs. This path is tested with a fake token and a fake endpoint only.
