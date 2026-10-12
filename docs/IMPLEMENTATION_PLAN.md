# Implementation plan

Each phase ends with checks run and `docs/STATUS.md` updated. A phase is not
started until the previous phase's acceptance criteria pass (or failures are
explicitly recorded).

## Phase 0 — documentation and scaffolding
- CLAUDE.md files, docs, ADRs, `.env.example`, `.gitignore`, Docker Compose, CI.
- Acceptance: repo layout matches CLAUDE.md; lockfiles committed.

## Phase 1 — minimal vertical slice
- Auth: login, logout, session invalidation, CSRF, login rate limit.
- Organisations + memberships + 4 roles with server-side enforcement
  (needed for tenant isolation from day one).
- Upload (PDF/DOCX/TXT) with validation, private storage, hashing, duplicate
  detection; Celery extraction into source blocks; retry.
- One synthetic published checklist (seeded per demo organisation).
- Deterministic engine + review runs as background jobs with cancel/retry.
- Findings with evidence; confirm/dismiss/accepted-risk decisions; remediation
  owner + due date; reviewer sign-off creating a report snapshot.
- Report export: printable HTML, PDF, CSV (formula-injection safe).
- UI: all nine navigation items backed by real endpoints (minimal where needed).
- Tests: backend integration (PostgreSQL), frontend components, Playwright
  happy path.
- Acceptance: critical Playwright flow passes locally.

## Phase 2 — versions, collaboration, workflow depth
- Document versions upload UI; checklist authoring (draft → publish → new draft).
- Source library CRUD with verification status.
- Invitations and password reset with expiring tokens (dev mail sink).
- Comments, bulk assignment, manual findings UI, full finding workflow
  (remediation in progress → ready for re-review → resolved), reopen with reason.

## Phase 3 — dashboard and polish
- Richer dashboard (coverage defined as "The proportion of checklist items reviewed.").
- Audit history filters, Arabic/RTL review pass, optional local OCR
  (Tesseract) with extraction warnings, better failure handling.

## Phase 4 — hardening and deployment planning
- Security review, dependency scanning, header/CSP tuning, backup/restore
  drill, cloud deployment plan with cost review (no provisioning).

## Phase 5 — optional backlog (only after Phase 4 acceptance)
Local semantic retrieval, grounded Q&A, MFA, SSO, approved regulatory-source
ingestion, notifications, integrations, checklist/document comparison, model
evaluation harness. None appear in the UI until implemented and tested.
