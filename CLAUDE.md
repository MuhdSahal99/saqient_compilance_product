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
- AI inference (Jais, Falcon or any other model) is **disabled**. The core
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
   executed, failures/blockers, remaining work, exact next milestone.

Do not claim a feature works unless it was tested. Do not provision cloud
resources, deploy, or upload data externally without explicit human approval.
