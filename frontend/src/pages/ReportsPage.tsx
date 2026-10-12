import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileCheck2, Lock } from "lucide-react";
import { api, qs } from "@/lib/api";
import type { Page, Report } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/common";
import { ReportLinks } from "@/components/report-links";

export function ReportsPage() {
  const { t, i18n } = useTranslation();
  const [page, setPage] = useState(1);
  const reports = useQuery({ queryKey: ["reports", "all", page], queryFn: () => api<Page<Report>>(`/reports${qs({ page })}`) });
  return (
    <>
      <PageHeader
        title={t("reports.title")}
        description={t("reports.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.reports") }]}
      />
      <Card className="overflow-hidden">
        {reports.isLoading && <LoadingState />}
        {reports.isError && <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />}
        {reports.data?.items.length === 0 && <EmptyState icon={FileCheck2} title={t("reports.empty")} description={t("reports.emptyHint")} />}
        {reports.data && reports.data.items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("reports.review")}</TH>
                  <TH>{t("reports.versionCol")}</TH>
                  <TH>{t("reports.signedOff")}</TH>
                  <TH className="text-end">{t("reports.export")}</TH>
                </tr>
              </THead>
              <TBody>
                {reports.data.items.map((r) => (
                  <TR key={r.id}>
                    <TD>
                      <div className="flex items-center gap-3">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-50 ring-1 ring-slate-200/80">
                          <FileCheck2 className="size-4 text-slate-500" aria-hidden />
                        </span>
                        <div className="min-w-0">
                          <Link to={`/reviews/${r.review_id}?tab=reports`} className="font-medium text-navy-900 transition-colors hover:text-teal-700">
                            {r.review_title}
                          </Link>
                          <p className="mt-0.5 text-xs tabular-nums text-slate-500">{t("reports.findingCount", { count: r.finding_count })}</p>
                        </div>
                      </div>
                    </TD>
                    <TD>
                      <Badge tone="neutral" className="font-mono tabular-nums">
                        v{r.version}
                      </Badge>
                    </TD>
                    <TD>
                      <div className="flex items-center gap-2.5">
                        <Avatar name={r.signed_off_by_name} className="size-7 text-[10px]" />
                        <div className="min-w-0 text-[13px]">
                          <div className="truncate text-slate-700">{r.signed_off_by_name ?? "—"}</div>
                          <div className="whitespace-nowrap text-xs text-slate-500">{formatDate(r.signed_off_at, i18n.language, true)}</div>
                        </div>
                      </div>
                    </TD>
                    <TD className="text-end">
                      <ReportLinks report={r} />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={20} total={reports.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <p className="mt-3 flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <Lock className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
        {t("reports.immutableNote")}
      </p>
    </>
  );
}
