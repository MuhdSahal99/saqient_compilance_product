import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle, CheckCircle2, Columns3, Fingerprint, Info, Loader2, Sigma, Upload } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { DatasetDetail, DatasetKindSchema, DatasetRows, DatasetVersionDetail } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { cn, formatBytes, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { DatasetStatusBadge, ErrorState, errorMessage, LoadingState, PageHeader, Pagination, SyntheticBadge, useUnsavedChangesWarning } from "@/components/common";
import { DatasetUploadDialog } from "./DatasetsPage";

const DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d"] as const;
const DATE_FORMAT_LABEL: Record<(typeof DATE_FORMATS)[number], string> = {
  "%Y-%m-%d": "2025-01-31",
  "%d/%m/%Y": "31/01/2025",
  "%m/%d/%Y": "01/31/2025",
  "%d-%m-%Y": "31-01-2025",
  "%d.%m.%Y": "31.01.2025",
  "%Y/%m/%d": "2025/01/31",
};
const BUSY = new Set(["pending", "parsing", "processing"]);
const ROWS_PAGE = 50;

function MappingForm({ version, schema }: { version: DatasetVersionDetail; schema: DatasetKindSchema }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [mapping, setMapping] = useState<Record<string, string>>(version.column_mapping);
  const [dateFormat, setDateFormat] = useState(version.parse_options.date_format ?? "%Y-%m-%d");
  const [decimal, setDecimal] = useState(version.parse_options.decimal_separator ?? ".");
  const dirty = JSON.stringify(mapping) !== JSON.stringify(version.column_mapping);
  useUnsavedChangesWarning(dirty);

  const missing = schema.fields.filter((f) => f.required && !mapping[f.name]).map((f) => f.name);
  // At least one group (e.g. debit + credit, or a signed amount) must be fully mapped.
  const groupMissing = schema.require_any.length > 0 && !schema.require_any.some((g) => g.every((f) => mapping[f]));
  const confirm = useMutation({
    mutationFn: () =>
      api<DatasetVersionDetail>(`/dataset-versions/${version.id}/mapping`, {
        method: "PUT",
        json: {
          mapping: Object.fromEntries(Object.entries(mapping).filter(([, v]) => v)),
          date_format: dateFormat,
          decimal_separator: decimal,
        },
      }),
    onSuccess: (v) => {
      qc.setQueryData(["dataset-version", v.id], v);
      void qc.invalidateQueries({ queryKey: ["dataset", v.dataset_id] });
      void qc.invalidateQueries({ queryKey: ["datasets"] });
      toast.success(t("datasets.mappingConfirmed"));
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Columns3 className="size-4 text-slate-400" aria-hidden />
          {t("datasets.mapping")}
        </CardTitle>
        <CardDescription>{t("datasets.mappingHint")}</CardDescription>
      </CardHeader>
      <form
        className="space-y-5 px-5 pb-5"
        onSubmit={(e) => {
          e.preventDefault();
          confirm.mutate();
        }}
        noValidate
      >
        <div className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
          {schema.fields.map((f) => {
            const id = `map-${f.name}`;
            return (
              <div key={f.name} className="space-y-1.5">
                <Label htmlFor={id} className="flex items-center gap-1.5">
                  <code className="font-mono text-[12px]">{f.name}</code>
                  <span className="text-[11px] font-normal text-slate-400">{t(`datasets.fieldType.${f.type}`, { defaultValue: f.type })}</span>
                  {f.required && <span className="text-[11px] font-normal text-amber-700">{t("datasets.required")}</span>}
                </Label>
                <Select
                  id={id}
                  dir="auto"
                  aria-invalid={f.required && !mapping[f.name]}
                  value={mapping[f.name] ?? ""}
                  onChange={(e) => setMapping((m) => ({ ...m, [f.name]: e.target.value }))}
                >
                  <option value="">{t("datasets.notMapped")}</option>
                  {version.source_columns.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </div>
            );
          })}
        </div>
        {schema.require_any.length > 0 && (
          <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
            {t("datasets.requireAny", { groups: schema.require_any.map((g) => g.join(" + ")).join(" | ") })}
          </p>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="map-date">{t("datasets.dateFormat")}</Label>
            <Select id="map-date" dir="ltr" value={dateFormat} onChange={(e) => setDateFormat(e.target.value)}>
              {DATE_FORMATS.map((f) => (
                <option key={f} value={f}>
                  {DATE_FORMAT_LABEL[f]}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="map-decimal">{t("datasets.decimalSeparator")}</Label>
            <Select id="map-decimal" value={decimal} onChange={(e) => setDecimal(e.target.value)}>
              <option value=".">{t("datasets.decimalDot")}</option>
              <option value=",">{t("datasets.decimalComma")}</option>
            </Select>
          </div>
        </div>
        {(missing.length > 0 || groupMissing) && (
          <p className="text-xs text-amber-800">
            {t("datasets.mappingIncomplete", {
              fields: [...missing, ...(groupMissing ? [schema.require_any.map((g) => g.join(" + ")).join(" | ")] : [])].join(", "),
            })}
          </p>
        )}
        {confirm.isError && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            {errorMessage(confirm.error, t("common.genericError"))}
          </p>
        )}
        <Button type="submit" variant="accent" disabled={confirm.isPending || missing.length > 0 || groupMissing}>
          {confirm.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {t("datasets.confirmMapping")}
        </Button>
      </form>
    </Card>
  );
}

function SimpleTable({ columns, rows, caption }: { columns: string[]; rows: (string | number | boolean | null | undefined)[][]; caption: string }) {
  return (
    <div className="max-h-[28rem] overflow-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-slate-50 text-slate-500">
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 text-start font-medium" dir="auto">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j} className="whitespace-nowrap px-3 py-1.5 font-mono tabular-nums text-slate-700" dir="auto">
                  {v === null || v === undefined || v === "" ? <span className="text-slate-300">—</span> : String(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RowsPanel({ versionId, highlight }: { versionId: string; highlight: number[] }) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const rows = useQuery({
    queryKey: ["dataset-rows", versionId, highlight.length ? highlight.join(",") : page],
    queryFn: () =>
      api<DatasetRows>(
        `/dataset-versions/${versionId}/rows${qs(highlight.length ? { row_ids: highlight.join(","), limit: 200 } : { offset: (page - 1) * ROWS_PAGE, limit: ROWS_PAGE })}`,
      ),
  });
  if (rows.isLoading) return <LoadingState />;
  if (rows.isError) return <ErrorState error={rows.error} onRetry={() => void rows.refetch()} />;
  if (!rows.data) return null;
  return (
    <>
      {highlight.length > 0 && <p className="border-b border-slate-100 px-4 py-2 text-xs text-slate-500">{t("datasets.showingRows", { rows: highlight.join(", ") })}</p>}
      <SimpleTable caption={t("datasets.rowsTab")} columns={rows.data.columns} rows={rows.data.rows.map((r) => rows.data.columns.map((c) => r[c]))} />
      {highlight.length === 0 && <Pagination page={page} pageSize={ROWS_PAGE} total={rows.data.total} onPage={setPage} />}
    </>
  );
}

type Panel = "preview" | "rows" | "errors";

export function DatasetDetailPage() {
  const { datasetId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [uploadOpen, setUploadOpen] = useState(false);
  const dataset = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api<DatasetDetail>(`/datasets/${datasetId}`),
    refetchInterval: (q) => (q.state.data?.versions.some((v) => BUSY.has(v.status)) ? 2500 : false),
  });
  const kinds = useQuery({ queryKey: ["dataset-kinds"], queryFn: () => api<DatasetKindSchema[]>("/dataset-kinds"), staleTime: Infinity });
  const versions = [...(dataset.data?.versions ?? [])].sort((a, b) => b.version_number - a.version_number);
  const versionId = params.get("version") ?? versions[0]?.id;
  const highlight = (params.get("rows") ?? "")
    .split(",")
    .map((x) => Number.parseInt(x, 10))
    .filter((n) => Number.isFinite(n));
  const version = useQuery({
    queryKey: ["dataset-version", versionId],
    queryFn: () => api<DatasetVersionDetail>(`/dataset-versions/${versionId}`),
    enabled: !!versionId,
    refetchInterval: (q) => (q.state.data && BUSY.has(q.state.data.status) ? 2500 : false),
  });
  const v = version.data;
  const panel: Panel = (params.get("panel") as Panel | null) ?? (highlight.length ? "rows" : v?.status === "ready" ? "rows" : v?.error_count ? "errors" : "preview");
  const setPanel = (p: Panel) =>
    setParams((s) => {
      s.set("panel", p);
      s.delete("rows");
      return s;
    });

  if (dataset.isLoading) return <LoadingState />;
  if (dataset.isError || !dataset.data) return <ErrorState error={dataset.error} onRetry={() => void dataset.refetch()} />;
  const d = dataset.data;
  const schema = kinds.data?.find((k) => k.kind === d.kind);
  const canMap = can("write") && v && (v.status === "needs_mapping" || (v.status === "failed" && v.source_columns.length > 0)) && !["mt940", "camt053"].includes(v.file_format);

  return (
    <>
      <PageHeader
        title={d.name}
        crumbs={[{ label: t("nav.datasets"), to: "/datasets" }, { label: d.name }]}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{t(`datasetKind.${d.kind}`)}</Badge>
            <span>{d.entity_name}</span>
            {(d.period_start || d.period_end) && (
              <span className="text-slate-400">
                {formatDate(d.period_start, i18n.language)} – {formatDate(d.period_end, i18n.language)}
              </span>
            )}
            {d.is_demo && <SyntheticBadge />}
          </span>
        }
        actions={
          can("write") && (
            <Button variant="outline" onClick={() => setUploadOpen(true)}>
              <Upload aria-hidden /> {t("datasets.newVersion")}
            </Button>
          )
        }
      />
      <div className="grid items-start gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="overflow-hidden">
          <p className="border-b border-slate-100 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{t("datasets.versions")}</p>
          <ul className="divide-y divide-slate-100">
            {versions.map((x) => (
              <li key={x.id}>
                <button
                  type="button"
                  onClick={() =>
                    setParams((s) => {
                      s.set("version", x.id);
                      s.delete("rows");
                      s.delete("panel");
                      return s;
                    })
                  }
                  aria-current={x.id === versionId}
                  className={cn("relative flex w-full flex-col gap-1 px-4 py-3 text-start transition-colors", x.id === versionId ? "bg-teal-50/70" : "hover:bg-slate-50")}
                >
                  <span className={cn("absolute inset-y-0 start-0 w-[3px]", x.id === versionId ? "bg-teal-500" : "bg-transparent")} aria-hidden />
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium tabular-nums text-navy-900">v{x.version_number}</span>
                    <DatasetStatusBadge status={x.status} />
                  </span>
                  <span className="truncate text-xs text-slate-500" dir="auto">
                    {x.original_filename}
                  </span>
                  <span className="text-[11px] text-slate-400">{formatDate(x.created_at, i18n.language, true)}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="min-w-0 space-y-6">
          {version.isLoading && <LoadingState />}
          {version.isError && <ErrorState error={version.error} onRetry={() => void version.refetch()} />}
          {v && (
            <>
              <Card className="p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <DatasetStatusBadge status={v.status} />
                  {BUSY.has(v.status) && (
                    <span className="flex items-center gap-1.5 text-xs text-slate-500">
                      <Loader2 className="size-3.5 animate-spin text-teal-600" aria-hidden />
                      {t(`datasets.busy.${v.status}`)}
                    </span>
                  )}
                </div>
                {v.failure_message && (
                  <p role="alert" className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                    {v.failure_message}
                  </p>
                )}
                <dl className="mt-4 grid gap-x-6 gap-y-2 text-[13px] sm:grid-cols-[auto_1fr]">
                  <dt className="text-slate-500">{t("datasets.file")}</dt>
                  <dd className="text-slate-800" dir="auto">
                    {v.original_filename} · {v.file_format.toUpperCase()} · {formatBytes(v.size_bytes)}
                  </dd>
                  <dt className="text-slate-500">{t("datasets.sourceRows")}</dt>
                  <dd className="tabular-nums text-slate-800">{v.source_row_count?.toLocaleString(i18n.language) ?? "—"}</dd>
                  {v.row_count !== null && (
                    <>
                      <dt className="text-slate-500">{t("datasets.canonicalRows")}</dt>
                      <dd className="tabular-nums text-slate-800">{v.row_count.toLocaleString(i18n.language)}</dd>
                    </>
                  )}
                  <dt className="flex items-center gap-1.5 text-slate-500">
                    <Fingerprint className="size-3.5" aria-hidden />
                    SHA-256
                  </dt>
                  <dd className="break-all font-mono text-[11px] text-slate-600" dir="ltr">
                    {v.raw_sha256}
                  </dd>
                  {v.parquet_sha256 && (
                    <>
                      <dt className="text-slate-500">{t("datasets.canonicalHash")}</dt>
                      <dd className="break-all font-mono text-[11px] text-slate-600" dir="ltr">
                        {v.parquet_sha256}
                      </dd>
                    </>
                  )}
                  {v.mapping_confirmed_at && (
                    <>
                      <dt className="text-slate-500">{t("datasets.mappingConfirmedAt")}</dt>
                      <dd className="text-slate-800">{formatDate(v.mapping_confirmed_at, i18n.language, true)}</dd>
                    </>
                  )}
                  {v.derived_fields.length > 0 && (
                    <>
                      <dt className="text-slate-500">{t("datasets.derived")}</dt>
                      <dd className="font-mono text-[12px] text-slate-700">{v.derived_fields.join(", ")}</dd>
                    </>
                  )}
                </dl>
                {Object.keys(v.totals).length > 0 && (
                  <div className="mt-4 border-t border-slate-100 pt-4">
                    <p className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-navy-900">
                      <Sigma className="size-4 text-slate-400" aria-hidden />
                      {t("datasets.totals")}
                    </p>
                    <dl className="grid gap-x-6 gap-y-1 text-[13px] sm:grid-cols-[auto_1fr]">
                      {Object.entries(v.totals).map(([k, val]) => (
                        <div key={k} className="contents">
                          <dt className="font-mono text-[12px] text-slate-500">{k}</dt>
                          <dd className="font-mono tabular-nums text-slate-800" dir="ltr">
                            {val}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                )}
                {v.status === "ready" && (
                  <p className="mt-4 flex items-center gap-1.5 text-xs text-emerald-700">
                    <CheckCircle2 className="size-3.5" aria-hidden />
                    {t("datasets.readyHint")}
                  </p>
                )}
              </Card>

              {canMap && schema && <MappingForm key={`${v.id}-${v.status}`} version={v} schema={schema} />}
              {canMap && kinds.isError && <ErrorState error={kinds.error} onRetry={() => void kinds.refetch()} />}

              <Card className="overflow-hidden">
                <Tabs
                  className="px-3"
                  label={t("datasets.dataSections")}
                  value={panel}
                  onChange={setPanel}
                  items={[
                    { key: "preview", label: t("datasets.previewTab") },
                    ...(v.status === "ready" ? [{ key: "rows" as const, label: t("datasets.rowsTab"), count: v.row_count ?? undefined }] : []),
                    { key: "errors", label: t("datasets.errorsTab"), count: v.error_count },
                  ]}
                />
                {panel === "preview" &&
                  (v.preview.length === 0 ? (
                    <p className="px-5 py-6 text-sm text-slate-500">{BUSY.has(v.status) ? t("datasets.previewPending") : t("datasets.noPreview")}</p>
                  ) : (
                    <>
                      <p className="border-b border-slate-100 px-4 py-2 text-xs text-slate-500">{t("datasets.previewHint")}</p>
                      <SimpleTable
                        caption={t("datasets.previewTab")}
                        columns={v.source_columns}
                        rows={v.preview.map((r) => v.source_columns.map((c) => r[c]))}
                      />
                    </>
                  ))}
                {panel === "rows" && v.status === "ready" && <RowsPanel versionId={v.id} highlight={highlight} />}
                {panel === "errors" &&
                  (v.errors.length === 0 ? (
                    <p className="px-5 py-6 text-sm text-slate-500">{t("datasets.noErrors")}</p>
                  ) : (
                    <>
                      {v.error_count > v.errors.length && (
                        <p className="border-b border-slate-100 px-4 py-2 text-xs text-slate-500">{t("datasets.errorsShown", { shown: v.errors.length, total: v.error_count })}</p>
                      )}
                      <SimpleTable
                        caption={t("datasets.errorsTab")}
                        columns={[t("evidence.row"), t("datasets.column"), t("datasets.value"), t("datasets.problem")]}
                        rows={v.errors.map((e) => [e.row_id, e.column ?? e.field, e.value, e.message])}
                      />
                    </>
                  ))}
              </Card>
            </>
          )}
        </div>
      </div>
      <DatasetUploadDialog open={uploadOpen} onOpenChange={setUploadOpen} datasetId={d.id} />
    </>
  );
}
