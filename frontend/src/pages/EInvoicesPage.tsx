import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  CheckCircle2,
  ChevronDown,
  Download,
  FileCode,
  Info,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  Radar,
  ShieldCheck,
  Upload,
  UploadCloud,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, qs, uploadWithProgress } from "@/lib/api";
import type { EInvoiceBatch, EInvoiceBatchDetail, EInvoiceMonitor, EInvoiceMonitorRun, MonitorCadence, MonitorRunStatus } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useEntities, usePublishedChecklists, usePublishedRulePacks } from "@/lib/queries";
import { cn, formatBytes, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, errorMessage, LoadingState, PageHeader, ProgressBar, SyntheticBadge } from "@/components/common";

const ACCEPT = ".xml,.zip,application/xml,text/xml,application/zip";
const CADENCES: MonitorCadence[] = ["daily", "weekly", "monthly"];

function Amount({ value, currency }: { value: string | null; currency: string | null }) {
  if (value == null) return <span className="text-slate-400">—</span>;
  return (
    <span className="whitespace-nowrap font-mono tabular-nums" dir="ltr">
      {value} {currency ?? ""}
    </span>
  );
}

/** The "nothing is sent anywhere" statement shown wherever e-invoices are handled. */
function NotSentNotice() {
  const { t } = useTranslation();
  return (
    <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
      <ShieldCheck className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
      {t("einvoices.notSent")}
    </p>
  );
}

// ---------------------------------------------------------------- upload

const uploadSchema = z.object({
  entity_id: z.string().min(1),
  name: z.string().trim().min(1).max(200),
});
type UploadValues = z.infer<typeof uploadSchema>;

function EInvoiceUploadDialog({
  open,
  onOpenChange,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onUploaded: (b: EInvoiceBatchDetail) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const entities = useEntities(open);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const form = useForm<UploadValues>({ resolver: zodResolver(uploadSchema), defaultValues: { entity_id: "", name: "" } });
  const busy = progress !== null;

  const reset = () => {
    setFile(null);
    setProgress(null);
    setError(null);
    setInputKey((k) => k + 1);
    form.reset();
  };

  const submit = async (v: UploadValues) => {
    if (!file) {
      setError(t("upload.chooseFile"));
      return;
    }
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("entity_id", v.entity_id);
    fd.append("name", v.name);
    setProgress(0);
    try {
      const batch = await uploadWithProgress<EInvoiceBatchDetail>("/einvoice-batches", fd, setProgress);
      toast.success(t("einvoices.uploaded", { count: batch.file_count }));
      void qc.invalidateQueries({ queryKey: ["einvoice-batches"] });
      reset();
      onOpenChange(false);
      onUploaded(batch);
    } catch (e) {
      setProgress(null);
      setError(e instanceof ApiError ? e.message : t("common.genericError"));
    }
  };

  const err = form.formState.errors;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (busy) return;
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent>
        <DialogTitle>{t("einvoices.upload")}</DialogTitle>
        <DialogDescription>{t("einvoices.uploadHint")}</DialogDescription>
        {entities.isLoading && <LoadingState rows={2} />}
        {entities.isError && <ErrorState error={entities.error} onRetry={() => void entities.refetch()} />}
        {entities.data?.length === 0 && (
          <p className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              {t("datasets.needEntity")}{" "}
              <Link to="/entities" className="font-medium underline" onClick={() => onOpenChange(false)}>
                {t("nav.entities")}
              </Link>
            </span>
          </p>
        )}
        {entities.data && entities.data.length > 0 && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => void submit(v))} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="ei-file">{t("upload.file")}</Label>
              <label
                htmlFor="ei-file"
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed px-4 py-4 transition-colors",
                  "has-[input:focus-visible]:border-teal-500 has-[input:focus-visible]:ring-4 has-[input:focus-visible]:ring-teal-500/15",
                  file ? "border-teal-300 bg-teal-50/30" : "border-slate-200 bg-slate-50/60 hover:border-slate-300",
                  busy && "cursor-not-allowed opacity-80",
                )}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (!busy) setFile(e.dataTransfer.files?.[0] ?? null);
                }}
              >
                <input
                  key={inputKey}
                  ref={inputRef}
                  id="ei-file"
                  type="file"
                  accept={ACCEPT}
                  className="sr-only"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    setFile(f);
                    if (f && !form.getValues("name")) form.setValue("name", f.name.replace(/\.[^.]+$/, ""));
                  }}
                />
                {file ? (
                  <>
                    <FileCode className="size-5 shrink-0 text-teal-700" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-navy-900" dir="auto">
                        {file.name}
                      </span>
                      <span className="text-xs tabular-nums text-slate-500">{formatBytes(file.size)}</span>
                    </span>
                    {busy ? <Loader2 className="size-4 animate-spin text-teal-600" aria-hidden /> : <CheckCircle2 className="size-5 text-teal-600" aria-hidden />}
                  </>
                ) : (
                  <>
                    <UploadCloud className="size-5 shrink-0 text-teal-600" aria-hidden />
                    <span className="text-sm text-slate-600">
                      {t("upload.dropzone")}
                      <span className="block text-xs text-slate-400">{t("einvoices.fileHint")}</span>
                    </span>
                  </>
                )}
              </label>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="ei-entity">{t("datasets.entity")}</Label>
                <Select id="ei-entity" disabled={busy} aria-invalid={!!err.entity_id} {...form.register("entity_id")}>
                  <option value="">{t("datasets.chooseEntity")}</option>
                  {entities.data.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </Select>
                <FieldError message={err.entity_id ? t("datasets.entityRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ei-name">{t("einvoices.batchName")}</Label>
                <Input id="ei-name" disabled={busy} aria-invalid={!!err.name} {...form.register("name")} />
                <FieldError message={err.name ? t("datasets.nameRequired") : undefined} />
              </div>
            </div>
            <NotSentNotice />
            {progress !== null && (
              <div className="space-y-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5">
                <p className="flex items-center gap-1.5 text-xs font-medium text-slate-700">
                  <Loader2 className="size-3.5 animate-spin text-teal-600" aria-hidden />
                  {progress < 1 ? t("upload.uploading", { pct: Math.round(progress * 100) }) : t("einvoices.finishing")}
                </p>
                <ProgressBar value={progress * 100} label={t("upload.progress")} />
              </div>
            )}
            {error && (
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {error}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={busy}>
                <Upload aria-hidden /> {t("upload.submit")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- batch detail

function BatchDetailDialog({ batchId, onOpenChange }: { batchId: string | null; onOpenChange: (o: boolean) => void }) {
  const { t, i18n } = useTranslation();
  const detail = useQuery({
    queryKey: ["einvoice-batch", batchId],
    queryFn: () => api<EInvoiceBatchDetail>(`/einvoice-batches/${batchId}`),
    enabled: !!batchId,
  });
  const b = detail.data;
  return (
    <Dialog open={batchId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl">
        <DialogTitle className="flex flex-wrap items-center gap-2">
          {b?.name ?? t("einvoices.batch")}
          {b?.is_demo && <SyntheticBadge />}
        </DialogTitle>
        <DialogDescription>
          {b ? t("einvoices.batchSummary", { entity: b.entity_name, file: b.original_filename, count: b.file_count }) : t("common.loading")}
        </DialogDescription>
        {detail.isLoading && <LoadingState rows={3} />}
        {detail.isError && <ErrorState error={detail.error} onRetry={() => void detail.refetch()} />}
        {b && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge tone="neutral">{t("einvoices.fileCount", { count: b.file_count })}</Badge>
              {b.duplicate_count > 0 && <Badge tone="amber">{t("einvoices.duplicateCount", { count: b.duplicate_count })}</Badge>}
              {b.failed_count > 0 && <Badge tone="red">{t("einvoices.failedCount", { count: b.failed_count })}</Badge>}
              <span className="font-mono text-[11px] text-slate-400" dir="ltr" title={t("evidence.sha256")}>
                SHA-256 {b.raw_sha256.slice(0, 16)}…
              </span>
            </div>
            {b.files.length === 0 ? (
              <p className="rounded-lg border border-slate-200 px-3 py-4 text-center text-sm text-slate-500">{t("einvoices.noFiles")}</p>
            ) : (
              <div className="max-h-[55vh] overflow-auto rounded-lg border border-slate-200">
                <Table>
                  <THead>
                    <tr>
                      <TH>{t("einvoices.filename")}</TH>
                      <TH>{t("einvoices.invoiceNumber")}</TH>
                      <TH>{t("einvoices.profile")}</TH>
                      <TH>{t("einvoices.issueDate")}</TH>
                      <TH className="text-end">{t("einvoices.payable")}</TH>
                      <TH className="text-end">{t("einvoices.tax")}</TH>
                      <TH className="text-end">
                        <span className="sr-only">{t("einvoices.download")}</span>
                      </TH>
                    </tr>
                  </THead>
                  <TBody>
                    {b.files.map((f) => (
                      <TR key={f.id}>
                        <TD className="max-w-56">
                          <span className="block truncate text-[13px] text-navy-900" dir="ltr" title={f.filename}>
                            {f.filename}
                          </span>
                          {f.parse_error && (
                            <Badge tone="red" className="mt-1 whitespace-normal" title={f.parse_error}>
                              {t("einvoices.parseError")}: {f.parse_error}
                            </Badge>
                          )}
                        </TD>
                        <TD className="font-mono text-[13px] text-slate-700" dir="ltr">
                          {f.invoice_number ?? "—"}
                        </TD>
                        <TD className="text-[13px] text-slate-600">
                          <span dir="ltr">{f.profile || "—"}</span>
                          {f.document_type && <span className="block text-xs text-slate-400">{f.document_type}</span>}
                        </TD>
                        <TD className="whitespace-nowrap text-[13px] text-slate-600">{formatDate(f.issue_date, i18n.language)}</TD>
                        <TD className="text-end text-[13px] text-slate-700">
                          <Amount value={f.payable_amount} currency={f.currency} />
                        </TD>
                        <TD className="text-end text-[13px] text-slate-700">
                          <Amount value={f.tax_amount} currency={f.currency} />
                        </TD>
                        <TD className="text-end">
                          <a
                            href={`/api/einvoice-files/${f.id}/download`}
                            className="inline-flex size-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-navy-900"
                            aria-label={t("einvoices.downloadNamed", { name: f.filename })}
                          >
                            <Download className="size-4" aria-hidden />
                          </a>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            )}
            <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
              <span>
                {t("einvoices.validateHint")}{" "}
                <Link to="/reviews?new" className="font-medium text-teal-700 underline" onClick={() => onOpenChange(false)}>
                  {t("reviews.new")}
                </Link>
              </span>
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- monitors

const monitorSchema = z.object({
  entity_id: z.string().min(1),
  name: z.string().trim().min(1).max(200),
  checklist_version_id: z.string().min(1),
  rule_pack_version_id: z.string(),
  sample_size: z.coerce.number().int().min(1).max(500),
  cadence: z.enum(["daily", "weekly", "monthly"]),
});
type MonitorValues = z.input<typeof monitorSchema>;
type MonitorParsed = z.output<typeof monitorSchema>;

function MonitorDialog({ open, onOpenChange, monitor }: { open: boolean; onOpenChange: (o: boolean) => void; monitor?: EInvoiceMonitor }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const creating = !monitor;
  const entities = useEntities(open && creating);
  const checklists = usePublishedChecklists(open && creating);
  const packs = usePublishedRulePacks(open && creating);
  const defaults = (): MonitorValues => ({
    entity_id: monitor?.entity_id ?? "",
    name: monitor?.name ?? "",
    checklist_version_id: monitor?.checklist_version_id ?? "",
    rule_pack_version_id: monitor?.rule_pack_version_id ?? "",
    sample_size: monitor?.sample_size ?? 25,
    cadence: monitor?.cadence ?? "weekly",
  });
  const form = useForm<MonitorValues, unknown, MonitorParsed>({ resolver: zodResolver(monitorSchema), defaultValues: defaults() });
  useEffect(() => {
    if (open) form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the dialog opens
  }, [open, monitor?.id]);
  useEffect(() => {
    const first = checklists.items[0];
    if (creating && first && !form.getValues("checklist_version_id")) form.setValue("checklist_version_id", first.v.id);
  }, [checklists.items, creating, form]);

  const save = useMutation({
    mutationFn: (v: MonitorParsed) =>
      monitor
        ? api<EInvoiceMonitor>(`/einvoice-monitors/${monitor.id}`, { method: "PATCH", json: { name: v.name, sample_size: v.sample_size } })
        : api<EInvoiceMonitor>("/einvoice-monitors", {
            json: {
              entity_id: v.entity_id,
              name: v.name,
              checklist_version_id: v.checklist_version_id,
              rule_pack_version_id: v.rule_pack_version_id || null,
              sample_size: v.sample_size,
              cadence: v.cadence,
            },
          }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["einvoice-monitors"] });
      toast.success(t(monitor ? "einvoices.monitorUpdated" : "einvoices.monitorCreated"));
      onOpenChange(false);
    },
  });
  const err = form.formState.errors;
  const loading = creating && (entities.isLoading || checklists.query.isLoading || packs.query.isLoading);
  const failed = creating && (entities.isError || checklists.query.isError || packs.query.isError);
  const ready = !creating || (entities.data && checklists.query.data && packs.query.data);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{monitor ? t("einvoices.editMonitor") : t("einvoices.newMonitor")}</DialogTitle>
        <DialogDescription>{t("einvoices.monitorHint")}</DialogDescription>
        {loading && <LoadingState rows={3} />}
        {failed && (
          <ErrorState
            error={entities.error ?? checklists.query.error ?? packs.query.error}
            onRetry={() => {
              void entities.refetch();
              void checklists.query.refetch();
              void packs.query.refetch();
            }}
          />
        )}
        {ready && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="mon-name">{t("einvoices.monitorName")}</Label>
              <Input id="mon-name" aria-invalid={!!err.name} {...form.register("name")} />
              <FieldError message={err.name ? t("datasets.nameRequired") : undefined} />
            </div>
            {creating && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="mon-entity">{t("datasets.entity")}</Label>
                  <Select id="mon-entity" aria-invalid={!!err.entity_id} {...form.register("entity_id")}>
                    <option value="">{t("datasets.chooseEntity")}</option>
                    {(entities.data ?? []).map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.name}
                      </option>
                    ))}
                  </Select>
                  <FieldError message={err.entity_id ? t("datasets.entityRequired") : undefined} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="mon-checklist">{t("reviews.checklist")}</Label>
                  <Select id="mon-checklist" aria-invalid={!!err.checklist_version_id} {...form.register("checklist_version_id")}>
                    {checklists.items.length === 0 && <option value="">{t("einvoices.noChecklists")}</option>}
                    {checklists.items.map(({ c, v }) => (
                      <option key={v.id} value={v.id}>
                        {c.name} · v{v.version_number}
                        {c.kind === "synthetic_demo" ? ` · ${t("common.synthetic")}` : ""}
                      </option>
                    ))}
                  </Select>
                  <FieldError message={err.checklist_version_id ? t("reviews.checklistRequired") : undefined} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="mon-pack">{t("reviews.rulePack")}</Label>
                  <Select id="mon-pack" {...form.register("rule_pack_version_id")}>
                    <option value="">{t("reviews.noRulePack")}</option>
                    {packs.items.map(({ p, v }) => (
                      <option key={v.id} value={v.id}>
                        {p.name} · v{v.version_number}
                        {p.is_synthetic ? ` · ${t("common.synthetic")}` : ""}
                        {v.unverified_count > 0 ? ` · ${t("rulePacks.unverifiedCount", { count: v.unverified_count })}` : ""}
                      </option>
                    ))}
                  </Select>
                </div>
              </>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="mon-sample">{t("einvoices.sampleSize")}</Label>
                <Input id="mon-sample" type="number" min={1} max={500} aria-invalid={!!err.sample_size} aria-describedby="mon-sample-hint" {...form.register("sample_size")} />
                <p id="mon-sample-hint" className="text-xs text-slate-500">
                  {t("einvoices.sampleHint")}
                </p>
                <FieldError message={err.sample_size ? t("einvoices.sampleRule") : undefined} />
              </div>
              {creating && (
                <div className="space-y-1.5">
                  <Label htmlFor="mon-cadence">{t("einvoices.cadence")}</Label>
                  <Select id="mon-cadence" {...form.register("cadence")}>
                    {CADENCES.map((c) => (
                      <option key={c} value={c}>
                        {t(`einvoices.cadenceOpt.${c}`)}
                      </option>
                    ))}
                  </Select>
                </div>
              )}
            </div>
            {save.isError && (
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {errorMessage(save.error, t("common.genericError"))}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={save.isPending}>
                {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t("common.save")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

const RUN_TONE: Record<MonitorRunStatus, "green" | "neutral" | "red"> = { review_created: "green", no_files: "neutral", failed: "red" };

function MonitorRuns({ monitorId }: { monitorId: string }) {
  const { t, i18n } = useTranslation();
  const runs = useQuery({
    queryKey: ["einvoice-monitors", monitorId, "runs"],
    queryFn: () => api<EInvoiceMonitorRun[]>(`/einvoice-monitors/${monitorId}/runs`),
  });
  if (runs.isLoading) return <LoadingState rows={2} />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  if (!runs.data || runs.data.length === 0) return <p className="px-5 py-3 text-xs text-slate-500">{t("einvoices.noRuns")}</p>;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("einvoices.runAt")}</TH>
          <TH>{t("einvoices.runStatusCol")}</TH>
          <TH>{t("einvoices.window")}</TH>
          <TH className="text-end">{t("einvoices.population")}</TH>
          <TH className="text-end">{t("einvoices.sampled")}</TH>
          <TH>{t("einvoices.review")}</TH>
        </tr>
      </THead>
      <TBody>
        {runs.data.map((r) => (
          <TR key={r.id}>
            <TD className="whitespace-nowrap text-[13px] text-slate-600">{formatDate(r.created_at, i18n.language, true)}</TD>
            <TD>
              <Badge tone={RUN_TONE[r.status]} dot>
                {t(`einvoices.runStatus.${r.status}`)}
              </Badge>
              {r.message && <p className="mt-1 max-w-64 text-xs text-slate-500">{r.message}</p>}
            </TD>
            <TD className="whitespace-nowrap text-[13px] text-slate-600">
              {formatDate(r.window_start, i18n.language, true)} – {formatDate(r.window_end, i18n.language, true)}
            </TD>
            <TD className="text-end tabular-nums text-[13px] text-slate-700">{r.population}</TD>
            <TD className="text-end tabular-nums text-[13px] text-slate-700">{r.sampled}</TD>
            <TD className="text-[13px]">
              {r.review_id ? (
                <Link to={`/reviews/${r.review_id}`} className="font-medium text-teal-700 hover:underline">
                  {t("einvoices.openReview")}
                </Link>
              ) : (
                "—"
              )}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function MonitorsCard({ entityId }: { entityId: string }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const decide = can("decide");
  const [editing, setEditing] = useState<EInvoiceMonitor | "new" | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const monitors = useQuery({
    queryKey: ["einvoice-monitors", { entityId }],
    queryFn: () => api<EInvoiceMonitor[]>(`/einvoice-monitors${qs({ entity_id: entityId })}`),
  });
  const toggle = useMutation({
    mutationFn: (m: EInvoiceMonitor) => api<EInvoiceMonitor>(`/einvoice-monitors/${m.id}`, { method: "PATCH", json: { is_active: !m.is_active } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["einvoice-monitors"] });
      toast.success(t("einvoices.monitorUpdated"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const run = useMutation({
    mutationFn: (m: EInvoiceMonitor) => api<EInvoiceMonitorRun>(`/einvoice-monitors/${m.id}/run`, { method: "POST" }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["einvoice-monitors"] });
      void qc.invalidateQueries({ queryKey: ["reviews"] });
      setExpanded(r.monitor_id);
      toast.success(t(`einvoices.runStatus.${r.status}`));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });

  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Radar className="size-4 text-slate-400" aria-hidden />
            {t("einvoices.monitors")}
          </CardTitle>
          <CardDescription>{t("einvoices.monitorsHint")}</CardDescription>
        </div>
        {decide && (
          <Button size="sm" variant="outline" onClick={() => setEditing("new")}>
            <Plus aria-hidden /> {t("einvoices.newMonitor")}
          </Button>
        )}
      </CardHeader>
      {monitors.isLoading && <LoadingState rows={2} />}
      {monitors.isError && <ErrorState error={monitors.error} onRetry={() => void monitors.refetch()} />}
      {monitors.data?.length === 0 && (
        <p className="border-t border-slate-100 px-5 py-4 text-sm text-slate-500">{decide ? t("einvoices.noMonitorsDecider") : t("einvoices.noMonitors")}</p>
      )}
      {monitors.data && monitors.data.length > 0 && (
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {monitors.data.map((m) => (
            <li key={m.id}>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-navy-900">{m.name}</span>
                    <Badge tone={m.is_active ? "green" : "neutral"} dot>
                      {m.is_active ? t("einvoices.active") : t("einvoices.paused")}
                    </Badge>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {m.entity_name} · {t(`einvoices.cadenceOpt.${m.cadence}`)} · {t("einvoices.sampleOf", { count: m.sample_size })}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {t("einvoices.nextRun", { date: formatDate(m.next_run_at, i18n.language, true) })}
                    {m.last_run_at && ` · ${t("einvoices.lastRun", { date: formatDate(m.last_run_at, i18n.language, true) })}`}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  {decide && (
                    <>
                      <Button size="sm" variant="outline" disabled={run.isPending} onClick={() => run.mutate(m)}>
                        {run.isPending && run.variables?.id === m.id ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
                        {t("einvoices.runNow")}
                      </Button>
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        disabled={toggle.isPending}
                        onClick={() => toggle.mutate(m)}
                        aria-label={t(m.is_active ? "einvoices.pauseNamed" : "einvoices.resumeNamed", { name: m.name })}
                      >
                        {m.is_active ? <Pause aria-hidden /> : <Play aria-hidden />}
                      </Button>
                      <Button size="icon-sm" variant="ghost" onClick={() => setEditing(m)} aria-label={t("einvoices.editNamed", { name: m.name })}>
                        <Pencil aria-hidden />
                      </Button>
                    </>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-expanded={expanded === m.id}
                    onClick={() => setExpanded((x) => (x === m.id ? null : m.id))}
                  >
                    {t("einvoices.runs")}
                    <ChevronDown className={cn("transition-transform", expanded === m.id && "rotate-180")} aria-hidden />
                  </Button>
                </div>
              </div>
              {expanded === m.id && (
                <div className="border-t border-slate-100 bg-slate-50/40">
                  <MonitorRuns monitorId={m.id} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <MonitorDialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} monitor={editing && editing !== "new" ? editing : undefined} />
    </Card>
  );
}

// ---------------------------------------------------------------- page

export function EInvoicesPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [entityId, setEntityId] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);
  const entities = useEntities();
  const batches = useQuery({
    queryKey: ["einvoice-batches", { entityId }],
    queryFn: () => api<EInvoiceBatch[]>(`/einvoice-batches${qs({ entity_id: entityId })}`),
  });
  return (
    <>
      <PageHeader
        title={t("einvoices.title")}
        description={t("einvoices.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.einvoices") }]}
        actions={
          can("write") && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <Upload aria-hidden /> {t("einvoices.upload")}
            </Button>
          )
        }
      />
      <div className="space-y-6">
        <NotSentNotice />
        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-slate-100 p-3">
            <Select aria-label={t("datasets.entity")} className="w-64" value={entityId} onChange={(e) => setEntityId(e.target.value)}>
              <option value="">{t("einvoices.allEntities")}</option>
              {(entities.data ?? []).map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </Select>
          </div>
          {batches.isLoading && <LoadingState />}
          {batches.isError && <ErrorState error={batches.error} onRetry={() => void batches.refetch()} />}
          {batches.data?.length === 0 && (
            <EmptyState
              icon={FileCode}
              title={t("einvoices.empty")}
              description={t("einvoices.emptyHint")}
              action={
                can("write") && (
                  <Button variant="accent" onClick={() => setOpen(true)}>
                    <Upload aria-hidden /> {t("einvoices.upload")}
                  </Button>
                )
              }
            />
          )}
          {batches.data && batches.data.length > 0 && (
            <Table>
              <THead>
                <tr>
                  <TH>{t("einvoices.batchName")}</TH>
                  <TH className="text-end">{t("einvoices.files")}</TH>
                  <TH className="text-end">{t("einvoices.duplicates")}</TH>
                  <TH className="text-end">{t("einvoices.failed")}</TH>
                  <TH>{t("einvoices.uploadedAt")}</TH>
                </tr>
              </THead>
              <TBody>
                {batches.data.map((b) => (
                  <TR key={b.id}>
                    <TD>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          className="text-start font-medium text-navy-900 transition-colors hover:text-teal-700"
                          onClick={() => setDetailId(b.id)}
                        >
                          {b.name}
                        </button>
                        {b.is_demo && <SyntheticBadge />}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500">{b.entity_name}</div>
                    </TD>
                    <TD className="text-end tabular-nums text-[13px] text-slate-700">{b.file_count}</TD>
                    <TD className="text-end tabular-nums text-[13px]">
                      {b.duplicate_count > 0 ? <Badge tone="amber">{b.duplicate_count}</Badge> : <span className="text-slate-400">0</span>}
                    </TD>
                    <TD className="text-end tabular-nums text-[13px]">
                      {b.failed_count > 0 ? <Badge tone="red">{b.failed_count}</Badge> : <span className="text-slate-400">0</span>}
                    </TD>
                    <TD className="whitespace-nowrap text-[13px] text-slate-500">{formatDate(b.created_at, i18n.language)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <MonitorsCard entityId={entityId} />
      </div>
      <EInvoiceUploadDialog open={open} onOpenChange={setOpen} onUploaded={(b) => setDetailId(b.id)} />
      <BatchDetailDialog batchId={detailId} onOpenChange={(o) => !o && setDetailId(null)} />
    </>
  );
}
