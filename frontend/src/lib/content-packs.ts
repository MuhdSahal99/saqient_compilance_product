/** Phase F sector content packs: API types (mirroring backend/app/schemas.py) and TanStack Query hooks. */
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { DatasetKind, Severity } from "./types";

export const PACK_SECTORS = ["financial_services", "banking", "insurance", "listed_companies", "sustainability", "corporate"] as const;
export type PackSector = (typeof PACK_SECTORS)[number];

export interface PackRequirement {
  code: string;
  title: string;
  category: string;
  severity: Severity;
  check_type: string;
}

export interface PackChecklist {
  name: string;
  requirements: PackRequirement[];
}

export interface PackInstall {
  id: string;
  pack_version: string;
  manifest_sha256: string;
  checklist_version_ids: string[];
  rule_pack_version_id: string | null;
  installed_by_name: string | null;
  created_at: string;
}

export interface ContentPack {
  id: string;
  version: string;
  title: string;
  sector: PackSector;
  jurisdiction: string;
  status: string;
  synthetic: boolean;
  disclaimer: string;
  description: string;
  dataset_kinds: DatasetKind[];
  open_questions: string[];
  manifest_sha256: string;
  checklists: PackChecklist[];
  rule_count: number;
  installs: PackInstall[];
}

export const contentPacksKey = ["content-packs"] as const;

export function useContentPacks() {
  return useQuery({ queryKey: [...contentPacksKey, "list"], queryFn: () => api<ContentPack[]>("/content-packs") });
}

export function useContentPack(id?: string) {
  return useQuery({
    queryKey: [...contentPacksKey, "detail", id ?? ""],
    queryFn: () => api<ContentPack>(`/content-packs/${encodeURIComponent(id ?? "")}`),
    enabled: !!id,
  });
}

export const requirementCount = (p: ContentPack) => p.checklists.reduce((n, c) => n + c.requirements.length, 0);

// ---------------------------------------------------------------- org AI opt-in

export interface OrgAISettings {
  deployment_available: boolean;
  provider: string;
  model: string | null;
  is_mock: boolean;
  opted_in: boolean;
  opted_in_at: string | null;
}

export const aiSettingsKey = ["org-ai-settings"] as const;

export function useOrgAISettings() {
  return useQuery({ queryKey: aiSettingsKey, queryFn: () => api<OrgAISettings>("/org/ai-settings") });
}
