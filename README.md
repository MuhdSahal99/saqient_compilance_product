# Saqient Compliance Workspace

A human-reviewed document review workspace for audit and compliance teams.

Upload a document → choose a versioned checklist → run deterministic checks →
inspect findings beside the evidence → assign remediation → a reviewer
confirms or dismisses findings and signs off → export a report (HTML, PDF, CSV).

> Saqient supports human review. It does not provide legal advice or certify
> legal or regulatory compliance. AI inference is disabled; the application
> works without any external AI service. Demo data is synthetic demonstration
> content, not legal guidance.

Status: Phase 1 (vertical slice). See [docs/STATUS.md](docs/STATUS.md) for what
was tested and [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for what
is missing.

## Quick start (Docker Compose)

```bash
docker compose up -d --build
docker compose exec api python -m app.seed --reset
```

Open http://localhost:8080 and sign in as `reviewer@alpha.example` with
`Demo-Password-2026!`. Demo accounts only work while `DEMO_MODE=true`; the API
refuses to start in production with demo mode or default secrets.
Synthetic sample files are in [`samples/`](samples/).

## Local development

Requirements: Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22 with
pnpm 10, PostgreSQL 16, Redis 7 (or `docker compose up -d db redis`).

```bash
cp .env.example backend/.env

cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.seed --reset
uv run uvicorn app.main:app --reload            # :8000
uv run celery -A app.worker.celery_app worker -l info

cd ../frontend
pnpm install
pnpm dev                                        # :5173, proxies /api to :8000
```

## Checks

```bash
cd backend  && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
cd frontend && pnpm e2e        # needs API, worker, `vite preview` on :4173 and seeded data
```

CI runs all of the above plus dependency audits and a compose build
([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Stack

FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL, Celery + Redis, RE2 for
restricted patterns · React 19, TypeScript (strict), Vite, Tailwind CSS 4,
shadcn/ui-style components, React Router, TanStack Query, React Hook Form + Zod,
Recharts, i18next (English and Arabic with RTL) · Vitest, Testing Library,
Playwright, pytest.

## Documentation

| | |
|---|---|
| [Product spec](docs/PRODUCT_SPEC.md) | Problem, users, roles, scope |
| [Architecture](docs/ARCHITECTURE.md) · [Data model](docs/DATA_MODEL.md) | How it fits together |
| [Security](docs/SECURITY.md) · [Threat model](docs/THREAT_MODEL.md) | Controls and risks |
| [Model integration](docs/MODEL_INTEGRATION.md) | Why AI is off and how it could be enabled |
| [Deployment](docs/DEPLOYMENT.md) | Compose, production settings, backups, hosting options |
| [Test plan](docs/TEST_PLAN.md) · [Status](docs/STATUS.md) | What is tested and what ran |
| [Demo script](docs/DEMO_SCRIPT.md) · [Known limitations](docs/KNOWN_LIMITATIONS.md) | |
| [Implementation plan](docs/IMPLEMENTATION_PLAN.md) · [ADRs](docs/adr/) | Phases and decisions |
