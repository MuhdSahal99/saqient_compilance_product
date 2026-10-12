# Architecture

```
Browser (React SPA, en/ar, RTL)
   │  same-origin /api (Vite proxy in dev, reverse proxy in prod)
   ▼
FastAPI (uvicorn) ── PostgreSQL 16  (all state, tenant rows carry org_id)
   │   │
   │   └── Storage adapter ── local private dir (default) | S3-compatible | GCS (optional)
   │
   └── Celery (Redis broker) ── worker: extraction jobs, review-run jobs
```

## Components

- **Frontend** (`frontend/`): React 19 + TypeScript strict, Vite, Tailwind v4,
  vendored shadcn/ui-style components (Radix primitives), React Router,
  TanStack Query, React Hook Form + Zod, Recharts, i18next.
- **API** (`backend/app`): FastAPI + Pydantic v2, SQLAlchemy 2 (psycopg 3),
  Alembic migrations.
- **Worker**: Celery 5 with Redis broker. Tasks: `process_document_version`,
  `run_review`. Both take `(id, org_id)`, re-verify tenant ownership, are
  idempotent, have soft/hard time limits and bounded retries.
- **Storage**: `StorageAdapter` interface (`put`, `open`, `delete`). Keys are
  generated (`{org_id}/{uuid}`), never derived from user filenames.
- **AI**: `app/ai/providers.py` — `DisabledProvider` (default), `MockProvider`
  (dev/test only), `OpenAICompatibleProvider` (allowlisted admin-configured
  base URL). Not wired into any user flow in the MVP.

## Authentication and sessions

- Email + password; Argon2id hashing (`argon2-cffi`).
- Opaque random session token in an `HttpOnly`, `SameSite=Lax` cookie
  (`Secure` outside development). Only a SHA-256 hash of the token is stored.
- Sessions expire (idle and absolute), are revoked on logout, and all of a
  user's sessions are revoked on password change.
- CSRF: per-session token returned at login, sent back in `X-CSRF-Token` for
  unsafe methods, compared in constant time.
- Login rate limiting per IP + email (Redis when available, in-memory fallback).

## Tenancy

The session stores the active `org_id`; every request re-loads the
`Membership(user, org)` and fails closed if it no longer exists. Repositories
filter by `org_id`; cross-tenant ids return 404.

## Review engine

Deterministic, versioned (`ENGINE_VERSION`). Requirement check configs are
validated Pydantic models (required text, phrase groups, prohibited terms,
restricted pattern, metadata, manual). Patterns use a restricted token syntax
compiled to bounded regular expressions — users never supply raw regex. The run
stores a configuration snapshot, timestamps, warnings, and per-requirement
results with evidence block ids. Results and findings are written in a single
transaction, with unique constraints `(run_id, requirement_id)` and
`(review_id, requirement_id)` so retries cannot duplicate findings.

## Reports

Sign-off freezes a JSON snapshot (`report_snapshots`, version n). HTML, PDF
(ReportLab) and CSV renderers read only from a snapshot (or a clearly marked
draft preview). Reopening a review records a reason; the next sign-off creates
version n+1. Earlier versions remain downloadable.

## Decisions

See `docs/adr/`. New frameworks or services require an ADR.
