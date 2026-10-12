# Security controls

This lists controls that are implemented. Gaps are in KNOWN_LIMITATIONS.md.
Nothing here claims certification, legal compliance, zero leakage or
production readiness.

| Area | Control |
|---|---|
| Passwords | Argon2id via `argon2-cffi`; minimum length 12 for new passwords |
| Sessions | Random 256-bit token, only SHA-256 hash stored; HttpOnly, SameSite=Lax, Secure outside dev; idle + absolute expiry; logout revokes |
| CSRF | Per-session token required in `X-CSRF-Token` on unsafe methods |
| Rate limiting | Login attempts limited per IP+email (Redis or in-memory fallback) |
| Tenancy | Server-side membership resolution each request; `org_id` filter on every lookup; 404 across tenants |
| Authorisation | Role checks in API dependencies, not only in the UI |
| Uploads | Extension + declared MIME + file signature; DOCX zip structure and uncompressed-size check; size and page limits; generated storage keys; original filename stored as metadata only |
| Processing | Documents treated as untrusted; Celery soft/hard time limits; char/block limits |
| Engine | No user regex; restricted pattern syntax with bounded quantifiers; config validation and size limits |
| Downloads | Streamed through the API after access checks; storage paths never returned |
| CSV export | Cells beginning with `= + - @ \t \r` prefixed with `'` |
| Headers | CSP, X-Content-Type-Options, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy; HSTS outside dev |
| CORS | Explicit origin allowlist (`CORS_ORIGINS`); same-origin by default |
| Errors | Generic messages; no stack traces, SQL or paths in responses |
| Logging | No document text, tokens or passwords; ids/counts only |
| Audit | `audit_events` for logins, uploads, deletions, reviews, decisions, sign-offs, exports (not tamper-proof) |
| Secrets | Only in backend env; frontend build contains no secrets |
| Production guard | Startup refuses demo mode, default `SECRET_KEY`, or insecure cookie settings when `APP_ENV=production` |
| Dependencies | CI runs `pip-audit` and `pnpm audit` |
| Telemetry | None |

Retention: soft-deleted documents are hidden immediately; stored files are
removed by the deletion service at delete time; database rows for source blocks
are removed; audit events are retained. See DEPLOYMENT.md for backup handling.
