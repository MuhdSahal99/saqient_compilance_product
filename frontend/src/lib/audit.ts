/** Phase D audit: API types (mirroring backend/app/schemas.py) and TanStack Query hooks. */
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "./api";
import type { CalcStep, Dataset, DatasetKindSchema, FindingStatus, Review, Severity, WorkpaperSummary } from "./types";

// All amounts and hours below are Decimal values serialised as strings; never parse them to floats.

export const ENGAGEMENT_KINDS = ["external_audit", "internal_audit"] as const;
export type EngagementKind = (typeof ENGAGEMENT_KINDS)[number];
export const ENGAGEMENT_PHASES = ["planning", "fieldwork", "completion", "reporting"] as const;
export type EngagementPhase = (typeof ENGAGEMENT_PHASES)[number];
export const ENGAGEMENT_STATUSES = [...ENGAGEMENT_PHASES, "closed"] as const;
export type EngagementStatus = (typeof ENGAGEMENT_STATUSES)[number];
export const ENGAGEMENT_ROLES = ["partner", "manager", "senior", "staff"] as const;
export type EngagementRole = (typeof ENGAGEMENT_ROLES)[number];
export const FS_SECTIONS = ["asset", "liability", "equity", "income", "expense"] as const;
export type FsSection = (typeof FS_SECTIONS)[number];
export const ASSERTIONS = [
  "existence",
  "occurrence",
  "completeness",
  "accuracy",
  "valuation",
  "cut_off",
  "classification",
  "rights_obligations",
  "presentation",
] as const;
export type Assertion = (typeof ASSERTIONS)[number];
export const RISK_LEVELS = ["low", "medium", "high"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];
export const PROCEDURE_STATUSES = ["not_started", "in_progress", "done"] as const;
export type ProcedureStatus = (typeof PROCEDURE_STATUSES)[number];
export const SAMPLING_METHODS = ["monetary_unit", "random", "stratified"] as const;
export type SamplingMethod = (typeof SAMPLING_METHODS)[number];
export type SampleItemResult = "not_tested" | "no_exception" | "exception";
export const CONFIRMATION_TYPES = ["bank", "receivable", "payable", "legal", "other"] as const;
export type ConfirmationType = (typeof CONFIRMATION_TYPES)[number];
export const CONFIRMATION_STATUSES = ["planned", "sent", "responded", "no_response", "closed"] as const;
export type ConfirmationStatus = (typeof CONFIRMATION_STATUSES)[number];
export type AdjustmentStatus = "proposed" | "recorded" | "passed";
export type PbcStatus = "requested" | "submitted" | "accepted" | "rejected";

export interface EngagementSummary {
  id: string;
  entity_id: string;
  entity_name: string;
  kind: EngagementKind;
  name: string;
  period_start: string;
  period_end: string;
  currency: string;
  status: EngagementStatus;
  is_demo: boolean;
  created_at: string;
}

export interface EngagementMember {
  user_id: string;
  full_name: string;
  email: string;
  role: EngagementRole;
  actual_hours: string;
}

export interface PhaseHours {
  phase: EngagementPhase;
  budget_hours: string;
  actual_hours: string;
  variance_hours: string;
  used_share: string | null;
}

export interface Engagement extends EngagementSummary {
  closed_at: string | null;
  cy_tb_version_id: string | null;
  py_tb_version_id: string | null;
  rule_pack_version_id: string | null;
  rules_prefix: string | null;
  members: EngagementMember[];
  phases: PhaseHours[];
  budget_hours: string;
  actual_hours: string;
}

export interface TimeEntry {
  id: string;
  user_id: string;
  user_name: string;
  phase: EngagementPhase;
  work_date: string;
  hours: string;
  note: string;
}

export interface TbVersionRef {
  id: string;
  dataset_name: string;
  version_number: number;
}

export interface LeadAccount {
  account_code: string;
  account_name: string | null;
  cy: string;
  py: string;
  movement: string;
  change_share: string | null;
  cy_row_ids: number[];
  py_row_ids: number[];
}

export interface LeadLine {
  code: string;
  name: string;
  section: FsSection;
  cy: string;
  py: string;
  movement: string;
  change_share: string | null;
  accounts: LeadAccount[];
}

export interface LeadReport {
  currency: string;
  current: TbVersionRef | null;
  prior: TbVersionRef | null;
  schedules: LeadLine[];
  unmapped: LeadAccount[];
  missing_accounts: string[];
  cy_net: string;
  py_net: string;
}

export interface LeadSchedule {
  code: string;
  name: string;
  section: FsSection;
}

export interface AccountMapping {
  account_code: string;
  lead_code: string;
}

export type AuditWorkpaperSummary = WorkpaperSummary;

export interface Risk {
  id: string;
  ref: string;
  title: string;
  description: string;
  lead_code: string | null;
  assertions: Assertion[];
  inherent_risk: RiskLevel;
  significant: boolean;
  fraud: boolean;
  response: string;
  procedure_ids: string[];
}

export interface Procedure {
  id: string;
  title: string;
  description: string;
  requirement_id: string | null;
  requirement_code: string | null;
  review_id: string | null;
  assignee_id: string | null;
  assignee_name: string | null;
  status: ProcedureStatus;
  conclusion: string;
  completed_at: string | null;
  risk_ids: string[];
}

export interface RiskCoverage {
  risk_id: string;
  ref: string;
  title: string;
  significant: boolean;
  fraud: boolean;
  procedures: number;
  done: number;
}

export interface Coverage {
  risks: RiskCoverage[];
  uncovered: string[];
  significant_open: string[];
  unlinked_procedures: string[];
}

export interface SampleItem {
  row_id: number;
  stratum: number | null;
  hits: number;
  book_value: string;
  audited_value: string | null;
  result: SampleItemResult;
  note: string;
  tested_at: string | null;
}

export interface SampleSummary {
  id: string;
  name: string;
  method: SamplingMethod;
  dataset_version_id: string;
  amount_column: string;
  seed: string;
  params: Record<string, unknown>;
  algorithm_version: string;
  population_count: number;
  population_value: string;
  population_sha256: string;
  risk_id: string | null;
  conclusion: string;
  item_count: number;
  created_at: string;
}

export interface Projection {
  projected: string;
  known: string;
  untested: number;
  steps: CalcStep[];
  performance_materiality: string | null;
  exceeds_performance: boolean | null;
}

export interface Sample extends SampleSummary {
  items: SampleItem[];
  projection: Projection;
}

export interface Reproduce {
  reproducible: boolean;
  population_unchanged: boolean;
  differences: number[];
}

export interface Confirmation {
  id: string;
  type: ConfirmationType;
  counterparty: string;
  reference: string;
  book_amount: string;
  currency: string;
  status: ConfirmationStatus;
  sent_on: string | null;
  responded_on: string | null;
  confirmed_amount: string | null;
  difference: string | null;
  response_document_id: string | null;
  conclusion: string;
}

export interface AdjustmentLine {
  account_code: string;
  debit: string;
  credit: string;
  lead_code: string | null;
  section: FsSection | null;
}

export interface Adjustment {
  id: string;
  ref: string;
  description: string;
  status: AdjustmentStatus;
  reason: string;
  finding_id: string | null;
  lines: AdjustmentLine[];
  profit_effect: string;
  net_assets_effect: string;
  unmapped_accounts: string[];
}

export interface Sud {
  adjustments: Adjustment[];
  profit_effect: string;
  net_assets_effect: string;
  materiality: { workpaper_id?: string; version?: number; overall?: string | null; performance?: string | null; trivial?: string | null } | null;
  clearly_trivial: string[];
  total_vs_overall: "below" | "at_or_above" | "not_determinable";
  steps: CalcStep[];
}

export interface PbcFile {
  document_id: string;
  title: string;
  uploaded_at: string;
}

export interface PbcRequest {
  id: string;
  ref: string;
  title: string;
  description: string;
  due_date: string | null;
  status: PbcStatus;
  client_note: string;
  review_note: string;
  submitted_at: string | null;
  files: PbcFile[];
}

export interface PbcStaffRequest extends PbcRequest {
  assignee_id: string | null;
  assignee_name: string | null;
  overdue: boolean;
}

export interface LetterPoint {
  id: string;
  finding_id: string;
  finding_title: string;
  finding_status: FindingStatus;
  severity: Severity;
  observation: string;
  include: boolean;
  recommendation: string;
  management_response: string;
  response_owner: string;
  response_due: string | null;
  evidence_refs: string[];
}

export interface LetterVersion {
  version: number;
  issued_by_name: string | null;
  issued_at: string;
  points: number;
}

export interface Letter {
  points: LetterPoint[];
  versions: LetterVersion[];
}

// ---------------------------------------------------------------- query keys and hooks

export const engagementsKey = ["engagements"] as const;
export const engagementKey = (id: string) => ["engagements", "detail", id] as const;
/** Everything that belongs to one engagement, so a mutation can refresh it in one call. */
export const engKey = (id: string, part: string) => ["engagements", "detail", id, part] as const;
export const portalKey = ["portal", "requests"] as const;

export function useEngagements(filters: { status: string }) {
  return useQuery({
    queryKey: [...engagementsKey, "list", filters],
    queryFn: () => api<EngagementSummary[]>(`/engagements${qs({ status: filters.status })}`),
  });
}

export function useEngagement(id: string | undefined) {
  return useQuery({ queryKey: engagementKey(id ?? ""), queryFn: () => api<Engagement>(`/engagements/${id}`), enabled: !!id });
}

function useEngPart<T>(id: string, part: string, path: string, enabled = true) {
  return useQuery({ queryKey: engKey(id, part), queryFn: () => api<T>(`/engagements/${id}${path}`), enabled: enabled && !!id });
}

export const useTimeEntries = (id: string) => useEngPart<TimeEntry[]>(id, "time", "/time-entries");
export const useLeadReport = (id: string, enabled = true) => useEngPart<LeadReport>(id, "lead-report", "/lead-report", enabled);
export const useLeadSchedules = (id: string) => useEngPart<LeadSchedule[]>(id, "lead-schedules", "/lead-schedules");
export const useAccountMappings = (id: string) => useEngPart<AccountMapping[]>(id, "mappings", "/account-mappings");
export const useEngagementWorkpapers = (id: string) => useEngPart<AuditWorkpaperSummary[]>(id, "workpapers", "/workpapers");
export const useRisks = (id: string) => useEngPart<Risk[]>(id, "risks", "/risks");
export const useProcedures = (id: string) => useEngPart<Procedure[]>(id, "procedures", "/procedures");
export const useCoverage = (id: string) => useEngPart<Coverage>(id, "coverage", "/risk-coverage");
export const useEngagementReviews = (id: string) => useEngPart<Review[]>(id, "reviews", "/reviews");
export const useSamples = (id: string) => useEngPart<SampleSummary[]>(id, "samples", "/samples");
export const useConfirmations = (id: string) => useEngPart<Confirmation[]>(id, "confirmations", "/confirmations");
export const useAdjustments = (id: string) => useEngPart<Adjustment[]>(id, "adjustments", "/adjustments");
export const useSud = (id: string) => useEngPart<Sud>(id, "sud", "/sud");
export const usePbcRequests = (id: string) => useEngPart<PbcStaffRequest[]>(id, "pbc", "/pbc");
export const useLetter = (id: string) => useEngPart<Letter>(id, "letter", "/letter");

export function useSample(id: string | null) {
  return useQuery({ queryKey: ["samples", id ?? ""], queryFn: () => api<Sample>(`/samples/${id}`), enabled: !!id });
}

/** Datasets of one entity (optionally one kind), with their latest version. */
export function useEntityDatasets(entityId: string, kind?: string) {
  return useQuery({
    queryKey: ["datasets", { entityId, kind: kind ?? "" }],
    queryFn: () => api<Dataset[]>(`/datasets${qs({ entity_id: entityId, kind })}`),
    enabled: !!entityId,
  });
}

export function useDatasetKinds(enabled = true) {
  return useQuery({ queryKey: ["dataset-kinds"], queryFn: () => api<DatasetKindSchema[]>("/dataset-kinds"), staleTime: Infinity, enabled });
}

export function usePortalRequests() {
  return useQuery({ queryKey: portalKey, queryFn: () => api<PbcRequest[]>("/portal/requests") });
}

// ---------------------------------------------------------------- input patterns

export const REF_PATTERN = /^[A-Za-z0-9._-]{1,20}$/;
export const LEAD_CODE_PATTERN = /^[A-Za-z0-9]{1,20}$/;
export const AMOUNT_PATTERN = /^\d{1,16}(\.\d{1,4})?$/;
export const SIGNED_AMOUNT_PATTERN = /^-?\d{1,16}(\.\d{1,4})?$/;
export const HOURS_PATTERN = /^\d{1,6}(\.\d{1,2})?$/;
export const SEED_PATTERN = /^[A-Za-z0-9_-]{4,64}$/;
export const PREFIX_PATTERN = /^[a-z0-9_]+(\.[a-z0-9_]+)*$/;

/** The next phase an engagement can move to, or null when it is closed. */
export function nextStatus(s: EngagementStatus): EngagementStatus | null {
  const i = ENGAGEMENT_STATUSES.indexOf(s);
  return i >= 0 && i < ENGAGEMENT_STATUSES.length - 1 ? (ENGAGEMENT_STATUSES[i + 1] ?? null) : null;
}

export function previousStatus(s: EngagementStatus): EngagementStatus | null {
  const i = ENGAGEMENT_STATUSES.indexOf(s);
  return i > 0 ? (ENGAGEMENT_STATUSES[i - 1] ?? null) : null;
}
