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
| `invitations` | org_id, email, role, token_hash, invited_by_id, expires_at, accepted_at, accepted_by_id, revoked_at, last_sent_at | Token stored as SHA-256 only; 7-day expiry; claimed by one conditional UPDATE, so single use. One open invitation per email per org (partial unique index). |
| `password_reset_tokens` | user_id, token_hash, expires_at, used_at | Account-level, not tenant data. 60-minute expiry, single use, only the newest works. Using one revokes every session of the user. |
| `notification_log` | org_id, kind (invitation, task_due_reminder), recipient_user_id, recipient_email, subject, object_type, object_id, dedupe_key (unique), status (sent, failed, disabled), error | Bodies are not stored (they hold links). Reminders use one dedupe key per owner, org and day. |

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
| `dataset_versions` | dataset_id, version_number, original_filename, file_format (csv/xlsx/mt940/camt053), size_bytes, raw_sha256, raw_storage_key, status, failure_message, source_columns, source_row_count, column_mapping, parse_options, mapping_confirmed_by_id/at, parquet_storage_key, parquet_sha256, row_count, derived_fields, totals, errors, error_count | Status: pending → parsing → needs_mapping → processing → ready / failed. Canonical schemas per kind are in `app/datasets/schemas.py`. Storage keys are never returned by the API. An unused dataset or version can be deleted (rows and files; the audit event keeps name, kind and hashes); anything referenced by a foreign key or by JSON evidence is refused with 409. (ADR 0007) |

## E-invoicing, VAT and tax calendar (Phase B)

| Table | Key columns | Notes |
|---|---|---|
| `rule_pack_files` | rule_pack_version_id, file_key, kind (xsd_bundle), entry_point, size_bytes, sha256, storage_key, source_url, verification_status | Schema bundles attached to a draft version; copied to new drafts. `rules.value` is now Text and `value_type` may be `json` (shape checked by key family). |
| `tax_periods` | entity_id, tax_type (vat/corporate_tax/zakat/wht), frequency, period_start, period_end, status (open/filed) | Non-overlapping per entity and tax type. |
| `entity_tax_codes` | entity_id, register, tax_code, treatment, recoverable | The entity's VAT treatment of its ERP tax codes. |
| `entity_tax_accounts` | entity_id, role (output_vat, input_vat, reverse_charge_output/input), account_code | VAT GL accounts for the GL reconciliation. |
| `einvoice_batches` / `einvoice_files` | entity_id, raw_sha256 / sha256 (unique per entity), storage_key, profile, invoice_number, invoice_uuid, issue_date, icv, currency, payable_amount, tax_amount, parse_error | Uploaded XML (or ZIP of XML); unreadable files are kept with their parse error. |
| `review_einvoices` | review_id, file_id | E-invoices a review validates. `reviews` gains entity_id and tax_period_id; `findings` gains finding_key. |
| `einvoice_monitors` / `einvoice_monitor_runs` | entity_id, checklist_version_id, rule_pack_version_id, sample_size, cadence, seed, next_run_at, covered_until / window, population, sampled, seed, sample_method, status, review_id | Scheduled sampling (Celery beat, hourly). |
| `tasks` | source_kind (tax_obligation/manual), source_id, entity_id, title, owner_id, due_date, status, completion_note | ADR 0009. Included in the daily digest. |
| `tax_obligations` | entity_id, tax_period_id, obligation_key, period_start/end, due_date, rule_pack_version_id, rule_key, rule_snapshot, formula, rule_verified, task_id | Generated from `<prefix>.obligations` (and go-live waves); unique (entity, key, period_start). |

## Documents

| Table | Key columns | Notes |
|---|---|---|
| `documents` | title, description, document_type, tags[], is_demo, created_by_id, deleted_at | Logical document. Soft-deleted rows keep only metadata. |
| `document_versions` | document_id, version_number, original_filename (metadata only), file_format, mime_type, size_bytes, sha256, storage_key, status, failure_message, page_count, block_count, extraction_warnings[] | Unique (document_id, version_number). `storage_key` is never returned by the API. Status: pending → processing → ready / failed. Deleting clears `storage_key` and source blocks. |
| `source_blocks` | document_version_id, ordinal, ref, page_number (PDF only), paragraph_number, section_heading, text, is_ocr, ocr_confidence | Unique (version, ordinal). The only place extracted text lives; evidence points here. OCR blocks (ref `p3.ocr1`) come from pages with no text layer when `OCR_PROVIDER=tesseract`. |

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
| `ai_tasks` | kind (contract_tax/finding_explain/letter_draft/pack_qa), subject_type, subject_id, question, language, status (running/ready/failed/accepted/dismissed), job_id, requested_by_id, provider, prompt_version, output, warnings[], error, decided_by_id, decided_at, decision_note | One multi-agent request (ADR 0015). Output is validated draft data only; no prompts or document text. |
| `ai_task_steps` | task_id, ordinal, agent, tier, provider, model, model_version, status, duration_ms, input/output tokens, note | One agent call; records which model and version produced each step. |
| `ai_suggestions` | run_id, review_id, requirement_id, assessment, summary, evidence (validated citations only), rejected_citations, status (pending/accepted/dismissed), decided_by_id, decided_at, decision_note, finding_id | Unique (run, requirement). Accepting creates a proposed finding. |
| `comments` | finding_id, author_id, body | |
| `report_snapshots` | review_id, version, content (JSON), signed_off_by_id, signed_off_at | Unique (review, version). Frozen at sign-off; exports render from this JSON only (ADR 0004). |

Evidence JSON items: `block_id, ref, page_number, paragraph_number, quote,
context, highlight_start, highlight_end`. Quotes are copied from
`source_blocks.text`.

## Direct tax (Phase C)

| Table | Key columns | Notes |
|---|---|---|
| `tax_workpapers` | entity_id, kind (corporate_tax, sbr_test, qfzp_test, pillar_two, zakat), period, currency, rule_pack_version_id, rules_prefix, status (draft, signed_off), calc_version, result_hash, warnings | One paper per entity, period and kind of work. |
| `workpaper_lines` | workpaper_id, source (manual, computed), section, line_key (unique per paper), category, amount NUMERIC(20,4) or value, formula_id, explanation, rule_snapshots, evidence | Computed keys are `calc:<key>`. |
| `workpaper_snapshots` | workpaper_id, version, content, signed_off_by_id | Immutable (trigger); exports render from it. |
| `tax_loss_entries` | entity_id, kind (incurred, used, transferred_in/out, forfeited), period, amount (positive), workpaper_id, counterparty_entity_id, transfer_id, explanation, rule_snapshots, evidence | Unique (workpaper_id, kind): a paper posts once. |
| `tax_group_memberships` | tax_group_id, entity_id, is_parent, ownership_share NUMERIC(7,6), joined_on, left_on | No overlapping memberships per entity; one parent at a time. |
| `related_parties` | entity_id, name, relation, jurisdiction | Unique (entity, name). |
| `related_party_transactions` | entity_id, related_party_id, period, transaction_type, direction, amount, currency, method, range_low/high, tested_value, benchmark_document_ids, evidence | Amounts in the entity's currency. |

Dataset kind `wht_payments` (payment id, date, payee, payee country, payment type,
gross, withheld, treaty rate, certificate) feeds the 1.3.0 `wht_rates` check.

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

## Audit (Phase D)

All tables carry `org_id` and are reached through the engagement.

| Table | Key columns | Notes |
|---|---|---|
| `audit_engagements` | entity_id, kind, name, period, phase, status, currency, cy/py_tb_version_id, rule_pack_version_id, rules_prefix | Closed engagements refuse changes. |
| `engagement_members`, `engagement_budgets`, `time_entries` | engagement_id, user_id, role / phase, hours | Budget vs actual per phase. |
| `lead_schedules`, `account_mappings` | engagement_id, code, name, section / account_code → lead_code | Feed lead schedule papers and the SUD. |
| `audit_risks`, `audit_procedures`, `risk_procedures` | ref, assertions, inherent risk, significant, fraud / title, status, requirement_id, review_id | Coverage = risks with procedures. |
| `audit_samples`, `audit_sample_items` | method, dataset_version_id, amount_column, seed, params, algorithm_version, population hash / row_id, stratum, hits, book/audited value, result | Reproducible from seed. |
| `audit_confirmations` | type, counterparty, reference, book/confirmed amount, status, dates, conclusion | planned → sent → responded / no_response → closed. |
| `audit_adjustments`, `adjustment_lines` | ref, status (proposed / recorded / passed), reason / account_code, debit, credit | Must balance; passed ones form the SUD. |
| `pbc_requests`, `pbc_files` | ref, title, due_date, assignee (client), status / document_version_id | Client uploads via the portal. |
| `letter_points`, `letter_snapshots` | finding_id, include, recommendation, response / version, content | Snapshots immutable (trigger). |

`tax_workpapers` gains `engagement_id`, `prepared_by_id`, `prepared_at`; `reviews` gains
`engagement_id`; roles gain `client`; checklist kinds gain `audit_programme`.

## Assurance (Phase E)

All tables carry `org_id`. Sign-off objects share `status`, `prepared_by/at`,
`signed_off_by/at`, `version`, `reopen_reason`; snapshots live in `assurance_snapshots`
(object, object_id, version, content, sha256; immutable by trigger).

| Table | Key columns | Notes |
|---|---|---|
| `bank_reconciliations`, `recon_matches`, `recon_match_lines` | entity, period, statement/ledger version, pack + prefix, balances / method, rule / side, row_id | A row matches once per side (unique). |
| `account_reconciliations`, `recon_support_items` | tb_version_id, account_code (unique pair), support items | Variance vs pack thresholds. |
| `intercompany_reconciliations` | entity a/b, TB versions a/b, accounts a/b | Difference vs pack limit. |
| `close_periods`, `close_items` | entity, period_end (unique pair), status / day_offset, task_id | Items are tasks (`close_checklist`). |
| `flux_reviews`, `flux_explanations` | CY/PY TB versions / account_code, text | Accounts above both pack limits need text. |
| `control_processes`, `control_risks`, `controls`, `control_tests` | entity / ref, assertions, rating / ref, key, nature, automation, frequency, risk_ids / kind, period, sample, exceptions, evidence, conclusion | Risk-control matrix. |
| `control_deficiencies`, `control_certifications` | control, test, classification, remediation_task_id / entity, period, statement | Remediation tasks are `control_remediation`. |
| `connectors`, `connector_syncs` | entity, provider, status, scopes, config, secret_enc, oauth state hash, datasets / kind, status, rows, sha256, dataset_version_id | Secrets encrypted; never returned. |

New dataset kinds: `user_roles`, `ap_payments`, `employee_master`, `three_way_match`,
`expense_claims`. New job kind: `connector_sync`.

## Sector packs (Phase F)

| Table | Key columns | Notes |
|---|---|---|
| `content_pack_installs` | org_id, pack_id, pack_version (unique triple), manifest_sha256, checklist_version_ids, rule_pack_version_id, installed_by_id | Installs draft checklists and a draft rule pack. |

`organizations` gains `ai_opt_in` and `ai_opt_in_at`. Workpaper kinds gain `fs_draft`
(engagement) and `lease_ifrs16` (entity). New dataset kind: `fixed_assets`.
