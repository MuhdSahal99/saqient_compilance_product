# ADR 0008 — Engine versions and deterministic data checks

Status: accepted (2026-10-18)

## Decision
The review engine is versioned. `app/engine/versions.py` maps each version
to the check configurations it accepts:

- `deterministic-1.0.0`: text checks only (required text, phrase groups,
  prohibited terms, restricted pattern, metadata, manual). Frozen.
- `deterministic-1.1.0` (current): the same text checks, run by the same
  unchanged code, plus data checks over canonical datasets: `reconcile`,
  `threshold`, `duplicate` (exact, normalised, similar), `field_format`,
  `date_rule` and `ratio` (`app/engine/data_checks.py`).

Each run stores the engine version, the requirement configs, and its inputs
(dataset versions with Parquet hashes, rule pack version, as-of date). Each
check result stores `result_hash`, the SHA-256 of the canonical JSON of its
outcome, attention flag, message, evidence and metadata.

Data checks are declarative Pydantic configurations validated against the
canonical dataset schemas; there is no user code and no user regex. Thresholds
can be fixed values or rule pack keys resolved for the review's as-of date
(review date, else the latest dataset period end, else the run date). An
unverified rule still runs, but its warning leads the result message and is
added to the run warnings; the rule snapshot is kept in `meta`.

Two outcomes are added: `exceptions_found` (needs attention, becomes a
proposed finding) and `no_exceptions`. A check whose input is missing (no
document for a text check, no dataset of the needed kind) is
`not_applicable` without a finding. A check that cannot run on the inputs it
has (rule missing, field not mapped, no period) is `not_applicable` with a
finding so a person looks at it.

## Why
Findings must be reproducible and explainable long after the run. Pinning
the 1.0.0 behaviour with a golden fixture
(`tests/fixtures/engine/golden_deterministic_1_0_0.json`) lets data checks
ship without changing any existing outcome. Hashing results makes "same
inputs, same output" testable: tests run each check twice, on Parquet
reloaded from bytes and on shuffled rows, and compare hashes.

## Consequences
- Changing text-check behaviour needs a new engine version and a regenerated
  golden fixture in the same change.
- Data checks sort by `row_id` everywhere, so storage order never changes
  results. Amounts stay `Decimal`; there are no floats in comparisons.
- Duplicate `similar` matching is O(n²) within a blocking group; groups over
  `max_group_size` rows are skipped with a warning.
- Weekend days are never assumed; `not_weekend` requires them.
