# Known limitations (through Phase A)

Features listed here are either absent or deliberately labelled in the UI.

## Product scope
- **No legal or regulatory content.** Only synthetic demonstration checklists
  and a synthetic rule pack (jurisdiction `SYNTHETIC`, rules unverified and not
  verifiable) are seeded. The product does not certify compliance or cover any specific
  GCC regulation.
- **Checklist authoring UI is not built.** The API supports drafts, editing
  and publishing (tested); the Checklists page is read-only and says so.
- **Email is the only notification channel.** Invitations, password resets and a
  daily task-due digest go by email (SMTP in production; a file sink in
  development). There are no in-app or chat notifications, and no per-user
  opt-out of the digest yet.
- **No SSO or MFA**, and invitations cannot restrict sign-in to a domain.
- **AI is off by default.** AI suggestions on a review exist and are tested
  with the mock provider only. No real model has been connected or evaluated;
  Jais/Falcon stay placeholders until their serving interface is verified and a
  GPU is approved (docs/MODEL_INTEGRATION.md). Suggestions use a word-overlap
  block selection, so very long documents may be partly left out of the AI input
  (the run shows a warning when that happens).

## Documents
- **OCR is optional and off by default.** With `OCR_PROVIDER=tesseract`, PDF pages
  with no text layer are read by local Tesseract (English and Arabic) and their
  blocks are marked as OCR; recognition can be wrong. Images inside pages that do
  have a text layer are not read. With OCR off, scanned PDFs fail with a clear message.
- **Malware scanning is optional and off by default.** With `MALWARE_SCAN=clamav`,
  document and dataset uploads are streamed to clamd before storage; infected files
  are refused and audited, and uploads stop (503) while the scanner is unreachable.
  Signature-based scanning misses new threats. Without it, uploads are validated by
  extension, MIME type and file signature only (DOCX macros, XLSX formulas and
  oversized archives are rejected).
- PDF paragraph detection uses vertical gaps between lines and can merge or
  split paragraphs on unusual layouts. Tables in PDFs are extracted as text lines.
- DOCX/TXT have no fixed pages, so evidence uses paragraph numbers.
- Supported formats: PDF with a text layer, DOCX, TXT (UTF-8/UTF-16).

## Finance data (Phase A)
- **Imports, not integrations.** Trial balance, general ledger, sales/purchase
  registers (CSV/XLSX) and bank statements (CSV/XLSX/MT940/CAMT.053) are uploaded
  files. There are no ERP or bank connectors.
- **No tax calculations or returns.** Data checks are reconcile, threshold,
  duplicate (exact and fuzzy), field format, date rule and ratio. Nothing
  computes VAT or corporate tax, and nothing is filed anywhere.
- **Rule packs are entered by people.** No official rates or thresholds ship
  with the product. A rule is "verified" only when an organisation admin marks
  it so with a source URL; reports flag every unverified rule a check used.
- **No FX conversion.** Checks compare amounts as stored, with their currency
  codes; nothing converts between currencies.
- **Large files** are limited by `DATASET_MAX_UPLOAD_MB` and `DATASET_MAX_ROWS`;
  a 100k-row ledger imports in well under a minute locally (test-enforced), but
  multi-million-row files have not been benchmarked.
- **Engine messages are English.** Check messages and evidence labels stored on
  results are written in English and shown as stored in the Arabic interface.

## Review engine
- Deterministic checks only: text checks (required text, phrase groups,
  prohibited terms, restricted patterns, metadata, manual) under engine
  `deterministic-1.0.0`, and data checks under `deterministic-1.1.0`. Text checks
  find words, not meaning; data checks find exceptions, not errors. Every
  outcome needs human review.
- Engine matching applies Unicode NFKC, whitespace collapsing and case folding
  only. Arabic diacritics or tatweel in a document can prevent a match, and
  there is no stemming or morphology. (The citation validator for future AI
  output does strip diacritics and tatweel; the engine does not yet.)

## Security and operations
- The audit log is hash-chained and verifiable (ADR 0006). Removing the newest
  events or a whole organisation is not detectable from the database alone;
  keep the `head_hash` from verification outside the system if you need that.
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
