import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertTriangle, ClipboardCheck, Download, FilePlus2, RotateCw, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { DocumentDetail, Job, Page, SourceBlock } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  errorMessage,
  LoadingState,
  PageHeader,
  ProcessingBadge,
  ProgressBar,
  SyntheticBadge,
  useDebounced,
  useUnsavedChangesWarning,
} from "@/components/common";
import { DOCUMENT_TYPES, UploadDialog } from "@/components/upload-dialog";
import { evidenceLocation } from "@/components/evidence";

const metaSchema = z.object({
  title: z.string().trim().min(1).max(300),
  description: z.string().max(5000),
  document_type: z.string().min(1),
  tags: z.string().max(1000),
});
type MetaValues = z.infer<typeof metaSchema>;

function MetadataForm({ doc }: { doc: DocumentDetail }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<MetaValues>({
    resolver: zodResolver(metaSchema),
    defaultValues: { title: doc.title, description: doc.description, document_type: doc.document_type, tags: doc.tags.join(", ") },
  });
  useUnsavedChangesWarning(form.formState.isDirty);
  const save = useMutation({
    mutationFn: (v: MetaValues) =>
      api<DocumentDetail>(`/documents/${doc.id}`, {
        method: "PATCH",
        json: { ...v, tags: v.tags.split(",").map((s) => s.trim()).filter(Boolean) },
      }),
    onSuccess: (d) => {
      qc.setQueryData(["document", doc.id], d);
      void qc.invalidateQueries({ queryKey: ["documents"] });
      form.reset({ title: d.title, description: d.description, document_type: d.document_type, tags: d.tags.join(", ") });
      toast.success(t("common.saved"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  return (
    <form className="space-y-3" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="meta-title">{t("documents.titleField")}</Label>
        <Input id="meta-title" aria-invalid={!!form.formState.errors.title} {...form.register("title")} />
        <FieldError message={form.formState.errors.title ? t("upload.titleRequired") : undefined} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="meta-type">{t("documents.type")}</Label>
          <Select id="meta-type" {...form.register("document_type")}>
            {DOCUMENT_TYPES.map((d) => (
              <option key={d} value={d}>
                {t(`documentType.${d}`)}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="meta-tags">{t("documents.tags")}</Label>
          <Input id="meta-tags" {...form.register("tags")} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="meta-desc">{t("documents.description")}</Label>
        <Textarea id="meta-desc" rows={2} {...form.register("description")} />
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" disabled={!form.formState.isDirty || save.isPending}>
          {t("common.save")}
        </Button>
        {form.formState.isDirty && <span className="text-xs text-amber-700">{t("common.unsavedBadge")}</span>}
      </div>
    </form>
  );
}

function BlocksViewer({ versionId, isPdf }: { versionId: string; isPdf: boolean }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const blocks = useQuery({
    queryKey: ["blocks", versionId, q],
    queryFn: () => api<Page<SourceBlock>>(`/document-versions/${versionId}/blocks${qs({ q, page_size: 500 })}`),
  });
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <div>
          <CardTitle>{t("documents.extractedText")}</CardTitle>
          <CardDescription>{isPdf ? t("documents.refsPdf") : t("documents.refsParagraph")}</CardDescription>
        </div>
        <div className="relative w-64">
          <Search className="pointer-events-none absolute start-3 top-2.5 size-4 text-slate-400" aria-hidden />
          <Input aria-label={t("documents.searchText")} placeholder={t("documents.searchText")} className="ps-9" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </CardHeader>
      <CardContent className="max-h-[32rem] space-y-2 overflow-y-auto">
        {blocks.isLoading && <LoadingState />}
        {blocks.isError && <ErrorState error={blocks.error} onRetry={() => void blocks.refetch()} />}
        {blocks.data?.items.length === 0 && <p className="py-6 text-center text-sm text-slate-500">{t("documents.noBlocks")}</p>}
        {blocks.data?.items.map((b) => (
          <div key={b.id} id={`block-${b.id}`} className="grid grid-cols-[6.5rem_1fr] gap-3 border-b border-slate-100 pb-2 text-sm">
            <div className="text-xs text-slate-500">
              <div className="font-medium">{evidenceLocation(b, t)}</div>
              <code className="text-[10px] text-slate-400">{b.ref}</code>
            </div>
            <div>
              {b.section_heading && b.section_heading !== b.text && <p className="text-xs font-medium text-slate-500">{b.section_heading}</p>}
              <p className="whitespace-pre-wrap text-slate-800" dir="auto">
                {b.text}
              </p>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function DocumentDetailPage() {
  const { documentId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [versionOpen, setVersionOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const doc = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api<DocumentDetail>(`/documents/${documentId}`),
    refetchInterval: (query) => {
      const s = query.state.data?.latest_version?.status;
      return s === "pending" || s === "processing" ? 1500 : false;
    },
  });
  const latest = doc.data?.latest_version;

  useEffect(() => {
    if (latest?.status === "ready") void qc.invalidateQueries({ queryKey: ["blocks", latest.id] });
  }, [latest?.status, latest?.id, qc]);

  const retry = useMutation({
    mutationFn: () => api<Job>(`/document-versions/${latest!.id}/retry`, { method: "POST" }),
    onSuccess: () => {
      toast.info(t("documents.retryQueued"));
      void doc.refetch();
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const cancel = useMutation({
    mutationFn: (jobId: string) => api<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: () => void doc.refetch(),
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const remove = useMutation({
    mutationFn: () => api(`/documents/${documentId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success(t("documents.deleted"));
      void qc.invalidateQueries({ queryKey: ["documents"] });
      navigate("/documents");
    },
    onError: (e) => {
      setConfirmDelete(false);
      toast.error(errorMessage(e, t("common.genericError")));
    },
  });

  if (doc.isLoading) return <LoadingState />;
  if (doc.isError) return <ErrorState error={doc.error} onRetry={() => void doc.refetch()} />;
  const d = doc.data!;
  const job = d.latest_job;
  const processing = latest && (latest.status === "pending" || latest.status === "processing");

  return (
    <>
      <PageHeader
        title={d.title}
        crumbs={[{ label: t("nav.documents"), to: "/documents" }, { label: d.title }]}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {d.is_demo && <SyntheticBadge />}
            {t(`documentType.${d.document_type}`, { defaultValue: d.document_type })} · {t("documents.uploadedBy", { name: d.created_by_name ?? "—" })}
          </span>
        }
        actions={
          <>
            {latest?.status === "ready" && can("write") && (
              <Button asChild variant="accent">
                <Link to={`/reviews?new=${latest.id}`}>
                  <ClipboardCheck aria-hidden /> {t("reviews.start")}
                </Link>
              </Button>
            )}
            {can("write") && (
              <Button variant="outline" onClick={() => setVersionOpen(true)}>
                <FilePlus2 aria-hidden /> {t("documents.newVersion")}
              </Button>
            )}
            {can("decide") && (
              <Button variant="outline" className="text-red-700" onClick={() => setConfirmDelete(true)}>
                <Trash2 aria-hidden /> {t("common.delete")}
              </Button>
            )}
          </>
        }
      />

      {latest && (
        <Card className="mb-6">
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <ProcessingBadge status={latest.status} />
              <span className="text-slate-600">
                v{latest.version_number} · {latest.original_filename} · {latest.file_format.toUpperCase()} · {formatBytes(latest.size_bytes)}
                {latest.page_count ? ` · ${t("documents.pages", { count: latest.page_count })}` : ""} ·{" "}
                {t("documents.blocks", { count: latest.block_count })}
              </span>
              <span className="ms-auto flex gap-2">
                {latest.status === "failed" && can("write") && (
                  <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate()}>
                    <RotateCw aria-hidden /> {t("common.retry")}
                  </Button>
                )}
                {processing && job && can("write") && !job.cancel_requested && (
                  <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job.id)}>
                    {t("jobs.cancel")}
                  </Button>
                )}
              </span>
            </div>
            {processing && job && (
              <div>
                <ProgressBar value={job.progress} label={t("jobs.progress")} />
                <p className="mt-1 text-xs text-slate-500">{t("jobs.extracting", { attempt: job.attempts, max: job.max_attempts })}</p>
              </div>
            )}
            {latest.status === "failed" && (
              <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {latest.failure_message ?? t("common.genericError")}
              </p>
            )}
            {latest.extraction_warnings.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <p className="flex items-center gap-1.5 font-medium">
                  <AlertTriangle className="size-4" aria-hidden /> {t("documents.warnings")}
                </p>
                <ul className="mt-1 list-disc ps-5">
                  {latest.extraction_warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-xs text-slate-500">{t("documents.noMalwareScan")}</p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div>
          {latest?.status === "ready" ? (
            <BlocksViewer versionId={latest.id} isPdf={latest.file_format === "pdf"} />
          ) : (
            <Card>
              <EmptyState title={t("documents.textUnavailable")} />
            </Card>
          )}
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("documents.versions")}</CardTitle>
            </CardHeader>
            <Table>
              <THead>
                <tr>
                  <TH>#</TH>
                  <TH>{t("documents.status")}</TH>
                  <TH>{t("documents.uploaded")}</TH>
                  <TH>
                    <span className="sr-only">{t("documents.download")}</span>
                  </TH>
                </tr>
              </THead>
              <TBody>
                {[...d.versions].reverse().map((v) => (
                  <TR key={v.id}>
                    <TD className="tabular-nums">v{v.version_number}</TD>
                    <TD>
                      <ProcessingBadge status={v.status} />
                    </TD>
                    <TD className="whitespace-nowrap text-xs">{formatDate(v.created_at, i18n.language, true)}</TD>
                    <TD>
                      <a
                        className="inline-flex items-center gap-1 text-xs text-teal-700 hover:underline"
                        href={`/api/document-versions/${v.id}/download`}
                        aria-label={t("documents.downloadVersion", { n: v.version_number })}
                      >
                        <Download className="size-3.5" aria-hidden />
                      </a>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>
          {can("write") && (
            <Card>
              <CardHeader>
                <CardTitle>{t("documents.details")}</CardTitle>
              </CardHeader>
              <CardContent>
                <MetadataForm key={d.updated_at} doc={d} />
              </CardContent>
            </Card>
          )}
          <p className="text-xs text-slate-500">{t("documents.retentionNote")}</p>
        </div>
      </div>

      <UploadDialog open={versionOpen} onOpenChange={setVersionOpen} documentId={d.id} />
      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={t("documents.deleteTitle")}
        description={t("documents.deleteDescription")}
        confirmLabel={t("common.delete")}
        destructive
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}
