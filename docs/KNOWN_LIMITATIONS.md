# Known limitations (Phase 1)

Features listed here are either absent or deliberately labelled in the UI.

## Product scope
- **No legal or regulatory content.** Only a synthetic demonstration checklist
  is seeded. The product does not certify compliance or cover any specific
  GCC regulation.
- **Checklist authoring UI is not built.** The API supports drafts, editing
  and publishing (tested); the Checklists page is read-only and says so.
- **Member management UI is not built.** Invitations, password reset and role
  changes are planned. Settings says so.
- **No notifications.** Due dates and overdue state are shown in the app only.
- **AI assistance is disabled.** Provider interfaces and citation validation
  exist and are tested, but no model is connected. Jais/Falcon are placeholders
  until their serving interfaces are verified (docs/MODEL_INTEGRATION.md).

## Documents
- **No OCR.** Scanned/image-only PDFs fail with a clear message.
- **No malware scanning.** Uploads are validated by extension, MIME type and
  file signature; DOCX macros and oversized archives are rejected. The UI says
  files are not scanned.
- PDF paragraph detection uses vertical gaps between lines and can merge or
  split paragraphs on unusual layouts. Tables in PDFs are extracted as text lines.
- DOCX/TXT have no fixed pages, so evidence uses paragraph numbers.
- Supported formats: PDF with a text layer, DOCX, TXT (UTF-8/UTF-16).

## Review engine
- Deterministic text checks only (required text, phrase groups, prohibited
  terms, restricted patterns, metadata, manual). They find words, not meaning;
  every outcome needs human review.
- Engine matching applies Unicode NFKC, whitespace collapsing and case folding
  only. Arabic diacritics or tatweel in a document can prevent a match, and
  there is no stemming or morphology. (The citation validator for future AI
  output does strip diacritics and tatweel; the engine does not yet.)

## Security and operations
- The audit log is an application table, **not tamper-proof**.
- Login rate limiting falls back to in-memory counters if Redis is unavailable
  (per-process only).
- S3 and GCS storage adapters are implemented but **not tested** against real
  buckets.
- No SSO/MFA yet. Sessions are cookie-based with CSRF tokens.
- Single-region, single-instance design; no high-availability setup.
- The compose file is for development and pilots; see docs/DEPLOYMENT.md for
  hardening steps.

## Frontend
- Light theme only.
- The production bundle is about 1.1 MB minified (330 KB gzip) across four
  chunks; routes are not lazy-loaded yet.
