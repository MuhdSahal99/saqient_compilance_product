# ADR 0004 — Reports render from immutable sign-off snapshots

Status: accepted (2026-10-12)

## Decision
Reviewer sign-off writes a JSON snapshot (`report_snapshots`, incrementing
version). HTML/PDF/CSV exports render from a snapshot. Reopening a review
requires a reason and the next sign-off creates a new version. PDFs are
generated with ReportLab (pure Python) rather than a headless browser or
WeasyPrint, to avoid heavy system dependencies in the API image.

## Consequences
ReportLab's default fonts do not shape Arabic text; Arabic content in PDF
exports is a known limitation (HTML export renders it correctly).
