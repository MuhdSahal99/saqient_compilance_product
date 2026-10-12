import { useTranslation } from "react-i18next";
import { FileCode2, FileText, Sheet } from "lucide-react";
import type { Report } from "@/lib/types";
import { cn } from "@/lib/utils";

const item =
  "inline-flex h-8 items-center gap-1.5 px-2.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 hover:text-navy-900 focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-teal-600 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-slate-400";

/** Export links for one report version (HTML opens in a new tab; PDF and CSV download). */
export function ReportLinks({ report, className }: { report: Report; className?: string }) {
  const { t } = useTranslation();
  const base = `/api/reports/${report.id}/export?format=`;
  return (
    <div
      className={cn(
        "inline-flex items-stretch divide-x divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs rtl:divide-x-reverse",
        className,
      )}
    >
      <a className={item} href={`${base}html`} target="_blank" rel="noopener noreferrer">
        <FileCode2 aria-hidden />
        {t("reports.html")}
      </a>
      <a className={item} href={`${base}pdf`}>
        <FileText aria-hidden />
        {t("reports.pdf")}
      </a>
      <a className={item} href={`${base}csv`}>
        <Sheet aria-hidden />
        {t("reports.csv")}
      </a>
    </div>
  );
}
