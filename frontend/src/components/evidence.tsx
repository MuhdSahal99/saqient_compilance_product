import { useTranslation } from "react-i18next";
import { Calculator, Download, FileCode, Table2 } from "lucide-react";
import type { AnyEvidence, ComputationEvidence, DatasetRowsEvidence, Evidence, XmlEvidence } from "@/lib/types";
import { detailText, evidenceLocation } from "@/lib/evidence";

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

/** Flagged dataset rows, shown with the exact values stored in the dataset version. */
export function DatasetRowsTable({ evidence }: { evidence: DatasetRowsEvidence }) {
  const { t } = useTranslation();
  const detail = Object.entries(evidence.detail ?? {});
  return (
    <figure className="overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-xs">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-3.5 py-2.5 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1.5 font-medium text-slate-700">
          <Table2 className="size-3.5 text-slate-400" aria-hidden />
          {t(`datasetKind.${evidence.dataset_kind}`)} v{evidence.version_number}
          <span className="font-normal text-slate-500">· {evidence.label}</span>
        </span>
        <span className="tabular-nums">
          {evidence.row_count > evidence.rows.length
            ? t("evidence.rowsShown", { shown: evidence.rows.length, total: evidence.row_count })
            : t("evidence.rowCount", { count: evidence.row_count })}
        </span>
      </figcaption>
      {detail.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border-b border-slate-100 px-3.5 py-2 text-xs">
          {detail.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-500">{k}</dt>
              <dd className="font-mono tabular-nums text-slate-800" dir="ltr">
                {v ?? "—"}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {evidence.rows.length > 0 && (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 text-slate-500">
              <tr>
                {evidence.columns.map((c) => (
                  <th key={c} scope="col" className="whitespace-nowrap px-3 py-1.5 text-start font-medium">
                    {c === "row_id" ? t("evidence.row") : c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {evidence.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((v, j) => (
                    <td key={j} className="whitespace-nowrap px-3 py-1.5 font-mono tabular-nums text-slate-700" dir="auto">
                      {v ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </figure>
  );
}

function DetailList({ detail }: { detail: [string, unknown][] }) {
  if (detail.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 px-3.5 py-2 text-xs">
      {detail.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="break-words font-mono tabular-nums text-slate-800" dir="ltr">
            {detailText(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** A location in a stored e-invoice XML file, with a link to download the exact bytes. */
export function XmlEvidenceCard({ evidence }: { evidence: XmlEvidence }) {
  const { t } = useTranslation();
  const detail = Object.entries(evidence.detail ?? {});
  return (
    <figure className="overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-xs">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-3.5 py-2.5 text-xs text-slate-500">
        <span className="inline-flex min-w-0 items-center gap-1.5 font-medium text-slate-700">
          <FileCode className="size-3.5 shrink-0 text-slate-400" aria-hidden />
          <span className="truncate" dir="auto">
            {evidence.invoice_number ?? evidence.filename}
          </span>
          {evidence.invoice_number && (
            <span className="truncate font-normal text-slate-500" dir="ltr">
              · {evidence.filename}
            </span>
          )}
        </span>
        <a
          href={`/api/einvoice-files/${evidence.einvoice_file_id}/download`}
          className="inline-flex items-center gap-1 rounded-md bg-teal-50 px-1.5 py-0.5 font-medium text-teal-700 transition-colors hover:bg-teal-100"
        >
          <Download className="size-3" aria-hidden />
          {t("evidence.downloadXml")}
        </a>
      </figcaption>
      <div className="space-y-1.5 px-3.5 py-2.5 text-xs">
        <p className="text-[13px] text-slate-700">{evidence.label}</p>
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-slate-500">{t("evidence.xpath")}</span>
          <span className="break-all rounded bg-slate-50 px-1.5 py-0.5 font-mono text-[11.5px] text-slate-800 ring-1 ring-slate-200/80" dir="ltr">
            {evidence.xpath}
          </span>
          {evidence.line != null && <span className="text-slate-500">{t("evidence.line", { n: evidence.line })}</span>}
        </p>
        {evidence.value != null && (
          <p className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-slate-500">{t("evidence.value")}</span>
            <span className="break-all font-mono text-slate-800" dir="ltr">
              {evidence.value}
            </span>
          </p>
        )}
      </div>
      {detail.length > 0 && (
        <div className="border-t border-slate-100">
          <DetailList detail={detail} />
        </div>
      )}
      <p className="border-t border-slate-100 px-3.5 py-1.5 font-mono text-[10px] text-slate-400" dir="ltr" title={t("evidence.sha256")}>
        SHA-256 {evidence.sha256}
      </p>
    </figure>
  );
}

const COMPUTATION_ORDER = ["expected", "returned", "gl", "difference", "formula"];

/** A recomputed figure: what the data gives, what was reported, the difference and the formula. */
export function ComputationEvidenceCard({ evidence }: { evidence: ComputationEvidence }) {
  const entries = Object.entries(evidence.detail ?? {});
  const rank = (k: string) => {
    const i = COMPUTATION_ORDER.indexOf(k);
    return i === -1 ? COMPUTATION_ORDER.length : i;
  };
  entries.sort(([a], [b]) => rank(a) - rank(b));
  return (
    <figure className="overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-xs">
      <figcaption className="flex items-center gap-1.5 border-b border-slate-100 px-3.5 py-2.5 text-xs font-medium text-slate-700">
        <Calculator className="size-3.5 text-slate-400" aria-hidden />
        <span dir="auto">{evidence.label}</span>
      </figcaption>
      <DetailList detail={entries} />
    </figure>
  );
}

export function EvidenceItem({ evidence, onLocate }: { evidence: AnyEvidence; onLocate?: (e: Evidence) => void }) {
  switch (evidence.type) {
    case "dataset_rows":
      return <DatasetRowsTable evidence={evidence} />;
    case "xml":
      return <XmlEvidenceCard evidence={evidence} />;
    case "computation":
      return <ComputationEvidenceCard evidence={evidence} />;
    default:
      return <EvidenceQuote evidence={evidence} onLocate={onLocate} />;
  }
}
