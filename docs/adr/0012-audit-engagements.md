# ADR 0012 — Audit engagements on the existing review pipeline

Status: accepted (2026-10-19)

## Context
Phase D adds statutory and internal audit work: engagements, trial balance mapping,
materiality, risks and procedures, sampling, journal entry testing, workpaper sign-off,
confirmations, adjustments, PBC requests with a client portal and a management letter.
It must reuse the evidence → checklist → check → finding → decision → snapshot pipeline
and keep every threshold out of code.

## Decision
- **Engagement is the container.** `audit_engagements` link an entity, a period, a
  current and optional prior-year trial balance version, a rule pack version and prefix.
  Team, phase budgets and time entries hang off it. Closing it blocks further changes
  through `require_open`.
- **Workpapers are reused.** Lead schedule and materiality papers are `tax_workpapers`
  kinds (`lead_schedule`, `materiality`) with an `engagement_id`, computed by the calc
  framework (`audit.lead_schedule`, `audit.materiality`) with golden files. Audit papers
  add a prepare step; sign-off needs a prepared paper and a reviewer who is not the
  preparer. Materiality percentages are entered by the team; the pack only holds
  guidance ranges, and a choice outside them is flagged, not refused.
- **Programmes are checklists.** `audit_programme` is a checklist kind; applying one
  creates procedures from its requirements. Procedures link to risks (per assertion)
  and optionally to a review, so coverage shows unaddressed risks.
- **Journal entry tests are an engine check** (`deterministic-1.4.0`,
  `journal_entry_test`) over the general ledger, so flags become proposed findings with
  row evidence. Weekend days, holidays, round multiple, approval limit and Benford bands
  are pack rules.
- **Sampling is reproducible.** Selection uses a SHA-256 counter stream from a recorded
  seed (`sampling-1.0.0`) and stores the population hash; `reproduce` re-runs it.
- **The letter uses confirmed findings only** and is issued as an immutable versioned
  snapshot (database trigger).
- **Clients are a separate role.** `client` users are refused (403) on every path except
  `/api/auth/` and `/api/portal/`, centrally in `current_context`. In the portal they see
  only PBC requests assigned to them and can upload and submit.

## Consequences
- Statistical sampling does not compute upper misstatement limits or confidence
  factors; projections are point estimates for the team to judge.
- A text or data flag is a lead for follow-up, never a conclusion of error or fraud.
