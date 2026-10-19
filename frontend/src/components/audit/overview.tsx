import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Clock, Loader2, Pencil, Plus, Trash2, UserMinus, Users } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers } from "@/lib/queries";
import {
  ENGAGEMENT_PHASES,
  ENGAGEMENT_ROLES,
  HOURS_PATTERN,
  engKey,
  engagementKey,
  useTimeEntries,
  type Engagement,
  type EngagementRole,
  type TimeEntry,
} from "@/lib/audit";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, errorMessage, LoadingState } from "@/components/common";
import { Amount } from "@/components/calc-explain";
import { Field, MutationError, Share } from "./shared";

function useEngagementSetter(e: Engagement) {
  const qc = useQueryClient();
  return (data: Engagement) => {
    qc.setQueryData(engagementKey(e.id), data);
    void qc.invalidateQueries({ queryKey: ["engagements", "list"] });
  };
}

function TeamCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const setEng = useEngagementSetter(e);
  const members = useMembers(can("decide"));
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<EngagementRole>("staff");
  const [removing, setRemoving] = useState<string | null>(null);
  const open = e.status !== "closed";
  const onErr = (err: unknown) => toast.error(errorMessage(err, t("common.genericError")));
  const put = useMutation({
    mutationFn: (v: { userId: string; role: EngagementRole }) => api<Engagement>(`/engagements/${e.id}/members/${v.userId}`, { method: "PUT", json: { role: v.role } }),
    onSuccess: (d) => {
      setEng(d);
      setUserId("");
      toast.success(t("engagements.team.saved"));
    },
    onError: onErr,
  });
  const remove = useMutation({
    mutationFn: (uid: string) => api<Engagement>(`/engagements/${e.id}/members/${uid}`, { method: "DELETE" }),
    onSuccess: (d) => {
      setEng(d);
      setRemoving(null);
      toast.success(t("engagements.team.removed"));
    },
    onError: onErr,
  });
  const onTeam = new Set(e.members.map((m) => m.user_id));
  const candidates = (members.data ?? []).filter((m) => m.role !== "client" && !onTeam.has(m.user_id));
  const removingMember = e.members.find((m) => m.user_id === removing);
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.team.title")}</CardTitle>
        <CardDescription>{t("engagements.team.hint")}</CardDescription>
      </CardHeader>
      {e.members.length === 0 ? (
        <EmptyState icon={Users} title={t("engagements.team.empty")} />
      ) : (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.team.member")}</TH>
              <TH>{t("engagements.team.role")}</TH>
              <TH className="text-end">{t("engagements.hours.actual")}</TH>
              {can("decide") && open && <TH className="w-16">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {e.members.map((m) => (
              <TR key={m.user_id}>
                <TD>
                  <span className="font-medium text-navy-900">{m.full_name}</span>
                  <span className="block text-xs text-slate-500">{m.email}</span>
                </TD>
                <TD>
                  {can("decide") && open ? (
                    <Select
                      aria-label={t("engagements.team.roleFor", { name: m.full_name })}
                      className="w-40"
                      value={m.role}
                      disabled={put.isPending}
                      onChange={(ev) => put.mutate({ userId: m.user_id, role: ev.target.value as EngagementRole })}
                    >
                      {ENGAGEMENT_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {t(`engagementRole.${r}`)}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Badge tone="neutral">{t(`engagementRole.${m.role}`)}</Badge>
                  )}
                </TD>
                <TD className="text-end">
                  <Amount value={m.actual_hours} />
                </TD>
                {can("decide") && open && (
                  <TD>
                    <Button variant="ghost" size="icon-sm" aria-label={t("engagements.team.removeNamed", { name: m.full_name })} onClick={() => setRemoving(m.user_id)}>
                      <UserMinus aria-hidden />
                    </Button>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {can("decide") && open && (
        <form
          className="grid gap-3 border-t border-slate-100 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_11rem_auto] sm:items-end"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (userId) put.mutate({ userId, role });
          }}
        >
          <Field id="team-user" label={t("engagements.team.addMember")}>
            <Select id="team-user" value={userId} onChange={(ev) => setUserId(ev.target.value)} disabled={members.isLoading}>
              <option value="">{t("engagements.team.chooseMember")}</option>
              {candidates.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.full_name} · {m.email}
                </option>
              ))}
            </Select>
          </Field>
          <Field id="team-role" label={t("engagements.team.role")}>
            <Select id="team-role" value={role} onChange={(ev) => setRole(ev.target.value as EngagementRole)}>
              {ENGAGEMENT_ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`engagementRole.${r}`)}
                </option>
              ))}
            </Select>
          </Field>
          <Button type="submit" variant="outline" disabled={!userId || put.isPending}>
            {put.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
            {t("engagements.team.add")}
          </Button>
          {members.isError && (
            <p role="alert" className="text-sm text-red-700 sm:col-span-3">
              {errorMessage(members.error, t("common.genericError"))}
            </p>
          )}
        </form>
      )}
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("engagements.team.removeTitle")}
        description={t("engagements.team.removeDescription", { name: removingMember?.full_name ?? "" })}
        confirmLabel={t("engagements.team.remove")}
        destructive
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </Card>
  );
}

const budgetSchema = z.object(Object.fromEntries(ENGAGEMENT_PHASES.map((p) => [p, z.string().trim().regex(HOURS_PATTERN)])) as Record<
  (typeof ENGAGEMENT_PHASES)[number],
  z.ZodString
>);
type BudgetValues = z.infer<typeof budgetSchema>;

function BudgetDialog({ e, open, onOpenChange }: { e: Engagement; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const setEng = useEngagementSetter(e);
  const defaults = (): BudgetValues => {
    const v = {} as BudgetValues;
    for (const p of ENGAGEMENT_PHASES) v[p] = e.phases.find((x) => x.phase === p)?.budget_hours ?? "0";
    return v;
  };
  const form = useForm<BudgetValues>({ resolver: zodResolver(budgetSchema), defaultValues: defaults() });
  useEffect(() => {
    if (open) form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset each time the dialog opens
  }, [open]);
  const save = useMutation({
    mutationFn: (v: BudgetValues) =>
      api<Engagement>(`/engagements/${e.id}/budget`, { method: "PUT", json: { phases: ENGAGEMENT_PHASES.map((p) => ({ phase: p, hours: v[p] })) } }),
    onSuccess: (d) => {
      setEng(d);
      toast.success(t("engagements.hours.budgetSaved"));
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
      <DialogContent>
        <DialogTitle>{t("engagements.hours.editBudget")}</DialogTitle>
        <DialogDescription>{t("engagements.hours.budgetHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            {ENGAGEMENT_PHASES.map((p) => (
              <Field key={p} id={`budget-${p}`} label={t(`engagementPhase.${p}`)} error={err[p] ? t("engagements.hours.hoursRule") : undefined}>
                <Input id={`budget-${p}`} dir="ltr" inputMode="decimal" aria-invalid={!!err[p]} {...form.register(p)} />
              </Field>
            ))}
          </div>
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

function HoursCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{t("engagements.hours.title")}</CardTitle>
          <CardDescription>{t("engagements.hours.hint")}</CardDescription>
        </div>
        {can("decide") && e.status !== "closed" && (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            <Pencil aria-hidden /> {t("engagements.hours.editBudget")}
          </Button>
        )}
      </CardHeader>
      <Table>
        <THead>
          <tr>
            <TH>{t("engagements.hours.phase")}</TH>
            <TH className="text-end">{t("engagements.hours.budget")}</TH>
            <TH className="text-end">{t("engagements.hours.actual")}</TH>
            <TH className="text-end">{t("engagements.hours.variance")}</TH>
            <TH className="text-end">{t("engagements.hours.usedShare")}</TH>
          </tr>
        </THead>
        <TBody>
          {e.phases.map((p) => (
            <TR key={p.phase}>
              <TD className="font-medium text-navy-900">{t(`engagementPhase.${p.phase}`)}</TD>
              <TD className="text-end">
                <Amount value={p.budget_hours} />
              </TD>
              <TD className="text-end">
                <Amount value={p.actual_hours} />
              </TD>
              <TD className="text-end">
                <Amount value={p.variance_hours} className={p.variance_hours.startsWith("-") ? "text-red-700" : undefined} />
              </TD>
              <TD className="text-end">
                <Share value={p.used_share} />
              </TD>
            </TR>
          ))}
          <TR className="bg-slate-50/60">
            <TD className="font-semibold text-navy-900">{t("engagements.hours.total")}</TD>
            <TD className="text-end">
              <Amount value={e.budget_hours} />
            </TD>
            <TD className="text-end">
              <Amount value={e.actual_hours} />
            </TD>
            <TD />
            <TD />
          </TR>
        </TBody>
      </Table>
      <p className="border-t border-slate-100 px-5 py-2 text-xs text-slate-500">{t("engagements.hours.varianceNote")}</p>
      <BudgetDialog e={e} open={open} onOpenChange={setOpen} />
    </Card>
  );
}

const timeSchema = z.object({
  phase: z.enum(ENGAGEMENT_PHASES),
  work_date: z.string().min(1),
  hours: z.string().trim().regex(/^\d{1,2}(\.\d{1,2})?$/),
  note: z.string().max(500),
});
type TimeValues = z.infer<typeof timeSchema>;

function TimeCard({ e }: { e: Engagement }) {
  const { t, i18n } = useTranslation();
  const { can, me } = useAuth();
  const qc = useQueryClient();
  const entries = useTimeEntries(e.id);
  const [deleting, setDeleting] = useState<TimeEntry | null>(null);
  const defaultPhase = e.status === "closed" ? "reporting" : e.status;
  const form = useForm<TimeValues>({ resolver: zodResolver(timeSchema), defaultValues: { phase: defaultPhase, work_date: "", hours: "", note: "" } });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: engKey(e.id, "time") });
    void qc.invalidateQueries({ queryKey: engagementKey(e.id), exact: true });
  };
  const add = useMutation({
    mutationFn: (v: TimeValues) => api<TimeEntry>(`/engagements/${e.id}/time-entries`, { json: v }),
    onSuccess: () => {
      refresh();
      form.reset({ phase: form.getValues("phase"), work_date: "", hours: "", note: "" });
      toast.success(t("engagements.time.added"));
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/time-entries/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      refresh();
      setDeleting(null);
      toast.success(t("engagements.time.deleted"));
    },
    onError: (err) => toast.error(errorMessage(err, t("common.genericError"))),
  });
  const err = form.formState.errors;
  const open = e.status !== "closed";
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.time.title")}</CardTitle>
        <CardDescription>{t("engagements.time.hint")}</CardDescription>
      </CardHeader>
      {can("write") && open && (
        <form className="grid gap-3 border-b border-slate-100 px-5 py-4 sm:grid-cols-4 sm:items-start" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
          <Field id="time-phase" label={t("engagements.hours.phase")}>
            <Select id="time-phase" {...form.register("phase")}>
              {ENGAGEMENT_PHASES.map((p) => (
                <option key={p} value={p}>
                  {t(`engagementPhase.${p}`)}
                </option>
              ))}
            </Select>
          </Field>
          <Field id="time-date" label={t("engagements.time.date")} error={err.work_date ? t("rulePacks.dateRequired") : undefined}>
            <Input id="time-date" type="date" aria-invalid={!!err.work_date} {...form.register("work_date")} />
          </Field>
          <Field id="time-hours" label={t("engagements.time.hours")} error={err.hours ? t("engagements.time.hoursRule") : undefined}>
            <Input id="time-hours" dir="ltr" inputMode="decimal" aria-invalid={!!err.hours} {...form.register("hours")} />
          </Field>
          <Field id="time-note" label={t("losses.note")}>
            <Input id="time-note" maxLength={500} {...form.register("note")} />
          </Field>
          <div className="space-y-2 sm:col-span-4">
            <MutationError error={add.error} />
            <Button type="submit" variant="outline" size="sm" disabled={add.isPending}>
              {add.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Clock aria-hidden />}
              {t("engagements.time.add")}
            </Button>
          </div>
        </form>
      )}
      {entries.isLoading && <LoadingState rows={3} />}
      {entries.isError && <ErrorState error={entries.error} onRetry={() => void entries.refetch()} />}
      {entries.data?.length === 0 && <EmptyState icon={Clock} title={t("engagements.time.empty")} />}
      {entries.data && entries.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.time.date")}</TH>
              <TH>{t("engagements.team.member")}</TH>
              <TH>{t("engagements.hours.phase")}</TH>
              <TH className="text-end">{t("engagements.time.hours")}</TH>
              <TH>{t("losses.note")}</TH>
              {open && <TH className="w-16">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {entries.data.map((x) => (
              <TR key={x.id}>
                <TD className="whitespace-nowrap text-[13px]">{formatDate(x.work_date, i18n.language)}</TD>
                <TD className="text-[13px]">{x.user_name}</TD>
                <TD className="text-[13px]">{t(`engagementPhase.${x.phase}`)}</TD>
                <TD className="text-end">
                  <Amount value={x.hours} />
                </TD>
                <TD className="max-w-64 text-xs text-slate-500">{x.note || "—"}</TD>
                {open && (
                  <TD>
                    {(can("decide") || (can("write") && x.user_id === me?.user.id)) && (
                      <Button variant="ghost" size="icon-sm" aria-label={t("engagements.time.deleteEntry")} onClick={() => setDeleting(x)}>
                        <Trash2 aria-hidden />
                      </Button>
                    )}
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t("engagements.time.deleteTitle")}
        description={t("engagements.time.deleteDescription")}
        confirmLabel={t("common.delete")}
        destructive
        busy={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </Card>
  );
}

export function OverviewTab({ e }: { e: Engagement }) {
  return (
    <div className="space-y-5">
      <HoursCard e={e} />
      <TeamCard e={e} />
      <TimeCard e={e} />
    </div>
  );
}
