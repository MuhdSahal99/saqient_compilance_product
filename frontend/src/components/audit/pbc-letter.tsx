import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CheckCircle2, FileCode2, FileText, Inbox, Loader2, Pencil, Plus, RefreshCw, Send, XCircle } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMembers } from "@/lib/queries";
import { REF_PATTERN, engKey, useLetter, usePbcRequests, type Engagement, type Letter, type LetterPoint, type PbcStaffRequest } from "@/lib/audit";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, FindingStatusBadge, LoadingState, SeverityBadge } from "@/components/common";
import { Field, MutationError, PbcStatusBadge } from "./shared";
import { AIAssist } from "@/components/ai-task";

// ---------------------------------------------------------------- PBC (staff)

const pbcSchema = z.object({
  ref: z.string().trim().regex(REF_PATTERN),
  title: z.string().trim().min(1).max(300),
  description: z.string().max(5000),
  due_date: z.string(),
  assignee_id: z.string(),
});
type PbcValues = z.infer<typeof pbcSchema>;

function NewPbcDialog({ e, open, onOpenChange }: { e: Engagement; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const members = useMembers(open);
  const clients = (members.data ?? []).filter((m) => m.role === "client");
  const form = useForm<PbcValues>({ resolver: zodResolver(pbcSchema), defaultValues: { ref: "", title: "", description: "", due_date: "", assignee_id: "" } });
  const create = useMutation({
    mutationFn: (v: PbcValues) => api<PbcStaffRequest>(`/engagements/${e.id}/pbc`, { json: { ...v, due_date: v.due_date || null, assignee_id: v.assignee_id || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "pbc") });
      toast.success(t("engagements.pbc.created"));
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
      <DialogContent>
        <DialogTitle>{t("engagements.pbc.new")}</DialogTitle>
        <DialogDescription>{t("engagements.pbc.newHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
            <Field id="pbc-ref" label={t("engagements.ref")} error={err.ref ? t("engagements.refRule") : undefined}>
              <Input id="pbc-ref" dir="ltr" aria-invalid={!!err.ref} {...form.register("ref")} />
            </Field>
            <Field id="pbc-title" label={t("workpapers.titleField")} error={err.title ? t("workpapers.titleRequired") : undefined}>
              <Input id="pbc-title" aria-invalid={!!err.title} {...form.register("title")} />
            </Field>
          </div>
          <Field id="pbc-desc" label={t("engagements.descriptionField")}>
            <Textarea id="pbc-desc" rows={3} {...form.register("description")} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="pbc-due" label={t("engagements.pbc.due")}>
              <Input id="pbc-due" type="date" {...form.register("due_date")} />
            </Field>
            <Field id="pbc-assignee" label={t("engagements.pbc.assignee")} hint={clients.length === 0 && members.data ? t("engagements.pbc.noClients") : undefined}>
              <Select id="pbc-assignee" {...form.register("assignee_id")}>
                <option value="">{t("engagements.procedures.unassigned")}</option>
                {clients.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.full_name} · {m.email}
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
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReviewPbcDialog({ e, target, onClose }: { e: Engagement; target: { r: PbcStaffRequest; accept: boolean } | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  // Keyed by the caller per request and decision.
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => api<PbcStaffRequest>(`/pbc/${target?.r.id}/review`, { json: { status: target?.accept ? "accepted" : "rejected", note } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "pbc") });
      toast.success(target?.accept ? t("engagements.pbc.accepted") : t("engagements.pbc.rejected"));
      save.reset();
      onClose();
    },
  });
  const reject = target ? !target.accept : false;
  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{reject ? t("engagements.pbc.rejectTitle", { ref: target?.r.ref ?? "" }) : t("engagements.pbc.acceptTitle", { ref: target?.r.ref ?? "" })}</DialogTitle>
        <DialogDescription>{reject ? t("engagements.pbc.rejectHint") : t("engagements.pbc.acceptHint")}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            save.mutate();
          }}
        >
          <Field id="pbc-note" label={t("engagements.pbc.reviewNote")}>
            <Textarea id="pbc-note" rows={3} value={note} onChange={(ev) => setNote(ev.target.value)} />
          </Field>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant={reject ? "destructive" : "accent"} disabled={save.isPending || (reject && !note.trim())}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {reject ? t("engagements.pbc.reject") : t("engagements.pbc.accept")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function PbcTab({ e }: { e: Engagement }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const list = usePbcRequests(e.id);
  const [open, setOpen] = useState(false);
  const [reviewing, setReviewing] = useState<{ r: PbcStaffRequest; accept: boolean } | null>(null);
  const editable = can("write") && e.status !== "closed";
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{t("engagements.pbc.title")}</CardTitle>
          <CardDescription>{t("engagements.pbc.hint")}</CardDescription>
        </div>
        {editable && (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            <Plus aria-hidden /> {t("engagements.pbc.new")}
          </Button>
        )}
      </CardHeader>
      {list.isLoading && <LoadingState rows={3} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.data?.length === 0 && <EmptyState icon={Inbox} title={t("engagements.pbc.empty")} />}
      {list.data && list.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.ref")}</TH>
              <TH>{t("engagements.pbc.request")}</TH>
              <TH>{t("engagements.pbc.assignee")}</TH>
              <TH>{t("engagements.pbc.due")}</TH>
              <TH>{t("engagements.pbc.files")}</TH>
              <TH>{t("engagements.status")}</TH>
              {editable && <TH>{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {list.data.map((r) => (
              <TR key={r.id}>
                <TD className="align-top">
                  <code dir="ltr" className="font-mono text-xs">
                    {r.ref}
                  </code>
                </TD>
                <TD className="max-w-80 align-top">
                  <span className="font-medium text-navy-900">{r.title}</span>
                  {r.description && <p className="mt-0.5 text-xs text-slate-500">{r.description}</p>}
                  {r.client_note && <p className="mt-1 text-xs text-slate-600">{t("engagements.pbc.clientNote", { note: r.client_note })}</p>}
                  {r.review_note && <p className="mt-1 text-xs text-slate-600">{t("engagements.pbc.reviewNoteShown", { note: r.review_note })}</p>}
                </TD>
                <TD className="align-top text-[13px] text-slate-600">{r.assignee_name ?? t("engagements.procedures.unassigned")}</TD>
                <TD className="whitespace-nowrap align-top text-[13px]">
                  {formatDate(r.due_date, i18n.language)}
                  {r.overdue && (
                    <Badge tone="red" className="ms-1.5">
                      {t("engagements.pbc.overdue")}
                    </Badge>
                  )}
                </TD>
                <TD className="align-top">
                  {r.files.length === 0 ? (
                    <span className="text-xs text-slate-400">—</span>
                  ) : (
                    <ul className="space-y-0.5 text-xs">
                      {r.files.map((f) => (
                        <li key={f.document_id}>
                          <Link to={`/documents/${f.document_id}`} className="text-teal-700 hover:underline">
                            {f.title}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </TD>
                <TD className="align-top">
                  <PbcStatusBadge status={r.status} />
                </TD>
                {editable && (
                  <TD className="align-top">
                    {r.status === "submitted" && (
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" onClick={() => setReviewing({ r, accept: true })}>
                          <CheckCircle2 aria-hidden /> {t("engagements.pbc.accept")}
                        </Button>
                        <Button variant="destructive-outline" size="sm" onClick={() => setReviewing({ r, accept: false })}>
                          <XCircle aria-hidden /> {t("engagements.pbc.reject")}
                        </Button>
                      </div>
                    )}
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <NewPbcDialog e={e} open={open} onOpenChange={setOpen} />
      <ReviewPbcDialog key={reviewing ? `${reviewing.r.id}:${reviewing.accept}` : "none"} e={e} target={reviewing} onClose={() => setReviewing(null)} />
    </Card>
  );
}

// ---------------------------------------------------------------- management letter

const pointSchema = z.object({
  include: z.boolean(),
  recommendation: z.string().max(5000),
  management_response: z.string().max(5000),
  response_owner: z.string().max(200),
  response_due: z.string(),
});
type PointValues = z.infer<typeof pointSchema>;

function PointDialog({ e, point, onClose }: { e: Engagement; point: LetterPoint | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<PointValues>({ resolver: zodResolver(pointSchema), defaultValues: { include: true, recommendation: "", management_response: "", response_owner: "", response_due: "" } });
  useEffect(() => {
    if (point)
      form.reset({
        include: point.include,
        recommendation: point.recommendation,
        management_response: point.management_response,
        response_owner: point.response_owner,
        response_due: point.response_due ?? "",
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset per point
  }, [point]);
  const save = useMutation({
    mutationFn: (v: PointValues) => api<LetterPoint>(`/letter-points/${point?.id}`, { method: "PUT", json: { ...v, response_due: v.response_due || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "letter") });
      toast.success(t("engagements.letter.pointSaved"));
      save.reset();
      onClose();
    },
  });
  return (
    <Dialog open={!!point} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{point?.finding_title}</DialogTitle>
        <DialogDescription>{t("engagements.letter.pointHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" className="size-4 accent-teal-600" {...form.register("include")} />
            {t("engagements.letter.include")}
          </label>
          <Field id="lp-rec" label={t("engagements.letter.recommendation")}>
            <Textarea id="lp-rec" rows={3} {...form.register("recommendation")} />
          </Field>
          <Field id="lp-resp" label={t("engagements.letter.response")}>
            <Textarea id="lp-resp" rows={3} {...form.register("management_response")} />
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="lp-owner" label={t("engagements.letter.owner")}>
              <Input id="lp-owner" maxLength={200} {...form.register("response_owner")} />
            </Field>
            <Field id="lp-due" label={t("engagements.letter.due")}>
              <Input id="lp-due" type="date" {...form.register("response_due")} />
            </Field>
          </div>
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

const linkCls =
  "inline-flex h-8 items-center gap-1.5 px-2.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 hover:text-navy-900 focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-teal-600 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-slate-400";

export function LetterTab({ e }: { e: Engagement }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const letter = useLetter(e.id);
  const [editing, setEditing] = useState<LetterPoint | null>(null);
  const [confirmIssue, setConfirmIssue] = useState(false);
  const editable = can("write") && e.status !== "closed";
  const onLetter = (msg: string) => (d: Letter) => {
    qc.setQueryData(engKey(e.id, "letter"), d);
    toast.success(msg);
  };
  const refresh = useMutation({
    mutationFn: () => api<Letter>(`/engagements/${e.id}/letter/refresh`, { method: "POST" }),
    onSuccess: onLetter(t("engagements.letter.refreshed")),
  });
  const issue = useMutation({
    mutationFn: () => api<Letter>(`/engagements/${e.id}/letter/issue`, { method: "POST" }),
    onSuccess: (d) => {
      setConfirmIssue(false);
      onLetter(t("engagements.letter.issued"))(d);
    },
  });
  if (letter.isLoading) return <LoadingState />;
  if (letter.isError || !letter.data) return <ErrorState error={letter.error} onRetry={() => void letter.refetch()} />;
  const l = letter.data;
  const included = l.points.filter((p) => p.include);
  const missingRec = included.filter((p) => !p.recommendation.trim()).length;
  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>{t("engagements.letter.title")}</CardTitle>
            <CardDescription>{t("engagements.letter.hint")}</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            {editable && (
              <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
                {refresh.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
                {t("engagements.letter.refresh")}
              </Button>
            )}
            {can("decide") && e.status !== "closed" && (
              <Button variant="accent" size="sm" disabled={included.length === 0 || issue.isPending} onClick={() => setConfirmIssue(true)}>
                <Send aria-hidden /> {t("engagements.letter.issue")}
              </Button>
            )}
          </div>
        </CardHeader>
        <div className="space-y-2 px-5 pt-3">
          <MutationError error={refresh.error} />
          <MutationError error={issue.error} />
          {missingRec > 0 && <p className="text-xs text-amber-800">{t("engagements.letter.missingRecommendation", { count: missingRec })}</p>}
        </div>
        {l.points.length === 0 ? (
          <EmptyState icon={FileText} title={t("engagements.letter.empty")} description={t("engagements.letter.emptyHint")} />
        ) : (
          <ul className="divide-y divide-slate-100">
            {l.points.map((p) => (
              <li key={p.id} className="flex items-start gap-3 px-5 py-4">
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-navy-900">{p.finding_title}</span>
                    <SeverityBadge severity={p.severity} />
                    <FindingStatusBadge status={p.finding_status} />
                    {!p.include && <Badge tone="neutral">{t("engagements.letter.excluded")}</Badge>}
                  </div>
                  <p className="text-[13px] leading-relaxed text-slate-600">{p.observation}</p>
                  <dl className="grid gap-2 text-[13px] sm:grid-cols-2">
                    <div>
                      <dt className="text-xs text-slate-500">{t("engagements.letter.recommendation")}</dt>
                      <dd className="text-slate-700">{p.recommendation || <span className="text-amber-700">{t("engagements.letter.notWritten")}</span>}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-slate-500">{t("engagements.letter.response")}</dt>
                      <dd className="text-slate-700">
                        {p.management_response || "—"}
                        {(p.response_owner || p.response_due) && (
                          <span className="block text-xs text-slate-500">
                            {[p.response_owner, p.response_due ? formatDate(p.response_due, i18n.language) : ""].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </dd>
                    </div>
                  </dl>
                  {p.evidence_refs.length > 0 && (
                    <p className="text-xs text-slate-500">
                      {t("engagements.letter.evidence")}: {p.evidence_refs.join("; ")}
                    </p>
                  )}
                  {e.status !== "closed" && <AIAssist kind="letter_draft" subjectId={p.id} />}
                </div>
                {editable && (
                  <Button variant="ghost" size="icon-sm" aria-label={t("workpapers.editNamed", { name: p.finding_title })} onClick={() => setEditing(p)}>
                    <Pencil aria-hidden />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>{t("engagements.letter.versions")}</CardTitle>
          <CardDescription>{t("engagements.letter.versionsHint")}</CardDescription>
        </CardHeader>
        {l.versions.length === 0 ? (
          <EmptyState icon={Send} title={t("engagements.letter.noVersions")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("workpapers.version")}</TH>
                <TH>{t("engagements.letter.issuedBy")}</TH>
                <TH className="text-end">{t("engagements.letter.points")}</TH>
                <TH>{t("workpapers.export")}</TH>
              </tr>
            </THead>
            <TBody>
              {l.versions.map((v) => {
                const base = `/api/engagements/${e.id}/letter/${v.version}/export?format=`;
                return (
                  <TR key={v.version}>
                    <TD className="font-medium text-navy-900">v{v.version}</TD>
                    <TD className="text-[13px] text-slate-600">
                      {v.issued_by_name ?? "—"}
                      <span className="block text-xs text-slate-400">{formatDate(v.issued_at, i18n.language, true)}</span>
                    </TD>
                    <TD className="text-end tabular-nums">{v.points}</TD>
                    <TD>
                      <div className="inline-flex items-stretch divide-x divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs rtl:divide-x-reverse">
                        <a className={linkCls} href={`${base}html`} target="_blank" rel="noopener noreferrer">
                          <FileCode2 aria-hidden />
                          {t("reports.html")}
                        </a>
                        <a className={linkCls} href={`${base}pdf`}>
                          <FileText aria-hidden />
                          {t("reports.pdf")}
                        </a>
                      </div>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
      <PointDialog e={e} point={editing} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={confirmIssue}
        onOpenChange={setConfirmIssue}
        title={t("engagements.letter.issueTitle")}
        description={t("engagements.letter.issueDescription", { count: included.length })}
        confirmLabel={t("engagements.letter.issue")}
        busy={issue.isPending}
        onConfirm={() => issue.mutate()}
      />
    </div>
  );
}
