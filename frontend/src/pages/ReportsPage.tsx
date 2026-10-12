import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, qs } from "@/lib/api";
import type { Page, Report } from "@/lib/types";
import { formatDate } from "@/lib/utils";
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
      <Card>
        {reports.isLoading && <LoadingState />}
        {reports.isError && <ErrorState error={reports.error} onRetry={() => void reports.refetch()} />}
        {reports.data?.items.length === 0 && <EmptyState title={t("reports.empty")} description={t("reports.emptyHint")} />}
        {reports.data && reports.data.items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("reports.review")}</TH>
                  <TH>{t("reports.versionCol")}</TH>
                  <TH>{t("reports.signedOff")}</TH>
                  <TH>{t("reports.export")}</TH>
                </tr>
              </THead>
              <TBody>
                {reports.data.items.map((r) => (
                  <TR key={r.id}>
                    <TD>
                      <Link to={`/reviews/${r.review_id}?tab=reports`} className="font-medium text-navy-900 hover:underline">
                        {r.review_title}
                      </Link>
                      <p className="text-xs text-slate-500">{t("reports.findingCount", { count: r.finding_count })}</p>
                    </TD>
                    <TD className="tabular-nums">v{r.version}</TD>
                    <TD className="text-xs">
                      {r.signed_off_by_name}
                      <br />
                      {formatDate(r.signed_off_at, i18n.language, true)}
                    </TD>
                    <TD>
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
      <p className="mt-3 text-xs text-slate-500">{t("reports.immutableNote")}</p>
    </>
  );
}
