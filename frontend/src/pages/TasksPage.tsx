import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, qs } from "@/lib/api";
import type { Finding, Page } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { BellOff, CalendarClock, CheckCircle2, ChevronRight } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  FindingStatusBadge,
  LoadingState,
  PageHeader,
  Pagination,
  SEVERITY_COLOR,
  SeverityBadge,
} from "@/components/common";

type Scope = "mine" | "all";

export function TasksPage() {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const [scope, setScope] = useState<Scope>("mine");
  const [overdue, setOverdue] = useState(params.get("overdue") === "1");
  const [page, setPage] = useState(1);
  const tasks = useQuery({
    queryKey: ["findings", "tasks", { scope, overdue, page }],
    queryFn: () =>
      api<Page<Finding>>(
        `/findings${qs({
          status: ["remediation_in_progress", "ready_for_rereview"],
          owner: scope === "mine" ? "me" : undefined,
          overdue,
          sort: "due_date",
          page,
          page_size: 25,
        })}`,
      ),
  });
  return (
    <>
      <PageHeader
        title={t("tasks.title")}
        description={t("tasks.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.tasks") }]}
      />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-3">
          <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
            {(["mine", "all"] as const).map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={scope === s}
                onClick={() => {
                  setScope(s);
                  setPage(1);
                }}
                className={cn(
                  "rounded-md px-3 py-1.5 text-[13px] font-medium transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600",
                  scope === s ? "bg-white text-navy-900 shadow-xs ring-1 ring-slate-200/80" : "text-slate-600 hover:text-navy-900",
                )}
              >
                {t(`tasks.scope.${s}`)}
              </button>
            ))}
          </div>
          <label
            className={cn(
              "ms-auto flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-medium transition-colors",
              overdue ? "border-red-200 bg-red-50 text-red-700" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
            )}
          >
            <input
              type="checkbox"
              className="size-3.5 accent-red-600"
              checked={overdue}
              onChange={(e) => {
                setOverdue(e.target.checked);
                setPage(1);
              }}
            />
            {t("tasks.overdueOnly")}
          </label>
        </div>
        {tasks.isLoading && <LoadingState />}
        {tasks.isError && <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />}
        {tasks.data?.items.length === 0 && <EmptyState icon={CheckCircle2} title={t("tasks.empty")} description={t("tasks.emptyHint")} />}
        {tasks.data && tasks.data.items.length > 0 && (
          <>
            <ul className="divide-y divide-slate-100">
              {tasks.data.items.map((f) => (
                <li
                  key={f.id}
                  className={cn(
                    "group relative grid gap-3 px-5 py-4 transition-colors hover:bg-slate-50/80 md:grid-cols-[minmax(0,1fr)_auto_11rem_10rem] md:items-center md:gap-5",
                    f.is_overdue && "bg-red-50/40 hover:bg-red-50/60",
                  )}
                >
                  <span
                    className="absolute inset-y-3 start-0 w-[3px] rounded-e-full"
                    style={{ backgroundColor: SEVERITY_COLOR[f.severity] }}
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <Link
                      to={`/reviews/${f.review_id}?finding=${f.id}`}
                      className="font-medium text-navy-900 transition-colors after:absolute after:inset-0 hover:text-teal-700"
                    >
                      {f.title}
                    </Link>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={f.severity} />
                      <span className="truncate text-xs text-slate-500">{f.review_title}</span>
                    </div>
                  </div>
                  <div>
                    <FindingStatusBadge status={f.status} />
                  </div>
                  <div className="flex min-w-0 items-center gap-2 text-[13px] text-slate-700">
                    <Avatar name={f.owner_name} className="size-6 text-[10px]" />
                    <span className="truncate">{f.owner_name ?? "—"}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px]",
                        f.is_overdue ? "font-medium text-red-700" : "text-slate-600",
                      )}
                    >
                      <CalendarClock className={cn("size-3.5", f.is_overdue ? "text-red-500" : "text-slate-400")} aria-hidden />
                      {formatDate(f.due_date, i18n.language)}
                      {f.is_overdue && <Badge tone="red">{t("findings.overdue")}</Badge>}
                    </span>
                    <ChevronRight className="hidden size-4 text-slate-300 transition-colors group-hover:text-slate-500 md:block rtl-flip" aria-hidden />
                  </div>
                </li>
              ))}
            </ul>
            <Pagination page={page} pageSize={25} total={tasks.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <p className="mt-3 flex items-center gap-2 text-xs text-slate-500">
        <BellOff className="size-3.5 shrink-0 text-slate-400" aria-hidden />
        {t("tasks.noNotifications")}
      </p>
    </>
  );
}
