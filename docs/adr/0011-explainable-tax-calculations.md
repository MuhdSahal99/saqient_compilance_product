# ADR 0011 — Explainable, versioned tax calculations and workpapers

Status: accepted (2026-10-18)

## Context
Phase C adds direct-tax work: a corporate tax bridge, SBR / QFZP eligibility, tax
losses and groups, transfer pricing thresholds, Pillar Two and zakat. Every rate,
threshold and date must come from a rule pack, and a reviewer must be able to
reproduce each number.

## Decision
- **Pure formulas in `app/calc/`.** Each formula takes input lines, a rule reader and a
  key prefix and returns outputs. Every output has a formula id, steps (label,
  expression, value) and the rule keys it read. Arithmetic is Decimal. Rounding uses
  `<prefix>.amount_decimals` and `<prefix>.rounding_mode`. `CALC_VERSION`
  (`calc-1.0.0`) is stored with every result.
- **Workpapers** (`tax_workpapers`, `workpaper_lines`, `workpaper_snapshots`):
  - Preparers enter input lines, either amounts or flags, each with evidence:
    source blocks, dataset rows, or trial balance accounts summed with the rows cited.
  - Compute replaces the computed lines and stores the rule snapshots, the
    unverified-rule warnings and a SHA-256 of inputs, rules and outputs. Changing any
    input clears the computed lines.
  - Sign-off freezes an immutable snapshot (a database trigger rejects UPDATE).
    Reopening needs a reason, and the next sign-off is version n+1.
  - Exports render from the snapshot only.
- **Standalone checks reuse the same formulas.** Loss transfers, tax group tests and the
  transfer pricing documentation check run through `workpapers.evaluate`, which gives
  the same steps, snapshots and hash.
- **Withholding tax is an engine check** (`deterministic-1.3.0`, `wht_rates`) over a
  new `wht_payments` dataset kind. This way it reuses findings, decisions, remediation
  and reports. 1.2.0 checks run unchanged.
- **Results are indications.** Values are `met / not_met / not_determinable` or
  `required / not_required / not_determinable`. A failed transfer is refused. Nothing
  states that an entity qualifies for anything.
- **Golden files.** `backend/tests/golden/*.json` hold hand-worked cases for every
  registered formula. A test fails when a formula has no golden file.

## Consequences
- Formula structure (which adjustments exist, how a limit combines) is code;
  parameters are data. Changing structure needs a new `CALC_VERSION`.
- Pillar Two is a simplified review model, not a GloBE computation (see
  KNOWN_LIMITATIONS).
