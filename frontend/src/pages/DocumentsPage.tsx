import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Search, Upload } from "lucide-react";
import { api, qs } from "@/lib/api";
import type { DocumentSummary, Page, VersionStatus } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Pagination,
  ProcessingBadge,
  SyntheticBadge,
  useDebounced,
} from "@/components/common";
import { DOCUMENT_TYPES, UploadDialog } from "@/components/upload-dialog";

export function DocumentsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search);
  const status = (params.get("status") as VersionStatus | null) ?? undefined;
  const type = params.get("type") ?? undefined;
  const page = Number(params.get("page") ?? 1);
  const [uploadOpen, setUploadOpen] = useState(false);

  const setParam = (k: string, v: string | undefined) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const docs = useQuery({
    queryKey: ["documents", { q, status, type, page }],
    queryFn: () => api<Page<DocumentSummary>>(`/documents${qs({ q, status, document_type: type, page, page_size: 20 })}`),
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => d.latest_version && ["pending", "processing"].includes(d.latest_version.status))
        ? 2000
        : false,
  });

  return (
    <>
      <PageHeader
        title={t("documents.title")}
        description={t("documents.description_page")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.documents") }]}
        actions={
          can("write") && (
            <Button variant="accent" onClick={() => setUploadOpen(true)}>
              <Upload aria-hidden /> {t("upload.title")}
            </Button>
          )
        }
      />
      <Card>
        <div className="flex flex-wrap gap-3 border-b border-slate-100 p-4">
          <div className="relative min-w-60 flex-1">
            <Search className="pointer-events-none absolute start-3 top-2.5 size-4 text-slate-400" aria-hidden />
            <Input
              aria-label={t("documents.search")}
              placeholder={t("documents.search")}
              className="ps-9"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setParam("q", e.target.value || undefined);
              }}
            />
          </div>
          <Select aria-label={t("documents.statusFilter")} className="w-44" value={status ?? ""} onChange={(e) => setParam("status", e.target.value || undefined)}>
            <option value="">{t("documents.allStatuses")}</option>
            {(["pending", "processing", "ready", "failed"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`processing.${s}`)}
              </option>
            ))}
          </Select>
          <Select aria-label={t("documents.type")} className="w-44" value={type ?? ""} onChange={(e) => setParam("type", e.target.value || undefined)}>
            <option value="">{t("documents.allTypes")}</option>
            {DOCUMENT_TYPES.map((d) => (
              <option key={d} value={d}>
                {t(`documentType.${d}`)}
              </option>
            ))}
          </Select>
        </div>
        {docs.isLoading && <LoadingState />}
        {docs.isError && <ErrorState error={docs.error} onRetry={() => void docs.refetch()} />}
        {docs.data && docs.data.items.length === 0 && (
          <EmptyState
            title={q || status || type ? t("documents.noMatches") : t("documents.empty")}
            description={q || status || type ? undefined : t("documents.emptyHint")}
            action={
              can("write") && !q && (
                <Button variant="accent" onClick={() => setUploadOpen(true)}>
                  <Upload aria-hidden /> {t("upload.title")}
                </Button>
              )
            }
          />
        )}
        {docs.data && docs.data.items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("documents.titleField")}</TH>
                  <TH>{t("documents.type")}</TH>
                  <TH>{t("documents.status")}</TH>
                  <TH>{t("documents.version")}</TH>
                  <TH>{t("documents.updated")}</TH>
                </tr>
              </THead>
              <TBody>
                {docs.data.items.map((d) => (
                  <TR key={d.id} className="cursor-pointer" onClick={() => navigate(`/documents/${d.id}`)}>
                    <TD>
                      <Link to={`/documents/${d.id}`} className="font-medium text-navy-900 hover:underline" onClick={(e) => e.stopPropagation()}>
                        {d.title}
                      </Link>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        {d.latest_version && (
                          <span>
                            {d.latest_version.file_format.toUpperCase()} · {formatBytes(d.latest_version.size_bytes)}
                          </span>
                        )}
                        {d.is_demo && <SyntheticBadge />}
                        {d.tags.map((tag) => (
                          <Badge key={tag}>{tag}</Badge>
                        ))}
                      </div>
                    </TD>
                    <TD>{t(`documentType.${d.document_type}`, { defaultValue: d.document_type })}</TD>
                    <TD>{d.latest_version && <ProcessingBadge status={d.latest_version.status} />}</TD>
                    <TD className="tabular-nums">v{d.latest_version?.version_number ?? "—"}</TD>
                    <TD className="whitespace-nowrap">{formatDate(d.updated_at, i18n.language)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={20} total={docs.data.total} onPage={(p) => setParam("page", String(p))} />
          </>
        )}
      </Card>
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} onUploaded={(d) => navigate(`/documents/${d.id}`)} />
    </>
  );
}
