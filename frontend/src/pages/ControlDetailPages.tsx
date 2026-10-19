import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CircleCheck, FlaskConical, Loader2, Plus, ShieldAlert, ShieldCheck, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ASSERTIONS, REF_PATTERN, RISK_LEVELS, useEntityDatasets } from "@/lib/audit";
import {
  certificationsKey,
  CONTROL_AUTOMATIONS,
  CONTROL_CONCLUSIONS,
  CONTROL_FREQUENCIES,
  CONTROL_NATURES,
  CONTROL_TEST_KINDS,
  deficienciesKey,
  detailKey,
  parseRowIds,
  processesKey,
  ROW_IDS_PATTERN,
  useCertification,
  useProcess,
  type Certification,
  type Control,
  type ControlConclusion,
  type ControlProcess,
  type ControlTest,
} from "@/lib/assurance";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { Field, MutationError } from "@/components/audit/shared";
import { AssuranceNote, AssuranceStatusBadge, Facts, MemberSelect, SignOffCard } from "@/components/assurance/shared";
import { DeficiencyTable } from "./ControlsPage";

function ConclusionBadge({ value }: { value: ControlConclusion | null }) {
  const { t } = useTranslation();
  if (!value) return <Badge tone="neutral">{t("controls.notTested")}</Badge>;
  return (
    <Badge tone={value === "effective" ? "green" : "red"} dot>
      {t(`controlConclusion.${value}`)}
    </Badge>
  );
}

function useProcessUpdate(processId: string) {
  const qc = useQueryClient();
  return (d: ControlProcess) => {
    qc.setQueryData(detailKey(processesKey, processId), d);
    void qc.invalidateQueries({ queryKey: [...processesKey, "list"] });
  };
}

// ---------------------------------------------------------------- risks

const riskSchema = z.object({
  ref: z.string().trim().regex(REF_PATTERN),
  description: z.string().trim().min(1).max(5000),
  rating: z.enum(RISK_LEVELS),
  assertions: z.array(z.enum(ASSERTIONS)),
});
type RiskValues = z.infer<typeof riskSchema>;

function AddRiskDialog({ p, open, onOpenChange }: { p: ControlProcess; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const update = useProcessUpdate(p.id);
  const form = useForm<RiskValues>({ resolver: zodResolver(riskSchema), defaultValues: { ref: "", description: "", rating: "medium", assertions: [] } });
  const add = useMutation({
    mutationFn: (v: RiskValues) => api<ControlProcess>(`/control-processes/${p.id}/risks`, { json: v }),
    onSuccess: (d) => {
      update(d);
      close();
      toast.success(t("controls.riskAdded"));
    },
  });
  function close() {
    form.reset();
    add.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogTitle>{t("controls.addRisk")}</DialogTitle>
        <DialogDescription>{t("controls.addRiskHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="risk-ref" label={t("controls.ref")} error={err.ref ? t("controls.refRule") : undefined}>
              <Input id="risk-ref" dir="ltr" aria-invalid={!!err.ref} {...form.register("ref")} />
            </Field>
            <Field id="risk-rating" label={t("controls.rating")}>
              <Select id="risk-rating" {...form.register("rating")}>
                {RISK_LEVELS.map((r) => (
                  <option key={r} value={r}>
                    {t(`riskLevel.${r}`)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field id="risk-desc" label={t("controls.descriptionField")} error={err.description ? t("recs.nameRequired") : undefined}>
            <Textarea id="risk-desc" rows={3} aria-invalid={!!err.description} {...form.register("description")} />
          </Field>
          <fieldset>
            <legend className="mb-1.5 text-[13px] font-medium text-slate-700">{t("controls.assertions")}</legend>
            <div className="grid gap-1.5 sm:grid-cols-3">
              {ASSERTIONS.map((a) => (
                <label key={a} className="flex items-center gap-2 text-[13px] text-slate-700">
                  <input type="checkbox" className="size-4 accent-teal-600" value={a} {...form.register("assertions")} />
                  {t(`assertion.${a}`)}
                </label>
              ))}
            </div>
          </fieldset>
          <MutationError error={add.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={add.isPending}>
              {add.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("controls.addRisk")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- controls

const controlSchema = z.object({
  ref: z.string().trim().regex(REF_PATTERN),
  title: z.string().trim().min(1).max(300),
  description: z.string().max(5000),
  key: z.boolean(),
  nature: z.enum(CONTROL_NATURES),
  automation: z.enum(CONTROL_AUTOMATIONS),
  frequency: z.enum(CONTROL_FREQUENCIES),
  owner_id: z.string(),
  risk_ids: z.array(z.string()),
});
type ControlValues = z.infer<typeof controlSchema>;

function AddControlDialog({ p, open, onOpenChange }: { p: ControlProcess; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const update = useProcessUpdate(p.id);
  const form = useForm<ControlValues>({
    resolver: zodResolver(controlSchema),
    defaultValues: { ref: "", title: "", description: "", key: false, nature: "preventive", automation: "manual", frequency: "monthly", owner_id: "", risk_ids: [] },
  });
  const add = useMutation({
    mutationFn: (v: ControlValues) => api<ControlProcess>(`/control-processes/${p.id}/controls`, { json: { ...v, owner_id: v.owner_id || null } }),
    onSuccess: (d) => {
      update(d);
      close();
      toast.success(t("controls.controlAdded"));
    },
  });
  function close() {
    form.reset();
    add.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{t("controls.addControl")}</DialogTitle>
        <DialogDescription>{t("controls.addControlHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-[1fr_2fr]">
            <Field id="ctl-ref" label={t("controls.ref")} error={err.ref ? t("controls.refRule") : undefined}>
              <Input id="ctl-ref" dir="ltr" aria-invalid={!!err.ref} {...form.register("ref")} />
            </Field>
            <Field id="ctl-title" label={t("controls.controlTitle")} error={err.title ? t("recs.nameRequired") : undefined}>
              <Input id="ctl-title" aria-invalid={!!err.title} {...form.register("title")} />
            </Field>
          </div>
          <Field id="ctl-desc" label={t("controls.descriptionField")}>
            <Textarea id="ctl-desc" rows={2} {...form.register("description")} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field id="ctl-nature" label={t("controls.nature")}>
              <Select id="ctl-nature" {...form.register("nature")}>
                {CONTROL_NATURES.map((n) => (
                  <option key={n} value={n}>
                    {t(`controlNature.${n}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="ctl-auto" label={t("controls.automation")}>
              <Select id="ctl-auto" {...form.register("automation")}>
                {CONTROL_AUTOMATIONS.map((n) => (
                  <option key={n} value={n}>
                    {t(`controlAutomation.${n}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="ctl-freq" label={t("controls.frequency")}>
              <Select id="ctl-freq" {...form.register("frequency")}>
                {CONTROL_FREQUENCIES.map((n) => (
                  <option key={n} value={n}>
                    {t(`controlFrequency.${n}`)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="grid items-end gap-3 sm:grid-cols-2">
            <MemberSelect id="ctl-owner" label={t("recs.owner")} reg={form.register("owner_id")} />
            <label className="flex h-9 items-center gap-2 text-[13px] text-slate-700">
              <input type="checkbox" className="size-4 accent-teal-600" {...form.register("key")} />
              {t("controls.keyControl")}
            </label>
          </div>
          <fieldset>
            <legend className="mb-1.5 text-[13px] font-medium text-slate-700">{t("controls.mitigates")}</legend>
            {p.risks.length === 0 ? (
              <p className="text-xs text-slate-500">{t("controls.noRisksYet")}</p>
            ) : (
              <div className="space-y-1.5">
                {p.risks.map((r) => (
                  <label key={r.id} className="flex items-start gap-2 text-[13px] text-slate-700">
                    <input type="checkbox" className="mt-0.5 size-4 accent-teal-600" value={r.id} {...form.register("risk_ids")} />
                    <span>
                      <span dir="ltr" className="font-medium">
                        {r.ref}
                      </span>{" "}
                      {r.description}
                    </span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <MutationError error={add.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={add.isPending}>
              {add.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("controls.addControl")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- tests

const testSchema = z
  .object({
    kind: z.enum(CONTROL_TEST_KINDS),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
    procedure: z.string().max(5000),
    sample_size: z.string().trim().regex(/^\d{1,5}$/),
    evidence: z.array(z.object({ dataset_version_id: z.string().min(1), row_ids: z.string().regex(ROW_IDS_PATTERN) })).max(50),
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type TestValues = z.infer<typeof testSchema>;

function AddTestDialog({ p, control, onClose }: { p: ControlProcess; control: Control; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const datasets = useEntityDatasets(p.entity_id);
  const versions = (datasets.data ?? []).filter((d) => d.latest_version?.status === "ready");
  const form = useForm<TestValues>({
    resolver: zodResolver(testSchema),
    defaultValues: { kind: "operating", period_start: "", period_end: "", procedure: "", sample_size: "0", evidence: [] },
  });
  const evidence = useFieldArray({ control: form.control, name: "evidence" });
  const add = useMutation({
    mutationFn: (v: TestValues) =>
      api<ControlTest>(`/controls/${control.id}/tests`, {
        json: {
          ...v,
          sample_size: Number(v.sample_size),
          evidence: v.evidence.map((e) => ({ kind: "dataset_rows", dataset_version_id: e.dataset_version_id, row_ids: parseRowIds(e.row_ids) })),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: detailKey(processesKey, p.id) });
      toast.success(t("controls.test.added"));
      onClose();
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{t("controls.test.addTitle", { ref: control.ref })}</DialogTitle>
        <DialogDescription>{t("controls.test.addHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="ct-kind" label={t("controls.test.kind")}>
              <Select id="ct-kind" {...form.register("kind")}>
                {CONTROL_TEST_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {t(`controlTestKind.${k}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="ct-sample" label={t("controls.test.sampleSize")} hint={t("controls.test.sampleSizeHint")} error={err.sample_size ? t("controls.test.sampleRule") : undefined}>
              <Input id="ct-sample" dir="ltr" inputMode="numeric" aria-invalid={!!err.sample_size} {...form.register("sample_size")} />
            </Field>
            <Field id="ct-start" label={t("workpapers.periodStart")} error={err.period_start ? t("rulePacks.dateRequired") : undefined}>
              <Input id="ct-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
            </Field>
            <Field
              id="ct-end"
              label={t("workpapers.periodEnd")}
              error={err.period_end ? (err.period_end.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired")) : undefined}
            >
              <Input id="ct-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
            </Field>
          </div>
          <Field id="ct-proc" label={t("controls.test.procedure")}>
            <Textarea id="ct-proc" rows={3} {...form.register("procedure")} />
          </Field>
          <div className="space-y-2">
            <p className="text-[13px] font-medium text-slate-700">{t("controls.test.evidence")}</p>
            <p className="text-xs text-slate-500">{t("controls.test.evidenceHint")}</p>
            {datasets.isError && <MutationError error={datasets.error} />}
            {evidence.fields.map((f, i) => (
              <div key={f.id} className="grid items-end gap-2 sm:grid-cols-[2fr_2fr_auto]">
                <Field id={`ev-ds-${i}`} label={t("controls.test.datasetVersion")} error={err.evidence?.[i]?.dataset_version_id ? t("assurance.datasetRequired") : undefined}>
                  <Select id={`ev-ds-${i}`} {...form.register(`evidence.${i}.dataset_version_id`)}>
                    <option value="">{t("assurance.chooseDataset")}</option>
                    {versions.map((d) => (
                      <option key={d.id} value={d.latest_version!.id}>
                        {d.name} · {t(`datasetKind.${d.kind}`)} · v{d.latest_version!.version_number}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field id={`ev-rows-${i}`} label={t("controls.test.rowIds")} error={err.evidence?.[i]?.row_ids ? t("controls.test.rowIdsRule") : undefined}>
                  <Input id={`ev-rows-${i}`} dir="ltr" placeholder="1, 2, 3" {...form.register(`evidence.${i}.row_ids`)} />
                </Field>
                <Button type="button" variant="ghost" size="icon" aria-label={t("controls.test.removeEvidence")} onClick={() => evidence.remove(i)}>
                  <Trash2 aria-hidden />
                </Button>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" onClick={() => evidence.append({ dataset_version_id: "", row_ids: "" })}>
              <Plus aria-hidden /> {t("controls.test.addEvidence")}
            </Button>
          </div>
          <MutationError error={add.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={add.isPending}>
              {add.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("controls.test.add")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const completeSchema = z.object({
  conclusion: z.enum(CONTROL_CONCLUSIONS),
  exceptions: z.string().trim().regex(/^\d{1,5}$/),
  rationale: z.string().trim().min(3).max(5000),
});
type CompleteValues = z.infer<typeof completeSchema>;

function CompleteTestDialog({ p, test, onClose }: { p: ControlProcess; test: ControlTest; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<CompleteValues>({ resolver: zodResolver(completeSchema), defaultValues: { conclusion: "effective", exceptions: "0", rationale: "" } });
  const done = useMutation({
    mutationFn: (v: CompleteValues) => api<ControlTest>(`/control-tests/${test.id}/complete`, { json: { ...v, exceptions: Number(v.exceptions) } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: detailKey(processesKey, p.id) });
      void qc.invalidateQueries({ queryKey: [...processesKey, "list"] });
      toast.success(t("controls.test.completed"));
      onClose();
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{t("controls.test.completeTitle")}</DialogTitle>
        <DialogDescription>{t("controls.test.completeHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => done.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="cc-conclusion" label={t("controls.test.conclusion")}>
              <Select id="cc-conclusion" {...form.register("conclusion")}>
                {CONTROL_CONCLUSIONS.map((c) => (
                  <option key={c} value={c}>
                    {t(`controlConclusion.${c}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="cc-exceptions" label={t("controls.test.exceptions")} error={err.exceptions ? t("controls.test.sampleRule") : undefined}>
              <Input id="cc-exceptions" dir="ltr" inputMode="numeric" aria-invalid={!!err.exceptions} {...form.register("exceptions")} />
            </Field>
          </div>
          <Field id="cc-rationale" label={t("controls.rationale")} error={err.rationale ? t("controls.rationaleRequired") : undefined}>
            <Textarea id="cc-rationale" rows={3} aria-invalid={!!err.rationale} {...form.register("rationale")} />
          </Field>
          <MutationError error={done.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={done.isPending}>
              {done.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("controls.test.complete")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const defSchema = z.object({ title: z.string().trim().min(1).max(300), description: z.string().max(5000), test_id: z.string() });
type DefValues = z.infer<typeof defSchema>;

function RaiseDeficiencyDialog({ p, control, onClose }: { p: ControlProcess; control: Control; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<DefValues>({ resolver: zodResolver(defSchema), defaultValues: { title: "", description: "", test_id: "" } });
  const raise = useMutation({
    mutationFn: (v: DefValues) => api(`/deficiencies`, { json: { control_id: control.id, title: v.title, description: v.description, test_id: v.test_id || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: deficienciesKey });
      void qc.invalidateQueries({ queryKey: detailKey(processesKey, p.id) });
      toast.success(t("controls.def.raised"));
      onClose();
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{t("controls.def.raiseTitle", { ref: control.ref })}</DialogTitle>
        <DialogDescription>{t("controls.def.raiseHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => raise.mutate(v))} noValidate>
          <Field id="rd-title" label={t("controls.def.title")} error={err.title ? t("recs.nameRequired") : undefined}>
            <Input id="rd-title" aria-invalid={!!err.title} {...form.register("title")} />
          </Field>
          <Field id="rd-desc" label={t("controls.descriptionField")}>
            <Textarea id="rd-desc" rows={3} {...form.register("description")} />
          </Field>
          <Field id="rd-test" label={t("controls.def.fromTest")}>
            <Select id="rd-test" {...form.register("test_id")}>
              <option value="">{t("controls.def.noTest")}</option>
              {control.tests.map((ts) => (
                <option key={ts.id} value={ts.id}>
                  {t(`controlTestKind.${ts.kind}`)} · {formatDate(ts.period_start, i18n.language)} – {formatDate(ts.period_end, i18n.language)}
                </option>
              ))}
            </Select>
          </Field>
          <MutationError error={raise.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={raise.isPending}>
              {raise.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("controls.def.raise")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function evidenceText(e: Record<string, unknown>): string {
  const rows = Array.isArray(e.row_ids) ? e.row_ids.join(", ") : "";
  const name = typeof e.dataset_name === "string" ? e.dataset_name : "";
  const v = e.version_number != null ? ` v${String(e.version_number)}` : "";
  return `${name}${v} · ${rows}`;
}

function ControlCard({ p, c, onAction }: { p: ControlProcess; c: Control; onAction: (a: { kind: "test" | "deficiency"; c: Control } | { kind: "complete"; test: ControlTest }) => void }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const risks = p.risks.filter((r) => c.risk_ids.includes(r.id));
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>
            <span dir="ltr">{c.ref}</span> · {c.title}
          </CardTitle>
          <CardDescription>
            {t(`controlNature.${c.nature}`)} · {t(`controlAutomation.${c.automation}`)} · {t(`controlFrequency.${c.frequency}`)} · {t("recs.owner")}: {c.owner_name ?? "—"}
          </CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {c.key && <Badge tone="teal">{t("controls.keyControl")}</Badge>}
          {c.open_deficiencies > 0 && <Badge tone="amber">{t("controls.openDeficiencies", { count: c.open_deficiencies })}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {c.description && <p className="text-[13px] text-slate-600">{c.description}</p>}
        <Facts
          items={[
            { label: t("controls.design"), value: <ConclusionBadge value={c.design} /> },
            { label: t("controls.operating"), value: <ConclusionBadge value={c.operating} /> },
            { label: t("controls.mitigates"), value: risks.length ? <span dir="ltr">{risks.map((r) => r.ref).join(", ")}</span> : "—" },
          ]}
        />
        {c.tests.length > 0 && (
          <Table>
            <THead>
              <tr>
                <TH>{t("controls.test.kind")}</TH>
                <TH>{t("workpapers.period")}</TH>
                <TH className="text-end">{t("controls.test.sampleSize")}</TH>
                <TH className="text-end">{t("controls.test.exceptions")}</TH>
                <TH>{t("controls.test.conclusion")}</TH>
                <TH>{t("controls.test.evidence")}</TH>
              </tr>
            </THead>
            <TBody>
              {c.tests.map((ts) => (
                <TR key={ts.id}>
                  <TD className="align-top text-[13px]">{t(`controlTestKind.${ts.kind}`)}</TD>
                  <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                    {formatDate(ts.period_start, i18n.language)} – {formatDate(ts.period_end, i18n.language)}
                  </TD>
                  <TD className="align-top text-end text-[13px] tabular-nums">{ts.sample_size}</TD>
                  <TD className="align-top text-end text-[13px] tabular-nums">{ts.status === "completed" ? ts.exceptions : "—"}</TD>
                  <TD className="align-top">
                    {ts.status === "completed" ? (
                      <>
                        <ConclusionBadge value={ts.conclusion} />
                        <p className="mt-1 text-xs text-slate-500">{ts.rationale}</p>
                        {ts.tester_name && <p className="text-xs text-slate-400">{ts.tester_name}</p>}
                      </>
                    ) : can("write") ? (
                      <Button size="sm" variant="outline" onClick={() => onAction({ kind: "complete", test: ts })}>
                        <CircleCheck aria-hidden /> {t("controls.test.complete")}
                      </Button>
                    ) : (
                      <Badge tone="neutral">{t("controls.test.planned")}</Badge>
                    )}
                  </TD>
                  <TD className="align-top text-xs text-slate-600">
                    {ts.evidence.length === 0 ? "—" : ts.evidence.map((e, i) => <p key={i} dir="ltr">{evidenceText(e)}</p>)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        {can("write") && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => onAction({ kind: "test", c })}>
              <FlaskConical aria-hidden /> {t("controls.test.add")}
            </Button>
            <Button size="sm" variant="outline" onClick={() => onAction({ kind: "deficiency", c })}>
              <ShieldAlert aria-hidden /> {t("controls.def.raise")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ProcessDetailPage() {
  const { processId } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const q = useProcess(processId);
  const [riskOpen, setRiskOpen] = useState(false);
  const [controlOpen, setControlOpen] = useState(false);
  const [action, setAction] = useState<{ kind: "test" | "deficiency"; c: Control } | { kind: "complete"; test: ControlTest } | null>(null);
  if (q.isLoading) return <LoadingState />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const p = q.data;
  const unmitigated = new Set(p.unmitigated_risk_ids);
  return (
    <>
      <PageHeader
        title={p.name}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {p.entity_name} · {t("recs.owner")}: {p.owner_name ?? "—"}
            {p.is_demo && <SyntheticBadge />}
          </span>
        }
        description={p.description || undefined}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.controls"), to: "/controls" }, { label: p.name }]}
        actions={
          can("write") && (
            <>
              <Button variant="outline" onClick={() => setRiskOpen(true)}>
                <Plus aria-hidden /> {t("controls.addRisk")}
              </Button>
              <Button variant="accent" onClick={() => setControlOpen(true)}>
                <Plus aria-hidden /> {t("controls.addControl")}
              </Button>
            </>
          )
        }
      />
      <div className="space-y-5">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{t("controls.matrix")}</CardTitle>
            <CardDescription>{t("controls.matrixHint")}</CardDescription>
          </CardHeader>
          {p.risks.length === 0 ? (
            <EmptyState icon={ShieldCheck} title={t("controls.noRisks")} description={t("controls.noRisksHint")} />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("controls.risk")}</TH>
                  <TH>{t("controls.rating")}</TH>
                  <TH>{t("controls.assertions")}</TH>
                  <TH>{t("controls.mitigatingControls")}</TH>
                </tr>
              </THead>
              <TBody>
                {p.risks.map((r) => {
                  const ctrls = p.controls.filter((c) => c.risk_ids.includes(r.id));
                  const gap = unmitigated.has(r.id);
                  return (
                    <TR key={r.id} className={gap ? "bg-red-50/60" : undefined}>
                      <TD className="align-top text-[13px]">
                        <span dir="ltr" className="font-medium text-navy-900">
                          {r.ref}
                        </span>{" "}
                        {r.description}
                      </TD>
                      <TD className="align-top">
                        <Badge tone={r.rating === "high" ? "orange" : r.rating === "medium" ? "amber" : "neutral"}>{t(`riskLevel.${r.rating}`)}</Badge>
                      </TD>
                      <TD className="align-top text-xs text-slate-600">{r.assertions.map((a) => t(`assertion.${a}`)).join(", ") || "—"}</TD>
                      <TD className="align-top text-[13px]">
                        {gap ? (
                          <Badge tone="red">
                            <TriangleAlert className="size-3" aria-hidden />
                            {t("controls.unmitigated")}
                          </Badge>
                        ) : (
                          <ul className="space-y-0.5">
                            {ctrls.map((c) => (
                              <li key={c.id} className="flex flex-wrap items-center gap-1.5">
                                <span dir="ltr" className="font-medium">
                                  {c.ref}
                                </span>
                                <span className="text-slate-600">{c.title}</span>
                                {c.key && <Badge tone="teal">{t("controls.keyControl")}</Badge>}
                              </li>
                            ))}
                          </ul>
                        )}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          )}
        </Card>
        <section className="space-y-3">
          <h2 className="text-[15px] font-semibold text-navy-900">{t("controls.controls")}</h2>
          {p.controls.length === 0 ? (
            <Card>
              <EmptyState icon={ShieldCheck} title={t("controls.noControls")} description={t("controls.noControlsHint")} />
            </Card>
          ) : (
            p.controls.map((c) => <ControlCard key={c.id} p={p} c={c} onAction={setAction} />)
          )}
        </section>
      </div>
      <AddRiskDialog p={p} open={riskOpen} onOpenChange={setRiskOpen} />
      <AddControlDialog p={p} open={controlOpen} onOpenChange={setControlOpen} />
      {action?.kind === "test" && <AddTestDialog p={p} control={action.c} onClose={() => setAction(null)} />}
      {action?.kind === "deficiency" && <RaiseDeficiencyDialog p={p} control={action.c} onClose={() => setAction(null)} />}
      {action?.kind === "complete" && <CompleteTestDialog p={p} test={action.test} onClose={() => setAction(null)} />}
    </>
  );
}

// ---------------------------------------------------------------- certification

function StatementEditor({ c, editable }: { c: Certification; editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [text, setText] = useState(c.statement);
  const save = useMutation({
    mutationFn: () => api<Certification>(`/control-certifications/${c.id}/statement`, { method: "PUT", json: { statement: text } }),
    onSuccess: (d) => {
      qc.setQueryData(detailKey(certificationsKey, c.id), d);
      toast.success(t("common.saved"));
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("controls.cert.statement")}</CardTitle>
        <CardDescription>{t("controls.cert.statementHint")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) save.mutate();
          }}
        >
          <Field id="cert-statement-edit" label={t("controls.cert.statement")}>
            <Textarea id="cert-statement-edit" rows={6} disabled={!editable} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <MutationError error={save.error} />
          {editable && (
            <Button type="submit" disabled={save.isPending || !text.trim() || text === c.statement}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

export function CertificationDetailPage() {
  const { certId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const q = useCertification(certId);
  if (q.isLoading) return <LoadingState />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const c = q.data;
  const title = `${c.entity_name} · ${formatDate(c.period_start, i18n.language)} – ${formatDate(c.period_end, i18n.language)}`;
  return (
    <>
      <PageHeader
        title={t("controls.cert.titleFor", { entity: c.entity_name })}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {title}
            {c.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.controls"), to: "/controls?tab=certifications" }, { label: c.entity_name }]}
        actions={<AssuranceStatusBadge status={c.sign_off.status} />}
      />
      <div className="space-y-5">
        <AssuranceNote>{t("controls.cert.note")}</AssuranceNote>
        <Card>
          <CardContent>
            <Facts
              items={[
                { label: t("controls.controls"), value: c.controls },
                { label: t("controls.cert.keyControls"), value: c.key_controls },
                { label: t("controls.cert.tested"), value: c.tested },
                { label: t("controls.cert.ineffective"), value: c.ineffective },
                { label: t("controls.cert.unclassified"), value: c.unclassified },
              ]}
              className="lg:grid-cols-5"
            />
          </CardContent>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{t("controls.cert.openDeficiencies")}</CardTitle>
          </CardHeader>
          {c.open_deficiencies.length === 0 ? <EmptyState title={t("controls.cert.noOpenDeficiencies")} /> : <DeficiencyTable items={c.open_deficiencies} />}
        </Card>
        <StatementEditor key={c.statement} c={c} editable={can("write") && c.sign_off.status !== "signed_off"} />
        <SignOffCard
          base="/control-certifications"
          listKey={certificationsKey}
          obj={c}
          blocker={!c.statement.trim() ? t("controls.cert.statementBlocks") : null}
        />
      </div>
    </>
  );
}
