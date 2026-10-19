import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Checklist, LegalEntity, Member, RulePack, TaxPeriod } from "./types";

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
