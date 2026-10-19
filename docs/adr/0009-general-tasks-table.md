# ADR 0009 — General tasks table next to finding tasks

Status: accepted (2026-10-18). Amends ADR 0005.

## Decision
Remediation of a finding stays a finding with an owner (ADR 0005). Work that is not
a finding gets a row in `tasks` (`source_kind` + `source_id`, owner, due date,
status, completion note). The first source is a tax obligation generated from a
rule pack; PBC requests (Phase D) and close checklist items (Phase E) reuse it.
The daily digest lists both kinds.

## Why
Filing deadlines exist before any finding does and must be tracked and closed with a
reference. Keeping them as findings would invent evidence and outcomes they do not have.

## Rules
- A tax obligation's due date comes only from the rule pack; regenerate to change it.
- Closing (done or cancelled) requires a note, e.g. the filing reference.
- Owners update their own tasks; reviewers and admins any task.
