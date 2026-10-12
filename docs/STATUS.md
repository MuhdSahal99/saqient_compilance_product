# Status

Last updated: 2026-10-12 · Phase 1 (vertical slice) complete, pending review.

## Completed

**Phase 0:** CLAUDE.md files, product/architecture/security/threat/test/model
docs, ADRs 0001–0005, `.env.example`, `.gitignore`, lockfiles (`uv.lock`,
`pnpm-lock.yaml`), Docker Compose, Dockerfiles, CI workflow.

**Phase 1 (all wired to real endpoints):**
- Cookie sessions (opaque token, SHA-256 at rest), CSRF header, Argon2id,
  login rate limit, idle/absolute expiry, password change revokes other
  sessions, organisation switching, demo users blocked unless `DEMO_MODE=true`,
  production config guard.
- Four roles enforced server-side; tenant isolation on every lookup (404 across tenants).
- Upload PDF/DOCX/TXT with extension + MIME + signature checks, size/page/char
  limits, DOCX macro and zip-bomb rejection, SHA-256 duplicate detection,
  document versions, private local storage, private download, deletion.
- Background extraction (Celery) into source blocks with page (PDF) or
  paragraph refs; clear failure for scanned PDFs; retry and cancel.
- Synthetic published checklist (8 requirements, labelled "Synthetic
  demonstration content — not legal guidance."); checklist versioning API.
- Deterministic engine `deterministic-1.0.0` (RE2-backed restricted patterns),
  review runs as jobs, findings with stored-text evidence.
- Reviewer decisions (confirm / dismiss / accept risk with rationale),
  remediation owner + due date, bulk assign, remediation status flow,
  manual findings, comments, sign-off with immutable report snapshots,
  reopen with reason (next sign-off = new version).
- Exports: HTML (escaped, CSP), PDF, CSV (formula-injection safe).
- Audit events with filters; dashboard with operational counts and coverage
  ("The proportion of checklist items reviewed.").
- UI: all nine navigation items, loading/empty/error states, English and
  Arabic with RTL, demo banner and synthetic labels.

Items from the Phase 2 list already delivered here: document version upload
UI, comments, bulk assignment, manual findings, full remediation workflow,
reopen with reason.

## Checks actually executed (2026-10-12, this environment)

| Check | Command | Result |
|---|---|---|
| Backend lint | `uv run ruff check .` / `ruff format --check .` | Pass |
| Backend types | `uv run mypy app` | Pass (29 files) |
| Backend tests (PostgreSQL 16) | `uv run pytest` | **83 passed** |
| Migration drift | `uv run alembic check` | No changes |
| Python dependency audit | `uvx pip-audit -r <uv export> --strict` | No known vulnerabilities |
| Frontend lint | `pnpm lint` | 0 errors, 7 warnings (react-refresh export hints) |
| Frontend types | `pnpm typecheck` | Pass |
| Frontend unit tests | `pnpm test` (Vitest) | **12 passed** |
| Frontend build | `pnpm build` | Pass (4 chunks, largest 435 KB) |
| npm dependency audit | `pnpm audit --prod --audit-level high` | No known vulnerabilities |
| E2E against local processes | `pnpm e2e` (uvicorn + Celery worker + `vite preview`) | **3 passed** (happy path, Arabic RTL, auth redirect) |
| E2E against Docker Compose | `E2E_BASE_URL=http://localhost:8080 pnpm e2e` | **3 passed** |
| Compose health | `curl /api/health/ready` through nginx | ok (database ok, redis ok) |
| Production guard in container | `APP_ENV=production … validate_for_production()` | Refused: default secret, demo mode, insecure cookie |
| GitHub Actions CI (PR #1, commit 2e89ffd) | backend, frontend, e2e, compose jobs | All 4 green |
| Backup/restore drill | `pg_dump -Fc` → `pg_restore` into a new DB; `tar` of storage volume | Restored rows present; archive readable |

Note on the Compose run: this sandbox blocks container registries other than
Docker Hub and requires a proxy CA, so the images were built from local copies
of the Dockerfiles with the proxy CA added in the build stage only. The
committed Dockerfiles were not built unmodified here; CI builds them as-is.

## Not executed

- S3 and GCS storage adapters against real buckets.
- Browsers other than Chromium; screen-reader testing.
- Load/performance testing.

## Bugs found by the end-to-end run and CI, and fixed

- The first CI run found `backend/app/storage/` missing from the repository:
  an unanchored `storage/` rule in `.gitignore` hid it. Rules are now anchored.

- After login the app returned to the login page: clearing the whole query
  cache detached the session observer. Fixed in `src/lib/auth.tsx`; unit
  regression test added.
- `GET /api/documents?status=ready` returned 500 (auto-correlated aggregate
  subquery). Fixed with an alias; backend regression test added.
- Reviews table header showed a toast message. Fixed.
- nginx dropped security headers in locations that set `Cache-Control`. Fixed
  with an included header snippet.

## Failures / blockers

None open. Lint warnings are fast-refresh hints only.

## Remaining work

See docs/IMPLEMENTATION_PLAN.md and docs/KNOWN_LIMITATIONS.md. Main gaps:
checklist authoring UI, source library UI, invitations and password reset,
member management, notifications, OCR, malware scanning, route-level code
splitting.

## Next milestone

**Phase 2 — authoring and membership:** checklist authoring UI (draft → edit
requirements → publish) on the existing tested API; source library with
verification status; invitations and password reset with expiring tokens and
a development mail sink; member management for org admins. Acceptance: each
with backend permission and cross-tenant tests, component tests, and a
Playwright flow that authors and publishes a checklist and runs a review on it.

## UI/UX redesign (branch ui-redesign)

- New design system: Inter + IBM Plex Sans Arabic (bundled via @fontsource), refreshed palette, shadows,
  animations, skeleton loaders, dot status badges, severity glyphs, progress ring.
- New app shell: grouped, collapsible sidebar with counts, org switcher, top bar, command palette (Ctrl K, "/"),
  mobile drawer.
- Redesigned login (split screen), overview (stat cards, "needs a decision" queue, severity donut, coverage
  rings, recent activity) and review workspace (progress stepper, decision summary, findings list with
  j/k navigation, evidence and document side by side).
- Restyled documents (drag-and-drop upload), checklists, reviews, findings (floating bulk-assign bar), tasks,
  reports, activity (timeline) and settings.
- Tests run: eslint (0 errors), tsc, vitest 12/12, vite build, Playwright e2e 3/3 against the dev server.

## AI suggestions (branch ai-suggestions)

- Added: `ai_suggest` job, `ai_suggestion_runs` / `ai_suggestions` tables
  (migration 0002), mock provider that returns labelled JSON, citation checks on
  every quote, accept (creates a proposed finding) and dismiss endpoints with
  audit events, AI origin in HTML/PDF/CSV reports, an *AI suggestions* tab
  shown only when a provider is on, an AI badge on findings, en/ar strings, and
  an optional `inference` (vLLM v0.31.0) compose service under the `ai` profile.
- Executed: ruff, ruff format, mypy, `alembic upgrade/downgrade/upgrade`,
  `alembic check`, full pytest (8 new AI tests), pnpm lint, typecheck, test,
  build; manual browser run with the mock provider (desktop and 390px).
- Not executed: any real model (no GPU, by design); `docker compose --profile ai up`.
- Next: pick an exact Jais or Falcon checkpoint, check its licence, and run the
  evaluation steps in docs/MODEL_INTEGRATION.md on approved GPU time.
