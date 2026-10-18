# Saqient Compliance Workspace — instructions for Claude

## Product purpose and boundaries

Saqient Compliance Workspace is a human-reviewed document review workspace for
audit and compliance teams. The supported workflow is:

upload document → choose a versioned checklist → run deterministic checks →
inspect findings and evidence → assign remediation → reviewer approves or
rejects findings → export a review report.

Boundaries (non-negotiable):

- The product does **not** certify legal or regulatory compliance. Never write
  UI copy, docs or reports that say or imply it does.
- It does **not** claim to support any particular GCC regulation. Only
  checklists whose sources are marked `verified` by an organisation may be
  presented as external regulatory requirements.
- No invented regulations, statutory citations, customers, metrics or results.
- A text match is not proof of compliance; a missing match is not
  automatically a violation. Automated outcomes are never final decisions.
- AI inference (Jais, Falcon or any other model) is **disabled by default**.
  The only AI feature is reviewer-accepted AI suggestions on a review. The core
  application must work with no external AI API.

## Repository structure

```
backend/        FastAPI app, SQLAlchemy models, Alembic migrations, Celery worker, pytest
  app/api/        HTTP routers (one per resource)
  app/services/   business logic (documents, reviews, reports, audit)
  app/engine/     deterministic check engine (no AI, no arbitrary regex)
  app/extraction/ PDF / DOCX / TXT text extraction into source blocks
  app/storage/    storage adapters (local default; S3 / GCS optional)
  app/ai/         provider abstraction (disabled by default) + citation validation
  tests/          integration tests against PostgreSQL
frontend/       React + TypeScript + Vite SPA
  src/components/ui/  vendored shadcn/ui-style components
  src/pages/          one folder/file per primary navigation item
  src/i18n/           English and Arabic resources
  e2e/                Playwright tests
docs/           product, architecture, security, status; docs/adr/ for decisions
```

## Setup and test commands

```bash
# Services (PostgreSQL 16 + Redis 7)
docker compose up -d db redis          # or use native postgres/redis

# Backend
cd backend
uv sync                                # installs from uv.lock
uv run alembic upgrade head
uv run python -m app.seed              # synthetic demo data (DEMO_MODE=true only)
uv run uvicorn app.main:app --reload
uv run celery -A app.worker.celery_app worker -l info
uv run ruff check . && uv run ruff format --check . && uv run mypy app
TEST_DATABASE_URL=postgresql+psycopg://saqient:saqient@localhost:5432/saqient_test uv run pytest

# Frontend
cd frontend
pnpm install --frozen-lockfile
pnpm dev            # http://localhost:5173, proxies /api to :8000
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm e2e            # needs backend + worker running with demo seed
```

## Coding conventions

- Python 3.13, typed (`mypy app` must pass), formatted with ruff.
- SQLAlchemy 2.x typed ORM (`Mapped[...]`). Every schema change ships with an
  Alembic migration. No `Base.metadata.create_all` outside tests.
- Routers stay thin; logic lives in `app/services`. Pydantic schemas in
  `app/schemas.py`.
- Frontend: TypeScript `strict`, no `any` without a comment saying why.
  Server state through TanStack Query; forms through React Hook Form + Zod.
  All user-facing strings go through i18n (`t('...')`) in both `en` and `ar`.
  Use logical CSS properties (`ms-`, `me-`, `ps-`, `pe-`, `start`, `end`) so RTL works.
- Keep unfinished features out of the UI, or visibly labelled "Not available".

## Dependency policy

- Use stable releases only (no alpha/beta/rc as direct dependencies) that have
  been public for at least 7 days.
- Frontend: exact versions in `package.json`; `frontend/pnpm-workspace.yaml`
  sets `minimumReleaseAge: 10080` so pnpm refuses anything newer.
- Backend: `[tool.uv] exclude-newer` in `backend/pyproject.toml` is a fixed
  cutoff date; move it forward deliberately when upgrading, then relock.
- Never take "latest" on the day of install.

## Tenant isolation requirements

- Every tenant-owned table has a non-null `org_id`.
- The active organisation is resolved server-side from the session and
  re-checked against `memberships` on every request. Never trust a client-supplied
  organisation id on its own.
- Every object lookup goes through a helper that filters by `org_id`
  (`get_owned_or_404`). A wrong-tenant id returns 404, never 403, so ids are not
  confirmable across tenants.
- Downloads, exports and reports re-check access.
- Background jobs receive `(object_id, org_id)` and re-verify that the object
  belongs to that org before doing work.
- Any new endpoint needs a cross-tenant test using a guessed/foreign UUID.

## Evidence and citation requirements

- Findings reference stored `source_blocks` by id plus a human-readable ref:
  PDF → page number; DOCX/TXT → paragraph number (never fake page numbers).
- Evidence quotes shown to users must come from stored block text.
- Reports include document version, checklist version, engine version and
  evidence references for each finding.
- Future AI citations must pass `app/ai/citations.py` validation; invalid
  citations are rejected or marked unsupported.

## AI-disabled behaviour

- Defaults: `AI_ENABLED=false`, `AI_PROVIDER=disabled`.
- `MockProvider` only works when `APP_ENV` is `development` or `test`, and its
  output is labelled mock. Never present mock output as analysis.
- No automatic fallback to an external provider. AI failures must never break
  deterministic reviews. AI suggestions require human acceptance.
- Jais/Falcon settings are placeholders; they are not "configured" until the
  serving interface is verified (see docs/MODEL_INTEGRATION.md).

## Rules against invented legal content

- Seeded checklists are synthetic and must carry:
  "Synthetic demonstration content — not legal guidance."
- Do not seed real-looking statute numbers, article citations, regulator names
  as sources, or real organisation/customer names.
- External regulatory requirements may only be entered by users with a source
  record; verification status is set by a human.

## Logging rules

- Never log document contents, extracted text, passwords, session tokens,
  CSRF tokens, reset/invite tokens, API keys or full request bodies.
- Log ids, sizes, counts, durations and error classes instead.
- Development email (tokens) goes to the console mail sink only when
  `APP_ENV=development`; production must use a real mailer and never print tokens.

## Definition of done (per change)

1. Code + migration + tests for the behaviour, including permission and
   cross-tenant cases for new endpoints.
2. `ruff`, `mypy`, `pytest`, `pnpm lint`, `pnpm typecheck`, `pnpm test`,
   `pnpm build` run; results reported honestly. Anything not executed is
   recorded as **not executed** with the reason.
3. No secrets, real customer data or real personal data committed.
4. Docs touched by the change are updated (keep them short and accurate).
5. `docs/STATUS.md` updated after each milestone: completed work, tests actually

# Saqient: Project Instructions

## Mission
Extend Saqient from a document compliance review workspace into the leading GCC
finance compliance, tax and audit assurance layer. Saqient CHECKS and EVIDENCES
finance work done in the client's own systems (ERP, accounting, invoicing). It does
NOT become an ERP, does NOT file returns with FTA/ZATCA, and does NOT act as an
e-invoicing ASP. It never certifies compliance; it produces evidence-linked
findings that qualified humans decide on.

## Existing system (do not break)
- Backend: FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, Celery + Redis.
- Frontend: React 19, TypeScript strict, Vite, Tailwind 4, TanStack Query,
  React Hook Form + Zod, i18next (English + Arabic, RTL).
- Core pipeline to REUSE for every new module:
  evidence -> versioned checklist -> deterministic check -> proposed finding ->
  human decision (rationale required) -> remediation task -> sign-off ->
  immutable report snapshot -> HTML/PDF/CSV export.
- Invariants: every tenant table has org_id; cross-tenant access returns 404;
  published checklist versions are immutable; snapshots are immutable;
  reopen requires a reason and creates version n+1; every state change writes
  an audit event; AI output is optional, labelled, citation-validated, and never
  auto-confirmed.
- Source of truth docs: docs/PRODUCT_SPEC.md, docs/ARCHITECTURE.md,
  docs/DATA_MODEL.md, docs/STATUS.md, docs/KNOWN_LIMITATIONS.md, docs/adr/.

## Working rules (token efficiency)
1. Before coding, read ONLY: this file, docs/STATUS.md, and the files directly
   relevant to the current task. Do not read the whole repo. Use search
   (rg / grep / glob) to locate code instead of opening many files.
2. Do not re-read a file you already read in this session unless it changed.
3. Plan first: write a short plan (max ~15 bullets) and wait for my "go"
   before large changes. For small, clearly scoped tasks, proceed directly.
4. Work in small vertical slices: model -> migration -> service -> API ->
   tests -> minimal UI wiring. One slice per commit.
5. Make targeted edits; never rewrite whole files to change a few lines.
6. Do not paste large file contents, logs or diffs into chat; summarise and
   reference paths/line numbers. Show only failing test output, trimmed.
7. Run the narrowest test set first (single test file), full suite before commit.
8. At the end of every session update docs/STATUS.md (done / next / blockers)
   in <= 20 lines so the next session starts without re-discovery.
9. If requirements are ambiguous, ask ONE concise question instead of guessing
   across many files.
10. Do not add dependencies without stating why and checking licence + maintenance.

## Security and safety rules (non-negotiable)
- Never commit secrets. Config via environment variables only; update
  .env.example with placeholders. Production guard must still refuse demo
  mode and default secrets.
- Every new table: org_id NOT NULL, indexed, enforced in every query through the
  existing tenant-scoping helper. Add a cross-tenant 404 test for every new
  endpoint.
- Authorisation: enforce existing roles (org admin, reviewer, analyst, viewer)
  server-side on every endpoint; add a permission test per role.
- Money: use Decimal / NUMERIC(20,4) everywhere. Never float. Store currency
  code (ISO 4217) with every amount. Explicit rounding rules per jurisdiction.
- Dates: store UTC; fiscal periods and tax periods are explicit entities;
  respect entity fiscal year and time zone (Asia/Dubai, Asia/Riyadh).
- File/data import: validate extension, MIME, signature, size, row count,
  column schema; reject macros and formulas; neutralise CSV formula injection
  on export; hash every imported dataset (SHA-256) and version it.
- No raw SQL string concatenation; parameterised queries only. No user-written
  regex; use RE2 and predefined patterns.
- Parse XML safely (defusedxml); no external entity resolution.
- Sensitive fields (IBAN, salary, national ID, TRN where required): encrypt at
  field level, mask in UI and logs, never log them.
- Audit events must be appended to a hash-chained log (implement in Phase A).
- Migrations must be reversible (upgrade + downgrade) and tested.
- AI features: off by default, in-region / self-hosted provider allowed,
  quotes validated against stored evidence, model + version recorded,
  never send data to an external model unless the org has explicitly enabled it.

## Domain accuracy rules (tax, audit, regulatory)
- NEVER hardcode tax rates, thresholds or deadlines in code. Put them in
  versioned "rule packs" (data, not code) with: jurisdiction, rule id, value,
  effective_from, effective_to, official source URL, verification status
  (draft | verified), verified_by, verified_at.
- Seed rule packs as status=draft. Only humans set verified. The UI and reports
  must show a clear "unverified rule" warning when a draft rule is used.
- Every calculation must be explainable: store inputs, rule pack version,
  formula id and output, so a reviewer can reproduce it.
- Deterministic first, AI second. Every finding must link to evidence:
  document source block OR dataset version + row ids + column values.
- If unsure about a regulatory detail, leave a TODO with the question and mark
  the rule draft. Do not invent regulations.

## Quality gates (before every commit)
- ruff/black (or project linters) clean, mypy/tsc strict clean.
- New code has unit tests; services have integration tests; each new endpoint
  has auth, tenant-isolation and validation tests.
- Calculations have golden-file tests with hand-checked expected values.
- CI green. Conventional commit messages. One feature branch per phase:
  feat/phase-<letter>-<slug>. Never push to main directly.
- Add or update an ADR in docs/adr/ for any significant design decision.

## UI rule
- For any UI/visual work, use the separately provided UI skills (taste,
  impeccable). Follow existing component patterns, i18n keys for ALL strings
  (en + ar), RTL-safe layouts, accessible forms. Do not invent a new design
  system.

## Definition of done (per feature)
Backend + migration + tests + API docs (OpenAPI descriptions) + i18n strings +
minimal UI via UI skills + STATUS.md updated + demo seed data (synthetic only).
   executed, failures/blockers, remaining work, exact next milestone.

Do not claim a feature works unless it was tested. Do not provision cloud
resources, deploy, or upload data externally without explicit human approval.
