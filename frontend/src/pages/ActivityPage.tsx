import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api, qs } from "@/lib/api";
import type { AuditEvent, Page } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, Pagination } from "@/components/common";

const OBJECT_TYPES = ["document", "review", "finding", "checklist", "checklist_version", "report", "user", "job"] as const;

function metaSummary(meta: Record<string, unknown>): string {
  return Object.entries(meta)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== "object")
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(" · ");
}

export function ActivityPage() {
  const { t, i18n } = useTranslation();
  const [objectType, setObjectType] = useState("");
  const [page, setPage] = useState(1);
  const events = useQuery({
    queryKey: ["activity", objectType, page],
    queryFn: () => api<Page<AuditEvent>>(`/audit-events${qs({ object_type: objectType, page, page_size: 50 })}`),
  });
  return (
    <>
      <PageHeader
        title={t("activity.title")}
        description={t("activity.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.activity") }]}
      />
      <Card>
        <div className="border-b border-slate-100 p-4">
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
        {events.data?.items.length === 0 && <EmptyState title={t("activity.empty")} />}
        {events.data && events.data.items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("activity.when")}</TH>
                  <TH>{t("activity.who")}</TH>
                  <TH>{t("activity.what")}</TH>
                  <TH>{t("activity.details")}</TH>
                </tr>
              </THead>
              <TBody>
                {events.data.items.map((e) => (
                  <TR key={e.id}>
                    <TD className="whitespace-nowrap text-xs">{formatDate(e.created_at, i18n.language, true)}</TD>
                    <TD>{e.actor_name ?? t("activity.system")}</TD>
                    <TD>{t(`audit.${e.action}`, { defaultValue: e.action })}</TD>
                    <TD className="max-w-md truncate text-xs text-slate-500" title={metaSummary(e.meta)}>
                      {metaSummary(e.meta)}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={50} total={events.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <p className="mt-3 text-xs text-slate-500">{t("activity.notTamperProof")}</p>
    </>
  );
}
