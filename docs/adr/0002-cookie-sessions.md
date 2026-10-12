# ADR 0002 — Server-side sessions in HttpOnly cookies, not JWTs

Status: accepted (2026-10-12)

## Decision
Opaque random session tokens stored hashed in PostgreSQL, delivered in an
HttpOnly cookie, with a per-session CSRF token in a header for unsafe methods.

## Why
Immediate revocation on logout/password change, no token in JavaScript-readable
storage, and the active organisation is held server-side so the client cannot
switch tenant by editing a token. Cost: one indexed DB lookup per request.
