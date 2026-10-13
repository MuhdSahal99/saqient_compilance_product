import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  BookMarked,
  Bot,
  Check,
  Gavel,
  History,
  Lock,
  MessageSquare,
  Quote,
  ShieldAlert,
  Sparkles,
  UserCheck,
  Wrench,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { AuditEvent, Comment, Evidence, Finding, Member, Page } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar } from "@/components/ui/avatar";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { errorMessage, FindingStatusBadge, OutcomeBadge, SeverityBadge, useUnsavedChangesWarning } from "./common";
import { EvidenceQuote } from "./evidence";
import { MockNotice } from "./ai-suggestions";

const DECIDABLE = new Set(["proposed", "in_review", "confirmed", "dismissed", "accepted_risk"]);
const ASSIGNABLE = new Set(["confirmed", "remediation_in_progress", "ready_for_rereview", "resolved", "accepted_risk"]);
const IN_REMEDIATION = new Set(["remediation_in_progress", "ready_for_rereview"]);

function useFindingMutation<TBody>(finding: Finding, path: string) {
  const qc = useQueryClient();
  const { t } = useTranslation();
  return useMutation({
    mutationFn: (body: TBody) => api<Finding>(`/findings/${finding.id}/${path}`, { json: body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["findings"] });
      void qc.invalidateQueries({ queryKey: ["review", finding.review_id] });
      void qc.invalidateQueries({ queryKey: ["finding-activity", finding.id] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(t("common.saved"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
}

const decisionSchema = z.object({ rationale: z.string().max(5000) });

function DecisionForm({ finding }: { finding: Finding }) {
  const { t } = useTranslation();
  const form = useForm<z.infer<typeof decisionSchema>>({
    resolver: zodResolver(decisionSchema),
    defaultValues: { rationale: finding.decision_rationale },
  });
  useUnsavedChangesWarning(form.formState.isDirty);
  const decide = useFindingMutation<{ decision: string; rationale: string }>(finding, "decision");
  const submit = (decision: "confirmed" | "dismissed" | "accepted_risk") =>
    form.handleSubmit((v) => {
      if (decision !== "confirmed" && v.rationale.trim().length < 5) {
        form.setError("rationale", { message: t("findings.rationaleRequired") });
        return;
      }
      decide.mutate({ decision, rationale: v.rationale }, { onSuccess: () => form.reset({ rationale: v.rationale }) });
    })();
  return (
    <section aria-labelledby="decision-h" className="space-y-2.5 rounded-xl border border-slate-200/80 bg-slate-50/60 p-4">
      <h3 id="decision-h" className="flex items-center gap-2 text-[13px] font-semibold text-navy-900">
        <Gavel className="size-4 text-slate-400" aria-hidden />
        {t("findings.reviewerDecision")}
      </h3>
      <Label htmlFor="rationale" className="text-xs text-slate-600">
        {t("findings.rationale")}
      </Label>
      <Textarea id="rationale" rows={2} className="bg-white" aria-invalid={!!form.formState.errors.rationale} {...form.register("rationale")} />
      <FieldError message={form.formState.errors.rationale?.message} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="default" className="min-w-24" disabled={decide.isPending} onClick={() => submit("confirmed")}>
          <Check aria-hidden /> {t("findings.confirm")}
        </Button>
        <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => submit("dismissed")}>
          <X aria-hidden /> {t("findings.dismiss")}
        </Button>
        <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => submit("accepted_risk")}>
          <ShieldAlert aria-hidden /> {t("findings.acceptRisk")}
        </Button>
      </div>
    </section>
  );
}

const assignSchema = z.object({ owner_id: z.string(), due_date: z.string() });

function AssignmentForm({ finding }: { finding: Finding }) {
  const { t } = useTranslation();
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members") });
  const form = useForm<z.infer<typeof assignSchema>>({
    resolver: zodResolver(assignSchema),
    defaultValues: { owner_id: finding.owner_id ?? "", due_date: finding.due_date ?? "" },
  });
  useUnsavedChangesWarning(form.formState.isDirty);
  const assign = useFindingMutation<{ owner_id: string | null; due_date: string | null }>(finding, "assignment");
  // Render the owner select only once members are loaded, so the saved owner is preselected.
  if (members.isLoading) return <div className="skeleton h-28 rounded-xl" aria-hidden />;
  return (
    <form
      aria-labelledby="assign-h"
      className="space-y-2.5 rounded-xl border border-slate-200/80 p-4"
      onSubmit={form.handleSubmit((v) =>
        assign.mutate({ owner_id: v.owner_id || null, due_date: v.due_date || null }, { onSuccess: () => form.reset(v) }),
      )}
    >
      <h3 id="assign-h" className="flex items-center gap-2 text-[13px] font-semibold text-navy-900">
        <Wrench className="size-4 text-slate-400" aria-hidden />
        {t("findings.remediation")}
      </h3>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="owner" className="text-xs text-slate-600">
            {t("findings.owner")}
          </Label>
          <Select id="owner" {...form.register("owner_id")}>
            <option value="">{t("findings.unassigned")}</option>
            {members.data?.map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.full_name}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="due" className="text-xs text-slate-600">
            {t("findings.dueDate")}
          </Label>
          <Input id="due" type="date" {...form.register("due_date")} />
        </div>
      </div>
      <Button size="sm" type="submit" disabled={!form.formState.isDirty || assign.isPending}>
        {t("findings.assign")}
      </Button>
    </form>
  );
}

const remediationSchema = z.object({ notes: z.string().max(10000) });

function RemediationForm({ finding, canDecide }: { finding: Finding; canDecide: boolean }) {
  const { t } = useTranslation();
  const form = useForm<z.infer<typeof remediationSchema>>({
    resolver: zodResolver(remediationSchema),
    defaultValues: { notes: finding.remediation_notes },
  });
  useUnsavedChangesWarning(form.formState.isDirty);
  const update = useFindingMutation<{ notes: string; status?: string }>(finding, "remediation");
  const send = (status?: string) =>
    form.handleSubmit((v) => update.mutate({ notes: v.notes, status }, { onSuccess: () => form.reset(v) }))();
  return (
    <section className="space-y-2.5 rounded-xl border border-slate-200/80 p-4">
      <Label htmlFor="remediation-notes" className="text-xs text-slate-600">
        {t("findings.remediationNotes")}
      </Label>
      <Textarea id="remediation-notes" rows={2} {...form.register("notes")} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => send()}>
          {t("findings.saveNotes")}
        </Button>
        {finding.status === "remediation_in_progress" && (
          <Button size="sm" variant="accent" disabled={update.isPending} onClick={() => send("ready_for_rereview")}>
            {t("findings.markReady")}
          </Button>
        )}
        {finding.status === "ready_for_rereview" && canDecide && (
          <>
            <Button size="sm" variant="accent" disabled={update.isPending} onClick={() => send("resolved")}>
              {t("findings.resolve")}
            </Button>
            <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => send("remediation_in_progress")}>
              {t("findings.sendBack")}
            </Button>
          </>
        )}
      </div>
    </section>
  );
}

function Comments({ finding, canWrite }: { finding: Finding; canWrite: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const comments = useQuery({ queryKey: ["comments", finding.id], queryFn: () => api<Comment[]>(`/findings/${finding.id}/comments`) });
  const form = useForm<{ body: string }>({ defaultValues: { body: "" } });
  const add = useMutation({
    mutationFn: (body: string) => api<Comment>(`/findings/${finding.id}/comments`, { json: { body } }),
    onSuccess: () => {
      form.reset();
      void qc.invalidateQueries({ queryKey: ["comments", finding.id] });
      void qc.invalidateQueries({ queryKey: ["finding-activity", finding.id] });
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-[13px] font-semibold text-navy-900">
        <MessageSquare className="size-4 text-slate-400" aria-hidden />
        {t("findings.comments")}
        {!!comments.data?.length && <span className="rounded-full bg-slate-100 px-1.5 text-[11px] text-slate-500">{comments.data.length}</span>}
      </h3>
      {comments.data?.length === 0 && <p className="text-xs text-slate-500">{t("findings.noComments")}</p>}
      <ul className="space-y-2.5">
        {comments.data?.map((c) => (
          <li key={c.id} className="flex gap-2.5">
            <Avatar name={c.author_name} className="size-7 text-[10px]" />
            <div className="min-w-0 flex-1 rounded-xl rounded-ss-sm bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-200/60">
              <p className="text-xs text-slate-500">
                <span className="font-medium text-slate-700">{c.author_name}</span> · {formatDate(c.created_at, i18n.language, true)}
              </p>
              <p className="mt-0.5 whitespace-pre-wrap text-slate-800" dir="auto">
                {c.body}
              </p>
            </div>
          </li>
        ))}
      </ul>
      {canWrite && (
        <form
          className="flex gap-2"
          onSubmit={form.handleSubmit((v) => {
            if (v.body.trim()) add.mutate(v.body.trim());
          })}
        >
          <Input aria-label={t("findings.addComment")} placeholder={t("findings.addComment")} {...form.register("body")} />
          <Button size="sm" type="submit" variant="outline" disabled={add.isPending}>
            {t("findings.post")}
          </Button>
        </form>
      )}
    </section>
  );
}

function FindingActivity({ findingId }: { findingId: string }) {
  const { t, i18n } = useTranslation();
  const events = useQuery({
    queryKey: ["finding-activity", findingId],
    queryFn: () => api<Page<AuditEvent>>(`/audit-events${qs({ object_id: findingId, page_size: 20 })}`),
  });
  if (!events.data?.items.length) return null;
  return (
    <section className="space-y-2.5">
      <h3 className="flex items-center gap-2 text-[13px] font-semibold text-navy-900">
        <History className="size-4 text-slate-400" aria-hidden />
        {t("findings.history")}
      </h3>
      <ol className="ms-1.5 space-y-2.5 border-s border-slate-200 ps-4 text-xs text-slate-600">
        {events.data.items.map((e) => (
          <li key={e.id} className="relative">
            <span className="absolute -start-[21px] top-1 size-2 rounded-full bg-slate-300 ring-2 ring-white" aria-hidden />
            <span className="font-medium text-slate-700">{e.actor_name ?? t("activity.system")}</span> ·{" "}
            {t(`audit.${e.action}`, { defaultValue: e.action })}
            {typeof e.meta.to === "string" && ` → ${t(`findingStatus.${e.meta.to}`, { defaultValue: e.meta.to })}`}
            <span className="block text-[11px] text-slate-400">{formatDate(e.created_at, i18n.language, true)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function FindingPanel({ finding, onLocate }: { finding: Finding; onLocate?: (e: Evidence) => void }) {
  const { t, i18n } = useTranslation();
  const { can, me } = useAuth();
  const signedOff = finding.review_status === "signed_off";
  const canDecide = can("decide");
  const isOwner = me?.user.id === finding.owner_id;

  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-1.5">
          <SeverityBadge severity={finding.severity} />
          <FindingStatusBadge status={finding.status} />
          {finding.requirement_code && (
            <code className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{finding.requirement_code}</code>
          )}
          {finding.is_manual && <Badge>{t("findings.manual")}</Badge>}
          {finding.ai_suggestion_id && (
            <Badge tone="violet">
              <Sparkles className="size-3" aria-hidden />
              {t("ai.badge")}
            </Badge>
          )}
          {finding.is_overdue && (
            <Badge tone="red" dot>
              {t("findings.overdue")}
            </Badge>
          )}
        </div>
        <h2 className="mt-3 text-lg font-semibold leading-snug tracking-tight text-navy-950">{finding.title}</h2>
        {finding.description && <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{finding.description}</p>}
        {finding.ai_suggestion_id && (
          <div className="mt-3 space-y-2">
            <p className="flex items-start gap-1.5 rounded-lg bg-violet-50/70 px-3 py-2 text-xs leading-relaxed text-violet-900 ring-1 ring-violet-200/70">
              <Sparkles className="mt-px size-3.5 shrink-0" aria-hidden />
              {t("ai.findingOrigin", {
                model: finding.ai_provider === "mock" ? t("ai.mockModel") : `${finding.ai_provider} · ${finding.ai_model}`,
              })}
            </p>
            {finding.ai_provider === "mock" && <MockNotice />}
          </div>
        )}
        {(finding.automated_outcome || finding.source_reference) && (
          <div className="mt-3 space-y-1 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500 ring-1 ring-slate-200/60">
            {finding.automated_outcome && (
              <p className="flex flex-wrap items-center gap-1.5">
                <Bot className="size-3.5 text-slate-400" aria-hidden />
                {t("findings.automatedOutcome")}: <OutcomeBadge outcome={finding.automated_outcome} />
                <span>{t("findings.automatedNotDecision")}</span>
              </p>
            )}
            {finding.source_reference && (
              <p className="flex items-center gap-1.5">
                <BookMarked className="size-3.5 text-slate-400" aria-hidden />
                {t("findings.sourceReference")}: {finding.source_reference}
              </p>
            )}
          </div>
        )}
      </div>

      <section className="space-y-2.5">
        <h3 className="flex items-center gap-2 text-[13px] font-semibold text-navy-900">
          <Quote className="size-4 text-slate-400" aria-hidden />
          {t("findings.evidence")}
          {finding.evidence.length > 0 && (
            <span className="rounded-full bg-slate-100 px-1.5 text-[11px] text-slate-500">{finding.evidence.length}</span>
          )}
        </h3>
        {finding.evidence.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 px-3 py-2.5 text-xs leading-relaxed text-slate-600">{t("findings.noEvidence")}</p>
        ) : (
          finding.evidence.map((e, i) => <EvidenceQuote key={`${e.block_id}-${i}`} evidence={e} onLocate={onLocate} />)
        )}
      </section>

      {finding.decided_by_name && (
        <p className="flex items-start gap-2 rounded-lg bg-emerald-50/60 px-3 py-2 text-xs text-emerald-900 ring-1 ring-emerald-200/60">
          <UserCheck className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>
          {t("findings.decidedBy", { name: finding.decided_by_name, date: formatDate(finding.decided_at, i18n.language, true) })}
          {finding.decision_rationale && <> — “{finding.decision_rationale}”</>}
          </span>
        </p>
      )}

      {canDecide && !signedOff && DECIDABLE.has(finding.status) && <DecisionForm key={finding.id + finding.status} finding={finding} />}
      {signedOff && DECIDABLE.has(finding.status) && canDecide && (
        <p className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-200/60">
          <Lock className="size-3.5 shrink-0" aria-hidden />
          {t("findings.lockedSignedOff")}
        </p>
      )}
      {canDecide && ASSIGNABLE.has(finding.status) && <AssignmentForm key={`${finding.id}-${finding.updated_at}`} finding={finding} />}
      {!canDecide && (finding.owner_name || finding.due_date) && (
        <p className="text-sm text-slate-700">
          {t("findings.owner")}: {finding.owner_name ?? "—"} · {t("findings.dueDate")}: {formatDate(finding.due_date, i18n.language)}
        </p>
      )}
      {IN_REMEDIATION.has(finding.status) && (canDecide || isOwner) && (
        <RemediationForm key={`${finding.id}-${finding.status}`} finding={finding} canDecide={canDecide} />
      )}
      {finding.remediation_notes && !(IN_REMEDIATION.has(finding.status) && (canDecide || isOwner)) && (
        <p className="text-sm text-slate-700">
          <span className="font-medium">{t("findings.remediationNotes")}:</span> {finding.remediation_notes}
        </p>
      )}
      <Comments finding={finding} canWrite={can("write")} />
      <FindingActivity findingId={finding.id} />
    </div>
  );
}
