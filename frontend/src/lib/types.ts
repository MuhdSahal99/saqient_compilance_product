export type Role = "org_admin" | "reviewer" | "analyst" | "viewer";
export type VersionStatus = "pending" | "processing" | "ready" | "failed";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ReviewStatus = "draft" | "running" | "in_review" | "signed_off";
export type Severity = "low" | "medium" | "high" | "critical";
export type CheckOutcome =
  | "match_found"
  | "no_match_found"
  | "needs_human_review"
  | "processing_error"
  | "not_applicable"
  | "exceptions_found"
  | "no_exceptions";
export type FindingStatus =
  | "proposed"
  | "in_review"
  | "confirmed"
  | "dismissed"
  | "remediation_in_progress"
  | "ready_for_rereview"
  | "resolved"
  | "accepted_risk";
export type ChecklistKind = "synthetic_demo" | "internal_policy" | "external_regulatory";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  is_demo: boolean;
}

export interface Me {
  user: { id: string; email: string; full_name: string; preferred_locale: string; is_demo: boolean };
  org: Org;
  role: Role;
  memberships: { org: Org; role: Role }[];
  csrf_token: string;
  demo_mode: boolean;
  ai_enabled: boolean;
  malware_scan_enabled?: boolean;
  ocr_enabled?: boolean;
}

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  progress: number;
  cancel_requested: boolean;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface DocumentVersion {
  id: string;
  document_id: string;
  version_number: number;
  original_filename: string;
  file_format: "pdf" | "docx" | "txt";
  mime_type: string;
  size_bytes: number;
  sha256: string;
  status: VersionStatus;
  failure_message: string | null;
  page_count: number | null;
  block_count: number;
  extraction_warnings: string[];
  created_at: string;
  processed_at: string | null;
}

export interface DocumentSummary {
  id: string;
  title: string;
  description: string;
  document_type: string;
  tags: string[];
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  created_by_name: string | null;
  latest_version: DocumentVersion | null;
  version_count: number;
}

export interface DocumentDetail extends DocumentSummary {
  versions: DocumentVersion[];
  latest_job: Job | null;
}

export interface SourceBlock {
  id: string;
  ordinal: number;
  ref: string;
  page_number: number | null;
  paragraph_number: number | null;
  section_heading: string | null;
  text: string;
  is_ocr?: boolean;
  ocr_confidence?: number | null;
}

export interface Source {
  id: string;
  title: string;
  publisher: string;
  url: string | null;
  version_label: string;
  verification_status: "synthetic" | "unverified" | "verified";
  excerpt: string;
  last_reviewed_at: string | null;
}

export interface Requirement {
  id: string;
  ordinal: number;
  code: string;
  title: string;
  description: string;
  jurisdiction: string | null;
  document_type: string | null;
  category: string;
  severity: Severity;
  human_instructions: string;
  check_config: Record<string, unknown> & { type: string };
  source_reference: string;
  effective_date: string | null;
  owner: string;
  source: Source | null;
}

export interface ChecklistVersion {
  id: string;
  checklist_id: string;
  version_number: number;
  state: "draft" | "published" | "archived";
  disclaimer: string;
  published_at: string | null;
  created_at: string;
  requirement_count: number;
}

export interface ChecklistVersionDetail extends ChecklistVersion {
  checklist_name: string;
  checklist_kind: ChecklistKind;
  requirements: Requirement[];
}

export interface Checklist {
  id: string;
  name: string;
  description: string;
  kind: ChecklistKind;
  created_at: string;
  versions: ChecklistVersion[];
}

export interface ReviewRun {
  id: string;
  engine_version: string;
  engine_mode: string;
  warnings: string[];
  inputs_snapshot?: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  job: Job;
}

export interface ReviewDataset {
  kind: DatasetKind;
  dataset_id: string;
  dataset_name: string;
  dataset_version_id: string;
  version_number: number;
  row_count: number | null;
}

export interface Review {
  id: string;
  title: string;
  status: ReviewStatus;
  is_demo: boolean;
  created_at: string;
  signed_off_at: string | null;
  signed_off_by_name: string | null;
  document_id: string | null;
  document_title: string | null;
  document_version_id: string | null;
  document_version_number: number | null;
  datasets: ReviewDataset[];
  rule_pack_version_id: string | null;
  rule_pack_name: string | null;
  rule_pack_version_number: number | null;
  as_of_date: string | null;
  checklist_id: string;
  checklist_name: string;
  checklist_version_id: string;
  checklist_version_number: number;
  checklist_kind: ChecklistKind;
  finding_counts: Partial<Record<FindingStatus, number>>;
  latest_run: ReviewRun | null;
}

/** A quote from a stored document source block. */
export interface Evidence {
  type?: undefined;
  block_id: string;
  ref: string;
  page_number: number | null;
  paragraph_number: number | null;
  quote: string;
  context: string;
  highlight_start: number;
  highlight_end: number;
}

/** Rows of a dataset version that a data check flagged (values are exact strings). */
export interface DatasetRowsEvidence {
  type: "dataset_rows";
  dataset_version_id: string;
  dataset_kind: DatasetKind;
  version_number: number;
  label: string;
  row_ids: number[];
  row_count: number;
  columns: string[];
  rows: (string | null)[][];
  detail: Record<string, string | null>;
}

export type AnyEvidence = Evidence | DatasetRowsEvidence;

export function isDatasetEvidence(e: AnyEvidence): e is DatasetRowsEvidence {
  return e.type === "dataset_rows";
}

export interface CheckResult {
  id: string;
  requirement_id: string;
  requirement_code: string;
  requirement_title: string;
  severity: Severity;
  outcome: CheckOutcome;
  needs_attention: boolean;
  message: string;
  evidence: AnyEvidence[];
  meta?: Record<string, unknown>;
  result_hash?: string | null;
}

export interface Finding {
  id: string;
  review_id: string;
  review_title: string;
  review_status: ReviewStatus;
  requirement_id: string | null;
  requirement_code: string | null;
  source_reference: string | null;
  is_manual: boolean;
  title: string;
  description: string;
  severity: Severity;
  automated_outcome: CheckOutcome | null;
  evidence: AnyEvidence[];
  status: FindingStatus;
  owner_id: string | null;
  owner_name: string | null;
  due_date: string | null;
  is_overdue: boolean;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_rationale: string;
  remediation_notes: string;
  ai_suggestion_id?: string | null;
  ai_provider?: string | null;
  ai_model?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Comment {
  id: string;
  author_name: string | null;
  body: string;
  created_at: string;
}

export interface Report {
  id: string;
  review_id: string;
  review_title: string;
  version: number;
  signed_off_at: string;
  signed_off_by_name: string | null;
  finding_count: number;
}

export interface AuditEvent {
  id: string;
  actor_name: string | null;
  action: string;
  object_type: string;
  object_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface Member {
  user_id: string;
  full_name: string;
  email: string;
  role: Role;
  membership_id: string | null;
  joined_at: string | null;
}

export interface Invitation {
  id: string;
  email: string;
  role: Role;
  invited_by_name: string | null;
  created_at: string;
  expires_at: string;
  is_expired: boolean;
  last_sent_at: string | null;
  last_delivery: "sent" | "failed" | "disabled" | null;
}

export interface InvitationLookup {
  organization_name: string;
  email: string;
  role: Role;
  has_account: boolean;
  expires_at: string;
}

// ---------------------------------------------------------------- finance (Phase A)

export type DatasetKind = "trial_balance" | "general_ledger" | "sales_register" | "purchase_register" | "bank_statement";
export const DATASET_KINDS: DatasetKind[] = ["trial_balance", "general_ledger", "sales_register", "purchase_register", "bank_statement"];
export type DatasetStatus = "pending" | "parsing" | "needs_mapping" | "processing" | "ready" | "failed";

export interface TaxGroup {
  id: string;
  name: string;
  country: string;
  trn_masked: string | null;
  entity_count: number;
  created_at: string;
}

export interface LegalEntity {
  id: string;
  name: string;
  country: string;
  trn_masked: string | null;
  fiscal_year_end_month: number;
  fiscal_year_end_day: number;
  functional_currency: string;
  timezone: string;
  tax_group_id: string | null;
  tax_group_name: string | null;
  is_free_zone: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DatasetVersion {
  id: string;
  version_number: number;
  original_filename: string;
  file_format: string;
  size_bytes: number;
  raw_sha256: string;
  status: DatasetStatus;
  failure_message: string | null;
  source_columns: string[];
  source_row_count: number | null;
  column_mapping: Record<string, string>;
  parse_options: Record<string, string>;
  mapping_confirmed_at: string | null;
  parquet_sha256: string | null;
  row_count: number | null;
  derived_fields: string[];
  totals: Record<string, string>;
  errors: { row_id?: number; column?: string; field?: string; value?: string; message?: string }[];
  error_count: number;
  created_at: string;
  processed_at: string | null;
}

export interface DatasetVersionDetail extends DatasetVersion {
  dataset_id: string;
  kind: DatasetKind;
  preview: Record<string, string | null>[];
  latest_job: Job | null;
}

export interface Dataset {
  id: string;
  entity_id: string;
  entity_name: string;
  kind: DatasetKind;
  name: string;
  period_start: string | null;
  period_end: string | null;
  is_demo: boolean;
  created_at: string;
  latest_version: DatasetVersion | null;
}

export interface DatasetDetail extends Dataset {
  versions: DatasetVersion[];
}

export interface DatasetKindSchema {
  kind: DatasetKind;
  fields: { name: string; type: string; required: boolean }[];
  require_any: string[][];
}

export interface DatasetRows {
  version_id: string;
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  total: number;
}

export type RuleValueType = "decimal" | "integer" | "string" | "boolean" | "date";

export interface Rule {
  id: string;
  rule_key: string;
  title: string;
  value_type: RuleValueType;
  value: string;
  unit: string;
  effective_from: string;
  effective_to: string | null;
  source_url: string | null;
  source_note: string;
  todo: string;
  verification_status: "draft" | "verified";
  verified_by_name: string | null;
  verified_at: string | null;
}

export interface RulePackVersion {
  id: string;
  rule_pack_id: string;
  version_number: number;
  state: "draft" | "published" | "archived";
  published_at: string | null;
  created_at: string;
  rule_count: number;
  unverified_count: number;
}

export interface RulePackVersionDetail extends RulePackVersion {
  pack_name: string;
  jurisdiction: string;
  is_synthetic: boolean;
  rules: Rule[];
}

export interface RulePack {
  id: string;
  name: string;
  jurisdiction: string;
  description: string;
  is_synthetic: boolean;
  created_at: string;
  versions: RulePackVersion[];
}

export interface Dashboard {
  documents_processed: number;
  documents_failed: number;
  active_reviews: number;
  findings_proposed: number;
  findings_confirmed: number;
  open_tasks: number;
  overdue_tasks: number;
  severity_distribution: Partial<Record<Severity, number>>;
  job_failures: number;
  coverage: { review_id: string; title: string; reviewed: number; total: number }[];
  coverage_definition: string;
}

export interface AIStatus {
  enabled: boolean;
  provider: string;
  model: string | null;
  available_features: string[];
  is_mock?: boolean;
  note: string;
}

export type AIAssessment = "addressed" | "not_addressed" | "unclear" | "invalid_output";
export type AISuggestionStatus = "pending" | "accepted" | "rejected";

export interface AISuggestion {
  id: string;
  requirement_id: string;
  requirement_code: string;
  requirement_title: string;
  severity: Severity;
  assessment: AIAssessment;
  summary: string;
  evidence: Evidence[];
  rejected_citations: number;
  status: AISuggestionStatus;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string;
  finding_id: string | null;
}

export interface AISuggestionRun {
  id: string;
  provider: string;
  model: string;
  is_mock: boolean;
  prompt_version: string;
  warnings: string[];
  created_at: string;
  finished_at: string | null;
  job: Job;
}

export interface AISuggestions {
  available: boolean;
  run: AISuggestionRun | null;
  suggestions: AISuggestion[];
}
