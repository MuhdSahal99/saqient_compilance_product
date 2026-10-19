# Status

Last updated: 2026-10-19 · Phase A is merged into main. Phases B (PR #7), C (PR #8) and D (PR #9) await review. Phase E (assurance) is complete on `feat/phase-e-assurance`, stacked on Phase D.

## Phase E — finance assurance

**Done:** E1 bank reconciliation with deterministic auto-match (`recon-1.0.0`), manual match, proof and ageing; E2 account and intercompany reconciliations with variance thresholds, close checklists as tasks, flux reviews needing explanations; E3 risk-control matrix, design/operating tests on evidence, deficiency classification and remediation tasks, management certification; E4 engine `deterministic-1.5.0` segregation of duties over `user_roles`; E5 AP and expense analytics (duplicates, vendor-employee IBAN match masked, missing TRN, dormant vendors, three-way match, expense policy); E6 read-only connectors (Zoho Books OAuth + PKCE, Odoo API key) with encrypted secrets and idempotent syncs, off by default. All sign-offs independent with immutable snapshots and HTML/PDF/CSV. UI in en/ar (lazy routes); synthetic seed; ADR 0013. Migrations 0025–0031.

**Checks executed (2026-10-19):** ruff + format, mypy (125 files), every migration round-tripped and `alembic check` clean, pytest **373 passed, 2 skipped** (role and tenant 404 tests on every new endpoint, hand-checked matching, SoD and AP cases, connectors against httpx MockTransport only); seed on a fresh database; pnpm lint (0 errors, 8 existing warnings), typecheck, Vitest **55 passed**, build (main chunk 995 kB, translations); Playwright **8 passed**.

**Not executed:** any live Zoho or Odoo account. **Not built:** UI to edit bank rec balances or delete risks/controls (API exists), incremental connector cursors (see KNOWN_LIMITATIONS).

**Next:** review of PRs #7–#9, then the Phase E PR; Phase F (sector packs) per /mnt/project-files/phase-f/PLAN.md.

## Phase D — audit

**Done:** D1 engagements (phases, team, budget vs actual hours, time entries); D2 trial balance → lead schedules with prior year and lead schedule workpapers; D3 materiality workpaper (benchmark, overall, performance, clearly trivial, rationale; pack guidance ranges only); D4 risk register per assertion, procedures, `audit_programme` checklists, coverage; D5 reproducible MUS / random / stratified sampling (`sampling-1.0.0`) with projection; D6 engine `deterministic-1.4.0` journal entry tests incl. Benford; D7 prepare + independent sign-off, confirmations, adjustments and SUD; D8 management letter snapshots from confirmed findings, PBC requests and the `client` role limited to `/api/auth/` and `/api/portal/`. UI in en/ar; synthetic seed (engagement + client user); ADR 0012. Migrations 0019–0024.

**Checks executed (2026-10-19):** ruff + format, mypy (103 files), migrations round-tripped and `alembic check` clean, pytest **350 passed, 2 skipped** (golden files for the new formulas, role and tenant 404 tests on every new endpoint); seed on a fresh database; pnpm lint (0 errors, 8 existing warnings), typecheck, Vitest **45 passed**, build (main chunk 949 kB, over the 900 kB warning limit); Playwright **7 passed**.

**Not built:** UML/reliability factors, a client-entity link, unlinking reviews from procedures in the UI (see KNOWN_LIMITATIONS).

**Next:** review of PRs #7 and #8, then the Phase D PR; then Phase E (assurance).

## Phase C — direct tax

**Done:** `app/calc` explainable formulas (`calc-1.0.0`) with workpapers: inputs with evidence (source blocks, dataset rows, trial balance import), computed lines with steps, rule snapshots and a result hash, sign-off snapshots, reopen to v n+1, HTML/PDF/CSV exports. C1 CT bridge (add-backs, entertainment share, interest limitation with carry-forward, exempt income, related-party, loss cap, rate bands); C2 SBR and QFZP tests; C3 loss register, posting from signed-off papers, loss transfers and dated tax group memberships with a group test; C4 related-party register, documentation thresholds, arm's length ranges, disclosure CSV; C5 Pillar Two (scope, ETR, SBIE, simplified top-up, safe harbours, readiness); C6 zakat base and engine `deterministic-1.3.0` WHT check over a new `wht_payments` dataset kind. UI in en/ar; synthetic seed; ADR 0011. Migrations 0015–0018.

**Checks executed (2026-10-18):** ruff + format, mypy (87 files), migrations upgrade/downgrade/upgrade and `alembic check` clean, pytest **322 passed, 2 skipped** (golden files for all 8 formulas, role and tenant 404 tests on every new endpoint); pnpm lint (0 errors, 8 existing warnings), typecheck, Vitest **37 passed**, build; Playwright **6 passed** against uvicorn + `vite preview` with the seed.

**Not executed / not built:** UI for evidence attachment, trial balance import, loss transfers and tax group memberships (API only, tested); WHT demo seed. No real rates (see KNOWN_LIMITATIONS, TODO questions there).

**Next:** review of PR #7, then the Phase C PR; then Phase D (audit).

## Phase B — e-invoicing and VAT

**Done:** rule packs hold structured `json` rules (shape-checked) and XSD bundles; engine
`deterministic-1.2.0` with e-invoice validation (schema, mandatory fields, code lists,
arithmetic, tax number shape, ZATCA QR, hash and counter chain, duplicates), go-live
readiness from waves, platform rejection matching (CSV or JSON results), master data
(TRN shape, completeness, party cross-check) and VAT return checks (box and GL
reconciliation, reverse charge, zero-rated evidence, blocked input VAT; cut-off and
duplicates reuse 1.1.0 checks); one finding per failure kind (`finding_key`); tax periods
and entity VAT setup; e-invoice store; sampling monitors (Celery beat); tax calendar with
obligation tasks in the daily digest (ADR 0009); VAT review pack sections in HTML/PDF/CSV;
UI in English and Arabic; synthetic demo seed. ADR 0010.

**Checks executed (2026-10-18):** ruff + format, mypy (71 files), migrations 0010–0014
upgrade/downgrade/upgrade and `alembic check` clean, backend pytest **274 passed, 2 skipped**
(golden VAT box/GL values, golden period and due-date tests, tenant 404 and role tests
for every new endpoint, XXE and unsafe ZIP refusal); pnpm lint (0 errors, 8 existing
warnings), typecheck, Vitest **29 passed**, build; Playwright **5 passed** against uvicorn
+ `vite preview` with eager jobs and the demo seed.

**Not executed:** official PINT-AE / ZATCA schemas and the ZATCA SDK (none shipped; hash
method unverified, see KNOWN_LIMITATIONS); a Celery beat process (task tested directly).

**Next:** owner review of the Phase B PR; then Phase C (direct tax), plan in the thread.

## Phase A — finance foundation (PR #6)

**Done:** legal entities and tax groups (TRN encrypted, masked); finance
datasets (TB, GL, sales/purchase registers, bank statements incl. MT940 and
CAMT.053) hashed, versioned and stored as canonical Parquet after a confirmed
column mapping; rule packs (draft → published versions, admin-only rule
verification, unverified-rule warnings in reviews and reports); data checks
under engine `deterministic-1.1.0` (reconcile, threshold, duplicate exact and
fuzzy, field format, date rule, ratio) with row-id evidence and a result hash,
while `deterministic-1.0.0` text checks are unchanged; hash-chained audit log;
invitations, role changes, member removal, password reset and a daily
task-due email digest (Celery beat); optional local Tesseract OCR and ClamAV
scanning, both off by default; UI for all of the above in English and Arabic;
synthetic finance demo seed (entity, ledger, trial balance, `SYNTHETIC` rule
pack, ledger review).

**Checks executed (2026-10-18, this environment):** ruff + format, mypy
(52 files), `alembic check` (no drift), backend pytest **230 passed** on
PostgreSQL 16 (includes the 100k-row GL import under 60 s, golden and
reproducibility tests for every data check, and tenant-isolation tests for
every new endpoint); pnpm lint (0 errors, 8 fast-refresh warnings),
typecheck, Vitest **23 passed**, build; Playwright **4 passed** against
uvicorn + `vite preview` with eager jobs instead of a Celery worker (CI runs
the worker). OCR tests ran against a real `tesseract` 5 install; ClamAV was
tested with an in-process fake clamd speaking INSTREAM.

**Not executed:** a real ClamAV daemon; SMTP delivery to a real server; the
`clamav` compose profile; multi-million-row imports.

**Next:** owner review of PR #6; the next phase is not planned yet. Open question for the
owner: which official sources an admin will cite when verifying the first real
rule pack (no real rules are seeded).

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

## UI/UX redesign (merged into main)

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

## AI suggestions and Vertex AI sign-in (merged into main)

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
