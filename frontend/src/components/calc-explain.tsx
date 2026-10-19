import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { BadgeCheck, ChevronDown, FileCode2, FileText, Sheet, TriangleAlert } from "lucide-react";
import type { CalcStep, RuleSnapshot } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { UnverifiedBadge } from "@/components/common";

/** Shown whenever a calculation used draft (unverified) rules or the backend raised other warnings. */
export function UnverifiedWarnings({ warnings, className }: { warnings: string[]; className?: string }) {
  const { t } = useTranslation();
  if (warnings.length === 0) return null;
  return (
    <div role="status" className={cn("rounded-lg border border-orange-200 bg-orange-50 px-3 py-2.5 text-xs text-orange-900", className)}>
      <p className="mb-1 flex items-center gap-1.5 font-medium">
        <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
        {t("directTax.warningsTitle")}
      </p>
      <p className="mb-1.5 leading-relaxed">{t("directTax.warningsHint")}</p>
      <ul className="list-disc space-y-0.5 ps-5">
        {warnings.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

/** A Decimal string shown as-is (never parsed to a float), left-to-right. */
export function Amount({ value, currency, className }: { value: string | null; currency?: string; className?: string }) {
  if (value == null) return <span className="text-slate-400">—</span>;
  return (
    <span dir="ltr" className={cn("font-mono text-[13px] tabular-nums text-navy-900", className)}>
      {value}
      {currency ? <span className="ms-1 text-slate-400">{currency}</span> : null}
    </span>
  );
}

/** "true"/"false" flags from a calculation, shown in words. */
export function LineValue({ value }: { value: string | null }) {
  const { t } = useTranslation();
  if (value == null) return <span className="text-slate-400">—</span>;
  if (value === "true") return <Badge tone="amber">{t("directTax.yes")}</Badge>;
  if (value === "false") return <Badge tone="neutral">{t("directTax.no")}</Badge>;
  return (
    <span dir="ltr" className="font-mono text-[13px] text-navy-900">
      {value}
    </span>
  );
}

export function CalcSteps({ steps }: { steps: CalcStep[] }) {
  const { t } = useTranslation();
  if (steps.length === 0) return <p className="text-xs text-slate-500">{t("directTax.noSteps")}</p>;
  return (
    <ol className="space-y-1 text-xs">
      {steps.map((s, i) => (
        <li key={i} className="flex flex-wrap items-baseline gap-x-1.5">
          <span className="font-medium text-slate-700">{s.label}:</span>
          <code dir="ltr" className="font-mono text-[11.5px] text-slate-600">
            {s.expression} = {s.value}
          </code>
        </li>
      ))}
    </ol>
  );
}

export function RulesUsed({ rules }: { rules: RuleSnapshot[] }) {
  const { t } = useTranslation();
  if (rules.length === 0) return null;
  return (
    <ul className="space-y-1 text-xs">
      {rules.map((r) => (
        <li key={`${r.rule_pack_version_id}:${r.rule_key}`} className="flex flex-wrap items-center gap-1.5">
          <code dir="ltr" className="font-mono text-[11.5px] text-slate-700">
            {r.rule_key}
          </code>
          <span className="text-slate-500">
            {t("directTax.packVersion", { pack: r.pack_name, version: r.pack_version })}
          </span>
          {r.verification_status === "verified" ? (
            <Badge tone="green">
              <BadgeCheck className="size-3" aria-hidden />
              {t("rulePacks.verifiedBadge")}
            </Badge>
          ) : (
            <UnverifiedBadge />
          )}
        </li>
      ))}
    </ul>
  );
}

/** A calculated line that expands to show its steps, formula id and the rules it read. */
export function ExplainedLine({
  label,
  value,
  formulaId,
  steps,
  rules,
}: {
  label: string;
  value: ReactNode;
  formulaId: string | null;
  steps: CalcStep[];
  rules: RuleSnapshot[];
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const anyDraft = rules.some((r) => r.verification_status !== "verified");
  return (
    <li className="border-b border-slate-100 last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-start transition-colors hover:bg-slate-50"
      >
        <ChevronDown
          className={cn("size-4 shrink-0 text-slate-400 transition-transform duration-150 motion-reduce:transition-none", open ? "rotate-0" : "-rotate-90 rtl:rotate-90")}
          aria-hidden
        />
        <span className="min-w-0 flex-1 text-sm text-navy-900">{label}</span>
        {anyDraft && <UnverifiedBadge className="hidden sm:inline-flex" />}
        <span className="shrink-0">{value}</span>
      </button>
      {open && (
        <div className="space-y-3 bg-slate-50/70 px-4 pb-3 pt-1 ps-11 animate-fade-in motion-reduce:animate-none">
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{t("directTax.steps")}</p>
            <CalcSteps steps={steps} />
          </div>
          {formulaId && (
            <p className="text-xs text-slate-500">
              {t("directTax.formulaId")}{" "}
              <code dir="ltr" className="font-mono text-[11.5px] text-slate-700">
                {formulaId}
              </code>
            </p>
          )}
          {rules.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{t("directTax.rulesUsed")}</p>
              <RulesUsed rules={rules} />
            </div>
          )}
        </div>
      )}
    </li>
  );
}

const linkCls =
  "inline-flex h-8 items-center gap-1.5 px-2.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 hover:text-navy-900 focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-teal-600 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-slate-400";

/** HTML / PDF / CSV export links for one signed-off workpaper snapshot. */
export function SnapshotLinks({ workpaperId, version }: { workpaperId: string; version: number }) {
  const { t } = useTranslation();
  const base = `/api/workpapers/${workpaperId}/snapshots/${version}/export?format=`;
  return (
    <div className="inline-flex items-stretch divide-x divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs rtl:divide-x-reverse">
      <a className={linkCls} href={`${base}html`} target="_blank" rel="noopener noreferrer">
        <FileCode2 aria-hidden />
        {t("reports.html")}
      </a>
      <a className={linkCls} href={`${base}pdf`}>
        <FileText aria-hidden />
        {t("reports.pdf")}
      </a>
      <a className={linkCls} href={`${base}csv`}>
        <Sheet aria-hidden />
        {t("reports.csv")}
      </a>
    </div>
  );
}
