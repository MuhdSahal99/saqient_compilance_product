/** Phase E continuous assurance: API types (mirroring backend/app/schemas.py) and TanStack Query hooks. */
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "./api";
import type { Assertion, RiskLevel } from "./audit";
import type { CalcStep, DatasetKind } from "./types";

// Every amount below is a Decimal serialised as a string; never parse it to a float.

export type AssuranceStatus = "draft" | "prepared" | "signed_off";

export interface SignOff {
  status: AssuranceStatus;
  version: number;
  prepared_by_name: string | null;
  prepared_at: string | null;
  signed_off_by_name: string | null;
  signed_off_at: string | null;
  reopen_reason: string;
}

export interface AssuranceVersion {
  version: number;
  signed_by_name: string | null;
  signed_at: string;
  sha256: string;
}

/** Steps arrive as plain string maps; the calculation ones carry label / expression / value. */
export type Step = Record<string, string>;
export function asCalcSteps(steps: Step[]): CalcStep[] {
  return steps.map((s) => ({ label: s.label ?? "", expression: s.expression ?? "", value: s.value ?? "" }));
}

// ---------------------------------------------------------------- bank reconciliations

export type ReconSide = "bank" | "book";
export type ReconMethod = "reference" | "amount_date" | "reference_group" | "manual";

export interface ReconItem {
  side: ReconSide;
  row_id: number;
  date: string;
  amount: string;
  reference: string;
  description: string;
  match_id: string | null;
  method: ReconMethod | null;
  age_days: number | null;
  bucket: string | null;
}

export interface ReconMatch {
  id: string;
  method: ReconMethod;
  reason: string;
  bank_row_ids: number[];
  book_row_ids: number[];
  bank_total: string;
  book_total: string;
  difference: string;
  created_by_name: string | null;
  created_at: string;
}

export interface Ageing {
  side: ReconSide;
  bucket: string;
  count: number;
  total: string;
}

export interface BankRecSummary {
  bank_closing_balance: string | null;
  bank_closing_source: "entered" | "statement" | "unknown";
  book_opening_balance: string;
  book_movement: string;
  book_closing_balance: string;
  unmatched_bank_total: string;
  unmatched_book_total: string;
  adjusted_bank: string | null;
  adjusted_book: string;
  difference: string | null;
  bank_items: number;
  book_items: number;
  matched_bank_items: number;
  matched_book_items: number;
  ageing: Ageing[];
  steps: Step[];
}

export interface BankRecListItem {
  id: string;
  entity_id: string;
  entity_name: string;
  name: string;
  account_label: string;
  period_start: string;
  period_end: string;
  currency: string;
  status: AssuranceStatus;
  version: number;
  is_demo: boolean;
  created_at: string;
}

export interface BankRec extends BankRecListItem {
  statement_version_id: string;
  ledger_version_id: string;
  gl_accounts: string[];
  rule_pack_version_id: string;
  rules_prefix: string;
  bank_closing_balance: string | null;
  book_opening_balance: string;
  matcher_version: string;
  matched_at: string | null;
  warnings: string[];
  parameters: Record<string, unknown>;
  sign_off: SignOff;
  summary: BankRecSummary;
  items: ReconItem[];
  matches: ReconMatch[];
  versions: AssuranceVersion[];
}

// ---------------------------------------------------------------- account and intercompany reconciliations

export interface SupportItem {
  description: string;
  amount: string;
  document_id: string | null;
  document_title: string | null;
  note: string;
}

export interface Variance {
  variance: string;
  threshold_abs: string;
  threshold_pct: string;
  exceeds: boolean;
  explanation_required: boolean;
  steps: Step[];
}

export interface AccountRecListItem {
  id: string;
  entity_id: string;
  entity_name: string;
  as_of: string;
  account_code: string;
  account_name: string;
  currency: string;
  tb_balance: string;
  supported: string;
  variance: string;
  exceeds: boolean;
  owner_name: string | null;
  status: AssuranceStatus;
  version: number;
  is_demo: boolean;
}

export interface AccountRec extends AccountRecListItem {
  tb_version_id: string;
  tb_row_ids: number[];
  rule_pack_version_id: string;
  rules_prefix: string;
  explanation: string;
  owner_id: string | null;
  items: SupportItem[];
  check: Variance;
  warnings: string[];
  sign_off: SignOff;
  versions: AssuranceVersion[];
}

export interface IntercompanySide {
  entity_id: string;
  entity_name: string;
  tb_version_id: string;
  accounts: string[];
  balance: string;
  row_ids: number[];
}

export interface Intercompany {
  id: string;
  name: string;
  as_of: string;
  currency: string;
  side_a: IntercompanySide;
  side_b: IntercompanySide;
  difference: string;
  threshold: string;
  exceeds: boolean;
  explanation: string;
  steps: Step[];
  rule_pack_version_id: string;
  rules_prefix: string;
  warnings: string[];
  is_demo: boolean;
  sign_off: SignOff;
  versions: AssuranceVersion[];
}

// ---------------------------------------------------------------- close and flux

export type CloseItemStatus = "open" | "in_progress" | "done" | "cancelled";

export interface CloseItem {
  id: string;
  title: string;
  day_offset: number;
  due_date: string | null;
  owner_id: string | null;
  owner_name: string | null;
  task_id: string;
  status: CloseItemStatus;
  completion_note: string;
  overdue: boolean;
}

export interface ClosePeriod {
  id: string;
  entity_id: string;
  entity_name: string;
  name: string;
  period_end: string;
  status: "open" | "closed";
  closed_by_name: string | null;
  closed_at: string | null;
  note: string;
  items: CloseItem[];
  done: number;
  total: number;
  is_demo: boolean;
}

export interface FluxLine {
  account_code: string;
  account_name: string;
  current: string;
  prior: string;
  change: string;
  change_pct: string | null;
  exceeds: boolean;
  explanation: string;
  explained_by_name: string | null;
  cy_row_ids: number[];
  py_row_ids: number[];
}

export interface Flux {
  id: string;
  entity_id: string;
  entity_name: string;
  name: string;
  as_of: string;
  currency: string;
  cy_tb_version_id: string;
  py_tb_version_id: string;
  rule_pack_version_id: string;
  rules_prefix: string;
  threshold_abs: string;
  threshold_pct: string;
  lines: FluxLine[];
  exceeding: number;
  unexplained: number;
  warnings: string[];
  is_demo: boolean;
  sign_off: SignOff;
  versions: AssuranceVersion[];
}

// ---------------------------------------------------------------- internal controls

export const CONTROL_NATURES = ["preventive", "detective"] as const;
export type ControlNature = (typeof CONTROL_NATURES)[number];
export const CONTROL_AUTOMATIONS = ["manual", "automated", "it_dependent"] as const;
export type ControlAutomation = (typeof CONTROL_AUTOMATIONS)[number];
export const CONTROL_FREQUENCIES = ["multiple_daily", "daily", "weekly", "monthly", "quarterly", "annual", "ad_hoc"] as const;
export type ControlFrequency = (typeof CONTROL_FREQUENCIES)[number];
export const CONTROL_TEST_KINDS = ["design", "operating"] as const;
export type ControlTestKind = (typeof CONTROL_TEST_KINDS)[number];
export const CONTROL_CONCLUSIONS = ["effective", "ineffective"] as const;
export type ControlConclusion = (typeof CONTROL_CONCLUSIONS)[number];
export const DEFICIENCY_CLASSES = ["deficiency", "significant_deficiency", "material_weakness"] as const;
export type DeficiencyClass = (typeof DEFICIENCY_CLASSES)[number];

export interface ControlRisk {
  id: string;
  ref: string;
  description: string;
  assertions: Assertion[];
  rating: RiskLevel;
}

export interface ControlTest {
  id: string;
  control_id: string;
  kind: ControlTestKind;
  period_start: string;
  period_end: string;
  procedure: string;
  sample_size: number;
  exceptions: number;
  evidence: Record<string, unknown>[];
  status: "planned" | "completed";
  conclusion: ControlConclusion | null;
  rationale: string;
  tester_name: string | null;
  completed_at: string | null;
}

export interface Control {
  id: string;
  process_id: string;
  ref: string;
  title: string;
  description: string;
  key: boolean;
  nature: ControlNature;
  automation: ControlAutomation;
  frequency: ControlFrequency;
  owner_id: string | null;
  owner_name: string | null;
  risk_ids: string[];
  design: ControlConclusion | null;
  operating: ControlConclusion | null;
  tests: ControlTest[];
  open_deficiencies: number;
}

export interface ControlProcess {
  id: string;
  entity_id: string;
  entity_name: string;
  name: string;
  description: string;
  owner_id: string | null;
  owner_name: string | null;
  is_demo: boolean;
  risks: ControlRisk[];
  controls: Control[];
  unmitigated_risk_ids: string[];
}

export interface Deficiency {
  id: string;
  control_id: string;
  control_ref: string;
  control_title: string;
  test_id: string | null;
  title: string;
  description: string;
  classification: DeficiencyClass | null;
  rationale: string;
  classified_by_name: string | null;
  classified_at: string | null;
  status: "open" | "remediated";
  remediation_task_id: string | null;
  remediation_note: string;
  created_at: string;
}

export interface Certification {
  id: string;
  entity_id: string;
  entity_name: string;
  period_start: string;
  period_end: string;
  statement: string;
  controls: number;
  key_controls: number;
  tested: number;
  ineffective: number;
  open_deficiencies: Deficiency[];
  unclassified: number;
  is_demo: boolean;
  sign_off: SignOff;
  versions: AssuranceVersion[];
}

// ---------------------------------------------------------------- connectors

export type ConnectorProvider = "zoho_books" | "odoo";
export type ConnectorStatus = "pending" | "connected" | "error" | "disconnected";
export type ConnectorSyncStatus = "queued" | "succeeded" | "unchanged" | "failed";

export interface ConnectorSync {
  id: string;
  kind: DatasetKind;
  status: ConnectorSyncStatus;
  rows: number;
  sha256: string | null;
  dataset_version_id: string | null;
  dataset_version_status: string | null;
  message: string;
  requested_by_name: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Connector {
  id: string;
  entity_id: string;
  entity_name: string;
  provider: ConnectorProvider;
  provider_label: string;
  auth: string;
  name: string;
  status: ConnectorStatus;
  scopes: string[];
  config: Record<string, unknown>;
  has_credentials: boolean;
  kinds: DatasetKind[];
  /** Dataset kind -> dataset id that syncs of this connector write into. */
  datasets: Record<string, string>;
  mapping_status: string;
  last_sync_at: string | null;
  last_error: string;
  syncs: ConnectorSync[];
  created_at: string;
}

export interface ConnectorProviderInfo {
  provider: ConnectorProvider;
  label: string;
  auth: string;
  kinds: DatasetKind[];
  scopes: string[];
  configured: boolean;
  mapping_status: string;
}

export interface ConnectorStatusInfo {
  enabled: boolean;
  providers: ConnectorProviderInfo[];
}

// ---------------------------------------------------------------- query keys and hooks

export const bankRecsKey = ["bank-recs"] as const;
export const accountRecsKey = ["account-recs"] as const;
export const icRecsKey = ["ic-recs"] as const;
export const closesKey = ["close-periods"] as const;
export const fluxKey = ["flux-reviews"] as const;
export const processesKey = ["control-processes"] as const;
export const deficienciesKey = ["deficiencies"] as const;
export const certificationsKey = ["control-certifications"] as const;
export const connectorsKey = ["connectors"] as const;

function useList<T>(key: readonly string[], path: string, enabled = true) {
  return useQuery({ queryKey: [...key, "list"], queryFn: () => api<T[]>(path), enabled });
}
function useOne<T>(key: readonly string[], path: string, id: string | undefined) {
  return useQuery({ queryKey: [...key, "detail", id ?? ""], queryFn: () => api<T>(`${path}/${id}`), enabled: !!id });
}
export const detailKey = (key: readonly string[], id: string) => [...key, "detail", id];

export const useBankRecs = () => useList<BankRecListItem>(bankRecsKey, "/bank-reconciliations");
export const useBankRec = (id?: string) => useOne<BankRec>(bankRecsKey, "/bank-reconciliations", id);
export const useAccountRecs = () => useList<AccountRecListItem>(accountRecsKey, "/account-reconciliations");
export const useAccountRec = (id?: string) => useOne<AccountRec>(accountRecsKey, "/account-reconciliations", id);
export const useIcRecs = () => useList<Intercompany>(icRecsKey, "/intercompany-reconciliations");
export const useIcRec = (id?: string) => useOne<Intercompany>(icRecsKey, "/intercompany-reconciliations", id);
export const useClosePeriods = () => useList<ClosePeriod>(closesKey, "/close-periods");
export const useClosePeriod = (id?: string) => useOne<ClosePeriod>(closesKey, "/close-periods", id);
export const useFluxReviews = () => useList<Flux>(fluxKey, "/flux-reviews");
export const useFluxReview = (id?: string) => useOne<Flux>(fluxKey, "/flux-reviews", id);
export const useProcesses = () => useList<ControlProcess>(processesKey, "/control-processes");
export const useProcess = (id?: string) => useOne<ControlProcess>(processesKey, "/control-processes", id);
export const useDeficiencies = (enabled = true) => useList<Deficiency>(deficienciesKey, "/deficiencies", enabled);
export const useCertifications = () => useList<Certification>(certificationsKey, "/control-certifications");
export const useCertification = (id?: string) => useOne<Certification>(certificationsKey, "/control-certifications", id);
export const useConnectors = (enabled = true) => useList<Connector>(connectorsKey, "/connectors", enabled);

export function useConnectorStatus() {
  return useQuery({ queryKey: [...connectorsKey, "status"], queryFn: () => api<ConnectorStatusInfo>("/connectors/status"), staleTime: 60_000 });
}

/** Export URL of one signed-off version. */
export function exportUrl(base: string, id: string, version: number, format: "html" | "pdf" | "csv"): string {
  return `/api${base}/${id}/versions/${version}/export${qs({ format })}`;
}

// ---------------------------------------------------------------- input patterns

export const ROW_IDS_PATTERN = /^\s*\d+(\s*,\s*\d+)*\s*$/;
export function parseRowIds(value: string): number[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number.parseInt(s, 10));
}
export function parseCodes(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}
export const CODES_PATTERN = /^\s*[^,\s][^,]{0,79}(\s*,\s*[^,\s][^,]{0,79})*\s*$/;
