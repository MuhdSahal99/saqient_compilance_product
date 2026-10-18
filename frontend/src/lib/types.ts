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
  entity_id?: string | null;
  entity_name?: string | null;
  tax_period_id?: string | null;
  tax_period_start?: string | null;
  tax_period_end?: string | null;
  einvoice_count?: number;
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

/** A location inside a stored e-invoice XML file. */
export interface XmlEvidence {
  type: "xml";
  einvoice_file_id: string;
  filename: string;
  sha256: string;
  invoice_number: string | null;
  xpath: string;
  line: number | null;
  value: string | null;
  label: string;
  detail: Record<string, unknown>;
}

/** A recomputed figure (expected vs returned) with the formula used. */
export interface ComputationEvidence {
  type: "computation";
  label: string;
  detail: Record<string, unknown>;
}

export type AnyEvidence = Evidence | DatasetRowsEvidence | XmlEvidence | ComputationEvidence;

export function isDatasetEvidence(e: AnyEvidence): e is DatasetRowsEvidence {
  return e.type === "dataset_rows";
}

/** A quote from a document source block (the only evidence type with a block id). */
export function isQuoteEvidence(e: AnyEvidence): e is Evidence {
  return e.type === undefined;
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
  finding_key?: string;
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

export const DATASET_KINDS = [
  "trial_balance",
  "general_ledger",
  "sales_register",
  "purchase_register",
  "bank_statement",
  "customer_master",
  "supplier_master",
  "vat_return",
  "einvoice_rejections",
  "wht_payments",
] as const;
export type DatasetKind = (typeof DATASET_KINDS)[number];
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
  size_basis_amount?: string | null;
  size_basis_currency?: string | null;
  size_basis_year?: number | null;
  einvoice_go_live_override?: string | null;
  einvoice_go_live_note?: string;
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

// ---------------------------------------------------------------- e-invoicing and VAT (Phase B)

export type TaxType = "vat" | "corporate_tax" | "zakat" | "wht";
export type PeriodFrequency = "monthly" | "quarterly" | "annual" | "custom";
export const PERIOD_FREQUENCIES: PeriodFrequency[] = ["monthly", "quarterly", "annual", "custom"];
export type TaxPeriodStatus = "open" | "filed";

export interface TaxPeriod {
  id: string;
  entity_id: string;
  tax_type: TaxType;
  frequency: PeriodFrequency;
  period_start: string;
  period_end: string;
  status: TaxPeriodStatus;
  created_at: string;
}

export const VAT_TREATMENTS = ["standard", "zero_rated", "zero_rated_export", "exempt", "out_of_scope", "reverse_charge", "import"] as const;
export type VatTreatment = (typeof VAT_TREATMENTS)[number];
export const TAX_ACCOUNT_ROLES = ["output_vat", "input_vat", "reverse_charge_output", "reverse_charge_input"] as const;
export type TaxAccountRole = (typeof TAX_ACCOUNT_ROLES)[number];
export type TaxCodeRegister = "sales_register" | "purchase_register";

export interface TaxCode {
  register: TaxCodeRegister;
  tax_code: string;
  treatment: VatTreatment;
  recoverable: boolean;
  description: string;
}

export interface TaxAccount {
  role: TaxAccountRole;
  account_code: string;
}

export interface VatSetup {
  entity_id: string;
  tax_codes: TaxCode[];
  tax_accounts: TaxAccount[];
}

export interface EInvoiceFile {
  id: string;
  batch_id: string;
  entity_id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  profile: string;
  document_type: string;
  invoice_number: string | null;
  invoice_uuid: string | null;
  issue_date: string | null;
  type_code: string | null;
  icv: number | null;
  currency: string | null;
  payable_amount: string | null;
  tax_amount: string | null;
  parse_error: string | null;
  created_at: string;
}

export interface EInvoiceBatch {
  id: string;
  entity_id: string;
  entity_name: string;
  name: string;
  original_filename: string;
  raw_sha256: string;
  file_count: number;
  duplicate_count: number;
  failed_count: number;
  is_demo: boolean;
  created_at: string;
}

export interface EInvoiceBatchDetail extends EInvoiceBatch {
  files: EInvoiceFile[];
}

export type MonitorCadence = "daily" | "weekly" | "monthly";
export type MonitorRunStatus = "review_created" | "no_files" | "failed";

export interface EInvoiceMonitor {
  id: string;
  entity_id: string;
  entity_name: string;
  name: string;
  checklist_version_id: string;
  rule_pack_version_id: string | null;
  sample_size: number;
  cadence: MonitorCadence;
  seed: string;
  is_active: boolean;
  next_run_at: string;
  last_run_at: string | null;
  covered_until: string | null;
  created_at: string;
}

export interface EInvoiceMonitorRun {
  id: string;
  monitor_id: string;
  review_id: string | null;
  window_start: string | null;
  window_end: string;
  population: number;
  sampled: number;
  seed: string;
  sample_method: string;
  status: MonitorRunStatus;
  message: string;
  created_at: string;
}

export type TaskStatus = "open" | "in_progress" | "done" | "cancelled";
export const TASK_STATUSES: TaskStatus[] = ["open", "in_progress", "done", "cancelled"];
export type TaskSource = "tax_obligation" | "manual";

export interface Task {
  id: string;
  source_kind: TaskSource;
  source_id: string | null;
  entity_id: string | null;
  entity_name: string | null;
  title: string;
  description: string;
  owner_id: string | null;
  owner_name: string | null;
  due_date: string | null;
  is_overdue: boolean;
  status: TaskStatus;
  completion_note: string;
  completed_at: string | null;
  created_at: string;
}

export interface TaxObligation {
  id: string;
  entity_id: string;
  entity_name: string;
  tax_period_id: string | null;
  obligation_key: string;
  label: string;
  tax_type: string;
  period_start: string;
  period_end: string;
  due_date: string;
  formula: string;
  rule_key: string;
  rule_pack_version_id: string;
  rule_verified: boolean;
  rule_snapshot: Record<string, unknown>;
  task: Task | null;
}

export interface TaxCalendarResult {
  created: number;
  updated: number;
  unchanged: number;
  periods_created: number;
  warnings: string[];
  obligations: TaxObligation[];
}

// ---------------------------------------------------------------- direct tax (Phase C)

export const WORKPAPER_KINDS = ["corporate_tax", "sbr_test", "qfzp_test", "pillar_two", "zakat"] as const;
export type WorkpaperKind = (typeof WORKPAPER_KINDS)[number];
export type WorkpaperStatus = "draft" | "signed_off";

/** Input categories the backend accepts for each workpaper kind. */
export const WORKPAPER_CATEGORIES: Record<WorkpaperKind, readonly string[]> = {
  corporate_tax: ["input", "non_deductible", "other_add", "exempt_income", "other_deduct", "related_party", "entertainment"],
  sbr_test: ["input"],
  qfzp_test: ["input"],
  pillar_two: [
    "input",
    "globe_income",
    "covered_taxes",
    "payroll",
    "tangible_assets",
    "cbcr_revenue",
    "cbcr_pbt",
    "simplified_taxes",
    "readiness",
  ],
  zakat: ["input", "zakat_addition", "zakat_deduction"],
};

/** One step of an explainable calculation: label: expression = value. */
export interface CalcStep {
  label: string;
  expression: string;
  value: string;
}

/** The rule as it was read for a calculation (immutable rule id + pack version). */
export interface RuleSnapshot {
  rule_id: string;
  rule_key: string;
  value: string | null;
  value_sha256: string | null;
  value_type: string;
  unit: string | null;
  rule_pack_version_id: string;
  pack_name: string;
  pack_version: number;
  verification_status: "draft" | "verified";
  effective_from: string;
  effective_to: string | null;
}

export interface WorkpaperLine {
  id: string;
  source: "manual" | "computed";
  section: string;
  line_key: string;
  category: string;
  label: string;
  ordinal: number;
  /** Decimal, serialised as a string; never parsed to a float. */
  amount: string | null;
  value: string | null;
  formula_id: string | null;
  explanation: CalcStep[];
  rule_snapshots: RuleSnapshot[];
  evidence: Record<string, unknown>[];
  note: string;
}

export interface WorkpaperSnapshot {
  version: number;
  signed_off_by_name: string | null;
  signed_off_at: string;
  result_hash: string | null;
}

export interface WorkpaperSummary {
  id: string;
  entity_id: string;
  entity_name: string;
  kind: WorkpaperKind;
  title: string;
  period_start: string;
  period_end: string;
  currency: string;
  status: WorkpaperStatus;
  computed_at: string | null;
  is_demo: boolean;
  created_at: string;
}

export interface Workpaper extends WorkpaperSummary {
  rule_pack_version_id: string;
  rules_prefix: string;
  calc_version: string | null;
  result_hash: string | null;
  warnings: string[];
  lines: WorkpaperLine[];
  snapshots: WorkpaperSnapshot[];
}

export type LossEntryKind = "incurred" | "used" | "transferred_in" | "transferred_out" | "forfeited";

export interface LossEntry {
  id: string;
  entity_id: string;
  kind: LossEntryKind;
  period_start: string;
  period_end: string;
  amount: string;
  signed_amount: string;
  currency: string;
  workpaper_id: string | null;
  counterparty_entity_id: string | null;
  counterparty_name: string | null;
  transfer_id: string | null;
  explanation: CalcStep[];
  rule_snapshots: RuleSnapshot[];
  evidence: Record<string, unknown>[];
  note: string;
  created_at: string;
}

export interface LossRegister {
  entity_id: string;
  currency: string;
  balance: string;
  entries: LossEntry[];
}

export interface LossPosting {
  created: LossEntry[];
  warnings: string[];
}

export const RELATED_PARTY_RELATIONS = [
  "parent",
  "subsidiary",
  "sister",
  "permanent_establishment",
  "connected_person",
  "other",
] as const;
export type RelatedPartyRelation = (typeof RELATED_PARTY_RELATIONS)[number];

export const RP_TRANSACTION_TYPES = [
  "goods",
  "services",
  "royalties",
  "financing",
  "guarantee",
  "cost_sharing",
  "asset_transfer",
  "other",
] as const;
export type RPTransactionType = (typeof RP_TRANSACTION_TYPES)[number];

export const TP_METHODS = ["not_set", "cup", "resale_price", "cost_plus", "tnmm", "profit_split", "other"] as const;
export type TPMethod = (typeof TP_METHODS)[number];

export interface RelatedParty {
  id: string;
  entity_id: string;
  name: string;
  relation: RelatedPartyRelation;
  jurisdiction: string;
  note: string;
  is_demo: boolean;
}

export interface RPTransaction {
  id: string;
  entity_id: string;
  related_party_id: string;
  related_party_name: string;
  period_start: string;
  period_end: string;
  transaction_type: RPTransactionType;
  direction: "receipt" | "payment";
  description: string;
  amount: string;
  currency: string;
  method: TPMethod;
  range_low: string | null;
  range_high: string | null;
  tested_value: string | null;
  range_metric: string;
  benchmark_documents: Record<string, unknown>[];
  evidence: Record<string, unknown>[];
  is_demo: boolean;
}

export interface CalcLine {
  key: string;
  label: string;
  section: string;
  formula_id: string;
  amount: string | null;
  value: string | null;
  explanation: CalcStep[];
  rule_snapshots: RuleSnapshot[];
}

export interface TPCheckResult {
  currency: string;
  rp_total: string;
  transaction_count: number;
  calc_version: string;
  result_hash: string;
  lines: CalcLine[];
  warnings: string[];
}
