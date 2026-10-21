/** Phase G multi-agent AI tasks: API types (mirroring backend/app/schemas.py) and TanStack Query hooks. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { Evidence, Job } from "./types";

export type AITaskKind = "contract_tax" | "finding_explain" | "letter_draft" | "pack_qa";
export type AITaskStatus = "running" | "ready" | "failed" | "accepted" | "dismissed";
export type AILanguage = "en" | "ar";

export interface AIAgent {
  name: string;
  tier: "reasoning" | "fast";
  model: string;
}

export interface AITaskStep {
  ordinal: number;
  agent: string;
  tier: string;
  provider: string;
  model: string;
  model_version: string;
  status: "ok" | "invalid_output" | "provider_error";
  duration_ms: number;
  input_tokens: number | null;
  output_tokens: number | null;
  note: string;
}

export interface ContractItem {
  topic: "vat_treatment" | "related_party";
  cue: string;
  summary: string;
  question_for_reviewer: string;
  evidence: Evidence[];
  checked: boolean;
}

export interface QASource {
  type: "rule" | "requirement";
  id: string;
  key: string;
  title: string;
  label: string;
}

/** Output shapes per task kind; every field is optional because a task may still be running. */
export interface AITaskOutput {
  items?: ContractItem[];
  explanation_en?: string;
  explanation_ar?: string;
  next_steps_en?: string[];
  next_steps_ar?: string[];
  evidence_used?: string[];
  implication?: string;
  recommendation?: string;
  question?: string;
  language?: AILanguage;
  answer?: string;
  insufficient?: boolean;
  sources?: QASource[];
  note?: string;
  checked?: boolean;
}

export interface AITask {
  id: string;
  kind: AITaskKind;
  subject_type: string;
  subject_id: string;
  question: string;
  language: AILanguage;
  status: AITaskStatus;
  provider: string;
  is_mock: boolean;
  prompt_version: string;
  output: AITaskOutput;
  warnings: string[];
  error: string;
  requested_by_name: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string;
  created_at: string;
  finished_at: string | null;
  steps: AITaskStep[];
  job: Job;
}

export interface AITaskRequest {
  kind: AITaskKind;
  subject_id?: string;
  question?: string;
  language?: AILanguage;
}

export const aiTasksKey = ["ai-tasks"] as const;

export function useAIAgents() {
  return useQuery({ queryKey: ["ai-agents"], queryFn: () => api<AIAgent[]>("/ai/agents") });
}

const isRunning = (t: AITask) => t.status === "running" && (t.job.status === "queued" || t.job.status === "running");

/** Tasks, newest first; polls while any of them is still running. */
export function useAITasks(params: { kind?: AITaskKind; subjectId?: string; limit?: number } = {}, enabled = true) {
  const search = new URLSearchParams();
  if (params.kind) search.set("kind", params.kind);
  if (params.subjectId) search.set("subject_id", params.subjectId);
  search.set("limit", String(params.limit ?? 20));
  return useQuery({
    queryKey: [...aiTasksKey, params.kind ?? "", params.subjectId ?? "", params.limit ?? 20],
    queryFn: () => api<AITask[]>(`/ai/tasks?${search.toString()}`),
    enabled,
    refetchInterval: (q) => (q.state.data?.some(isRunning) ? 1500 : false),
  });
}

export function useRunAITask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AITaskRequest) => api<AITask>("/ai/tasks", { json: body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: aiTasksKey }),
  });
}

export function useDecideAITask(task: AITask, onDone?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ decision, note }: { decision: "accept" | "dismiss"; note: string }) =>
      api<AITask>(`/ai/tasks/${task.id}/${decision}`, { json: { note } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: aiTasksKey });
      onDone?.();
    },
  });
}
