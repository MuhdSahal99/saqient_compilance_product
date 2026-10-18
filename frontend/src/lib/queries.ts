import { useQuery } from "@tanstack/react-query";
import { api, qs } from "./api";
import type {
  Checklist,
  LegalEntity,
  LossRegister,
  Member,
  RelatedParty,
  RPTransaction,
  RulePack,
  TaxPeriod,
  Workpaper,
  WorkpaperSummary,
} from "./types";

/** Active legal entities (same key the entity and dataset pages use). */
export function useEntities(enabled = true) {
  return useQuery({ queryKey: ["entities", { showInactive: false }], queryFn: () => api<LegalEntity[]>("/entities"), enabled });
}

export function useMembers(enabled = true) {
  return useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members"), enabled });
}

/** Published checklist versions, flattened with their checklist. */
export function usePublishedChecklists(enabled = true) {
  const q = useQuery({ queryKey: ["checklists"], queryFn: () => api<Checklist[]>("/checklists"), enabled });
  const items = (q.data ?? []).flatMap((c) => c.versions.filter((v) => v.state === "published").map((v) => ({ c, v })));
  return { query: q, items };
}

/** Published rule pack versions, flattened with their pack. */
export function usePublishedRulePacks(enabled = true) {
  const q = useQuery({ queryKey: ["rule-packs"], queryFn: () => api<RulePack[]>("/rule-packs"), enabled });
  const items = (q.data ?? []).flatMap((p) => p.versions.filter((v) => v.state === "published").map((v) => ({ p, v })));
  return { query: q, items };
}

export const taxPeriodsKey = (entityId: string) => ["tax-periods", entityId] as const;

export function useTaxPeriods(entityId: string | null | undefined) {
  return useQuery({
    queryKey: taxPeriodsKey(entityId ?? ""),
    queryFn: () => api<TaxPeriod[]>(`/entities/${entityId}/tax-periods`),
    enabled: !!entityId,
  });
}

// ---------------------------------------------------------------- direct tax (Phase C)

export const workpapersKey = ["workpapers"] as const;
export const workpaperKey = (id: string) => ["workpapers", "detail", id] as const;
export const lossRegisterKey = (entityId: string) => ["tax-losses", entityId] as const;
export const relatedPartiesKey = (entityId: string) => ["related-parties", entityId] as const;
export const rpTransactionsKey = (entityId: string) => ["rp-transactions", entityId] as const;

export function useWorkpapers(filters: { entityId: string; kind: string }) {
  return useQuery({
    queryKey: [...workpapersKey, "list", filters],
    queryFn: () => api<WorkpaperSummary[]>(`/workpapers${qs({ entity_id: filters.entityId, kind: filters.kind })}`),
  });
}

export function useWorkpaper(id: string | undefined) {
  return useQuery({ queryKey: workpaperKey(id ?? ""), queryFn: () => api<Workpaper>(`/workpapers/${id}`), enabled: !!id });
}

export function useLossRegister(entityId: string) {
  return useQuery({
    queryKey: lossRegisterKey(entityId),
    queryFn: () => api<LossRegister>(`/entities/${entityId}/tax-losses`),
    enabled: !!entityId,
  });
}

export function useRelatedParties(entityId: string) {
  return useQuery({
    queryKey: relatedPartiesKey(entityId),
    queryFn: () => api<RelatedParty[]>(`/entities/${entityId}/related-parties`),
    enabled: !!entityId,
  });
}

export function useRpTransactions(entityId: string) {
  return useQuery({
    queryKey: rpTransactionsKey(entityId),
    queryFn: () => api<RPTransaction[]>(`/entities/${entityId}/rp-transactions`),
    enabled: !!entityId,
  });
}
