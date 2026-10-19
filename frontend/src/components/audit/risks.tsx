import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ClipboardList, Link2, ListPlus, Loader2, Pencil, Plus, ShieldAlert, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers, usePublishedChecklists } from "@/lib/queries";
import type { Page, Review } from "@/lib/types";
import {
  ASSERTIONS,
  PROCEDURE_STATUSES,
  REF_PATTERN,
  RISK_LEVELS,
  engKey,
  useCoverage,
  useEngagementReviews,
  useLeadSchedules,
  useProcedures,
  useRisks,
  type Assertion,
  type Engagement,
  type Procedure,
  type ProcedureStatus,
  type Risk,
} from "@/lib/audit";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, errorMessage, LoadingState, ReviewStatusBadge } from "@/components/common";
import { Field, MutationError } from "./shared";

function useRefreshRisks(engagementId: string) {
  const qc = useQueryClient();
  return () => {
    for (const part of ["risks", "procedures", "coverage", "reviews"]) void qc.invalidateQueries({ queryKey: engKey(engagementId, part) });
  };
}

const LEVEL_TONE = { low: "neutral", medium: "amber", high: "red" } as const;

// ---------------------------------------------------------------- risks

const riskSchema = z.object({
  ref: z.string().trim().regex(REF_PATTERN),
  title: z.string().trim().min(1).max(300),
  description: z.string().max(5000),
  lead_code: z.string(),
  assertions: z.array(z.enum(ASSERTIONS)).min(1),
  inherent_risk: z.enum(RISK_LEVELS),
  significant: z.boolean(),
  fraud: z.boolean(),
  response: z.string().max(5000),
});
type RiskValues = z.infer<typeof riskSchema>;

function RiskDialog({ e, risk, open, onOpenChange }: { e: Engagement; risk: Risk | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const refresh = useRefreshRisks(e.id);
  const schedules = useLeadSchedules(e.id);
  const defaults = (): RiskValues => ({
    ref: risk?.ref ?? "",
    title: risk?.title ?? "",
    description: risk?.description ?? "",
    lead_code: risk?.lead_code ?? "",
    assertions: risk?.assertions ?? [],
    inherent_risk: risk?.inherent_risk ?? "medium",
    significant: risk?.significant ?? false,
    fraud: risk?.fraud ?? false,
    response: risk?.response ?? "",
  });
  const form = useForm<RiskValues>({ resolver: zodResolver(riskSchema), defaultValues: defaults() });
  useEffect(() => {
    if (open) form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset each time the dialog opens
  }, [open, risk]);
  const save = useMutation({
    mutationFn: (v: RiskValues) =>
      api<Risk>(risk ? `/risks/${risk.id}` : `/engagements/${e.id}/risks`, {
        method: risk ? "PUT" : "POST",
        json: { ...v, lead_code: v.lead_code || null },
      }),
    onSuccess: () => {
      refresh();
      toast.success(t("engagements.risks.saved"));
      close();
    },
  });
  function close() {
    save.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{risk ? t("engagements.risks.edit") : t("engagements.risks.add")}</DialogTitle>
        <DialogDescription>{t("engagements.risks.dialogHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
            <Field id="risk-ref" label={t("engagements.ref")} error={err.ref ? t("engagements.refRule") : undefined}>
              <Input id="risk-ref" dir="ltr" aria-invalid={!!err.ref} {...form.register("ref")} />
            </Field>
            <Field id="risk-title" label={t("workpapers.titleField")} error={err.title ? t("workpapers.titleRequired") : undefined}>
              <Input id="risk-title" aria-invalid={!!err.title} {...form.register("title")} />
            </Field>
          </div>
          <Field id="risk-desc" label={t("engagements.descriptionField")}>
            <Textarea id="risk-desc" rows={2} {...form.register("description")} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="risk-lead" label={t("engagements.tb.leadSchedule")}>
              <Select id="risk-lead" {...form.register("lead_code")}>
                <option value="">{t("engagements.risks.noLead")}</option>
                {(schedules.data ?? []).map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.code} · {s.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="risk-level" label={t("engagements.risks.inherent")}>
              <Select id="risk-level" {...form.register("inherent_risk")}>
                {RISK_LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {t(`riskLevel.${l}`)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <fieldset className="space-y-1.5">
            <legend className="text-[13px] font-medium text-slate-700">{t("engagements.risks.assertions")}</legend>
            <Controller
              control={form.control}
              name="assertions"
              render={({ field }) => (
                <div className="grid gap-1.5 sm:grid-cols-3">
                  {ASSERTIONS.map((a) => (
                    <label key={a} className="flex items-center gap-2 text-sm text-slate-700">
                      <input
                        type="checkbox"
                        className="size-4 accent-teal-600"
                        checked={field.value.includes(a)}
                        onChange={(ev) => field.onChange(ev.target.checked ? [...field.value, a] : field.value.filter((x) => x !== a))}
                      />
                      {t(`assertion.${a}`)}
                    </label>
                  ))}
                </div>
              )}
            />
            {err.assertions && (
              <p role="alert" className="text-xs font-medium text-red-600">
                {t("engagements.risks.assertionRequired")}
              </p>
            )}
          </fieldset>
          <div className="flex flex-wrap gap-5">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" className="size-4 accent-teal-600" {...form.register("significant")} />
              {t("engagements.risks.significant")}
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" className="size-4 accent-teal-600" {...form.register("fraud")} />
              {t("engagements.risks.fraud")}
            </label>
          </div>
          <Field id="risk-response" label={t("engagements.risks.response")}>
            <Textarea id="risk-response" rows={2} {...form.register("response")} />
          </Field>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
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

function RiskRegister({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const refresh = useRefreshRisks(e.id);
  const risks = useRisks(e.id);
  const [assertion, setAssertion] = useState<"" | Assertion>("");
  const [editing, setEditing] = useState<Risk | null>(null);
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState<Risk | null>(null);
  const editable = can("write") && e.status !== "closed";
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/risks/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      refresh();
      setDeleting(null);
      toast.success(t("engagements.risks.deleted"));
    },
    onError: (err) => toast.error(errorMessage(err, t("common.genericError"))),
  });
  const rows = (risks.data ?? []).filter((r) => !assertion || r.assertions.includes(assertion));
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{t("engagements.risks.register")}</CardTitle>
          <CardDescription>{t("engagements.risks.registerHint")}</CardDescription>
        </div>
        {editable && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus aria-hidden /> {t("engagements.risks.add")}
          </Button>
        )}
      </CardHeader>
      <div className="border-b border-slate-100 p-3">
        <div className="space-y-1">
          <Label htmlFor="risk-filter">{t("engagements.risks.byAssertion")}</Label>
          <Select id="risk-filter" className="w-56" value={assertion} onChange={(ev) => setAssertion(ev.target.value as "" | Assertion)}>
            <option value="">{t("engagements.risks.allAssertions")}</option>
            {ASSERTIONS.map((a) => (
              <option key={a} value={a}>
                {t(`assertion.${a}`)}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {risks.isLoading && <LoadingState rows={3} />}
      {risks.isError && <ErrorState error={risks.error} onRetry={() => void risks.refetch()} />}
      {risks.data && rows.length === 0 && <EmptyState icon={ShieldAlert} title={t("engagements.risks.empty")} />}
      {rows.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.ref")}</TH>
              <TH>{t("engagements.risks.risk")}</TH>
              <TH>{t("engagements.risks.assertions")}</TH>
              <TH>{t("engagements.risks.inherent")}</TH>
              <TH className="text-end">{t("engagements.risks.procedures")}</TH>
              {editable && <TH className="w-24">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {rows.map((r) => (
              <TR key={r.id}>
                <TD className="align-top">
                  <code dir="ltr" className="font-mono text-xs">
                    {r.ref}
                  </code>
                </TD>
                <TD className="max-w-80 align-top">
                  <span className="font-medium text-navy-900">{r.title}</span>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {r.lead_code && <Badge tone="neutral">{r.lead_code}</Badge>}
                    {r.significant && <Badge tone="orange">{t("engagements.risks.significant")}</Badge>}
                    {r.fraud && <Badge tone="red">{t("engagements.risks.fraud")}</Badge>}
                  </div>
                  {r.response && <p className="mt-1 text-xs text-slate-500">{r.response}</p>}
                </TD>
                <TD className="align-top">
                  <div className="flex max-w-64 flex-wrap gap-1">
                    {r.assertions.map((a) => (
                      <Badge key={a} tone="teal">
                        {t(`assertion.${a}`)}
                      </Badge>
                    ))}
                  </div>
                </TD>
                <TD className="align-top">
                  <Badge tone={LEVEL_TONE[r.inherent_risk]} dot>
                    {t(`riskLevel.${r.inherent_risk}`)}
                  </Badge>
                </TD>
                <TD className="text-end align-top tabular-nums">{r.procedure_ids.length}</TD>
                {editable && (
                  <TD className="align-top">
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("workpapers.editNamed", { name: r.ref })}
                        onClick={() => {
                          setEditing(r);
                          setOpen(true);
                        }}
                      >
                        <Pencil aria-hidden />
                      </Button>
                      <Button variant="ghost" size="icon-sm" aria-label={t("workpapers.removeNamed", { name: r.ref })} onClick={() => setDeleting(r)}>
                        <Trash2 aria-hidden />
                      </Button>
                    </div>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <RiskDialog e={e} risk={editing} open={open} onOpenChange={setOpen} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("engagements.risks.deleteTitle")}
        description={t("engagements.risks.deleteDescription", { ref: deleting?.ref ?? "" })}
        confirmLabel={t("common.delete")}
        destructive
        busy={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </Card>
  );
}

// ---------------------------------------------------------------- procedures

const procSchema = z.object({
  title: z.string().trim().min(1).max(300),
  description: z.string().max(5000),
  assignee_id: z.string(),
  review_id: z.string(),
  risk_ids: z.array(z.string()).max(50),
});
type ProcValues = z.infer<typeof procSchema>;

function ProcedureDialog({ e, proc, open, onOpenChange }: { e: Engagement; proc: Procedure | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const refresh = useRefreshRisks(e.id);
  const risks = useRisks(e.id);
  const reviews = useEngagementReviews(e.id);
  const members = useMembers(open);
  const defaults = (): ProcValues => ({
    title: proc?.title ?? "",
    description: proc?.description ?? "",
    assignee_id: proc?.assignee_id ?? "",
    review_id: proc?.review_id ?? "",
    risk_ids: proc?.risk_ids ?? [],
  });
  const form = useForm<ProcValues>({ resolver: zodResolver(procSchema), defaultValues: defaults() });
  useEffect(() => {
    if (open) form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset each time the dialog opens
  }, [open, proc]);
  const save = useMutation({
    mutationFn: (v: ProcValues) =>
      api<Procedure>(proc ? `/procedures/${proc.id}` : `/engagements/${e.id}/procedures`, {
        method: proc ? "PUT" : "POST",
        json: {
          title: v.title,
          description: v.description,
          requirement_id: proc?.requirement_id ?? null,
          assignee_id: v.assignee_id || null,
          review_id: v.review_id || null,
          risk_ids: v.risk_ids,
        },
      }),
    onSuccess: () => {
      refresh();
      toast.success(t("engagements.procedures.saved"));
      close();
    },
  });
  function close() {
    save.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  const staff = (members.data ?? []).filter((m) => m.role !== "client" && m.role !== "viewer");
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{proc ? t("engagements.procedures.edit") : t("engagements.procedures.add")}</DialogTitle>
        <DialogDescription>{t("engagements.procedures.dialogHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <Field id="proc-title" label={t("workpapers.titleField")} error={err.title ? t("workpapers.titleRequired") : undefined}>
            <Input id="proc-title" aria-invalid={!!err.title} {...form.register("title")} />
          </Field>
          <Field id="proc-desc" label={t("engagements.descriptionField")}>
            <Textarea id="proc-desc" rows={2} {...form.register("description")} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="proc-assignee" label={t("engagements.procedures.assignee")}>
              <Select id="proc-assignee" {...form.register("assignee_id")}>
                <option value="">{t("engagements.procedures.unassigned")}</option>
                {staff.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.full_name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="proc-review" label={t("engagements.procedures.review")}>
              <Select id="proc-review" {...form.register("review_id")}>
                <option value="">{t("engagements.procedures.noReview")}</option>
                {(reviews.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <fieldset className="space-y-1.5">
            <legend className="text-[13px] font-medium text-slate-700">{t("engagements.procedures.risks")}</legend>
            {(risks.data ?? []).length === 0 ? (
              <p className="text-xs text-slate-500">{t("engagements.risks.empty")}</p>
            ) : (
              <Controller
                control={form.control}
                name="risk_ids"
                render={({ field }) => (
                  <div className="grid max-h-48 gap-1.5 overflow-y-auto sm:grid-cols-2">
                    {(risks.data ?? []).map((r) => (
                      <label key={r.id} className="flex items-center gap-2 text-sm text-slate-700">
                        <input
                          type="checkbox"
                          className="size-4 accent-teal-600"
                          checked={field.value.includes(r.id)}
                          onChange={(ev) => field.onChange(ev.target.checked ? [...field.value, r.id] : field.value.filter((x) => x !== r.id))}
                        />
                        <span className="truncate">
                          {r.ref} · {r.title}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              />
            )}
          </fieldset>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
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

function StatusDialog({ e, proc, onClose }: { e: Engagement; proc: { p: Procedure; status: ProcedureStatus } | null; onClose: () => void }) {
  const { t } = useTranslation();
  const refresh = useRefreshRisks(e.id);
  // Keyed by the caller per procedure and target status.
  const [conclusion, setConclusion] = useState(proc?.p.conclusion ?? "");
  const save = useMutation({
    mutationFn: (v: { id: string; status: ProcedureStatus; conclusion: string }) =>
      api<Procedure>(`/procedures/${v.id}/status`, { json: { status: v.status, conclusion: v.conclusion } }),
    onSuccess: () => {
      refresh();
      toast.success(t("engagements.procedures.statusSaved"));
      save.reset();
      onClose();
    },
  });
  const needsConclusion = proc?.status === "done";
  return (
    <Dialog open={!!proc} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{t("engagements.procedures.statusTitle", { status: proc ? t(`procedureStatus.${proc.status}`) : "" })}</DialogTitle>
        <DialogDescription>{needsConclusion ? t("engagements.procedures.conclusionHint") : t("engagements.procedures.statusHint")}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (proc) save.mutate({ id: proc.p.id, status: proc.status, conclusion });
          }}
        >
          <Field id="proc-conclusion" label={t("engagements.procedures.conclusion")}>
            <Textarea id="proc-conclusion" rows={3} value={conclusion} onChange={(ev) => setConclusion(ev.target.value)} />
          </Field>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={save.isPending || (needsConclusion && !conclusion.trim())}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const STATUS_TONE = { not_started: "neutral", in_progress: "teal", done: "green" } as const;

function ProceduresCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const procs = useProcedures(e.id);
  const risks = useRisks(e.id);
  const [editing, setEditing] = useState<Procedure | null>(null);
  const [open, setOpen] = useState(false);
  const [statusFor, setStatusFor] = useState<{ p: Procedure; status: ProcedureStatus } | null>(null);
  const editable = can("write") && e.status !== "closed";
  const refOf = (id: string) => risks.data?.find((r) => r.id === id)?.ref ?? id.slice(0, 6);
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{t("engagements.procedures.title")}</CardTitle>
          <CardDescription>{t("engagements.procedures.hint")}</CardDescription>
        </div>
        {editable && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus aria-hidden /> {t("engagements.procedures.add")}
          </Button>
        )}
      </CardHeader>
      {procs.isLoading && <LoadingState rows={3} />}
      {procs.isError && <ErrorState error={procs.error} onRetry={() => void procs.refetch()} />}
      {procs.data?.length === 0 && <EmptyState icon={ClipboardList} title={t("engagements.procedures.empty")} description={t("engagements.procedures.emptyHint")} />}
      {procs.data && procs.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.procedures.procedure")}</TH>
              <TH>{t("engagements.procedures.risks")}</TH>
              <TH>{t("engagements.procedures.assignee")}</TH>
              <TH>{t("engagements.status")}</TH>
              {editable && <TH className="w-14">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {procs.data.map((p) => (
              <TR key={p.id}>
                <TD className="max-w-96 align-top">
                  <span className="font-medium text-navy-900">{p.title}</span>
                  {p.requirement_code && (
                    <code dir="ltr" className="ms-2 font-mono text-[11px] text-slate-400">
                      {p.requirement_code}
                    </code>
                  )}
                  {p.conclusion && <p className="mt-1 text-xs text-slate-500">{p.conclusion}</p>}
                </TD>
                <TD className="align-top">
                  {p.risk_ids.length === 0 ? (
                    <span className="text-xs text-amber-700">{t("engagements.procedures.noRisk")}</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {p.risk_ids.map((id) => (
                        <Badge key={id} tone="neutral">
                          {refOf(id)}
                        </Badge>
                      ))}
                    </div>
                  )}
                </TD>
                <TD className="align-top text-[13px] text-slate-600">{p.assignee_name ?? t("engagements.procedures.unassigned")}</TD>
                <TD className="align-top">
                  {editable ? (
                    <Select
                      aria-label={t("engagements.procedures.statusFor", { title: p.title })}
                      className="w-40"
                      value={p.status}
                      onChange={(ev) => setStatusFor({ p, status: ev.target.value as ProcedureStatus })}
                    >
                      {PROCEDURE_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {t(`procedureStatus.${s}`)}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Badge tone={STATUS_TONE[p.status]} dot>
                      {t(`procedureStatus.${p.status}`)}
                    </Badge>
                  )}
                </TD>
                {editable && (
                  <TD className="align-top">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("workpapers.editNamed", { name: p.title })}
                      onClick={() => {
                        setEditing(p);
                        setOpen(true);
                      }}
                    >
                      <Pencil aria-hidden />
                    </Button>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <ProcedureDialog e={e} proc={editing} open={open} onOpenChange={setOpen} />
      <StatusDialog key={statusFor ? `${statusFor.p.id}:${statusFor.status}` : "none"} e={e} proc={statusFor} onClose={() => setStatusFor(null)} />
    </Card>
  );
}

// ---------------------------------------------------------------- coverage, programme, reviews

function CoverageCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const cov = useCoverage(e.id);
  const c = cov.data;
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.coverage.title")}</CardTitle>
        <CardDescription>{t("engagements.coverage.hint")}</CardDescription>
      </CardHeader>
      {cov.isLoading && <LoadingState rows={2} />}
      {cov.isError && <ErrorState error={cov.error} onRetry={() => void cov.refetch()} />}
      {c && (
        <div className="space-y-3 px-5 py-4 text-[13px]">
          <dl className="grid gap-3 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-slate-500">{t("engagements.coverage.uncovered")}</dt>
              <dd className={c.uncovered.length ? "font-medium text-amber-800" : "text-slate-700"}>{c.uncovered.length ? c.uncovered.join(", ") : t("engagements.coverage.none")}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">{t("engagements.coverage.significantOpen")}</dt>
              <dd className={c.significant_open.length ? "font-medium text-red-700" : "text-slate-700"}>
                {c.significant_open.length ? c.significant_open.join(", ") : t("engagements.coverage.none")}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">{t("engagements.coverage.unlinked")}</dt>
              <dd className="tabular-nums text-slate-700">{c.unlinked_procedures.length}</dd>
            </div>
          </dl>
          {c.risks.length > 0 && (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100">
              {c.risks.map((r) => (
                <li key={r.risk_id} className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="min-w-0 truncate">
                    <code dir="ltr" className="me-2 font-mono text-xs">
                      {r.ref}
                    </code>
                    {r.title}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-slate-500">{t("engagements.coverage.doneOf", { done: r.done, total: r.procedures })}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function ProgrammeCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const lists = usePublishedChecklists();
  const programmes = lists.items.filter((x) => x.c.kind === "audit_programme");
  const [versionId, setVersionId] = useState("");
  const apply = useMutation({
    mutationFn: (id: string) => api<Procedure[]>(`/engagements/${e.id}/programme`, { json: { checklist_version_id: id } }),
    onSuccess: (d) => {
      qc.setQueryData(engKey(e.id, "procedures"), d);
      void qc.invalidateQueries({ queryKey: engKey(e.id, "coverage") });
      toast.success(t("engagements.programme.applied"));
    },
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("engagements.programme.title")}</CardTitle>
        <CardDescription>{t("engagements.programme.hint")}</CardDescription>
      </CardHeader>
      <form
        className="space-y-3 px-5 py-4"
        onSubmit={(ev) => {
          ev.preventDefault();
          if (versionId) apply.mutate(versionId);
        }}
      >
        {lists.query.isError && <ErrorState error={lists.query.error} onRetry={() => void lists.query.refetch()} />}
        {lists.query.data && programmes.length === 0 && <p className="text-sm text-slate-500">{t("engagements.programme.none")}</p>}
        {programmes.length > 0 && (
          <Field id="prog-version" label={t("reviews.checklist")}>
            <Select id="prog-version" value={versionId} onChange={(ev) => setVersionId(ev.target.value)}>
              <option value="">{t("engagements.programme.choose")}</option>
              {programmes.map(({ c, v }) => (
                <option key={v.id} value={v.id}>
                  {c.name} · v{v.version_number}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <MutationError error={apply.error} />
        <Button type="submit" variant="outline" size="sm" disabled={!versionId || apply.isPending}>
          {apply.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <ListPlus aria-hidden />}
          {t("engagements.programme.apply")}
        </Button>
      </form>
    </Card>
  );
}

function ReviewsCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const linked = useEngagementReviews(e.id);
  const editable = can("write") && e.status !== "closed";
  const all = useQuery({ queryKey: ["reviews", "for-engagement"], queryFn: () => api<Page<Review>>("/reviews?page_size=100"), enabled: editable });
  const [reviewId, setReviewId] = useState("");
  const link = useMutation({
    mutationFn: (id: string) => api<void>(`/engagements/${e.id}/reviews/${id}`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "reviews") });
      setReviewId("");
      toast.success(t("engagements.reviews.linked"));
    },
  });
  const linkedIds = new Set((linked.data ?? []).map((r) => r.id));
  const candidates = (all.data?.items ?? []).filter((r) => !linkedIds.has(r.id));
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.reviews.title")}</CardTitle>
        <CardDescription>{t("engagements.reviews.hint")}</CardDescription>
      </CardHeader>
      {linked.isLoading && <LoadingState rows={2} />}
      {linked.isError && <ErrorState error={linked.error} onRetry={() => void linked.refetch()} />}
      {linked.data?.length === 0 && <EmptyState icon={Link2} title={t("engagements.reviews.empty")} />}
      {linked.data && linked.data.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {linked.data.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
              <Link to={`/reviews/${r.id}`} className="truncate text-sm font-medium text-navy-900 hover:text-teal-700 hover:underline">
                {r.title}
              </Link>
              <ReviewStatusBadge status={r.status} />
            </li>
          ))}
        </ul>
      )}
      {editable && (
        <form
          className="grid gap-3 border-t border-slate-100 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (reviewId) link.mutate(reviewId);
          }}
        >
          <Field id="link-review" label={t("engagements.reviews.linkReview")}>
            <Select id="link-review" value={reviewId} onChange={(ev) => setReviewId(ev.target.value)}>
              <option value="">{t("engagements.reviews.choose")}</option>
              {candidates.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                </option>
              ))}
            </Select>
          </Field>
          <Button type="submit" variant="outline" disabled={!reviewId || link.isPending}>
            {link.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Link2 aria-hidden />}
            {t("engagements.reviews.link")}
          </Button>
          <div className="sm:col-span-2">
            <MutationError error={link.error} />
          </div>
        </form>
      )}
    </Card>
  );
}

export function RisksTab({ e }: { e: Engagement }) {
  const { can } = useAuth();
  return (
    <div className="space-y-5">
      <RiskRegister e={e} />
      <ProceduresCard e={e} />
      <div className="grid gap-5 xl:grid-cols-2">
        <CoverageCard e={e} />
        <div className="space-y-5">
          {can("write") && e.status !== "closed" && <ProgrammeCard e={e} />}
          <ReviewsCard e={e} />
        </div>
      </div>
    </div>
  );
}
