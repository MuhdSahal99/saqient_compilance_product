# ADR 0013 — Finance assurance: reconciliations, close, controls, analytics, connectors

Status: accepted (2026-10-19)

## Context
Phase E adds the assurance work finance teams repeat every period: bank and account
reconciliations, intercompany, the close checklist, flux review, internal controls,
segregation of duties, AP and expense analytics, and read-only links to accounting
systems. Saqient checks and evidences that work; it never posts, files or approves it.

## Decision
- **Own tables with one sign-off pattern.** Reconciliations, flux reviews and
  certifications are their own tables (not workpapers) sharing `SignOffMixin`:
  draft → prepared → signed off by someone other than the preparer, an immutable
  `assurance_snapshots` row (trigger) with a SHA-256, reopen with a reason to version
  n+1, and HTML/PDF/CSV exports rendered only from snapshots.
- **Matching is deterministic and versioned** (`recon-1.0.0`): reference, then amount
  and date within the pack's tolerance and window, then reference groups; ties break
  by date gap and row id. A bank rec signs off only when the proof difference is zero.
- **Thresholds are pack rules.** Variance, intercompany, flux, ageing buckets, matching
  tolerances, SoD conflict matrices, AP and expense parameters are rule pack values
  (`syn.recon`, `syn.sod`, `syn.ap` in the synthetic draft pack). Nothing is hardcoded.
- **Close items are tasks** (`close_checklist` source), and control remediation is a
  task (`control_remediation`), so the existing task list, digest and owners apply.
- **Controls conclude on evidence.** A test needs evidence (source blocks or dataset
  rows) before it concludes; an ineffective test raises a deficiency. Only reviewers or
  admins classify (with a rationale), assign remediation and certify; certification is
  refused while an open deficiency is unclassified.
- **SoD and AP analytics are engine checks** (`deterministic-1.5.0`, `sod_conflict`,
  `ap_analytics`) over new dataset kinds, so flags become proposed findings with row
  evidence and human decisions. IBANs are compared in memory and appear in evidence
  masked to the last four characters.
- **Connectors are adapters behind a registry.** Each adapter maps a provider API to
  canonical rows; a sync is a job that writes a canonical CSV through the existing
  dataset pipeline and stores a new version only when its SHA-256 changes. OAuth uses
  state + PKCE and read scopes; secrets are AES-GCM encrypted per organisation.
  Odoo hosts must match an allowlist. Off unless `CONNECTORS_ENABLED=true`.

## Consequences
- Adding QuickBooks, Xero, Dynamics 365, NetSuite or SAP is one adapter module plus a
  registry entry; the API, service and UI are shared.
- Connector field mappings follow public documentation and stay labelled unverified
  until checked against a live account.
- Analytics flags are leads for review, not conclusions of error or fraud.
