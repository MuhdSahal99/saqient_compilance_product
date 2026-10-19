import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CheckCheck, Dices, FlaskRound, Loader2, Pencil, Plus, RefreshCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  AMOUNT_PATTERN,
  SAMPLING_METHODS,
  SEED_PATTERN,
  engKey,
  useDatasetKinds,
  useEntityDatasets,
  useRisks,
  useSample,
  useSamples,
  type Engagement,
  type Reproduce,
  type Sample,
  type SampleItem,
} from "@/lib/audit";
import { cn, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState } from "@/components/common";
import { Amount, CalcSteps } from "@/components/calc-explain";
import { Field, Meta, MutationError, ShortHash } from "./shared";

const sampleSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    method: z.enum(SAMPLING_METHODS),
    dataset_version_id: z.string().min(1),
    amount_column: z.string().regex(/^[a-z_]{1,60}$/),
    size: z.string().trim(),
    strata: z.array(z.object({ upper: z.string().trim(), size: z.string().trim() })).max(10),
    seed: z.union([z.literal(""), z.string().trim().regex(SEED_PATTERN)]),
    risk_id: z.string(),
  })
  .superRefine((v, ctx) => {
    if (v.method === "stratified") {
      if (v.strata.length === 0) ctx.addIssue({ code: "custom", path: ["strata"], message: "strata" });
      v.strata.forEach((s, i) => {
        if (s.upper && !AMOUNT_PATTERN.test(s.upper)) ctx.addIssue({ code: "custom", path: ["strata", i, "upper"], message: "amount" });
        if (s.size && !/^\d{1,4}$/.test(s.size)) ctx.addIssue({ code: "custom", path: ["strata", i, "size"], message: "size" });
      });
    } else if (!/^\d{1,4}$/.test(v.size) || /^0+$/.test(v.size)) {
      ctx.addIssue({ code: "custom", path: ["size"], message: "size" });
    }
  });
type SampleValues = z.infer<typeof sampleSchema>;

function NewSampleDialog({ e, open, onOpenChange, onCreated }: { e: Engagement; open: boolean; onOpenChange: (o: boolean) => void; onCreated: (s: Sample) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const datasets = useEntityDatasets(open ? e.entity_id : "");
  const kinds = useDatasetKinds(open);
  const risks = useRisks(e.id);
  const form = useForm<SampleValues>({
    resolver: zodResolver(sampleSchema),
    defaultValues: { name: "", method: "monetary_unit", dataset_version_id: "", amount_column: "", size: "", strata: [], seed: "", risk_id: "" },
  });
  const strata = useFieldArray({ control: form.control, name: "strata" });
  const method = useWatch({ control: form.control, name: "method" });
  const versionId = useWatch({ control: form.control, name: "dataset_version_id" });
  const ready = (datasets.data ?? []).filter((d) => d.latest_version?.status === "ready");
  const chosen = ready.find((d) => d.latest_version?.id === versionId);
  const amountCols = (kinds.data?.find((k) => k.kind === chosen?.kind)?.fields ?? []).filter((f) => f.type === "amount").map((f) => f.name);
  const create = useMutation({
    mutationFn: (v: SampleValues) =>
      api<Sample>(`/engagements/${e.id}/samples`, {
        json: {
          name: v.name,
          method: v.method,
          dataset_version_id: v.dataset_version_id,
          amount_column: v.amount_column,
          size: v.method === "stratified" ? null : Number(v.size),
          strata: v.method === "stratified" ? v.strata.map((s) => ({ upper: s.upper || null, size: s.size ? Number(s.size) : null })) : [],
          seed: v.seed || null,
          risk_id: v.risk_id || null,
        },
      }),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "samples") });
      qc.setQueryData(["samples", s.id], s);
      toast.success(t("engagements.sampling.created"));
      onCreated(s);
      close();
    },
  });
  function close() {
    form.reset();
    create.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{t("engagements.sampling.new")}</DialogTitle>
        <DialogDescription>{t("engagements.sampling.newHint")}</DialogDescription>
        {datasets.isLoading && <LoadingState rows={3} />}
        {datasets.isError && <ErrorState error={datasets.error} onRetry={() => void datasets.refetch()} />}
        {datasets.data && ready.length === 0 && <EmptyState title={t("engagements.sampling.noDatasets")} />}
        {ready.length > 0 && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="smp-name" label={t("engagements.sampling.name")} error={err.name ? t("engagements.nameRequired") : undefined}>
                <Input id="smp-name" aria-invalid={!!err.name} {...form.register("name")} />
              </Field>
              <Field id="smp-method" label={t("engagements.sampling.method")}>
                <Select id="smp-method" {...form.register("method")}>
                  {SAMPLING_METHODS.map((m) => (
                    <option key={m} value={m}>
                      {t(`samplingMethod.${m}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="smp-dataset" label={t("engagements.sampling.dataset")} error={err.dataset_version_id ? t("engagements.sampling.datasetRequired") : undefined}>
                <Select id="smp-dataset" aria-invalid={!!err.dataset_version_id} {...form.register("dataset_version_id")}>
                  <option value="">{t("engagements.sampling.chooseDataset")}</option>
                  {ready.map((d) => (
                    <option key={d.id} value={d.latest_version?.id}>
                      {d.name} · {t(`datasetKind.${d.kind}`)} · v{d.latest_version?.version_number}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="smp-column" label={t("engagements.sampling.amountColumn")} error={err.amount_column ? t("engagements.sampling.columnRequired") : undefined}>
                <Select id="smp-column" aria-invalid={!!err.amount_column} disabled={!chosen} {...form.register("amount_column")}>
                  <option value="">{t("engagements.sampling.chooseColumn")}</option>
                  {amountCols.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            {method !== "stratified" ? (
              <Field id="smp-size" label={t("engagements.sampling.size")} error={err.size ? t("engagements.sampling.sizeRule") : undefined}>
                <Input id="smp-size" dir="ltr" inputMode="numeric" className="sm:w-40" aria-invalid={!!err.size} {...form.register("size")} />
              </Field>
            ) : (
              <fieldset className="space-y-2">
                <legend className="text-[13px] font-medium text-slate-700">{t("engagements.sampling.strata")}</legend>
                <p className="text-xs text-slate-500">{t("engagements.sampling.strataHint")}</p>
                {strata.fields.map((f, i) => (
                  <div key={f.id} className="flex flex-wrap items-end gap-2">
                    <Field id={`smp-upper-${i}`} label={t("engagements.sampling.upper", { n: i + 1 })}>
                      <Input id={`smp-upper-${i}`} dir="ltr" inputMode="decimal" className="w-44" aria-invalid={!!err.strata?.[i]?.upper} {...form.register(`strata.${i}.upper`)} />
                    </Field>
                    <Field id={`smp-ssize-${i}`} label={t("engagements.sampling.stratumSize", { n: i + 1 })}>
                      <Input id={`smp-ssize-${i}`} dir="ltr" inputMode="numeric" className="w-32" aria-invalid={!!err.strata?.[i]?.size} {...form.register(`strata.${i}.size`)} />
                    </Field>
                    <Button type="button" variant="ghost" size="icon-sm" aria-label={t("engagements.tb.removeRow", { n: i + 1 })} onClick={() => strata.remove(i)}>
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                ))}
                {err.strata && <p role="alert" className="text-xs font-medium text-red-600">{t("engagements.sampling.strataRule")}</p>}
                <Button type="button" variant="outline" size="sm" disabled={strata.fields.length >= 10} onClick={() => strata.append({ upper: "", size: "" })}>
                  <Plus aria-hidden /> {t("engagements.sampling.addStratum")}
                </Button>
              </fieldset>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="smp-seed" label={t("engagements.sampling.seed")} hint={t("engagements.sampling.seedHint")} error={err.seed ? t("engagements.sampling.seedRule") : undefined}>
                <Input id="smp-seed" dir="ltr" aria-invalid={!!err.seed} {...form.register("seed")} />
              </Field>
              <Field id="smp-risk" label={t("engagements.sampling.risk")}>
                <Select id="smp-risk" {...form.register("risk_id")}>
                  <option value="">{t("engagements.sampling.noRisk")}</option>
                  {(risks.data ?? []).map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.ref} · {r.title}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <MutationError error={create.error} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={create.isPending}>
                {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t("engagements.sampling.select")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

const itemSchema = z.object({ audited_value: z.string().trim().regex(AMOUNT_PATTERN), note: z.string().max(1000) });
type ItemValues = z.infer<typeof itemSchema>;

function ItemDialog({ sample, item, onClose }: { sample: Sample; item: SampleItem | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<ItemValues>({ resolver: zodResolver(itemSchema), defaultValues: { audited_value: "", note: "" } });
  useEffect(() => {
    if (item) form.reset({ audited_value: item.audited_value ?? "", note: item.note });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset per item
  }, [item]);
  const save = useMutation({
    mutationFn: (v: ItemValues) => api<Sample>(`/samples/${sample.id}/items/${item?.row_id}`, { method: "PUT", json: v }),
    onSuccess: (s) => {
      qc.setQueryData(["samples", s.id], s);
      toast.success(t("engagements.sampling.itemSaved"));
      save.reset();
      onClose();
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open={!!item} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{t("engagements.sampling.testItem", { row: item?.row_id ?? "" })}</DialogTitle>
        <DialogDescription>{t("engagements.sampling.testItemHint", { book: item?.book_value ?? "" })}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <Field id="item-value" label={t("engagements.sampling.auditedValue")} error={err.audited_value ? t("engagements.amountRule") : undefined}>
            <div className="flex gap-2">
              <Input id="item-value" dir="ltr" inputMode="decimal" aria-invalid={!!err.audited_value} {...form.register("audited_value")} />
              <Button type="button" variant="outline" onClick={() => item && form.setValue("audited_value", item.book_value, { shouldValidate: true })}>
                {t("engagements.sampling.useBook")}
              </Button>
            </div>
          </Field>
          <Field id="item-note" label={t("losses.note")} hint={t("engagements.sampling.noteHint")}>
            <Textarea id="item-note" rows={2} {...form.register("note")} />
          </Field>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const RESULT_TONE = { not_tested: "neutral", no_exception: "green", exception: "red" } as const;

function SampleDetail({ e, sampleId }: { e: Engagement; sampleId: string }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const sample = useSample(sampleId);
  const [item, setItem] = useState<SampleItem | null>(null);
  const [conclusion, setConclusion] = useState("");
  // The caller keys this component by sample, so the reproduce result resets per sample.
  const [repro, setRepro] = useState<Reproduce | null>(null);
  const conclude = useMutation({
    mutationFn: (text: string) => api<Sample>(`/samples/${sampleId}/conclusion`, { json: { conclusion: text } }),
    onSuccess: (s) => {
      qc.setQueryData(["samples", s.id], s);
      void qc.invalidateQueries({ queryKey: engKey(e.id, "samples") });
      toast.success(t("engagements.sampling.concluded"));
    },
  });
  const reproduce = useMutation({
    mutationFn: () => api<Reproduce>(`/samples/${sampleId}/reproduce`),
    onSuccess: setRepro,
  });
  if (sample.isLoading) return <LoadingState rows={4} />;
  if (sample.isError || !sample.data) return <ErrorState error={sample.error} onRetry={() => void sample.refetch()} />;
  const s = sample.data;
  const editable = can("write") && e.status !== "closed";
  const untested = s.items.filter((x) => x.result === "not_tested").length;
  const p = s.projection;
  return (
    <div className="space-y-5">
      <Card className="px-5 py-4">
        <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Meta label={t("engagements.sampling.method")}>{t(`samplingMethod.${s.method}`)}</Meta>
          <Meta label={t("engagements.sampling.seed")}>
            <code dir="ltr" className="font-mono text-xs">
              {s.seed}
            </code>
          </Meta>
          <Meta label={t("engagements.sampling.algorithm")}>
            <code dir="ltr" className="font-mono text-xs">
              {s.algorithm_version}
            </code>
          </Meta>
          <Meta label={t("engagements.sampling.population")}>
            {s.population_count} · <Amount value={s.population_value} currency={e.currency} />
          </Meta>
          <Meta label={t("engagements.sampling.populationHash")}>
            <ShortHash value={s.population_sha256} />
          </Meta>
          <Meta label={t("engagements.sampling.amountColumn")}>
            <code dir="ltr" className="font-mono text-xs">
              {s.amount_column}
            </code>
          </Meta>
        </dl>
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
          <Button variant="outline" size="sm" disabled={reproduce.isPending} onClick={() => reproduce.mutate()}>
            {reproduce.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCcw aria-hidden />}
            {t("engagements.sampling.reproduce")}
          </Button>
          {repro && (
            <span role="status" className="flex flex-wrap items-center gap-2 text-xs">
              <Badge tone={repro.reproducible ? "green" : "red"} dot>
                {repro.reproducible ? t("engagements.sampling.reproducible") : t("engagements.sampling.notReproducible")}
              </Badge>
              <Badge tone={repro.population_unchanged ? "green" : "amber"} dot>
                {repro.population_unchanged ? t("engagements.sampling.populationUnchanged") : t("engagements.sampling.populationChanged")}
              </Badge>
              {repro.differences.length > 0 && <span className="text-slate-600">{t("engagements.sampling.differences", { rows: repro.differences.join(", ") })}</span>}
            </span>
          )}
          <MutationError error={reproduce.error} />
        </div>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>{t("engagements.sampling.items", { count: s.items.length })}</CardTitle>
          <CardDescription>{t("engagements.sampling.itemsHint")}</CardDescription>
        </CardHeader>
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.sampling.row")}</TH>
              {s.method === "stratified" && <TH>{t("engagements.sampling.stratum")}</TH>}
              {s.method === "monetary_unit" && <TH className="text-end">{t("engagements.sampling.hits")}</TH>}
              <TH className="text-end">{t("engagements.sampling.bookValue")}</TH>
              <TH className="text-end">{t("engagements.sampling.auditedValue")}</TH>
              <TH>{t("engagements.sampling.result")}</TH>
              <TH>{t("losses.note")}</TH>
              {editable && !s.conclusion && <TH className="w-14">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {s.items.map((x) => (
              <TR key={x.row_id}>
                <TD className="tabular-nums">{x.row_id}</TD>
                {s.method === "stratified" && <TD className="tabular-nums">{x.stratum != null ? x.stratum + 1 : "—"}</TD>}
                {s.method === "monetary_unit" && <TD className="text-end tabular-nums">{x.hits}</TD>}
                <TD className="text-end">
                  <Amount value={x.book_value} />
                </TD>
                <TD className="text-end">
                  <Amount value={x.audited_value} />
                </TD>
                <TD>
                  <Badge tone={RESULT_TONE[x.result]} dot>
                    {t(`sampleItemResult.${x.result}`)}
                  </Badge>
                </TD>
                <TD className="max-w-64 text-xs text-slate-500">
                  {x.note || "—"}
                  {x.tested_at && <span className="block text-slate-400">{formatDate(x.tested_at, i18n.language, true)}</span>}
                </TD>
                {editable && !s.conclusion && (
                  <TD>
                    <Button variant="ghost" size="icon-sm" aria-label={t("engagements.sampling.testItem", { row: x.row_id })} onClick={() => setItem(x)}>
                      <Pencil aria-hidden />
                    </Button>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("engagements.sampling.projection")}</CardTitle>
            <CardDescription>{t("engagements.sampling.projectionHint")}</CardDescription>
          </CardHeader>
          <div className="space-y-3 px-5 py-4">
            <dl className="grid gap-3 sm:grid-cols-3">
              <Meta label={t("engagements.sampling.projected")}>
                <Amount value={p.projected} currency={e.currency} />
              </Meta>
              <Meta label={t("engagements.sampling.known")}>
                <Amount value={p.known} />
              </Meta>
              <Meta label={t("engagements.sampling.untested")}>{p.untested}</Meta>
            </dl>
            <CalcSteps steps={p.steps} />
            {p.performance_materiality == null ? (
              <p className="text-xs text-slate-500">{t("engagements.sampling.noMateriality")}</p>
            ) : (
              <p className={cn("rounded-lg border px-3 py-2 text-xs", p.exceeds_performance ? "border-red-200 bg-red-50 text-red-800" : "border-slate-200 bg-slate-50 text-slate-700")}>
                {p.exceeds_performance
                  ? t("engagements.sampling.exceeds", { pm: p.performance_materiality })
                  : t("engagements.sampling.below", { pm: p.performance_materiality })}
              </p>
            )}
          </div>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("engagements.sampling.conclusion")}</CardTitle>
            <CardDescription>{t("engagements.sampling.conclusionHint")}</CardDescription>
          </CardHeader>
          <div className="space-y-3 px-5 py-4">
            {s.conclusion ? (
              <p className="whitespace-pre-wrap text-sm text-slate-700">{s.conclusion}</p>
            ) : editable ? (
              <form
                className="space-y-3"
                onSubmit={(ev) => {
                  ev.preventDefault();
                  if (conclusion.trim()) conclude.mutate(conclusion.trim());
                }}
              >
                <Field id="smp-conclusion" label={t("engagements.sampling.conclusion")}>
                  <Textarea id="smp-conclusion" rows={3} value={conclusion} onChange={(ev) => setConclusion(ev.target.value)} />
                </Field>
                {untested > 0 && <p className="text-xs text-slate-500">{t("engagements.sampling.untestedLeft", { count: untested })}</p>}
                <MutationError error={conclude.error} />
                <Button type="submit" variant="accent" size="sm" disabled={!conclusion.trim() || untested > 0 || conclude.isPending}>
                  {conclude.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <CheckCheck aria-hidden />}
                  {t("engagements.sampling.conclude")}
                </Button>
              </form>
            ) : (
              <p className="text-sm text-slate-500">{t("engagements.sampling.notConcluded")}</p>
            )}
          </div>
        </Card>
      </div>
      <ItemDialog sample={s} item={item} onClose={() => setItem(null)} />
    </div>
  );
}

export function SamplingTab({ e }: { e: Engagement }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const list = useSamples(e.id);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? list.data?.[0]?.id ?? null;
  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>{t("engagements.sampling.title")}</CardTitle>
            <CardDescription>{t("engagements.sampling.hint")}</CardDescription>
          </div>
          {can("write") && e.status !== "closed" && (
            <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
              <Dices aria-hidden /> {t("engagements.sampling.new")}
            </Button>
          )}
        </CardHeader>
        {list.isLoading && <LoadingState rows={2} />}
        {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
        {list.data?.length === 0 && <EmptyState icon={FlaskRound} title={t("engagements.sampling.empty")} />}
        {list.data && list.data.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {list.data.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  aria-pressed={current === s.id}
                  onClick={() => setSelected(s.id)}
                  className={cn("flex w-full flex-wrap items-center justify-between gap-2 px-5 py-2.5 text-start transition-colors hover:bg-slate-50", current === s.id && "bg-teal-50/60")}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-navy-900">{s.name}</span>
                    <span className="block text-xs text-slate-500">
                      {t(`samplingMethod.${s.method}`)} · {t("engagements.sampling.itemCount", { count: s.item_count })} · {formatDate(s.created_at, i18n.language)}
                    </span>
                  </span>
                  <Badge tone={s.conclusion ? "green" : "neutral"} dot>
                    {s.conclusion ? t("engagements.sampling.concludedBadge") : t("engagements.sampling.open")}
                  </Badge>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {current && <SampleDetail key={current} e={e} sampleId={current} />}
      <NewSampleDialog e={e} open={open} onOpenChange={setOpen} onCreated={(s) => setSelected(s.id)} />
    </div>
  );
}
