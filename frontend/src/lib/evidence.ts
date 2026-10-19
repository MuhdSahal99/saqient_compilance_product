import type { AnyEvidence, Evidence } from "./types";

type T = (k: string, o?: Record<string, unknown>) => string;

export function evidenceLocation(e: Pick<Evidence, "page_number" | "paragraph_number" | "ref">, t: T): string {
  if (e.page_number) return t("evidence.page", { page: e.page_number });
  if (e.paragraph_number) return t("evidence.paragraph", { n: e.paragraph_number });
  return e.ref;
}
/** Short location for any evidence item: page/paragraph, dataset rows, an XML path or a computation label. */
export function anyEvidenceLocation(e: AnyEvidence, t: T): string {
  switch (e.type) {
    case "dataset_rows": {
      const rows = e.row_ids.slice(0, 5).join(", ") + (e.row_count > 5 ? " …" : "");
      return t("evidence.datasetRows", { kind: t(`datasetKind.${e.dataset_kind}`), v: e.version_number, rows });
    }
    case "xml":
      return t("evidence.xmlLocation", { file: e.invoice_number ?? e.filename, xpath: e.xpath });
    case "computation":
      return e.label;
    default:
      return evidenceLocation(e, t);
  }
}

export function evidenceKey(e: AnyEvidence, i: number): string {
  switch (e.type) {
    case "dataset_rows":
      return `${e.dataset_version_id}-${e.label}-${i}`;
    case "xml":
      return `${e.einvoice_file_id}-${e.xpath}-${i}`;
    case "computation":
      return `computation-${e.label}-${i}`;
    default:
      return `${e.block_id}-${i}`;
  }
}

/** Render an arbitrary evidence detail value as plain text (values are exact strings from the server). */
export function detailText(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(detailText).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
