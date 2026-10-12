import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Activity,
  Cog,
  FileCheck2,
  FileText,
  Filter,
  Info,
  ListChecks,
  ClipboardCheck,
  ClipboardList,
  User,
  Layers,
  type LucideIcon,
} from "lucide-react";
import { api, qs } from "@/lib/api";
import type { AuditEvent, Page } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";
import { Avatar } from "@/components/ui/avatar";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/common";

const OBJECT_TYPES = ["document", "review", "finding", "checklist", "checklist_version", "report", "user", "job"] as const;

const OBJECT_ICON: Record<string, { icon: LucideIcon; tone: string }> = {
  document: { icon: FileText, tone: "bg-sky-50 text-sky-700 ring-sky-200/80" },
  review: { icon: ClipboardCheck, tone: "bg-teal-50 text-teal-700 ring-teal-200/80" },
  finding: { icon: ListChecks, tone: "bg-amber-50 text-amber-700 ring-amber-200/80" },
  checklist: { icon: ClipboardList, tone: "bg-indigo-50 text-indigo-700 ring-indigo-200/80" },
  checklist_version: { icon: Layers, tone: "bg-indigo-50 text-indigo-700 ring-indigo-200/80" },
  report: { icon: FileCheck2, tone: "bg-emerald-50 text-emerald-700 ring-emerald-200/80" },
  user: { icon: User, tone: "bg-slate-50 text-slate-600 ring-slate-200" },
  job: { icon: Cog, tone: "bg-slate-50 text-slate-600 ring-slate-200" },
};
const FALLBACK_ICON = { icon: Activity, tone: "bg-slate-50 text-slate-600 ring-slate-200" };

function metaSummary(meta: Record<string, unknown>): string {
  return Object.entries(meta)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(" · ");
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

function relativeTime(value: string, locale: string): string {
  const diff = (new Date(value).getTime() - Date.now()) / 1000;
  if (Number.isNaN(diff)) return "";
  const rtf = new Intl.RelativeTimeFormat(locale === "ar" ? "ar" : "en", { numeric: "auto" });
  for (const [unit, secs] of UNITS) {
    if (Math.abs(diff) >= secs || unit === "second") return rtf.format(Math.round(diff / secs), unit);
  }
  return "";
}

function formatTime(value: string, locale: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat(locale === "ar" ? "ar" : "en-GB", { timeStyle: "short" }).format(d);
}

function dayKey(value: string): string {
  const d = new Date(value);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export function ActivityPage() {
  const { t, i18n } = useTranslation();
  const [objectType, setObjectType] = useState("");
  const [page, setPage] = useState(1);
  const events = useQuery({
    queryKey: ["activity", objectType, page],
    queryFn: () => api<Page<AuditEvent>>(`/audit-events${qs({ object_type: objectType, page, page_size: 50 })}`),
  });

  // Group consecutive events by calendar day (the API returns newest first).
  const groups: { key: string; label: string; items: AuditEvent[] }[] = [];
  for (const e of events.data?.items ?? []) {
    const key = dayKey(e.created_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) last.items.push(e);
    else groups.push({ key, label: formatDate(e.created_at, i18n.language), items: [e] });
  }

  return (
    <>
      <PageHeader
        title={t("activity.title")}
        description={t("activity.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.activity") }]}
      />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <Filter className="ms-1 size-4 text-slate-400" aria-hidden />
          <Select
            aria-label={t("activity.filter")}
            className="w-56"
            value={objectType}
            onChange={(e) => {
              setObjectType(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t("activity.allObjects")}</option>
            {OBJECT_TYPES.map((o) => (
              <option key={o} value={o}>
                {t(`activity.object.${o}`)}
              </option>
            ))}
          </Select>
        </div>
        {events.isLoading && <LoadingState />}
        {events.isError && <ErrorState error={events.error} onRetry={() => void events.refetch()} />}
        {events.data?.items.length === 0 && <EmptyState icon={Activity} title={t("activity.empty")} />}
        {groups.length > 0 && (
          <>
            <div className="px-5 py-2">
              {groups.map((g) => (
                <section key={g.key} aria-label={g.label} className="py-3">
                  <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{g.label}</h2>
                  <ol className="relative">
                    {g.items.map((e, i) => {
                      const { icon: Icon, tone } = OBJECT_ICON[e.object_type] ?? FALLBACK_ICON;
                      const meta = metaSummary(e.meta);
                      const actor = e.actor_name ?? t("activity.system");
                      const isLast = i === g.items.length - 1;
                      return (
                        <li key={e.id} className="relative flex gap-4 pb-5 last:pb-1">
                          {!isLast && <span className="absolute start-[17px] top-9 bottom-0 w-px bg-slate-200" aria-hidden />}
                          <span
                            className={cn("relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full ring-1", tone)}
                            title={OBJECT_TYPES.includes(e.object_type as (typeof OBJECT_TYPES)[number]) ? t(`activity.object.${e.object_type}`) : e.object_type}
                          >
                            <Icon className="size-4" aria-hidden />
                          </span>
                          <div className="min-w-0 flex-1 pt-1">
                            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
                              <p className="flex min-w-0 flex-wrap items-center gap-x-1.5 text-sm">
                                {e.actor_name ? (
                                  <Avatar name={e.actor_name} className="size-5 text-[9px]" />
                                ) : (
                                  <Cog className="size-4 text-slate-400" aria-hidden />
                                )}
                                <span className="font-medium text-navy-900">{actor}</span>
                                <span className="text-slate-600">{t(`audit.${e.action}`, { defaultValue: e.action })}</span>
                              </p>
                              <time
                                dateTime={e.created_at}
                                title={formatDate(e.created_at, i18n.language, true)}
                                className="shrink-0 text-xs tabular-nums whitespace-nowrap text-slate-500"
                              >
                                {relativeTime(e.created_at, i18n.language)}
                                <span className="text-slate-300"> · </span>
                                {formatTime(e.created_at, i18n.language)}
                              </time>
                            </div>
                            {meta && (
                              <p className="mt-1 truncate font-mono text-[11px] text-slate-500" title={meta}>
                                {meta}
                              </p>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                </section>
              ))}
            </div>
            <Pagination page={page} pageSize={50} total={events.data!.total} onPage={setPage} />
          </>
        )}
      </Card>
      <p className="mt-3 flex items-start gap-2 text-xs text-slate-500">
        <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
        {t("activity.notTamperProof")}
      </p>
    </>
  );
}
