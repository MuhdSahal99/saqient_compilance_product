# ADR 0001 — Monorepo with FastAPI backend and React SPA

Status: accepted (2026-10-12)

## Context
The brief fixes the stack: React/TypeScript/Vite frontend, FastAPI/SQLAlchemy/
Alembic/PostgreSQL backend, Celery + Redis jobs. One small team, one repo.

## Decision
Single repository with `backend/` and `frontend/`, shared `docs/`, one CI
workflow. Python dependencies managed with `uv` (`uv.lock` committed);
frontend with `pnpm` (`pnpm-lock.yaml` committed). Versions pinned to stable
majors known to work together (React 19, Vite 7, TypeScript 5.9, Tailwind 4,
FastAPI, SQLAlchemy 2.x, Pydantic 2, Celery 5).

TypeScript 7 (native compiler) and Vite 8 were available but not chosen: tooling
compatibility (typescript-eslint, vitest) is less proven.

## Consequences
Two toolchains in CI. No second web framework or service may be added without
an ADR.
