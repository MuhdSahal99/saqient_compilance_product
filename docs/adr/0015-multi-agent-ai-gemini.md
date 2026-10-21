# ADR 0015 — Multi-agent AI layer, Gemini first

Status: accepted (2026-10-21)

## Context
Phase F4 listed four AI assists that were set aside: contract → VAT and related-party
suggestions, management letter wording from confirmed findings, plain-language
explanations of findings, and bilingual Q&A grounded only in verified content. The
owner asked for a multi-agent layer using Gemini now, with Falcon on SageMaker later.

## Decision
- **Provider.** `AI_PROVIDER=gemini` calls the Gemini Developer API `generateContent`
  over httpx (no SDK dependency): key in the `x-goog-api-key` header only, fixed
  Google host, JSON response mode, bounded retry on 429/5xx, no redirects. Other
  providers keep the existing OpenAI-compatible adapter, so Groq, OpenRouter, vLLM or a
  SageMaker endpoint behind an OpenAI-compatible gateway need no agent changes.
- **Two model tiers.** Each agent declares `reasoning` or `fast`;
  `AI_MODEL_REASONING` / `AI_MODEL_FAST` pick the model (Gemini defaults
  `gemini-3.8-flash` and `gemini-3.5-flash-lite`, both stable with a free tier).
- **Agents** (`app/ai/agents/definitions.py`): contract analyst, letter drafter and
  verified-content answerer (reasoning); router, finding explainer and checking agent
  (fast). Each has a versioned prompt (`agents-v1`) and a strict Pydantic output.
- **Pipeline per task** (`app/services/ai_tasks.py`): deterministic retrieval →
  specialist → deterministic guards → checking agent → stored draft. Guards: quotes
  through `validate_citations` (unmatched quotes and items without a valid quote are
  dropped), cited ids must be among those supplied, numbers in drafts must appear in
  the evidence, cue labels from a fixed list. The checking agent's verdicts mark drafts
  "not confirmed"; its failure is a warning, not a task failure.
- **Q&A uses verified content only:** rules with `verification_status=verified` in
  published rule pack versions, and requirements of published checklists whose source
  is verified. With nothing relevant, no answering agent runs.
- **Records.** `ai_tasks` (kind, subject, output, warnings, decision) and
  `ai_task_steps` (agent, tier, provider, model, model version, tokens, duration,
  outcome). Prompts and document text are neither stored nor logged.
- **Humans decide.** Every task is a draft; reviewers accept or dismiss it (audited
  with the models used). Only accepted letter wording changes other data: it becomes
  the letter point's recommendation while the engagement is open.
- **Switches unchanged:** deployment flag + provider + org admin opt-in, re-checked
  when the job runs; no fallback between providers.

## Consequences
Gemini is a hosted service outside the region; on its free tier prompts may be used
by Google to improve its products, so the free tier is for synthetic data only and
real client data needs a paid key (or a self-hosted model later). Agents were tested
with a mock and scripted providers; quality on real documents is not yet measured.
