# Data model

PostgreSQL 16, managed by Alembic (`backend/alembic/versions`). Enums are
stored as `VARCHAR` with named check constraints. All primary keys are UUIDs.
Every tenant-owned table has a non-null `org_id` (FK to `organizations`,
`ON DELETE CASCADE`); every query filters on it.

```
organizations ─┬─ memberships ── users ── user_sessions
               ├─ documents ── document_versions ── source_blocks
               ├─ sources
               ├─ checklists ── checklist_versions ── requirements ──(source_id)── sources
               ├─ jobs
               ├─ reviews ──┬─ review_runs ── check_results
               │            ├─ ai_suggestion_runs ── ai_suggestions
               │            ├─ findings ── comments
               │            └─ report_snapshots
               └─ audit_events
```

## Identity and tenancy

| Table | Key columns | Notes |
|---|---|---|
| `organizations` | name, slug, is_demo | Tenant. |
| `users` | email (unique), full_name, password_hash (Argon2id), is_active, is_demo, preferred_locale | `is_demo` users are rejected unless `DEMO_MODE=true`. |
| `memberships` | org_id, user_id, role | Unique (org_id, user_id). Role ∈ org_admin, reviewer, analyst, viewer. Re-read on every request. |
| `user_sessions` | token_hash (SHA-256 of the cookie token), csrf_token, user_id, org_id (active org), last_seen_at, expires_at, revoked_at | Raw session tokens are never stored. Idle and absolute expiry. |

## Legal entities

| Table | Key columns | Notes |
|---|---|---|
| `tax_groups` | name, country, trn_encrypted, trn_last4 | Unique (org, name). |
| `legal_entities` | name, country (ISO 3166-1), trn_encrypted, trn_last4, fiscal_year_end_month/day, functional_currency (ISO 4217), timezone (IANA), tax_group_id, is_free_zone, is_active | Unique (org, name). TRN is AES-256-GCM encrypted (`app/crypto.py`), bound to org and field; API returns it masked. Archive with `is_active=false`. |

## Rule packs

| Table | Key columns | Notes |
|---|---|---|
| `rule_packs` | name, jurisdiction (ISO 3166-1 or `SYNTHETIC`), description, is_synthetic | Unique (org, name). |
| `rule_pack_versions` | rule_pack_id, version_number, state (draft/published/archived), published_at, published_by_id | Published versions are immutable; publishing archives the previous one. |
| `rules` | rule_pack_version_id, rule_key, title, value_type (decimal/integer/string/boolean/date), value (string, parsed by type, never float), unit, effective_from, effective_to, source_url, source_note, todo, verification_status (draft/verified), verified_by_id, verified_at | Unique (version, key, effective_from); periods per key may not overlap. Only org admins verify, and only with a source URL, no open TODO and a non-synthetic pack. Checks resolve a rule by key + date and record a snapshot; a draft rule adds an "unverified rule" warning. |

## Datasets

| Table | Key columns | Notes |
|---|---|---|
| `datasets` | entity_id, kind (trial_balance, general_ledger, sales_register, purchase_register, bank_statement), name, period_start, period_end | Logical dataset for one legal entity. |
| `dataset_versions` | dataset_id, version_number, original_filename, file_format (csv/xlsx/mt940/camt053), size_bytes, raw_sha256, raw_storage_key, status, failure_message, source_columns, source_row_count, column_mapping, parse_options, mapping_confirmed_by_id/at, parquet_storage_key, parquet_sha256, row_count, derived_fields, totals, errors, error_count | Status: pending → parsing → needs_mapping → processing → ready / failed. Canonical schemas per kind are in `app/datasets/schemas.py`. Storage keys are never returned by the API. (ADR 0007) |

## Documents

| Table | Key columns | Notes |
|---|---|---|
| `documents` | title, description, document_type, tags[], is_demo, created_by_id, deleted_at | Logical document. Soft-deleted rows keep only metadata. |
| `document_versions` | document_id, version_number, original_filename (metadata only), file_format, mime_type, size_bytes, sha256, storage_key, status, failure_message, page_count, block_count, extraction_warnings[] | Unique (document_id, version_number). `storage_key` is never returned by the API. Status: pending → processing → ready / failed. Deleting clears `storage_key` and source blocks. |
| `source_blocks` | document_version_id, ordinal, ref, page_number (PDF only), paragraph_number, section_heading, text | Unique (version, ordinal). The only place extracted text lives; evidence points here. |

## Checklists

| Table | Key columns | Notes |
|---|---|---|
| `sources` | title, publisher, url, version_label, verification_status, excerpt, last_reviewed_at | verification ∈ synthetic, unverified, verified (set by a human). |
| `checklists` | name, description, kind | kind ∈ synthetic_demo, internal_policy, external_regulatory. |
| `checklist_versions` | checklist_id, version_number, state, disclaimer, published_at, published_by_id | Unique (checklist, version). Published versions are immutable; publishing archives the previous one. |
| `requirements` | checklist_version_id, ordinal, code, title, description, jurisdiction, document_type, category, severity, human_instructions, check_config (JSON), source_id, source_reference, effective_date, owner | Unique (version, code). `check_config` is validated by `app/engine` (required_text, phrase_groups, prohibited_terms, pattern, metadata, manual). |

## Reviews

| Table | Key columns | Notes |
|---|---|---|
| `jobs` | kind (extract, review_run, ai_suggest, dataset_parse, dataset_build), target_id, status, attempts, max_attempts, progress, cancel_requested, error | Background work record. Workers receive (job_id, org_id) and re-check ownership. |
| `reviews` | title, document_version_id (nullable), checklist_version_id, rule_pack_version_id (nullable), as_of_date (nullable), status, signed_off_by_id, signed_off_at | Pinned to exact versions. Needs a document, datasets, or both (checked by the service). Status: draft → running → in_review → signed_off (reopen returns to in_review). |
| `review_datasets` | review_id, kind, dataset_version_id | One ready dataset version per kind per review (unique review, kind). |
| `review_runs` | review_id, job_id, document_version_id (nullable), engine_version, engine_mode, config_snapshot (JSON), inputs_snapshot (JSON), warnings[] | Each run records the engine version, a copy of the requirement configs, and the inputs: dataset versions with Parquet hashes, rule pack version, as-of date and where it came from. |
| `check_results` | run_id, requirement_id, outcome, needs_attention, message, evidence (JSON), meta (JSON), result_hash | Unique (run, requirement). Outcome ∈ match_found, no_match_found, needs_human_review, processing_error, not_applicable, exceptions_found, no_exceptions. `meta` holds rule snapshots and counts; `result_hash` is SHA-256 of the canonical result (ADR 0008). Data-check evidence items have `type: dataset_rows` with dataset version id, row ids, columns and row values. |
| `findings` | review_id, requirement_id, check_result_id, is_manual, title, severity, automated_outcome, evidence (JSON), status, owner_id, due_date, decided_by_id, decided_at, decision_rationale, remediation_notes | Partial unique index on (review_id, requirement_id) for automated findings, so re-runs update rather than duplicate. Tasks are findings with an owner (ADR 0005). |
| `findings.ai_suggestion_id` | | Set when a reviewer accepted an AI suggestion; the finding is still a human decision. |
| `ai_suggestion_runs` | review_id, job_id, requested_by_id, provider, model, prompt_version, document_version_id, checklist_version_id, warnings[], finished_at | One provider request per run; records which model produced the suggestions. |
| `ai_suggestions` | run_id, review_id, requirement_id, assessment, summary, evidence (validated citations only), rejected_citations, status (pending/accepted/dismissed), decided_by_id, decided_at, decision_note, finding_id | Unique (run, requirement). Accepting creates a proposed finding. |
| `comments` | finding_id, author_id, body | |
| `report_snapshots` | review_id, version, content (JSON), signed_off_by_id, signed_off_at | Unique (review, version). Frozen at sign-off; exports render from this JSON only (ADR 0004). |

Evidence JSON items: `block_id, ref, page_number, paragraph_number, quote,
context, highlight_start, highlight_end`. Quotes are copied from
`source_blocks.text`.

## Finding status transitions

```
proposed ──confirm──▶ confirmed ──assign owner──▶ remediation_in_progress
   │                                                  │      ▲
   ├──dismiss (rationale)──▶ dismissed                ▼      │ send back
   └──accept risk (rationale)──▶ accepted_risk   ready_for_rereview ──resolve (reviewer)──▶ resolved
```

Decisions are locked while the review is signed off; remediation updates
remain allowed.

## Audit

`audit_events`: org_id, actor_id, action, object_type, object_id, metadata
(JSON), created_at, seq, prev_hash, hash. Unique (org_id, seq) with NULLs not
distinct. Append-only hash chain per organisation (ADR 0006); a trigger
rejects UPDATE. `services/audit.record` strips keys such as `text`,
`content`, `password`, `token`, `csrf`, `body`.
