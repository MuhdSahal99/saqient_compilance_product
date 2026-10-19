import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ChevronDown, FilePlus2, Layers, Loader2, Plus, Save, Table2, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { usePublishedRulePacks } from "@/lib/queries";
import type { Workpaper } from "@/lib/types";
import {
  FS_SECTIONS,
  LEAD_CODE_PATTERN,
  PREFIX_PATTERN,
  engKey,
  engagementKey,
  useAccountMappings,
  useEngagementWorkpapers,
  useEntityDatasets,
  useLeadReport,
  useLeadSchedules,
  type AccountMapping,
  type Engagement,
  type LeadLine,
  type LeadSchedule,
} from "@/lib/audit";
import { cn, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState } from "@/components/common";
import { Amount } from "@/components/calc-explain";
import { WorkpaperStatusBadge } from "@/pages/WorkpapersPage";
import { Field, MutationError, Share } from "./shared";

// ---------------------------------------------------------------- setup

const setupSchema = z
  .object({
    cy_tb_version_id: z.string(),
    py_tb_version_id: z.string(),
    rule_pack_version_id: z.string(),
    rules_prefix: z.union([z.literal(""), z.string().trim().max(80).regex(PREFIX_PATTERN)]),
  })
  .refine((v) => !v.rule_pack_version_id === !v.rules_prefix, { path: ["rules_prefix"], message: "both" });
type SetupValues = z.infer<typeof setupSchema>;

function SetupCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const editable = can("decide") && e.status !== "closed";
  const tbs = useEntityDatasets(e.entity_id, "trial_balance");
  const packs = usePublishedRulePacks(editable);
  const defaults = (): SetupValues => ({
    cy_tb_version_id: e.cy_tb_version_id ?? "",
    py_tb_version_id: e.py_tb_version_id ?? "",
    rule_pack_version_id: e.rule_pack_version_id ?? "",
    rules_prefix: e.rules_prefix ?? "",
  });
  const form = useForm<SetupValues>({ resolver: zodResolver(setupSchema), defaultValues: defaults() });
  useEffect(() => {
    form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow the saved engagement
  }, [e.cy_tb_version_id, e.py_tb_version_id, e.rule_pack_version_id, e.rules_prefix]);
  const save = useMutation({
    mutationFn: (v: SetupValues) =>
      api<Engagement>(`/engagements/${e.id}/setup`, {
        method: "PUT",
        json: {
          cy_tb_version_id: v.cy_tb_version_id || null,
          py_tb_version_id: v.py_tb_version_id || null,
          rule_pack_version_id: v.rule_pack_version_id || null,
          rules_prefix: v.rules_prefix || null,
        },
      }),
    onSuccess: (d) => {
      qc.setQueryData(engagementKey(e.id), d);
      void qc.invalidateQueries({ queryKey: engKey(e.id, "lead-report") });
      toast.success(t("engagements.tb.setupSaved"));
    },
  });
  const versions = (tbs.data ?? []).flatMap((d) =>
    d.latest_version && d.latest_version.status === "ready" ? [{ id: d.latest_version.id, label: `${d.name} · v${d.latest_version.version_number}` }] : [],
  );
  const labelFor = (id: string | null) => (id ? (versions.find((v) => v.id === id)?.label ?? id.slice(0, 8)) : t("engagements.tb.notChosen"));
  const packId = useWatch({ control: form.control, name: "rule_pack_version_id" });
  const selectedPack = packs.items.find((x) => x.v.id === packId);
  const err = form.formState.errors;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("engagements.tb.setup")}</CardTitle>
        <CardDescription>{t("engagements.tb.setupHint")}</CardDescription>
      </CardHeader>
      {tbs.isError && <ErrorState error={tbs.error} onRetry={() => void tbs.refetch()} />}
      {!editable && (
        <dl className="grid gap-4 px-5 py-4 sm:grid-cols-3">
          <div>
            <dt className="text-xs text-slate-500">{t("engagements.tb.currentTb")}</dt>
            <dd className="mt-0.5 text-[13px] text-navy-900">{labelFor(e.cy_tb_version_id)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t("engagements.tb.priorTb")}</dt>
            <dd className="mt-0.5 text-[13px] text-navy-900">{labelFor(e.py_tb_version_id)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t("directTax.rulesPrefix")}</dt>
            <dd className="mt-0.5 text-[13px] text-navy-900">
              <code dir="ltr" className="font-mono text-xs">
                {e.rules_prefix ?? "—"}
              </code>
            </dd>
          </div>
        </dl>
      )}
      {editable && (
        <form className="space-y-4 px-5 py-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          {tbs.data && versions.length === 0 && <p className="text-sm text-slate-500">{t("engagements.tb.noTbs")}</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="setup-cy" label={t("engagements.tb.currentTb")}>
              <Select id="setup-cy" {...form.register("cy_tb_version_id")}>
                <option value="">{t("engagements.tb.notChosen")}</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="setup-py" label={t("engagements.tb.priorTb")}>
              <Select id="setup-py" {...form.register("py_tb_version_id")}>
                <option value="">{t("engagements.tb.notChosen")}</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="setup-pack" label={t("reviews.rulePack")}>
              <Select id="setup-pack" {...form.register("rule_pack_version_id")}>
                <option value="">{t("engagements.tb.noPack")}</option>
                {packs.items.map(({ p, v }) => (
                  <option key={v.id} value={v.id}>
                    {p.name} · v{v.version_number}
                    {p.is_synthetic ? ` · ${t("common.synthetic")}` : ""}
                    {v.unverified_count > 0 ? ` · ${t("rulePacks.unverifiedCount", { count: v.unverified_count })}` : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              id="setup-prefix"
              label={t("directTax.rulesPrefix")}
              hint={t("directTax.rulesPrefixHint")}
              error={err.rules_prefix ? (err.rules_prefix.message === "both" ? t("engagements.tb.packAndPrefix") : t("rulePacks.ruleKeyRule")) : undefined}
            >
              <Input id="setup-prefix" dir="ltr" placeholder="syn.audit" aria-invalid={!!err.rules_prefix} {...form.register("rules_prefix")} />
            </Field>
          </div>
          {selectedPack && selectedPack.v.unverified_count > 0 && (
            <p className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-orange-900">
              <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
              {t("directTax.unverifiedPack")}
            </p>
          )}
          <MutationError error={save.error} />
          <Button type="submit" variant="accent" size="sm" disabled={save.isPending}>
            {save.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
            {t("common.save")}
          </Button>
        </form>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- lead schedules

const schedulesSchema = z.object({
  schedules: z.array(z.object({ code: z.string().trim().regex(LEAD_CODE_PATTERN), name: z.string().trim().min(1).max(200), section: z.enum(FS_SECTIONS) })).max(200),
});
type SchedulesValues = z.infer<typeof schedulesSchema>;

function SchedulesEditor({ e, schedules }: { e: Engagement; schedules: LeadSchedule[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<SchedulesValues>({ resolver: zodResolver(schedulesSchema), defaultValues: { schedules } });
  const rows = useFieldArray({ control: form.control, name: "schedules" });
  useEffect(() => {
    form.reset({ schedules });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow the saved list
  }, [schedules]);
  const save = useMutation({
    mutationFn: (v: SchedulesValues) => api<LeadSchedule[]>(`/engagements/${e.id}/lead-schedules`, { method: "PUT", json: v }),
    onSuccess: (d) => {
      qc.setQueryData(engKey(e.id, "lead-schedules"), d);
      void qc.invalidateQueries({ queryKey: engKey(e.id, "lead-report") });
      toast.success(t("engagements.tb.schedulesSaved"));
    },
  });
  const err = form.formState.errors.schedules;
  return (
    <form onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
      {rows.fields.length === 0 ? (
        <EmptyState icon={Layers} title={t("engagements.tb.noSchedules")} description={t("engagements.tb.noSchedulesHint")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <TH className="w-36">{t("engagements.tb.code")}</TH>
              <TH>{t("engagements.tb.scheduleName")}</TH>
              <TH className="w-44">{t("engagements.tb.section")}</TH>
              <TH className="w-14">
                <span className="sr-only">{t("common.actions")}</span>
              </TH>
            </tr>
          </THead>
          <TBody>
            {rows.fields.map((f, i) => (
              <TR key={f.id}>
                <TD>
                  <Input
                    dir="ltr"
                    aria-label={t("engagements.tb.codeRow", { n: i + 1 })}
                    aria-invalid={!!err?.[i]?.code}
                    {...form.register(`schedules.${i}.code`)}
                  />
                </TD>
                <TD>
                  <Input aria-label={t("engagements.tb.nameRow", { n: i + 1 })} aria-invalid={!!err?.[i]?.name} {...form.register(`schedules.${i}.name`)} />
                </TD>
                <TD>
                  <Select aria-label={t("engagements.tb.sectionRow", { n: i + 1 })} {...form.register(`schedules.${i}.section`)}>
                    {FS_SECTIONS.map((s) => (
                      <option key={s} value={s}>
                        {t(`fsSection.${s}`)}
                      </option>
                    ))}
                  </Select>
                </TD>
                <TD>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={t("engagements.tb.removeRow", { n: i + 1 })} onClick={() => rows.remove(i)}>
                    <Trash2 aria-hidden />
                  </Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <div className="space-y-2 border-t border-slate-100 px-5 py-3">
        {err && <p role="alert" className="text-xs font-medium text-red-600">{t("engagements.tb.scheduleRule")}</p>}
        <MutationError error={save.error} />
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => rows.append({ code: "", name: "", section: "asset" })}>
            <Plus aria-hidden /> {t("engagements.tb.addSchedule")}
          </Button>
          <Button type="submit" variant="accent" size="sm" disabled={save.isPending || !form.formState.isDirty}>
            {save.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
            {t("common.save")}
          </Button>
        </div>
      </div>
    </form>
  );
}

function SchedulesCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useLeadSchedules(e.id);
  const editable = can("write") && e.status !== "closed";
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.tb.schedules")}</CardTitle>
        <CardDescription>{t("engagements.tb.schedulesHint")}</CardDescription>
      </CardHeader>
      {list.isLoading && <LoadingState rows={3} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.data && editable && <SchedulesEditor e={e} schedules={list.data} />}
      {list.data && !editable && list.data.length === 0 && <EmptyState icon={Layers} title={t("engagements.tb.noSchedules")} />}
      {list.data && !editable && list.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.tb.code")}</TH>
              <TH>{t("engagements.tb.scheduleName")}</TH>
              <TH>{t("engagements.tb.section")}</TH>
            </tr>
          </THead>
          <TBody>
            {list.data.map((s) => (
              <TR key={s.code}>
                <TD>
                  <code dir="ltr" className="font-mono text-xs">
                    {s.code}
                  </code>
                </TD>
                <TD>{s.name}</TD>
                <TD>{t(`fsSection.${s.section}`)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- account mappings

const mappingsSchema = z.object({
  mappings: z.array(z.object({ account_code: z.string().trim().min(1).max(80), lead_code: z.string().regex(LEAD_CODE_PATTERN) })).max(5000),
});
type MappingsValues = z.infer<typeof mappingsSchema>;

function MappingsEditor({ e, mappings, schedules, unmapped }: { e: Engagement; mappings: AccountMapping[]; schedules: LeadSchedule[]; unmapped: string[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<MappingsValues>({ resolver: zodResolver(mappingsSchema), defaultValues: { mappings } });
  const rows = useFieldArray({ control: form.control, name: "mappings" });
  useEffect(() => {
    form.reset({ mappings });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- follow the saved list
  }, [mappings]);
  const save = useMutation({
    mutationFn: (v: MappingsValues) => api<AccountMapping[]>(`/engagements/${e.id}/account-mappings`, { method: "PUT", json: v }),
    onSuccess: (d) => {
      qc.setQueryData(engKey(e.id, "mappings"), d);
      void qc.invalidateQueries({ queryKey: engKey(e.id, "lead-report") });
      toast.success(t("engagements.tb.mappingsSaved"));
    },
  });
  const current = useWatch({ control: form.control, name: "mappings" });
  const listed = new Set((current ?? []).map((m) => m.account_code));
  const toAdd = unmapped.filter((a) => !listed.has(a));
  const err = form.formState.errors.mappings;
  return (
    <form onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
      {rows.fields.length === 0 ? (
        <EmptyState icon={Table2} title={t("engagements.tb.noMappings")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.tb.account")}</TH>
              <TH>{t("engagements.tb.leadSchedule")}</TH>
              <TH className="w-14">
                <span className="sr-only">{t("common.actions")}</span>
              </TH>
            </tr>
          </THead>
          <TBody>
            {rows.fields.map((f, i) => (
              <TR key={f.id}>
                <TD>
                  <Input dir="ltr" aria-label={t("engagements.tb.accountRow", { n: i + 1 })} aria-invalid={!!err?.[i]?.account_code} {...form.register(`mappings.${i}.account_code`)} />
                </TD>
                <TD>
                  <Select aria-label={t("engagements.tb.leadRow", { n: i + 1 })} aria-invalid={!!err?.[i]?.lead_code} {...form.register(`mappings.${i}.lead_code`)}>
                    <option value="">{t("engagements.tb.chooseSchedule")}</option>
                    {schedules.map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.code} · {s.name}
                      </option>
                    ))}
                  </Select>
                </TD>
                <TD>
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={t("engagements.tb.removeRow", { n: i + 1 })} onClick={() => rows.remove(i)}>
                    <Trash2 aria-hidden />
                  </Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <div className="space-y-2 border-t border-slate-100 px-5 py-3">
        {err && <p role="alert" className="text-xs font-medium text-red-600">{t("engagements.tb.mappingRule")}</p>}
        <MutationError error={save.error} />
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => rows.append({ account_code: "", lead_code: "" })}>
            <Plus aria-hidden /> {t("engagements.tb.addMapping")}
          </Button>
          {toAdd.length > 0 && (
            <Button type="button" variant="outline" size="sm" onClick={() => rows.append(toAdd.map((a) => ({ account_code: a, lead_code: "" })))}>
              <Plus aria-hidden /> {t("engagements.tb.addUnmapped", { count: toAdd.length })}
            </Button>
          )}
          <Button type="submit" variant="accent" size="sm" disabled={save.isPending || !form.formState.isDirty}>
            {save.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Save aria-hidden />}
            {t("common.save")}
          </Button>
        </div>
      </div>
    </form>
  );
}

function MappingsCard({ e, unmapped }: { e: Engagement; unmapped: string[] }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useAccountMappings(e.id);
  const schedules = useLeadSchedules(e.id);
  const editable = can("write") && e.status !== "closed";
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.tb.mappings")}</CardTitle>
        <CardDescription>{t("engagements.tb.mappingsHint")}</CardDescription>
      </CardHeader>
      {(list.isLoading || schedules.isLoading) && <LoadingState rows={3} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.data && schedules.data && editable && <MappingsEditor e={e} mappings={list.data} schedules={schedules.data} unmapped={unmapped} />}
      {list.data && !editable && list.data.length === 0 && <EmptyState icon={Table2} title={t("engagements.tb.noMappings")} />}
      {list.data && !editable && list.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.tb.account")}</TH>
              <TH>{t("engagements.tb.leadSchedule")}</TH>
            </tr>
          </THead>
          <TBody>
            {list.data.map((m) => (
              <TR key={m.account_code}>
                <TD>
                  <code dir="ltr" className="font-mono text-xs">
                    {m.account_code}
                  </code>
                </TD>
                <TD>{m.lead_code}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- lead report

function LeadRow({ line, currency }: { line: LeadLine; currency: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <TR>
        <TD>
          <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 text-start">
            <ChevronDown
              className={cn("size-4 shrink-0 text-slate-400 transition-transform duration-150 motion-reduce:transition-none", open ? "rotate-0" : "-rotate-90 rtl:rotate-90")}
              aria-hidden
            />
            <span>
              <span className="font-medium text-navy-900">{line.name}</span>
              <code dir="ltr" className="ms-2 font-mono text-[11px] text-slate-400">
                {line.code}
              </code>
            </span>
          </button>
        </TD>
        <TD className="text-[13px] text-slate-600">{t(`fsSection.${line.section}`)}</TD>
        <TD className="text-end">
          <Amount value={line.cy} currency={currency} />
        </TD>
        <TD className="text-end">
          <Amount value={line.py} />
        </TD>
        <TD className="text-end">
          <Amount value={line.movement} />
        </TD>
        <TD className="text-end">
          <Share value={line.change_share} />
        </TD>
      </TR>
      {open &&
        line.accounts.map((a) => (
          <TR key={a.account_code} className="bg-slate-50/60">
            <TD className="ps-12 text-[13px]">
              <code dir="ltr" className="font-mono text-xs">
                {a.account_code}
              </code>
              {a.account_name && <span className="ms-2 text-slate-500">{a.account_name}</span>}
            </TD>
            <TD />
            <TD className="text-end">
              <Amount value={a.cy} />
            </TD>
            <TD className="text-end">
              <Amount value={a.py} />
            </TD>
            <TD className="text-end">
              <Amount value={a.movement} />
            </TD>
            <TD className="text-end">
              <Share value={a.change_share} />
            </TD>
          </TR>
        ))}
      {open && line.accounts.length === 0 && (
        <TR className="bg-slate-50/60">
          <TD colSpan={6} className="ps-12 text-xs text-slate-500">
            {t("engagements.tb.noAccounts")}
          </TD>
        </TR>
      )}
    </>
  );
}

function LeadReportCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const report = useLeadReport(e.id);
  const r = report.data;
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.tb.report")}</CardTitle>
        <CardDescription>
          {r
            ? t("engagements.tb.reportSources", {
                cy: r.current ? `${r.current.dataset_name} v${r.current.version_number}` : t("engagements.tb.notChosen"),
                py: r.prior ? `${r.prior.dataset_name} v${r.prior.version_number}` : t("engagements.tb.notChosen"),
              })
            : t("engagements.tb.reportHint")}
        </CardDescription>
      </CardHeader>
      {report.isLoading && <LoadingState rows={4} />}
      {report.isError && <ErrorState error={report.error} onRetry={() => void report.refetch()} />}
      {r && r.schedules.length === 0 && <EmptyState icon={Layers} title={t("engagements.tb.reportEmpty")} description={t("engagements.tb.reportEmptyHint")} />}
      {r && r.schedules.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.tb.leadSchedule")}</TH>
              <TH>{t("engagements.tb.section")}</TH>
              <TH className="text-end">{t("engagements.tb.cy")}</TH>
              <TH className="text-end">{t("engagements.tb.py")}</TH>
              <TH className="text-end">{t("engagements.tb.movement")}</TH>
              <TH className="text-end">{t("engagements.tb.changeShare")}</TH>
            </tr>
          </THead>
          <TBody>
            {r.schedules.map((l) => (
              <LeadRow key={l.code} line={l} currency={r.currency} />
            ))}
          </TBody>
        </Table>
      )}
      {r && (
        <div className="space-y-3 border-t border-slate-100 px-5 py-4 text-[13px]">
          <dl className="flex flex-wrap gap-6">
            <div>
              <dt className="text-xs text-slate-500">{t("engagements.tb.cyNet")}</dt>
              <dd>
                <Amount value={r.cy_net} currency={r.currency} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">{t("engagements.tb.pyNet")}</dt>
              <dd>
                <Amount value={r.py_net} currency={r.currency} />
              </dd>
            </div>
          </dl>
          <p className="text-xs text-slate-500">{t("engagements.tb.netHint")}</p>
          {r.unmapped.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <p className="font-medium">{t("engagements.tb.unmapped", { count: r.unmapped.length })}</p>
              <p className="mt-1 font-mono" dir="ltr">
                {r.unmapped.map((a) => `${a.account_code} (${a.cy})`).join(", ")}
              </p>
            </div>
          )}
          {r.missing_accounts.length > 0 && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
              <p className="font-medium">{t("engagements.tb.missing", { count: r.missing_accounts.length })}</p>
              <p className="mt-1 font-mono" dir="ltr">
                {r.missing_accounts.join(", ")}
              </p>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- audit workpapers

const wpSchema = z.object({ kind: z.enum(["lead_schedule", "materiality", "fs_draft"]), title: z.string().trim().min(1).max(300) });
type WpValues = z.infer<typeof wpSchema>;

function WorkpapersCard({ e }: { e: Engagement }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const list = useEngagementWorkpapers(e.id);
  const form = useForm<WpValues>({ resolver: zodResolver(wpSchema), defaultValues: { kind: "materiality", title: "" } });
  const create = useMutation({
    mutationFn: (v: WpValues) => api<Workpaper>(`/engagements/${e.id}/workpapers`, { json: v }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "workpapers") });
      void qc.invalidateQueries({ queryKey: ["workpapers"] });
      form.reset({ kind: form.getValues("kind"), title: "" });
      toast.success(t("engagements.tb.workpaperCreated"));
    },
  });
  const noPack = !e.rule_pack_version_id;
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.tb.workpapers")}</CardTitle>
        <CardDescription>{t("engagements.tb.workpapersHint")}</CardDescription>
      </CardHeader>
      {list.isLoading && <LoadingState rows={2} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.data?.length === 0 && <EmptyState icon={FilePlus2} title={t("engagements.tb.noWorkpapers")} />}
      {list.data && list.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("workpapers.titleField")}</TH>
              <TH>{t("workpapers.kind")}</TH>
              <TH>{t("workpapers.status")}</TH>
              <TH>{t("workpapers.preparedBy")}</TH>
            </tr>
          </THead>
          <TBody>
            {list.data.map((w) => (
              <TR key={w.id}>
                <TD>
                  <Link to={`/workpapers/${w.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                    {w.title}
                  </Link>
                </TD>
                <TD>
                  <Badge tone="neutral">{t(`workpaperKind.${w.kind}`)}</Badge>
                </TD>
                <TD>
                  <WorkpaperStatusBadge status={w.status} />
                </TD>
                <TD className="text-[13px] text-slate-600">
                  {w.prepared_at ? `${w.prepared_by_name ?? "—"} · ${formatDate(w.prepared_at, i18n.language)}` : t("workpapers.notPrepared")}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {can("write") && e.status !== "closed" && (
        <form
          className="grid gap-3 border-t border-slate-100 px-5 py-4 sm:grid-cols-[12rem_minmax(0,1fr)_auto] sm:items-end"
          onSubmit={form.handleSubmit((v) => create.mutate(v))}
          noValidate
        >
          <Field id="awp-kind" label={t("workpapers.kind")}>
            <Select id="awp-kind" {...form.register("kind")}>
              <option value="materiality">{t("workpaperKind.materiality")}</option>
              <option value="lead_schedule">{t("workpaperKind.lead_schedule")}</option>
              <option value="fs_draft">{t("workpaperKind.fs_draft")}</option>
            </Select>
          </Field>
          <Field id="awp-title" label={t("workpapers.titleField")} error={form.formState.errors.title ? t("workpapers.titleRequired") : undefined}>
            <Input id="awp-title" aria-invalid={!!form.formState.errors.title} {...form.register("title")} />
          </Field>
          <Button type="submit" variant="outline" disabled={create.isPending || noPack}>
            {create.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <FilePlus2 aria-hidden />}
            {t("engagements.tb.createWorkpaper")}
          </Button>
          <div className="sm:col-span-3">
            {noPack && <p className="text-xs text-slate-500">{t("engagements.tb.needPack")}</p>}
            <MutationError error={create.error} />
          </div>
        </form>
      )}
    </Card>
  );
}

export function TrialBalanceTab({ e }: { e: Engagement }) {
  const report = useLeadReport(e.id);
  const unmapped = (report.data?.unmapped ?? []).map((a) => a.account_code);
  return (
    <div className="space-y-5">
      <SetupCard e={e} />
      <LeadReportCard e={e} />
      <div className="grid gap-5 xl:grid-cols-2">
        <SchedulesCard e={e} />
        <MappingsCard e={e} unmapped={unmapped} />
      </div>
      <WorkpapersCard e={e} />
    </div>
  );
}
