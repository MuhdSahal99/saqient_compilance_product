import { useEffect, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { BookDown, BookUp, Calculator, FileStack, Loader2, Pencil, Plus, RefreshCw, RotateCcw, Signature, Trash2, UserCheck } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { AUDIT_WORKPAPER_KINDS, WORKPAPER_CATEGORIES, type LossPosting, type Workpaper, type WorkpaperKind, type WorkpaperLine } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { lossRegisterKey, useWorkpaper, workpaperKey, workpapersKey } from "@/lib/queries";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, errorMessage, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { Amount, ExplainedLine, LineValue, SnapshotLinks, UnverifiedWarnings } from "@/components/calc-explain";
import { WorkpaperStatusBadge } from "./WorkpapersPage";

const LINE_KEY = /^[a-z][a-z0-9_]{0,79}$/;
const SIGNED_AMOUNT = /^-?\d{1,16}(\.\d{1,4})?$/;

/** Audit workpapers also take short text inputs (e.g. the materiality benchmark type and rationale). */
const isAuditKind = (k: WorkpaperKind) => (AUDIT_WORKPAPER_KINDS as readonly string[]).includes(k);

/** Stored evidence back to the reference shape the API accepts, so an edit keeps it. */
type EvidenceRef =
  | { kind: "source_block"; source_block_id: string }
  | { kind: "dataset_rows"; dataset_version_id: string; row_ids: unknown[] };

function evidenceRefs(evidence: Record<string, unknown>[]): EvidenceRef[] {
  return evidence.flatMap((e): EvidenceRef[] => {
    if (e.kind === "source_block" && typeof e.source_block_id === "string") return [{ kind: "source_block", source_block_id: e.source_block_id }];
    if (e.kind === "dataset_rows" && typeof e.dataset_version_id === "string" && Array.isArray(e.row_ids))
      return [{ kind: "dataset_rows", dataset_version_id: e.dataset_version_id, row_ids: e.row_ids }];
    return [];
  });
}

function evidenceLabel(e: Record<string, unknown>): string {
  if (e.kind === "source_block") return `${String(e.document_title ?? "")} · ${String(e.ref ?? "")}`;
  if (e.kind === "dataset_rows") {
    const rows = Array.isArray(e.row_ids) ? e.row_ids.length : 0;
    return `${String(e.dataset_name ?? "")} v${String(e.version_number ?? "")} · ${rows}`;
  }
  return "";
}

const inputSchema = z
  .object({
    line_key: z.string().trim().regex(LINE_KEY),
    category: z.string().min(1),
    label: z.string().trim().min(1).max(300),
    mode: z.enum(["amount", "flag", "text"]),
    amount: z.string().trim(),
    flag: z.enum(["true", "false"]),
    text: z.string().trim().max(200),
    note: z.string().max(4000),
  })
  .superRefine((v, ctx) => {
    if (v.mode === "amount" && !SIGNED_AMOUNT.test(v.amount)) ctx.addIssue({ code: "custom", path: ["amount"], message: "amount" });
    if (v.mode === "text" && !v.text) ctx.addIssue({ code: "custom", path: ["text"], message: "text" });
  });
type InputValues = z.infer<typeof inputSchema>;

function InputDialog({
  workpaper,
  line,
  open,
  onOpenChange,
}: {
  workpaper: Workpaper;
  line: WorkpaperLine | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const categories = WORKPAPER_CATEGORIES[workpaper.kind];
  const defaults = (): InputValues => ({
    line_key: line?.line_key ?? "",
    category: line?.category ?? categories[0] ?? "input",
    label: line?.label ?? "",
    mode: line && line.amount == null ? (line.value === "true" || line.value === "false" ? "flag" : "text") : "amount",
    amount: line?.amount ?? "",
    flag: line?.value === "true" ? "true" : "false",
    text: line && line.value !== "true" && line.value !== "false" ? (line.value ?? "") : "",
    note: line?.note ?? "",
  });
  const form = useForm<InputValues>({ resolver: zodResolver(inputSchema), defaultValues: defaults() });
  useEffect(() => {
    if (open) form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset each time the dialog opens for a line
  }, [open, line]);
  const save = useMutation({
    mutationFn: (v: InputValues) =>
      api<Workpaper>(`/workpapers/${workpaper.id}/inputs/${v.line_key}`, {
        method: "PUT",
        json: {
          category: v.category,
          label: v.label,
          amount: v.mode === "amount" ? v.amount : null,
          value: v.mode === "flag" ? v.flag : v.mode === "text" ? v.text : null,
          note: v.note,
          evidence: line ? evidenceRefs(line.evidence) : [],
        },
      }),
    onSuccess: (wp) => {
      qc.setQueryData(workpaperKey(wp.id), wp);
      void qc.invalidateQueries({ queryKey: workpapersKey });
      toast.success(t("workpapers.inputSaved"));
      close();
    },
  });
  function close() {
    save.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  const mode = useWatch({ control: form.control, name: "mode" });
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogTitle>{line ? t("workpapers.editInput") : t("workpapers.addInput")}</DialogTitle>
        <DialogDescription>{t("workpapers.inputHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="in-key">{t("workpapers.lineKey")}</Label>
              <Input id="in-key" dir="ltr" disabled={!!line} aria-invalid={!!err.line_key} aria-describedby="in-key-hint" {...form.register("line_key")} />
              <p id="in-key-hint" className="text-xs text-slate-500">
                {t("workpapers.lineKeyHint")}
              </p>
              <FieldError message={err.line_key ? t("workpapers.lineKeyRule") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="in-category">{t("workpapers.category")}</Label>
              <Select id="in-category" {...form.register("category")}>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {t(`workpaperCategory.${c}`, { defaultValue: c })}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="in-label">{t("workpapers.label")}</Label>
            <Input id="in-label" aria-invalid={!!err.label} {...form.register("label")} />
            <FieldError message={err.label ? t("workpapers.labelRequired") : undefined} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="in-mode">{t("workpapers.valueKind")}</Label>
              <Select id="in-mode" {...form.register("mode")}>
                <option value="amount">{t("workpapers.valueKindAmount")}</option>
                <option value="flag">{t("workpapers.valueKindFlag")}</option>
                {isAuditKind(workpaper.kind) && <option value="text">{t("workpapers.valueKindText")}</option>}
              </Select>
            </div>
            {mode === "text" ? (
              <div className="space-y-1.5">
                <Label htmlFor="in-text">{t("workpapers.textValue")}</Label>
                <Input id="in-text" maxLength={200} aria-invalid={!!err.text} {...form.register("text")} />
                <FieldError message={err.text ? t("workpapers.textRequired") : undefined} />
              </div>
            ) : mode === "amount" ? (
              <div className="space-y-1.5">
                <Label htmlFor="in-amount">{t("losses.amount")}</Label>
                <Input id="in-amount" dir="ltr" inputMode="decimal" aria-invalid={!!err.amount} {...form.register("amount")} />
                <FieldError message={err.amount ? t("directTax.signedAmountRule") : undefined} />
              </div>
            ) : (
              <div className="space-y-1.5">
                <Label htmlFor="in-flag">{t("workpapers.flag")}</Label>
                <Select id="in-flag" {...form.register("flag")}>
                  <option value="true">{t("directTax.yes")}</option>
                  <option value="false">{t("directTax.no")}</option>
                </Select>
              </div>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="in-note">{t("losses.note")}</Label>
            <Textarea id="in-note" rows={2} {...form.register("note")} />
          </div>
          {line && line.evidence.length > 0 && <p className="text-xs text-slate-500">{t("workpapers.evidenceKept", { count: line.evidence.length })}</p>}
          {save.isError && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {errorMessage(save.error, t("common.genericError"))}
            </p>
          )}
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

function ReopenDialog({ workpaper, open, onOpenChange }: { workpaper: Workpaper; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<{ reason: string }>({
    resolver: zodResolver(z.object({ reason: z.string().trim().min(3).max(4000) })),
    defaultValues: { reason: "" },
  });
  const reopen = useMutation({
    mutationFn: (v: { reason: string }) => api<Workpaper>(`/workpapers/${workpaper.id}/reopen`, { json: v }),
    onSuccess: (wp) => {
      qc.setQueryData(workpaperKey(wp.id), wp);
      void qc.invalidateQueries({ queryKey: workpapersKey });
      toast.success(t("workpapers.reopened"));
      close();
    },
  });
  function close() {
    form.reset();
    reopen.reset();
    onOpenChange(false);
  }
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogTitle>{t("workpapers.reopenTitle")}</DialogTitle>
        <DialogDescription>{t("workpapers.reopenHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => reopen.mutate(v))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="reopen-reason">{t("workpapers.reason")}</Label>
            <Textarea id="reopen-reason" rows={3} aria-invalid={!!form.formState.errors.reason} {...form.register("reason")} />
            <FieldError message={form.formState.errors.reason ? t("workpapers.reasonRequired") : undefined} />
          </div>
          {reopen.isError && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {errorMessage(reopen.error, t("common.genericError"))}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="default" disabled={reopen.isPending}>
              {reopen.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("workpapers.reopen")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px] text-navy-900">{children}</dd>
    </div>
  );
}

export function WorkpaperDetailPage() {
  const { workpaperId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const wp = useWorkpaper(workpaperId);
  const [editing, setEditing] = useState<WorkpaperLine | null>(null);
  const [inputOpen, setInputOpen] = useState(false);
  const [removing, setRemoving] = useState<WorkpaperLine | null>(null);
  const [confirmSignOff, setConfirmSignOff] = useState(false);
  const [confirmPost, setConfirmPost] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [postWarnings, setPostWarnings] = useState<string[]>([]);

  const onWp = (msg: string) => (data: Workpaper) => {
    qc.setQueryData(workpaperKey(data.id), data);
    void qc.invalidateQueries({ queryKey: workpapersKey });
    toast.success(msg);
  };
  const onErr = (e: unknown) => toast.error(errorMessage(e, t("common.genericError")));
  const compute = useMutation({
    mutationFn: () => api<Workpaper>(`/workpapers/${workpaperId}/compute`, { method: "POST" }),
    onSuccess: onWp(t("workpapers.computed")),
    onError: onErr,
  });
  const signOff = useMutation({
    mutationFn: () => api<Workpaper>(`/workpapers/${workpaperId}/sign-off`, { method: "POST" }),
    onSuccess: (d) => {
      setConfirmSignOff(false);
      onWp(t("workpapers.signedOff"))(d);
    },
    onError: onErr,
  });
  const removeInput = useMutation({
    mutationFn: (key: string) => api<Workpaper>(`/workpapers/${workpaperId}/inputs/${key}`, { method: "DELETE" }),
    onSuccess: (d) => {
      setRemoving(null);
      onWp(t("workpapers.inputRemoved"))(d);
    },
    onError: onErr,
  });
  const prefill = useMutation({
    mutationFn: () => api<Workpaper>(`/workpapers/${workpaperId}/prefill-losses`, { method: "POST" }),
    onSuccess: onWp(t("workpapers.prefilled")),
    onError: onErr,
  });
  const prepare = useMutation({
    mutationFn: () => api<Workpaper>(`/workpapers/${workpaperId}/prepare`, { method: "POST" }),
    onSuccess: onWp(t("workpapers.prepared")),
    onError: onErr,
  });
  const reloadLeads = useMutation({
    mutationFn: () => api<Workpaper>(`/workpapers/${workpaperId}/reload-leads`, { method: "POST" }),
    onSuccess: onWp(t("workpapers.leadsReloaded")),
    onError: onErr,
  });
  const post = useMutation({
    mutationFn: () => api<LossPosting>(`/workpapers/${workpaperId}/post-losses`, { method: "POST" }),
    onSuccess: (r) => {
      setConfirmPost(false);
      setPostWarnings(r.warnings);
      if (wp.data) void qc.invalidateQueries({ queryKey: lossRegisterKey(wp.data.entity_id) });
      toast.success(t("workpapers.posted", { count: r.created.length }));
    },
    onError: onErr,
  });

  if (wp.isLoading) return <LoadingState />;
  if (wp.isError || !wp.data) {
    if (wp.error instanceof ApiError && wp.error.status === 404)
      return <EmptyState icon={Calculator} title={t("common.notFound")} description={t("common.notFoundHint")} />;
    return <ErrorState error={wp.error} onRetry={() => void wp.refetch()} />;
  }
  const w = wp.data;
  const draft = w.status === "draft";
  const manual = w.lines.filter((l) => l.source === "manual");
  const computed = w.lines.filter((l) => l.source === "computed");
  const sections = Array.from(new Set(computed.map((l) => l.section)));
  const isCt = w.kind === "corporate_tax";
  const audit = isAuditKind(w.kind);
  const busy = compute.isPending || signOff.isPending || prefill.isPending || post.isPending || prepare.isPending || reloadLeads.isPending;
  const parentCrumb = w.engagement_id
    ? { label: t("nav.engagements"), to: `/engagements/${w.engagement_id}?tab=tb` }
    : { label: t("nav.directTax"), to: "/workpapers" };

  return (
    <>
      <PageHeader
        title={w.title}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <span>{w.entity_name}</span>
            <Badge tone="neutral">{t(`workpaperKind.${w.kind}`)}</Badge>
            <WorkpaperStatusBadge status={w.status} />
            {w.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={[{ label: t("nav.overview"), to: "/" }, parentCrumb, { label: w.title }]}
        actions={
          <>
            {draft && can("write") && isCt && (
              <Button variant="outline" disabled={busy} onClick={() => prefill.mutate()}>
                {prefill.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <BookDown aria-hidden />}
                {t("workpapers.prefillLosses")}
              </Button>
            )}
            {draft && can("write") && w.kind === "lead_schedule" && (
              <Button variant="outline" disabled={busy} onClick={() => reloadLeads.mutate()}>
                {reloadLeads.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
                {t("workpapers.reloadLeads")}
              </Button>
            )}
            {draft && can("write") && (
              <Button variant="accent" disabled={busy} onClick={() => compute.mutate()}>
                {compute.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Calculator aria-hidden />}
                {t("workpapers.compute")}
              </Button>
            )}
            {draft && can("write") && audit && !w.prepared_at && (
              <Button variant="outline" disabled={busy || !w.computed_at} onClick={() => prepare.mutate()}>
                {prepare.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <UserCheck aria-hidden />}
                {t("workpapers.markPrepared")}
              </Button>
            )}
            {draft && can("decide") && (
              <Button variant="default" disabled={busy || !w.computed_at || (audit && !w.prepared_at)} onClick={() => setConfirmSignOff(true)}>
                <Signature aria-hidden />
                {t("workpapers.signOff")}
              </Button>
            )}
            {!draft && can("decide") && isCt && (
              <Button variant="outline" disabled={busy} onClick={() => setConfirmPost(true)}>
                <BookUp aria-hidden />
                {t("workpapers.postLosses")}
              </Button>
            )}
            {!draft && can("decide") && (
              <Button variant="outline" disabled={busy} onClick={() => setReopenOpen(true)}>
                <RotateCcw aria-hidden />
                {t("workpapers.reopen")}
              </Button>
            )}
          </>
        }
      />
      <div className="space-y-5">
        <p className="text-xs leading-relaxed text-slate-500">{t("directTax.indicationNote")}</p>
        <UnverifiedWarnings warnings={w.warnings} />
        <UnverifiedWarnings warnings={postWarnings} />
        <Card className="px-5 py-4">
          <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <Meta label={t("workpapers.period")}>
              {formatDate(w.period_start, i18n.language)} – {formatDate(w.period_end, i18n.language)}
            </Meta>
            <Meta label={t("workpapers.currency")}>{w.currency}</Meta>
            <Meta label={t("directTax.rulesPrefix")}>
              <code dir="ltr" className="font-mono text-xs">
                {w.rules_prefix}
              </code>
            </Meta>
            <Meta label={t("workpapers.computedAt")}>{w.computed_at ? formatDate(w.computed_at, i18n.language, true) : t("workpapers.notComputed")}</Meta>
            {audit && (
              <Meta label={t("workpapers.preparedBy")}>
                {w.prepared_at ? `${w.prepared_by_name ?? "—"} · ${formatDate(w.prepared_at, i18n.language, true)}` : t("workpapers.notPrepared")}
              </Meta>
            )}
            <Meta label={t("workpapers.calcVersion")}>
              <code dir="ltr" className="font-mono text-xs">
                {w.calc_version ?? "—"}
              </code>
            </Meta>
            <Meta label={t("workpapers.resultHash")}>
              <code dir="ltr" className="font-mono text-xs" title={w.result_hash ?? undefined}>
                {w.result_hash ? w.result_hash.slice(0, 16) : "—"}
              </code>
            </Meta>
          </dl>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>{t("workpapers.inputs")}</CardTitle>
              <CardDescription>{draft ? t("workpapers.inputsHint") : t("workpapers.inputsLocked")}</CardDescription>
            </div>
            {draft && can("write") && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditing(null);
                  setInputOpen(true);
                }}
              >
                <Plus aria-hidden /> {t("workpapers.addInput")}
              </Button>
            )}
          </CardHeader>
          {manual.length === 0 ? (
            <EmptyState icon={FileStack} title={t("workpapers.noInputs")} description={t("workpapers.noInputsHint")} />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("workpapers.label")}</TH>
                  <TH>{t("workpapers.category")}</TH>
                  <TH className="text-end">{t("workpapers.value")}</TH>
                  <TH>{t("workpapers.evidence")}</TH>
                  {draft && can("write") && <TH className="w-24">{t("common.actions")}</TH>}
                </tr>
              </THead>
              <TBody>
                {manual.map((l) => (
                  <TR key={l.id}>
                    <TD className="align-top">
                      <span className="font-medium text-navy-900">{l.label}</span>
                      <code dir="ltr" className="mt-0.5 block font-mono text-[11px] text-slate-400">
                        {l.line_key}
                      </code>
                      {l.note && <p className="mt-0.5 text-xs text-slate-500">{l.note}</p>}
                    </TD>
                    <TD className="align-top text-[13px] text-slate-600">{t(`workpaperCategory.${l.category}`, { defaultValue: l.category })}</TD>
                    <TD className="whitespace-nowrap text-end align-top">
                      {l.amount != null ? <Amount value={l.amount} /> : <LineValue value={l.value} />}
                    </TD>
                    <TD className="max-w-64 align-top text-xs text-slate-500">
                      {l.evidence.length === 0 ? "—" : l.evidence.map((e, i) => <p key={i}>{evidenceLabel(e)}</p>)}
                    </TD>
                    {draft && can("write") && (
                      <TD className="align-top">
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={t("workpapers.editNamed", { name: l.label })}
                            onClick={() => {
                              setEditing(l);
                              setInputOpen(true);
                            }}
                          >
                            <Pencil aria-hidden />
                          </Button>
                          <Button variant="ghost" size="icon-sm" aria-label={t("workpapers.removeNamed", { name: l.label })} onClick={() => setRemoving(l)}>
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
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{t("workpapers.results")}</CardTitle>
            <CardDescription>{t("workpapers.resultsHint")}</CardDescription>
          </CardHeader>
          {computed.length === 0 ? (
            <EmptyState icon={Calculator} title={t("workpapers.notComputedYet")} description={t("workpapers.notComputedHint")} />
          ) : (
            sections.map((s) => (
              <section key={s} aria-label={t(`workpaperSection.${s}`, { defaultValue: s })}>
                <h3 className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  {t(`workpaperSection.${s}`, { defaultValue: s })}
                </h3>
                <ul>
                  {computed
                    .filter((l) => l.section === s)
                    .map((l) => (
                      <ExplainedLine
                        key={l.id}
                        label={l.label}
                        value={l.amount != null ? <Amount value={l.amount} currency={w.currency} /> : <LineValue value={l.value} />}
                        formulaId={l.formula_id}
                        steps={l.explanation}
                        rules={l.rule_snapshots}
                      />
                    ))}
                </ul>
              </section>
            ))
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{t("workpapers.snapshots")}</CardTitle>
            <CardDescription>{t("workpapers.snapshotsHint")}</CardDescription>
          </CardHeader>
          {w.snapshots.length === 0 ? (
            <EmptyState icon={Signature} title={t("workpapers.noSnapshots")} />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("workpapers.version")}</TH>
                  <TH>{t("workpapers.signedOffBy")}</TH>
                  <TH>{t("workpapers.resultHash")}</TH>
                  <TH>{t("workpapers.export")}</TH>
                </tr>
              </THead>
              <TBody>
                {w.snapshots.map((s) => (
                  <TR key={s.version}>
                    <TD className="font-medium text-navy-900">v{s.version}</TD>
                    <TD className="text-[13px] text-slate-600">
                      {s.signed_off_by_name ?? "—"}
                      <span className="block text-xs text-slate-400">{formatDate(s.signed_off_at, i18n.language, true)}</span>
                    </TD>
                    <TD>
                      <code dir="ltr" className="font-mono text-xs text-slate-600" title={s.result_hash ?? undefined}>
                        {s.result_hash ? s.result_hash.slice(0, 16) : "—"}
                      </code>
                    </TD>
                    <TD>
                      <SnapshotLinks workpaperId={w.id} version={s.version} />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>

      <InputDialog workpaper={w} line={editing} open={inputOpen} onOpenChange={setInputOpen} />
      <ReopenDialog workpaper={w} open={reopenOpen} onOpenChange={setReopenOpen} />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("workpapers.removeTitle")}
        description={t("workpapers.removeDescription", { name: removing?.label ?? "" })}
        confirmLabel={t("common.delete")}
        destructive
        busy={removeInput.isPending}
        onConfirm={() => removing && removeInput.mutate(removing.line_key)}
      />
      <ConfirmDialog
        open={confirmSignOff}
        onOpenChange={setConfirmSignOff}
        title={t("workpapers.signOffTitle")}
        description={w.warnings.length > 0 ? t("workpapers.signOffUnverified") : t("workpapers.signOffDescription")}
        confirmLabel={t("workpapers.signOff")}
        busy={signOff.isPending}
        onConfirm={() => signOff.mutate()}
      />
      <ConfirmDialog
        open={confirmPost}
        onOpenChange={setConfirmPost}
        title={t("workpapers.postTitle")}
        description={t("workpapers.postDescription")}
        confirmLabel={t("workpapers.postLosses")}
        busy={post.isPending}
        onConfirm={() => post.mutate()}
      />
    </>
  );
}
