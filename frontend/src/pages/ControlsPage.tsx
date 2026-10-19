import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CheckCheck, ClipboardList, Loader2, Plus, ShieldCheck, Tags } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  certificationsKey,
  DEFICIENCY_CLASSES,
  deficienciesKey,
  processesKey,
  useCertifications,
  useDeficiencies,
  useProcesses,
  type Certification,
  type Deficiency,
  type DeficiencyClass,
  type ControlProcess,
} from "@/lib/assurance";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { Field, MutationError } from "@/components/audit/shared";
import { AssuranceNote, AssuranceStatusBadge, EntitySelect, MemberSelect } from "@/components/assurance/shared";

const TABS = ["processes", "deficiencies", "certifications"] as const;
type Tab = (typeof TABS)[number];

const CLASS_TONE: Record<DeficiencyClass, "amber" | "orange" | "red"> = { deficiency: "amber", significant_deficiency: "orange", material_weakness: "red" };

export function DeficiencyClassBadge({ value }: { value: DeficiencyClass | null }) {
  const { t } = useTranslation();
  if (!value) return <Badge tone="neutral">{t("controls.def.unclassified")}</Badge>;
  return <Badge tone={CLASS_TONE[value]}>{t(`deficiencyClass.${value}`)}</Badge>;
}

// ---------------------------------------------------------------- processes

const processSchema = z.object({
  entity_id: z.string().min(1),
  name: z.string().trim().min(1).max(200),
  description: z.string().max(5000),
  owner_id: z.string(),
});
type ProcessValues = z.infer<typeof processSchema>;

function NewProcessDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<ProcessValues>({ resolver: zodResolver(processSchema), defaultValues: { entity_id: "", name: "", description: "", owner_id: "" } });
  const create = useMutation({
    mutationFn: (v: ProcessValues) => api<ControlProcess>("/control-processes", { json: { ...v, owner_id: v.owner_id || null } }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: processesKey });
      close();
      navigate(`/controls/processes/${p.id}`);
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
      <DialogContent>
        <DialogTitle>{t("controls.process.new")}</DialogTitle>
        <DialogDescription>{t("controls.process.newHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <EntitySelect id="cpr-entity" reg={form.register("entity_id")} error={!!err.entity_id} />
          <Field id="cpr-name" label={t("recs.name")} error={err.name ? t("recs.nameRequired") : undefined}>
            <Input id="cpr-name" aria-invalid={!!err.name} {...form.register("name")} />
          </Field>
          <Field id="cpr-desc" label={t("controls.descriptionField")}>
            <Textarea id="cpr-desc" rows={3} {...form.register("description")} />
          </Field>
          <MemberSelect id="cpr-owner" label={t("recs.owner")} reg={form.register("owner_id")} />
          <MutationError error={create.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("controls.process.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ProcessList() {
  const { t } = useTranslation();
  const list = useProcesses();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={ShieldCheck} title={t("controls.process.empty")} description={t("controls.process.emptyHint")} />;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("controls.process.name")}</TH>
          <TH>{t("recs.owner")}</TH>
          <TH className="text-end">{t("controls.risks")}</TH>
          <TH className="text-end">{t("controls.controls")}</TH>
          <TH>{t("controls.coverage")}</TH>
        </tr>
      </THead>
      <TBody>
        {list.data.map((p) => (
          <TR key={p.id}>
            <TD className="align-top">
              <Link to={`/controls/processes/${p.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                {p.name}
              </Link>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                <span>{p.entity_name}</span>
                {p.is_demo && <SyntheticBadge />}
              </div>
            </TD>
            <TD className="align-top text-[13px] text-slate-600">{p.owner_name ?? "—"}</TD>
            <TD className="align-top text-end text-[13px] tabular-nums">{p.risks.length}</TD>
            <TD className="align-top text-end text-[13px] tabular-nums">{p.controls.length}</TD>
            <TD className="align-top">
              {p.unmitigated_risk_ids.length > 0 ? (
                <Badge tone="red">{t("controls.unmitigatedCount", { count: p.unmitigated_risk_ids.length })}</Badge>
              ) : (
                <Badge tone="neutral">{t("controls.allMapped")}</Badge>
              )}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

// ---------------------------------------------------------------- deficiencies

type DefAction = "classify" | "remediation" | "remediated";

const classifySchema = z.object({ classification: z.enum(DEFICIENCY_CLASSES), rationale: z.string().trim().min(3).max(5000) });
const remediationSchema = z.object({ owner_id: z.string().min(1), due_date: z.string().min(1), title: z.string().max(300) });
const remediatedSchema = z.object({ note: z.string().trim().min(3).max(5000) });

function DeficiencyActionDialog({ d, action, onClose }: { d: Deficiency; action: DefAction; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const schema = action === "classify" ? classifySchema : action === "remediation" ? remediationSchema : remediatedSchema;
  // The three schemas share one form; values are typed per action when sent.
  const form = useForm<Record<string, string>>({
    resolver: zodResolver(schema as unknown as z.ZodType<Record<string, string>, Record<string, string>>),
    defaultValues:
      action === "classify"
        ? { classification: d.classification ?? "deficiency", rationale: d.rationale }
        : action === "remediation"
          ? { owner_id: "", due_date: "", title: "" }
          : { note: "" },
  });
  const send = useMutation({
    mutationFn: (v: Record<string, string>) => api<Deficiency>(`/deficiencies/${d.id}/${action}`, { json: v }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: deficienciesKey });
      void qc.invalidateQueries({ queryKey: processesKey });
      void qc.invalidateQueries({ queryKey: certificationsKey });
      if (action === "remediation") void qc.invalidateQueries({ queryKey: ["tasks"] });
      toast.success(t(`controls.def.done_${action}`));
      onClose();
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{t(`controls.def.${action}Title`, { title: d.title })}</DialogTitle>
        <DialogDescription>{t(`controls.def.${action}Hint`)}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => send.mutate(v))} noValidate>
          {action === "classify" && (
            <>
              <Field id="def-class" label={t("controls.def.classification")}>
                <Select id="def-class" {...form.register("classification")}>
                  {DEFICIENCY_CLASSES.map((c) => (
                    <option key={c} value={c}>
                      {t(`deficiencyClass.${c}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="def-rationale" label={t("controls.rationale")} error={err.rationale ? t("controls.rationaleRequired") : undefined}>
                <Textarea id="def-rationale" rows={3} aria-invalid={!!err.rationale} {...form.register("rationale")} />
              </Field>
            </>
          )}
          {action === "remediation" && (
            <>
              <div>
                <MemberSelect id="def-owner" label={t("recs.owner")} reg={form.register("owner_id")} optional={false} />
                {err.owner_id && (
                  <p role="alert" className="mt-1 text-xs font-medium text-red-600">
                    {t("controls.def.ownerRequired")}
                  </p>
                )}
              </div>
              <Field id="def-due" label={t("close.due")} error={err.due_date ? t("rulePacks.dateRequired") : undefined}>
                <Input id="def-due" type="date" aria-invalid={!!err.due_date} {...form.register("due_date")} />
              </Field>
              <Field id="def-task" label={t("controls.def.taskTitle")} hint={t("controls.def.taskTitleHint")}>
                <Input id="def-task" {...form.register("title")} />
              </Field>
            </>
          )}
          {action === "remediated" && (
            <Field id="def-note" label={t("close.note")} error={err.note ? t("controls.rationaleRequired") : undefined}>
              <Textarea id="def-note" rows={3} aria-invalid={!!err.note} {...form.register("note")} />
            </Field>
          )}
          <MutationError error={send.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={send.isPending}>
              {send.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t(`controls.def.${action}`)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DeficiencyTable({ items }: { items: Deficiency[] }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [active, setActive] = useState<{ d: Deficiency; action: DefAction } | null>(null);
  return (
    <>
      <Table>
        <THead>
          <tr>
            <TH>{t("controls.def.title")}</TH>
            <TH>{t("controls.control")}</TH>
            <TH>{t("controls.def.classification")}</TH>
            <TH>{t("recs.status")}</TH>
            {can("decide") && (
              <TH>
                <span className="sr-only">{t("common.actions")}</span>
              </TH>
            )}
          </tr>
        </THead>
        <TBody>
          {items.map((d) => (
            <TR key={d.id}>
              <TD className="align-top text-[13px]">
                <span className="font-medium text-navy-900">{d.title}</span>
                {d.description && <p className="text-xs text-slate-500">{d.description}</p>}
                <p className="text-xs text-slate-400">{formatDate(d.created_at, i18n.language)}</p>
              </TD>
              <TD className="align-top text-[13px] text-slate-600">
                <span dir="ltr">{d.control_ref}</span> {d.control_title}
              </TD>
              <TD className="align-top">
                <DeficiencyClassBadge value={d.classification} />
                {d.classified_by_name && <p className="mt-1 text-xs text-slate-400">{d.classified_by_name}</p>}
              </TD>
              <TD className="align-top">
                <Badge tone={d.status === "remediated" ? "green" : "amber"} dot>
                  {t(`controls.def.status_${d.status}`)}
                </Badge>
                {d.remediation_task_id && (
                  <p className="mt-1 text-xs">
                    <Link to="/tasks" className="text-teal-700 hover:underline">
                      {t("controls.def.taskAssigned")}
                    </Link>
                  </p>
                )}
              </TD>
              {can("decide") && (
                <TD className="align-top">
                  {d.status === "open" && (
                    <div className="flex flex-wrap justify-end gap-1.5">
                      <Button size="sm" variant="outline" onClick={() => setActive({ d, action: "classify" })} aria-label={t("controls.def.classifyNamed", { title: d.title })}>
                        <Tags aria-hidden /> {t("controls.def.classify")}
                      </Button>
                      {!d.remediation_task_id && (
                        <Button size="sm" variant="outline" onClick={() => setActive({ d, action: "remediation" })}>
                          <ClipboardList aria-hidden /> {t("controls.def.remediation")}
                        </Button>
                      )}
                      <Button size="sm" variant="outline" onClick={() => setActive({ d, action: "remediated" })}>
                        <CheckCheck aria-hidden /> {t("controls.def.remediated")}
                      </Button>
                    </div>
                  )}
                </TD>
              )}
            </TR>
          ))}
        </TBody>
      </Table>
      {active && <DeficiencyActionDialog d={active.d} action={active.action} onClose={() => setActive(null)} />}
    </>
  );
}

function DeficiencyList() {
  const { t } = useTranslation();
  const list = useDeficiencies();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={ShieldCheck} title={t("controls.def.empty")} description={t("controls.def.emptyHint")} />;
  return <DeficiencyTable items={list.data} />;
}

// ---------------------------------------------------------------- certifications

const certSchema = z
  .object({ entity_id: z.string().min(1), period_start: z.string().min(1), period_end: z.string().min(1), statement: z.string().max(10000) })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type CertValues = z.infer<typeof certSchema>;

function NewCertDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<CertValues>({ resolver: zodResolver(certSchema), defaultValues: { entity_id: "", period_start: "", period_end: "", statement: "" } });
  const create = useMutation({
    mutationFn: (v: CertValues) => api<Certification>("/control-certifications", { json: v }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: certificationsKey });
      close();
      navigate(`/controls/certifications/${c.id}`);
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
      <DialogContent>
        <DialogTitle>{t("controls.cert.new")}</DialogTitle>
        <DialogDescription>{t("controls.cert.newHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <EntitySelect id="cert-entity" reg={form.register("entity_id")} error={!!err.entity_id} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="cert-start" label={t("workpapers.periodStart")} error={err.period_start ? t("rulePacks.dateRequired") : undefined}>
              <Input id="cert-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
            </Field>
            <Field
              id="cert-end"
              label={t("workpapers.periodEnd")}
              error={err.period_end ? (err.period_end.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired")) : undefined}
            >
              <Input id="cert-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
            </Field>
          </div>
          <Field id="cert-statement" label={t("controls.cert.statement")} hint={t("controls.cert.statementHint")}>
            <Textarea id="cert-statement" rows={4} {...form.register("statement")} />
          </Field>
          <MutationError error={create.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("controls.cert.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CertList() {
  const { t, i18n } = useTranslation();
  const list = useCertifications();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={ShieldCheck} title={t("controls.cert.empty")} description={t("controls.cert.emptyHint")} />;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("datasets.entity")}</TH>
          <TH>{t("workpapers.period")}</TH>
          <TH>{t("controls.cert.openDeficiencies")}</TH>
          <TH>{t("recs.status")}</TH>
        </tr>
      </THead>
      <TBody>
        {list.data.map((c) => (
          <TR key={c.id}>
            <TD className="align-top">
              <Link to={`/controls/certifications/${c.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                {c.entity_name}
              </Link>
              {c.is_demo && <SyntheticBadge className="ms-2" />}
            </TD>
            <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
              {formatDate(c.period_start, i18n.language)} – {formatDate(c.period_end, i18n.language)}
            </TD>
            <TD className="align-top text-[13px] tabular-nums text-slate-600">{c.open_deficiencies.length}</TD>
            <TD className="align-top">
              <AssuranceStatusBadge status={c.sign_off.status} />
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function ControlsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState<Tab | null>(null);
  const raw = params.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(raw ?? "") ? (raw as Tab) : "processes";
  return (
    <>
      <PageHeader
        title={t("controls.title")}
        description={t("controls.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.controls") }]}
        actions={
          can("write") &&
          tab !== "deficiencies" && (
            <Button variant="accent" onClick={() => setOpen(tab)}>
              <Plus aria-hidden /> {tab === "processes" ? t("controls.process.new") : t("controls.cert.new")}
            </Button>
          )
        }
      />
      <div className="space-y-4">
        <AssuranceNote>{t("controls.disclaimer")}</AssuranceNote>
        <Tabs
          label={t("controls.title")}
          value={tab}
          onChange={(k) => setParams(k === "processes" ? {} : { tab: k }, { replace: true })}
          items={TABS.map((k) => ({ key: k, label: t(`controls.tab.${k}`) }))}
        />
        <Card className="overflow-hidden">
          {tab === "processes" && <ProcessList />}
          {tab === "deficiencies" && <DeficiencyList />}
          {tab === "certifications" && <CertList />}
        </Card>
      </div>
      <NewProcessDialog open={open === "processes"} onOpenChange={(o) => setOpen(o ? "processes" : null)} />
      <NewCertDialog open={open === "certifications"} onOpenChange={(o) => setOpen(o ? "certifications" : null)} />
    </>
  );
}
