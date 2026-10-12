# Test plan

| Layer | Tool | Location | Runs against |
|---|---|---|---|
| Backend unit + integration | pytest | `backend/tests` | Real PostgreSQL (`TEST_DATABASE_URL`), Celery tasks invoked eagerly |
| Frontend components | Vitest + Testing Library | `frontend/src/**/*.test.tsx` | jsdom |
| End-to-end | Playwright | `frontend/e2e` | Running API + worker + seeded demo data |
| Static | ruff, mypy, eslint, tsc | CI | — |
| Dependencies | pip-audit, pnpm audit | CI | — |

## Required coverage (maps to the product brief)

| Area | Test file |
|---|---|
| Login/logout, session invalidation, CSRF, rate limit | `test_auth.py` |
| Membership and role enforcement | `test_permissions.py` |
| Cross-tenant denial with guessed UUIDs | `test_tenancy.py` |
| Private downloads | `test_documents.py` |
| File validation, extraction failures | `test_documents.py` |
| Document versioning, duplicate detection | `test_documents.py` |
| Checklist publishing/versioning | `test_checklists.py` |
| Deterministic checks and pattern safety | `test_engine.py` |
| Job retries, idempotency, cancellation | `test_jobs.py` |
| Reviewer decisions, sign-off, reopen | `test_reviews.py` |
| Audit events | `test_reviews.py`, `test_auth.py` |
| Report permissions and exports, CSV injection | `test_reports.py` |
| Deletion behaviour | `test_documents.py` |
| AI-disabled operation, citation validation, prompt injection fixtures | `test_ai_and_config.py` |
| Production config guard | `test_ai_and_config.py` |
| Arabic/RTL layout | `frontend/src/i18n/i18n.test.ts` (key parity, dir switch), Playwright RTL check |
| Login form, badges, evidence highlight, confirm dialog | `frontend/src/pages/LoginPage.test.tsx`, `frontend/src/components/common.test.tsx` |
| Full happy path | `frontend/e2e/happy-path.spec.ts` |

## Running the end-to-end tests

```bash
cd backend && uv run alembic upgrade head && uv run python -m app.seed --reset
uv run uvicorn app.main:app --port 8000 &
uv run celery -A app.worker.celery_app worker -l info -c 2 &
cd ../frontend && pnpm build && pnpm exec vite preview --port 4173 &
pnpm e2e                                   # or E2E_BASE_URL=http://localhost:8080 pnpm e2e against Docker Compose
```

The happy path signs in as the synthetic analyst (upload, start review, cannot
decide) and then as the synthetic reviewer (inspect evidence, confirm, assign,
dismiss with rationale, accept risk, sign off, export HTML/PDF/CSV). Each run
uploads a uniquely suffixed copy of `samples/synthetic-vendor-policy.txt`, so
re-running against the same database works.

Results of actual runs are recorded in `docs/STATUS.md`, never here.
