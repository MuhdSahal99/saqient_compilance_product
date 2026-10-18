import { isDatasetEvidence, type AnyEvidence, type Evidence } from "./types";

type T = (k: string, o?: Record<string, unknown>) => string;

export function evidenceLocation(e: Pick<Evidence, "page_number" | "paragraph_number" | "ref">, t: T): string {
  if (e.page_number) return t("evidence.page", { page: e.page_number });
  if (e.paragraph_number) return t("evidence.paragraph", { n: e.paragraph_number });
  return e.ref;
}
/** Short location for any evidence item: page/paragraph, or dataset version and row ids. */
export function anyEvidenceLocation(e: AnyEvidence, t: T): string {
  if (!isDatasetEvidence(e)) return evidenceLocation(e, t);
  const rows = e.row_ids.slice(0, 5).join(", ") + (e.row_count > 5 ? " …" : "");
  return t("evidence.datasetRows", { kind: t(`datasetKind.${e.dataset_kind}`), v: e.version_number, rows });
}

export function evidenceKey(e: AnyEvidence, i: number): string {
  return isDatasetEvidence(e) ? `${e.dataset_version_id}-${e.label}-${i}` : `${e.block_id}-${i}`;
}

