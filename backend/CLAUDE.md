# Backend instructions

Read the root `CLAUDE.md` first. This file adds backend specifics.

## Layout

- `app/main.py` — app factory, middleware (security headers, CORS, CSRF), routers.
- `app/config.py` — `Settings` (pydantic-settings). `validate_for_production()`
  refuses insecure defaults (demo mode, default secret, AI misconfiguration).
- `app/models.py` — all ORM models. Every tenant-owned model has `org_id`.
- `app/deps.py` — `current_context` (user + membership + org from the session),
  `require_role(...)`, CSRF check.
- `app/services/` — business logic; routers call services.
- `app/engine/` — deterministic checks. Configs are validated Pydantic models;
  patterns use the restricted syntax in `engine/patterns.py`, never raw regex
  from users.
- `app/extraction/` — returns `ExtractedBlock`s with page (PDF only) or
  paragraph refs.
- `app/worker.py` — Celery app and tasks. Tasks take `(id, org_id)` and are
  idempotent; results are written in one transaction.
- `alembic/versions/` — migrations. Autogenerate, then read and fix the output.

## Rules

- Use `get_owned_or_404(session, Model, id, org_id)` for every lookup by id.
- Return 404 for objects in other tenants.
- Role checks happen server-side via `require_role`; the frontend hiding a
  button is not a permission check.
- Write an `AuditEvent` (`services/audit.py: record`) for every state change a
  reviewer or admin would care about. Metadata must not include document text.
- Never log extracted text or tokens. Use `logger.info("...", extra={...})`
  with ids and counts only.
- Errors returned to clients use `{"detail": "..."}` with safe messages. No
  stack traces, storage paths or SQL in responses.

## Tests

- Tests run against a real PostgreSQL database (`TEST_DATABASE_URL`). The test
  suite creates the schema with Alembic migrations, and truncates tables
  between tests.
- Celery tasks are exercised by calling the task functions directly
  (`task.apply()` in eager mode) — no broker needed in tests.
- Every new endpoint: happy path, role denial, cross-tenant 404.
