import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CheckCircle2, Info, Loader2, Sheet, Table2, Upload, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError, qs, uploadWithProgress } from "@/lib/api";
import { DATASET_KINDS, type Dataset, type DatasetDetail, type DatasetKind, type LegalEntity } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { cn, formatBytes, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { DatasetStatusBadge, EmptyState, ErrorState, LoadingState, PageHeader, ProgressBar, SyntheticBadge } from "@/components/common";

const ACCEPT = ".csv,.xlsx,.sta,.mt940,.xml,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/xml,text/xml";

const schema = z
  .object({
    entity_id: z.string().min(1),
    kind: z.enum(["trial_balance", "general_ledger", "sales_register", "purchase_register", "bank_statement"]),
    name: z.string().trim().min(1).max(200),
    period_start: z.string(),
    period_end: z.string(),
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type Values = z.infer<typeof schema>;

/** Import a new dataset, or (with datasetId) upload a new version of one. */
export function DatasetUploadDialog({
  open,
  onOpenChange,
  datasetId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  datasetId?: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const entities = useQuery({ queryKey: ["entities", { showInactive: false }], queryFn: () => api<LegalEntity[]>("/entities"), enabled: open && !datasetId });
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [duplicateId, setDuplicateId] = useState<string | null>(null);
  const [inputKey, setInputKey] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { entity_id: "", kind: "general_ledger", name: "", period_start: "", period_end: "" },
  });
  const busy = progress !== null;

  const reset = () => {
    setFile(null);
    setProgress(null);
    setError(null);
    setDuplicateId(null);
    setInputKey((k) => k + 1);
    form.reset();
  };

  const submit = async (v: Values, allowDuplicate = false) => {
    if (!file) {
      setError(t("upload.chooseFile"));
      return;
    }
    setError(null);
    setDuplicateId(null);
    const fd = new FormData();
    fd.append("file", file);
    if (allowDuplicate) fd.append("allow_duplicate", "true");
    if (!datasetId) {
      fd.append("entity_id", v.entity_id);
      fd.append("kind", v.kind);
      fd.append("name", v.name);
      if (v.period_start) fd.append("period_start", v.period_start);
      if (v.period_end) fd.append("period_end", v.period_end);
    }
    setProgress(0);
    try {
      const ds = await uploadWithProgress<DatasetDetail>(datasetId ? `/datasets/${datasetId}/versions` : "/datasets", fd, setProgress);
      toast.success(t("datasets.uploaded"));
      void qc.invalidateQueries({ queryKey: ["datasets"] });
      void qc.invalidateQueries({ queryKey: ["dataset", ds.id] });
      reset();
      onOpenChange(false);
      if (!datasetId) navigate(`/datasets/${ds.id}`);
    } catch (e) {
      setProgress(null);
      if (e instanceof ApiError && e.status === 409 && typeof e.data.duplicate_dataset_id === "string") setDuplicateId(e.data.duplicate_dataset_id);
      setError(e instanceof ApiError ? e.message : t("common.genericError"));
    }
  };

  // In version mode the form fields are not shown, so submit without validating them.
  const onSubmit = (allowDuplicate = false) =>
    datasetId ? void submit(form.getValues(), allowDuplicate) : void form.handleSubmit((v) => submit(v, allowDuplicate))();

  const err = form.formState.errors;
  const noEntities = !datasetId && entities.data?.length === 0;
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
        <DialogTitle>{datasetId ? t("datasets.newVersion") : t("datasets.upload")}</DialogTitle>
        <DialogDescription>{t("datasets.uploadHint")}</DialogDescription>
        {!datasetId && entities.isLoading && <LoadingState rows={2} />}
        {!datasetId && entities.isError && <ErrorState error={entities.error} onRetry={() => void entities.refetch()} />}
        {noEntities && (
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
        {(datasetId || (entities.data && entities.data.length > 0)) && (
          <form
            className="mt-5 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit();
            }}
            noValidate
          >
            <div className="space-y-1.5">
              <Label htmlFor="ds-file">{t("upload.file")}</Label>
              <label
                htmlFor="ds-file"
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
                  id="ds-file"
                  type="file"
                  accept={ACCEPT}
                  className="sr-only"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0] ?? null;
                    setFile(f);
                    if (f && !datasetId && !form.getValues("name")) form.setValue("name", f.name.replace(/\.[^.]+$/, ""));
                  }}
                />
                {file ? (
                  <>
                    <Sheet className="size-5 shrink-0 text-teal-700" aria-hidden />
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
                      <span className="block text-xs text-slate-400">CSV · XLSX · MT940 · CAMT.053</span>
                    </span>
                  </>
                )}
              </label>
            </div>
            {!datasetId && entities.data && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="ds-entity">{t("datasets.entity")}</Label>
                    <Select id="ds-entity" disabled={busy} aria-invalid={!!err.entity_id} {...form.register("entity_id")}>
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
                    <Label htmlFor="ds-kind">{t("datasets.kind")}</Label>
                    <Select id="ds-kind" disabled={busy} {...form.register("kind")}>
                      {DATASET_KINDS.map((k) => (
                        <option key={k} value={k}>
                          {t(`datasetKind.${k}`)}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="ds-name">{t("datasets.name")}</Label>
                  <Input id="ds-name" disabled={busy} aria-invalid={!!err.name} {...form.register("name")} />
                  <FieldError message={err.name ? t("datasets.nameRequired") : undefined} />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="ds-start">{t("datasets.periodStart")}</Label>
                    <Input id="ds-start" type="date" disabled={busy} {...form.register("period_start")} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="ds-end">{t("datasets.periodEnd")}</Label>
                    <Input id="ds-end" type="date" disabled={busy} aria-invalid={!!err.period_end} {...form.register("period_end")} />
                    <FieldError message={err.period_end ? t("datasets.periodOrder") : undefined} />
                  </div>
                </div>
              </>
            )}
            {progress !== null && (
              <div className="space-y-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5">
                <p className="flex items-center gap-1.5 text-xs font-medium text-slate-700">
                  <Loader2 className="size-3.5 animate-spin text-teal-600" aria-hidden />
                  {progress < 1 ? t("upload.uploading", { pct: Math.round(progress * 100) }) : t("datasets.finishing")}
                </p>
                <ProgressBar value={progress * 100} label={t("upload.progress")} />
              </div>
            )}
            {error && (
              <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {error}
                {duplicateId && (
                  <div className="mt-2 flex flex-wrap gap-3">
                    <Link className="font-medium underline" to={`/datasets/${duplicateId}`} onClick={() => onOpenChange(false)}>
                      {t("datasets.openExisting")}
                    </Link>
                    <button type="button" className="font-medium underline" onClick={() => onSubmit(true)}>
                      {t("upload.uploadAnyway")}
                    </button>
                  </div>
                )}
              </div>
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

export function DatasetsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<DatasetKind | "">("");
  const datasets = useQuery({
    queryKey: ["datasets", { kind }],
    queryFn: () => api<Dataset[]>(`/datasets${qs({ kind })}`),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((d) => ["pending", "parsing", "processing"].includes(d.latest_version?.status ?? "")) ? 3000 : false,
  });
  return (
    <>
      <PageHeader
        title={t("datasets.title")}
        description={t("datasets.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.datasets") }]}
        actions={
          can("write") && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <Upload aria-hidden /> {t("datasets.upload")}
            </Button>
          )
        }
      />
      <Card className="overflow-hidden">
        <div className="flex items-center gap-2 border-b border-slate-100 p-3">
          <Select aria-label={t("datasets.kind")} className="w-56" value={kind} onChange={(e) => setKind(e.target.value as DatasetKind | "")}>
            <option value="">{t("datasets.allKinds")}</option>
            {DATASET_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`datasetKind.${k}`)}
              </option>
            ))}
          </Select>
        </div>
        {datasets.isLoading && <LoadingState />}
        {datasets.isError && <ErrorState error={datasets.error} onRetry={() => void datasets.refetch()} />}
        {datasets.data?.length === 0 && (
          <EmptyState
            icon={Table2}
            title={t("datasets.empty")}
            description={t("datasets.emptyHint")}
            action={
              can("write") && (
                <Button variant="accent" onClick={() => setOpen(true)}>
                  <Upload aria-hidden /> {t("datasets.upload")}
                </Button>
              )
            }
          />
        )}
        {datasets.data && datasets.data.length > 0 && (
          <Table>
            <THead>
              <tr>
                <TH>{t("datasets.name")}</TH>
                <TH>{t("datasets.kind")}</TH>
                <TH>{t("datasets.period")}</TH>
                <TH>{t("datasets.latest")}</TH>
                <TH className="text-end">{t("datasets.rows")}</TH>
              </tr>
            </THead>
            <TBody>
              {datasets.data.map((d) => (
                <TR key={d.id}>
                  <TD>
                    <div className="flex flex-wrap items-center gap-2">
                      <Link to={`/datasets/${d.id}`} className="font-medium text-navy-900 transition-colors hover:text-teal-700">
                        {d.name}
                      </Link>
                      {d.is_demo && <SyntheticBadge />}
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">{d.entity_name}</div>
                  </TD>
                  <TD className="text-[13px] text-slate-700">{t(`datasetKind.${d.kind}`)}</TD>
                  <TD className="whitespace-nowrap text-[13px] text-slate-600">
                    {d.period_start || d.period_end ? `${formatDate(d.period_start, i18n.language)} – ${formatDate(d.period_end, i18n.language)}` : "—"}
                  </TD>
                  <TD>
                    {d.latest_version ? (
                      <span className="flex items-center gap-2">
                        <span className="text-xs tabular-nums text-slate-500">v{d.latest_version.version_number}</span>
                        <DatasetStatusBadge status={d.latest_version.status} />
                      </span>
                    ) : (
                      "—"
                    )}
                  </TD>
                  <TD className="text-end tabular-nums text-[13px] text-slate-700">{d.latest_version?.row_count?.toLocaleString(i18n.language) ?? "—"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <DatasetUploadDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
