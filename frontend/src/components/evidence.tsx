import { useTranslation } from "react-i18next";
import type { Evidence } from "@/lib/types";

export function evidenceLocation(e: Pick<Evidence, "page_number" | "paragraph_number" | "ref">, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (e.page_number) return t("evidence.page", { page: e.page_number });
  if (e.paragraph_number) return t("evidence.paragraph", { n: e.paragraph_number });
  return e.ref;
}

export function EvidenceQuote({ evidence, onLocate }: { evidence: Evidence; onLocate?: (e: Evidence) => void }) {
  const { t } = useTranslation();
  const ctx = evidence.context ?? evidence.quote;
  const start = evidence.highlight_start ?? 0;
  const end = evidence.highlight_end ?? ctx.length;
  return (
    <figure className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <figcaption className="mb-1.5 flex items-center justify-between gap-2 text-xs text-slate-500">
        {onLocate ? (
          <button type="button" className="font-medium text-teal-700 hover:underline" onClick={() => onLocate(evidence)}>
            {evidenceLocation(evidence, t)}
          </button>
        ) : (
          <span className="font-medium">{evidenceLocation(evidence, t)}</span>
        )}
        <code className="text-[10px] text-slate-400">{evidence.ref}</code>
      </figcaption>
      <blockquote className="text-sm leading-relaxed text-slate-800" dir="auto">
        {start > 0 && "…"}
        {ctx.slice(0, start)}
        <mark className="evidence">{ctx.slice(start, end)}</mark>
        {ctx.slice(end)}
        {end < ctx.length && "…"}
      </blockquote>
    </figure>
  );
}
