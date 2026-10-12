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
| File validation, extraction failures | `test_documents.py`, `test_extraction.py` |
| Document versioning, duplicate detection | `test_documents.py` |
| Checklist publishing/versioning | `test_checklists.py` |
| Deterministic checks and pattern safety | `test_engine.py` |
| Job retries, idempotency, cancellation | `test_jobs.py` |
| Reviewer decisions, sign-off, reopen | `test_reviews.py` |
| Audit events | `test_reviews.py`, `test_auth.py` |
| Report permissions and exports, CSV injection | `test_reports.py` |
| Deletion behaviour | `test_documents.py` |
| AI-disabled operation, citation validation, prompt injection fixtures | `test_ai.py` |
| Production config guard | `test_config.py` |
| Arabic/RTL layout | `frontend/src/App.test.tsx` (dir switch), Playwright RTL check |
| Full happy path | `frontend/e2e/happy-path.spec.ts` |

Results of actual runs are recorded in `docs/STATUS.md`, never here.
