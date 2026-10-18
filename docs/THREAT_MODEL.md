# Threat model (MVP)

Assets: uploaded documents and extracted text, findings and decisions,
credentials and sessions, audit trail, report exports.

Trust boundaries: browser ↔ API; API ↔ worker (via Redis); API/worker ↔
storage and database; future: API ↔ model endpoint.

| Threat | Mitigation | Residual |
|---|---|---|
| Cross-tenant data access by guessing UUIDs | org-scoped lookups, 404s, tests with foreign ids | Logic bugs in new endpoints — tests required per endpoint |
| Session theft / fixation | HttpOnly cookie, new token at login, hashed storage, expiry | XSS would still allow actions within the page |
| CSRF | Token header on unsafe methods, SameSite=Lax | — |
| Credential stuffing | Rate limit, Argon2id | No MFA yet |
| Malicious upload (parser exploits, zip bombs) | Signature checks, size limits, zip size check, time limits in worker; optional ClamAV scan before storage (fails closed) | Scanning is off by default and signature-based; parser CVEs — keep deps patched |
| ReDoS via checklist patterns | Restricted syntax, bounded quantifiers, length limits | — |
| Stored XSS via document text or names | React escaping; HTML report uses autoescaping templates | — |
| Spreadsheet formula injection | CSV cell prefixing | — |
| Path traversal via filenames | Generated storage keys | — |
| Sensitive data in logs | Logging rules, no bodies logged | Third-party library logs — keep at WARNING in prod |
| Insider misuse | Roles, audit events | Audit log is not tamper-proof |
| Prompt injection (future AI) | AI disabled; citation validation; fixtures | Must re-assess before enabling AI |
| SSRF via AI endpoint | Admin-configured allowlisted hosts only | — |
| Demo credentials in production | Startup guard; demo users rejected unless demo mode | — |
| Redis/worker tampering | Private network only in Compose | No broker auth by default — set a password in deployments |
