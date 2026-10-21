import { Fragment, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  AlertTriangle,
  Calendar,
  ClipboardCheck,
  Download,
  FilePlus2,
  FileText,
  Hash,
  Layers,
  RotateCw,
  Search,
  ShieldAlert,
  Tag,
  Trash2,
  User,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { DocumentDetail, Job, Page, SourceBlock } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatBytes, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, IconInput, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  errorMessage,
  LoadingState,
  OcrBadge,
  PageHeader,
  ProcessingBadge,
  ProgressBar,
  SyntheticBadge,
  useDebounced,
  useUnsavedChangesWarning,
} from "@/components/common";
import { DOCUMENT_TYPES, FileTypeTile, UploadDialog } from "@/components/upload-dialog";
import { evidenceLocation } from "@/lib/evidence";
import { AIAssist } from "@/components/ai-task";

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
  const items = blocks.data?.items ?? [];
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <FileText className="size-4 text-slate-400" aria-hidden />
            {t("documents.extractedText")}
          </CardTitle>
          <CardDescription>{isPdf ? t("documents.refsPdf") : t("documents.refsParagraph")}</CardDescription>
        </div>
        <IconInput
          icon={Search}
          aria-label={t("documents.searchText")}
          placeholder={t("documents.searchText")}
          className="w-full sm:w-64"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </CardHeader>
      <div className="max-h-[44rem] overflow-y-auto bg-slate-50/70 px-3 py-5 sm:px-6">
        {blocks.isLoading && <LoadingState />}
        {blocks.isError && <ErrorState error={blocks.error} onRetry={() => void blocks.refetch()} />}
        {blocks.data && items.length === 0 && (
          <EmptyState icon={Search} title={t("documents.noBlocks")} />
        )}
        {items.length > 0 && (
          <article className="mx-auto max-w-3xl rounded-lg bg-white px-5 py-6 shadow-card ring-1 ring-slate-200/80 sm:px-10 sm:py-9">
            {items.map((b, i) => {
              const prev = items[i - 1];
              const newPage = b.page_number != null && b.page_number !== prev?.page_number;
              return (
                <Fragment key={b.id}>
                  {newPage && (
                    <div className={i === 0 ? "mb-4" : "my-6"} role="separator" aria-label={t("evidence.page", { page: b.page_number })}>
                      <div className="flex items-center gap-3 text-[11px] font-medium uppercase tracking-wider text-slate-400">
                        <span className="h-px flex-1 bg-slate-200" aria-hidden />
                        <span aria-hidden>{t("evidence.page", { page: b.page_number })}</span>
                        <span className="h-px flex-1 bg-slate-200" aria-hidden />
                      </div>
                    </div>
                  )}
                  <div
                    id={`block-${b.id}`}
                    className="group relative grid grid-cols-[2.75rem_1fr] gap-3 rounded-md sm:grid-cols-[4.5rem_1fr] sm:gap-4 py-1.5 target:bg-amber-50 target:ring-1 target:ring-amber-200"
                  >
                    <div className="pt-0.5 text-end text-[11px] leading-5 text-slate-400">
                      {b.page_number == null && <div className="font-medium text-slate-500">{evidenceLocation(b, t)}</div>}
                      <code className="text-[10px] text-slate-400 opacity-70 transition-opacity group-hover:opacity-100">{b.ref}</code>
                    </div>
                    <div className="min-w-0">
                      {b.section_heading && b.section_heading !== b.text && (
                        <p className="mb-1 text-[13px] font-semibold text-navy-900" dir="auto">
                          {b.section_heading}
                        </p>
                      )}
                      <p className="whitespace-pre-wrap text-[14.5px] leading-7 text-slate-800" dir="auto">
                        {b.is_ocr && <OcrBadge confidence={b.ocr_confidence} />}
                        {b.text}
                      </p>
                    </div>
                  </div>
                </Fragment>
              );
            })}
          </article>
        )}
      </div>
    </Card>
  );
}

function MetaChip({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
      <Icon className="size-3.5 text-slate-400" aria-hidden />
      {children}
    </span>
  );
}

export function DocumentDetailPage() {
  const { documentId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const { can, me } = useAuth();
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
          <span className="mt-1 flex flex-wrap items-center gap-1.5">
            {d.is_demo && <SyntheticBadge />}
            <MetaChip icon={Layers}>{t(`documentType.${d.document_type}`, { defaultValue: d.document_type })}</MetaChip>
            {latest && (
              <MetaChip icon={FileText}>
                <span className="tabular-nums">
                  {latest.file_format.toUpperCase()} · {formatBytes(latest.size_bytes)}
                </span>
              </MetaChip>
            )}
            {latest?.page_count ? <MetaChip icon={Hash}>{t("documents.pages", { count: latest.page_count })}</MetaChip> : null}
            <MetaChip icon={User}>{t("documents.uploadedBy", { name: d.created_by_name ?? "—" })}</MetaChip>
            <MetaChip icon={Calendar}>{formatDate(d.updated_at, i18n.language)}</MetaChip>
          </span>
        }
        actions={
          <>
            {can("decide") && (
              <Button variant="destructive-outline" onClick={() => setConfirmDelete(true)}>
                <Trash2 aria-hidden /> {t("common.delete")}
              </Button>
            )}
            {can("write") && (
              <Button variant="outline" onClick={() => setVersionOpen(true)}>
                <FilePlus2 aria-hidden /> {t("documents.newVersion")}
              </Button>
            )}
            {latest?.status === "ready" && can("write") && (
              <Button asChild variant="accent">
                <Link to={`/reviews?new=${latest.id}`}>
                  <ClipboardCheck aria-hidden /> {t("reviews.start")}
                </Link>
              </Button>
            )}
          </>
        }
      />

      {latest && (
        <Card className="mb-6 overflow-hidden">
          <div className="space-y-3 px-5 py-4">
            <div className="flex flex-wrap items-center gap-4">
              <FileTypeTile format={latest.file_format} size="lg" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-navy-900" dir="auto">
                  {latest.original_filename}
                </p>
                <p className="mt-0.5 text-[13px] tabular-nums text-slate-500">
                  v{latest.version_number} · {latest.file_format.toUpperCase()} · {formatBytes(latest.size_bytes)}
                  {latest.page_count ? ` · ${t("documents.pages", { count: latest.page_count })}` : ""} ·{" "}
                  {t("documents.blocks", { count: latest.block_count })}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <ProcessingBadge status={latest.status} />
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
              </div>
            </div>
            {processing && job && (
              <div className="rounded-lg bg-slate-50 px-3 py-2.5 ring-1 ring-slate-200/70">
                <ProgressBar value={job.progress} label={t("jobs.progress")} />
                <p className="mt-1.5 text-xs text-slate-500">{t("jobs.extracting", { attempt: job.attempts, max: job.max_attempts })}</p>
              </div>
            )}
            {latest.status === "failed" && (
              <p role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                {latest.failure_message ?? t("common.genericError")}
              </p>
            )}
            {latest.extraction_warnings.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
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
          </div>
          <p className="flex items-center gap-2 border-t border-slate-100 bg-slate-50/70 px-5 py-2.5 text-xs text-slate-600">
            <ShieldAlert className="size-3.5 shrink-0 text-slate-400" aria-hidden />
            {me?.malware_scan_enabled ? t("documents.malwareScanned") : t("documents.noMalwareScan")}
          </p>
        </Card>
      )}

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          {latest?.status === "ready" ? (
            <BlocksViewer versionId={latest.id} isPdf={latest.file_format === "pdf"} />
          ) : (
            <Card>
              <EmptyState icon={FileText} title={t("documents.textUnavailable")} />
            </Card>
          )}
        </div>
        <div className="space-y-6">
          {latest?.status === "ready" && (
            <AIAssist kind="contract_tax" subjectId={latest.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs" />
          )}
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>{t("documents.versions")}</CardTitle>
              <Badge className="tabular-nums">{d.versions.length}</Badge>
            </CardHeader>
            <ol className="divide-y divide-slate-100">
              {[...d.versions].reverse().map((v) => (
                <li key={v.id} className="flex items-center gap-3 px-5 py-3">
                  <span
                    className={
                      v.id === latest?.id
                        ? "flex size-8 shrink-0 items-center justify-center rounded-lg bg-teal-50 font-mono text-xs font-semibold tabular-nums text-teal-700 ring-1 ring-teal-200"
                        : "flex size-8 shrink-0 items-center justify-center rounded-lg bg-slate-50 font-mono text-xs font-semibold tabular-nums text-slate-600 ring-1 ring-slate-200"
                    }
                  >
                    v{v.version_number}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-slate-800" dir="auto" title={v.original_filename}>
                      {v.original_filename}
                    </p>
                    <p className="text-xs tabular-nums text-slate-500">
                      {formatDate(v.created_at, i18n.language, true)} · {formatBytes(v.size_bytes)}
                    </p>
                  </div>
                  <ProcessingBadge status={v.status} />
                  <Button asChild variant="ghost" size="icon-sm">
                    <a href={`/api/document-versions/${v.id}/download`} aria-label={t("documents.downloadVersion", { n: v.version_number })}>
                      <Download aria-hidden />
                    </a>
                  </Button>
                </li>
              ))}
            </ol>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t("documents.details")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
                {!can("write") && (
                  <>
                    <dt className="text-slate-500">{t("documents.type")}</dt>
                    <dd className="text-slate-800">{t(`documentType.${d.document_type}`, { defaultValue: d.document_type })}</dd>
                  </>
                )}
                <dt className="text-slate-500">{t("documents.uploaded")}</dt>
                <dd className="tabular-nums text-slate-800">{formatDate(d.created_at, i18n.language, true)}</dd>
                <dt className="text-slate-500">{t("documents.updated")}</dt>
                <dd className="tabular-nums text-slate-800">{formatDate(d.updated_at, i18n.language, true)}</dd>
                {!can("write") && d.tags.length > 0 && (
                  <>
                    <dt className="text-slate-500">{t("documents.tags")}</dt>
                    <dd className="flex flex-wrap gap-1">
                      {d.tags.map((tag) => (
                        <Badge key={tag} className="px-1.5 py-0 text-[11px]">
                          <Tag className="size-3" aria-hidden />
                          {tag}
                        </Badge>
                      ))}
                    </dd>
                  </>
                )}
                {!can("write") && d.description && (
                  <>
                    <dt className="text-slate-500">{t("documents.description")}</dt>
                    <dd className="text-slate-700" dir="auto">
                      {d.description}
                    </dd>
                  </>
                )}
              </dl>
              {can("write") && (
                <div className="border-t border-slate-100 pt-4">
                  <MetadataForm key={d.updated_at} doc={d} />
                </div>
              )}
            </CardContent>
          </Card>
          <p className="px-1 text-xs leading-relaxed text-slate-500">{t("documents.retentionNote")}</p>
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
