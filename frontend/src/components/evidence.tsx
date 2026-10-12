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
    <figure className="relative overflow-hidden rounded-xl border border-slate-200/80 bg-white p-3.5 ps-4 shadow-xs">
      <span className="absolute inset-y-0 start-0 w-[3px] bg-amber-300" aria-hidden />
      <figcaption className="mb-2 flex items-center justify-between gap-2 text-xs text-slate-500">
        {onLocate ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md bg-teal-50 px-1.5 py-0.5 font-medium text-teal-700 transition-colors hover:bg-teal-100"
            onClick={() => onLocate(evidence)}
          >
            {evidenceLocation(evidence, t)}
          </button>
        ) : (
          <span className="font-medium">{evidenceLocation(evidence, t)}</span>
        )}
        <code className="text-[10px] text-slate-400">{evidence.ref}</code>
      </figcaption>
      <blockquote className="text-[13.5px] leading-relaxed text-slate-700" dir="auto">
        {start > 0 && "…"}
        {ctx.slice(0, start)}
        <mark className="evidence">{ctx.slice(start, end)}</mark>
        {ctx.slice(end)}
        {end < ctx.length && "…"}
      </blockquote>
    </figure>
  );
}
