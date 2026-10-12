import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronRight, FileStack, Search, SearchX, Upload } from "lucide-react";
import { api, qs } from "@/lib/api";
import type { DocumentSummary, Page, VersionStatus } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconInput, Select } from "@/components/ui/input";
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
import { DOCUMENT_TYPES, FileTypeTile, UploadDialog } from "@/components/upload-dialog";

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
  const [uploadState, setUploadState] = useState(false);
  // The command palette links to /documents?upload=1 to open the dialog directly.
  const uploadParam = params.get("upload") === "1";
  const uploadOpen = can("write") && (uploadState || uploadParam);
  const uploadedRef = useRef(false);
  const setUploadOpen = (open: boolean) => {
    setUploadState(open);
    if (!open && params.has("upload") && !uploadedRef.current) {
      const next = new URLSearchParams(params);
      next.delete("upload");
      setParams(next, { replace: true });
    }
    if (open) uploadedRef.current = false;
  };
  const filtered = Boolean(q || status || type);

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
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <IconInput
            icon={Search}
            aria-label={t("documents.search")}
            placeholder={t("documents.search")}
            className="min-w-60 flex-1"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setParam("q", e.target.value || undefined);
            }}
          />
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
            icon={filtered ? SearchX : FileStack}
            title={filtered ? t("documents.noMatches") : t("documents.empty")}
            description={filtered ? undefined : t("documents.emptyHint")}
            action={
              can("write") &&
              !q && (
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
                  <TH className="ps-5">{t("documents.titleField")}</TH>
                  <TH>{t("documents.type")}</TH>
                  <TH>{t("documents.status")}</TH>
                  <TH className="text-end">{t("documents.version")}</TH>
                  <TH>{t("documents.updated")}</TH>
                  <TH className="w-10" aria-hidden />
                </tr>
              </THead>
              <TBody>
                {docs.data.items.map((d) => (
                  <TR key={d.id} className="group cursor-pointer" onClick={() => navigate(`/documents/${d.id}`)}>
                    <TD className="ps-5">
                      <div className="flex items-center gap-3">
                        <FileTypeTile format={d.latest_version?.file_format} />
                        <div className="min-w-0">
                          <Link
                            to={`/documents/${d.id}`}
                            className="block truncate font-medium text-navy-900 transition-colors hover:text-teal-700"
                            onClick={(e) => e.stopPropagation()}
                            dir="auto"
                          >
                            {d.title}
                          </Link>
                          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                            {d.latest_version && (
                              <span className="tabular-nums">
                                {d.latest_version.file_format.toUpperCase()} · {formatBytes(d.latest_version.size_bytes)}
                              </span>
                            )}
                            {d.is_demo && <SyntheticBadge />}
                            {d.tags.map((tag) => (
                              <Badge key={tag} className="px-1.5 py-0 text-[11px]">
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      </div>
                    </TD>
                    <TD className="whitespace-nowrap text-[13px]">{t(`documentType.${d.document_type}`, { defaultValue: d.document_type })}</TD>
                    <TD>{d.latest_version && <ProcessingBadge status={d.latest_version.status} />}</TD>
                    <TD className="text-end">
                      <span className="inline-flex items-center rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-medium tabular-nums text-slate-600">
                        v{d.latest_version?.version_number ?? "—"}
                      </span>
                    </TD>
                    <TD className="whitespace-nowrap text-[13px] text-slate-500">
                      <div>{formatDate(d.updated_at, i18n.language)}</div>
                      {d.created_by_name && <div className="text-xs text-slate-400">{d.created_by_name}</div>}
                    </TD>
                    <TD className="pe-4">
                      <ChevronRight className="size-4 text-slate-300 transition-transform group-hover:translate-x-0.5 group-hover:text-slate-500 rtl-flip rtl:group-hover:-translate-x-0.5" aria-hidden />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={20} total={docs.data.total} onPage={(p) => setParam("page", String(p))} />
          </>
        )}
      </Card>
      <UploadDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        onUploaded={(d) => {
          uploadedRef.current = true;
          navigate(`/documents/${d.id}`);
        }}
      />
    </>
  );
}
