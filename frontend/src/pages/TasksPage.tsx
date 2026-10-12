import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, qs } from "@/lib/api";
import type { Finding, Page } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, FindingStatusBadge, LoadingState, PageHeader, Pagination, SeverityBadge } from "@/components/common";

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
      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-4">
          {(["mine", "all"] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={scope === s}
              onClick={() => {
                setScope(s);
                setPage(1);
              }}
              className={cn("rounded-full px-3 py-1 text-sm", scope === s ? "bg-navy-800 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200")}
            >
              {t(`tasks.scope.${s}`)}
            </button>
          ))}
          <label className="ms-auto flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
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
        {tasks.data?.items.length === 0 && <EmptyState title={t("tasks.empty")} description={t("tasks.emptyHint")} />}
        {tasks.data && tasks.data.items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("findings.titleField")}</TH>
                  <TH>{t("findings.severity")}</TH>
                  <TH>{t("findings.status")}</TH>
                  <TH>{t("findings.owner")}</TH>
                  <TH>{t("findings.dueDate")}</TH>
                </tr>
              </THead>
              <TBody>
                {tasks.data.items.map((f) => (
                  <TR key={f.id} className={f.is_overdue ? "bg-red-50/40" : undefined}>
                    <TD>
                      <Link to={`/reviews/${f.review_id}?finding=${f.id}`} className="font-medium text-navy-900 hover:underline">
                        {f.title}
                      </Link>
                      <p className="text-xs text-slate-500">{f.review_title}</p>
                    </TD>
                    <TD>
                      <SeverityBadge severity={f.severity} />
                    </TD>
                    <TD>
                      <FindingStatusBadge status={f.status} />
                    </TD>
                    <TD>{f.owner_name ?? "—"}</TD>
                    <TD className="whitespace-nowrap">
                      {formatDate(f.due_date, i18n.language)}
                      {f.is_overdue && (
                        <Badge tone="red" className="ms-1">
                          {t("findings.overdue")}
                        </Badge>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={25} total={tasks.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <p className="mt-3 text-xs text-slate-500">{t("tasks.noNotifications")}</p>
    </>
  );
}
