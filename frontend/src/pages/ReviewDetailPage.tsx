import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertTriangle, FileCheck2, FilePlus, Play, RotateCcw, Unlock } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { CheckResult, Evidence, Finding, FindingStatus, Job, Page, Report, Review, Severity, SourceBlock } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  errorMessage,
  FindingStatusBadge,
  LoadingState,
  OutcomeBadge,
  PageHeader,
  ProgressBar,
  ReviewStatusBadge,
  SeverityBadge,
  SyntheticBadge,
} from "@/components/common";
import { evidenceLocation } from "@/components/evidence";
import { FindingPanel } from "@/components/finding-panel";
import { ReportLinks } from "@/components/report-links";

type Tab = "findings" | "results" | "reports";

function DocumentPanel({ versionId, highlight }: { versionId: string; highlight: { blockIds: Set<string>; focus?: string } }) {
  const { t } = useTranslation();
  const blocks = useQuery({
    queryKey: ["blocks", versionId, ""],
    queryFn: () => api<Page<SourceBlock>>(`/document-versions/${versionId}/blocks${qs({ page_size: 500 })}`),
  });
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!highlight.focus || !containerRef.current) return;
    const el = containerRef.current.querySelector(`[data-block="${highlight.focus}"]`);
    if (el instanceof HTMLElement) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      el.focus({ preventScroll: true });
    }
  }, [highlight.focus, blocks.data]);

  let lastPage: number | null = null;
  return (
    <Card className="flex max-h-[44rem] flex-col">
      <CardHeader>
        <CardTitle>{t("reviewDetail.document")}</CardTitle>
      </CardHeader>
      <div ref={containerRef} className="flex-1 space-y-1 overflow-y-auto px-5 py-3">
        {blocks.isLoading && <LoadingState />}
        {blocks.isError && <ErrorState error={blocks.error} onRetry={() => void blocks.refetch()} />}
        {blocks.data?.items.map((b) => {
          const pageBreak = b.page_number !== null && b.page_number !== lastPage;
          lastPage = b.page_number;
          const hit = highlight.blockIds.has(b.id);
          return (
            <div key={b.id}>
              {pageBreak && (
                <div className="sticky top-0 z-10 my-2 bg-white/90 py-1 text-xs font-semibold text-slate-500" id={`page-${b.page_number}`}>
                  {t("evidence.page", { page: b.page_number })}
                </div>
              )}
              <div
                data-block={b.id}
                tabIndex={-1}
                className={cn(
                  "rounded px-2 py-1 text-sm outline-none transition-colors",
                  hit ? "bg-amber-100 ring-1 ring-amber-300" : "text-slate-700",
                  highlight.focus === b.id && "ring-2 ring-teal-600",
                )}
              >
                {b.page_number === null && <span className="me-2 text-[10px] text-slate-400">{evidenceLocation(b, t)}</span>}
                <span className="whitespace-pre-wrap" dir="auto">
                  {b.text}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

const reopenSchema = z.object({ reason: z.string().trim().min(5).max(2000) });

function ReopenDialog({ review, open, onOpenChange }: { review: Review; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<z.infer<typeof reopenSchema>>({ resolver: zodResolver(reopenSchema), defaultValues: { reason: "" } });
  const reopen = useMutation({
    mutationFn: (reason: string) => api<Review>(`/reviews/${review.id}/reopen`, { json: { reason } }),
    onSuccess: (r) => {
      qc.setQueryData(["review", review.id], r);
      void qc.invalidateQueries({ queryKey: ["findings"] });
      toast.success(t("reviewDetail.reopened"));
      form.reset();
      onOpenChange(false);
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{t("reviewDetail.reopenTitle")}</DialogTitle>
        <DialogDescription>{t("reviewDetail.reopenDescription")}</DialogDescription>
        <form className="mt-4 space-y-2" onSubmit={form.handleSubmit((v) => reopen.mutate(v.reason))}>
          <Label htmlFor="reopen-reason">{t("reviewDetail.reason")}</Label>
          <Textarea id="reopen-reason" aria-invalid={!!form.formState.errors.reason} {...form.register("reason")} />
          <FieldError message={form.formState.errors.reason ? t("reviewDetail.reasonRequired") : undefined} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={reopen.isPending}>
              {t("reviewDetail.reopen")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const manualSchema = z.object({
  title: z.string().trim().min(1).max(300),
  description: z.string().max(5000),
  severity: z.enum(["low", "medium", "high", "critical"]),
  block_id: z.string(),
});

function ManualFindingDialog({ review, open, onOpenChange }: { review: Review; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const blocks = useQuery({
    queryKey: ["blocks", review.document_version_id, ""],
    queryFn: () => api<Page<SourceBlock>>(`/document-versions/${review.document_version_id}/blocks${qs({ page_size: 500 })}`),
    enabled: open,
  });
  const form = useForm<z.infer<typeof manualSchema>>({
    resolver: zodResolver(manualSchema),
    defaultValues: { title: "", description: "", severity: "medium", block_id: "" },
  });
  const create = useMutation({
    mutationFn: (v: z.infer<typeof manualSchema>) =>
      api<Finding>(`/reviews/${review.id}/findings`, {
        json: { title: v.title, description: v.description, severity: v.severity, block_ids: v.block_id ? [v.block_id] : [] },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["findings"] });
      void qc.invalidateQueries({ queryKey: ["review", review.id] });
      toast.success(t("reviewDetail.manualCreated"));
      form.reset();
      onOpenChange(false);
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{t("reviewDetail.addManual")}</DialogTitle>
        <form className="mt-4 space-y-3" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="mf-title">{t("findings.titleField")}</Label>
            <Input id="mf-title" aria-invalid={!!form.formState.errors.title} {...form.register("title")} />
            <FieldError message={form.formState.errors.title ? t("upload.titleRequired") : undefined} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mf-sev">{t("findings.severity")}</Label>
            <Select id="mf-sev" {...form.register("severity")}>
              {(["low", "medium", "high", "critical"] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`severity.${s}`)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mf-block">{t("reviewDetail.evidenceBlock")}</Label>
            <Select id="mf-block" {...form.register("block_id")}>
              <option value="">{t("reviewDetail.noEvidenceBlock")}</option>
              {blocks.data?.items.map((b) => (
                <option key={b.id} value={b.id}>
                  {evidenceLocation(b, t)} — {b.text.slice(0, 70)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mf-desc">{t("documents.description")}</Label>
            <Textarea id="mf-desc" rows={3} {...form.register("description")} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {t("reviewDetail.addManual")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}


export function ReviewDetailPage() {
  const { reviewId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab | null) ?? "findings";
  const selectedId = params.get("finding");
  const [statusFilter, setStatusFilter] = useState<FindingStatus | "open" | "">("");
  const [focusBlock, setFocusBlock] = useState<string | undefined>();
  const [confirmSignoff, setConfirmSignoff] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);

  const review = useQuery({
    queryKey: ["review", reviewId],
    queryFn: () => api<Review>(`/reviews/${reviewId}`),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false),
  });
  const r = review.data;
  const running = r?.status === "running";

  const findings = useQuery({
    queryKey: ["findings", "review", reviewId, statusFilter],
    queryFn: () =>
      api<Page<Finding>>(
        `/findings${qs({
          review_id: reviewId,
          status: statusFilter === "open" ? ["proposed", "in_review"] : statusFilter || undefined,
          page_size: 200,
        })}`,
      ),
    enabled: !!r && !running,
  });
  const results = useQuery({
    queryKey: ["results", reviewId, r?.latest_run?.id],
    queryFn: () => api<CheckResult[]>(`/reviews/${reviewId}/results`),
    enabled: !!r && !running && tab === "results",
  });
  const reports = useQuery({
    queryKey: ["reports", reviewId, r?.status],
    queryFn: () => api<Page<Report>>(`/reports${qs({ review_id: reviewId })}`),
    enabled: !!r,
  });

  useEffect(() => {
    if (r && !running) {
      void qc.invalidateQueries({ queryKey: ["findings", "review", reviewId] });
    }
  }, [running, r, qc, reviewId]);

  const rerun = useMutation({
    mutationFn: () => api<Review>(`/reviews/${reviewId}/runs`, { method: "POST" }),
    onSuccess: (data) => qc.setQueryData(["review", reviewId], data),
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const cancelRun = useMutation({
    mutationFn: (jobId: string) => api<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      toast.info(t("jobs.cancelRequested"));
      void review.refetch();
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const signoff = useMutation({
    mutationFn: () => api<Report>(`/reviews/${reviewId}/signoff`, { method: "POST" }),
    onSuccess: () => {
      setConfirmSignoff(false);
      toast.success(t("reviewDetail.signedOffToast"));
      void qc.invalidateQueries({ queryKey: ["review", reviewId] });
      void qc.invalidateQueries({ queryKey: ["reports"] });
      void qc.invalidateQueries({ queryKey: ["findings"] });
      setParams((p) => {
        p.set("tab", "reports");
        return p;
      });
    },
    onError: (e) => {
      setConfirmSignoff(false);
      toast.error(errorMessage(e, t("common.genericError")));
    },
  });

  const items = findings.data?.items ?? [];
  const selected = items.find((f) => f.id === selectedId) ?? null;
  const highlight = useMemo(
    () => ({ blockIds: new Set((selected?.evidence ?? []).map((e) => e.block_id)), focus: focusBlock }),
    [selected, focusBlock],
  );
  const undecided = (r?.finding_counts.proposed ?? 0) + (r?.finding_counts.in_review ?? 0);

  const select = (f: Finding) => {
    setFocusBlock(f.evidence[0]?.block_id);
    setParams((p) => {
      p.set("finding", f.id);
      return p;
    });
  };
  const setTab = (next: Tab) =>
    setParams((p) => {
      p.set("tab", next);
      return p;
    });

  if (review.isLoading) return <LoadingState />;
  if (review.isError || !r) return <ErrorState error={review.error} onRetry={() => void review.refetch()} />;
  const job = r.latest_run?.job;
  const warnings = r.latest_run?.warnings ?? [];

  return (
    <>
      <PageHeader
        title={r.title}
        crumbs={[{ label: t("nav.reviews"), to: "/reviews" }, { label: r.title }]}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <ReviewStatusBadge status={r.status} />
            {(r.is_demo || r.checklist_kind === "synthetic_demo") && <SyntheticBadge />}
            <span>
              {r.document_title} v{r.document_version_number} · {r.checklist_name} v{r.checklist_version_number}
            </span>
          </span>
        }
        actions={
          <>
            {can("write") && r.status !== "signed_off" && !running && (
              <Button variant="outline" onClick={() => setManualOpen(true)}>
                <FilePlus aria-hidden /> {t("reviewDetail.addManual")}
              </Button>
            )}
            {can("write") && r.status !== "signed_off" && !running && (
              <Button variant="outline" disabled={rerun.isPending} onClick={() => rerun.mutate()}>
                <Play aria-hidden /> {t("reviewDetail.rerun")}
              </Button>
            )}
            {can("decide") && r.status === "in_review" && (
              <Button variant="accent" onClick={() => setConfirmSignoff(true)} disabled={undecided > 0} title={undecided > 0 ? t("reviewDetail.signoffBlocked", { count: undecided }) : undefined}>
                <FileCheck2 aria-hidden /> {t("reviewDetail.signoff")}
              </Button>
            )}
            {can("decide") && r.status === "signed_off" && (
              <Button variant="outline" onClick={() => setReopenOpen(true)}>
                <Unlock aria-hidden /> {t("reviewDetail.reopen")}
              </Button>
            )}
          </>
        }
      />

      <Card className="mb-6">
        <CardContent className="space-y-3 text-sm">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-slate-600">
            <span>
              {t("reviewDetail.engine")}: <strong className="font-medium text-slate-800">{r.latest_run?.engine_mode ?? "—"}</strong> ·{" "}
              {r.latest_run?.engine_version}
            </span>
            {r.latest_run?.finished_at && (
              <span>
                {t("reviewDetail.lastRun")}: {formatDate(r.latest_run.finished_at, i18n.language, true)}
              </span>
            )}
            {r.signed_off_at && (
              <span>
                {t("reviewDetail.signedOffBy", { name: r.signed_off_by_name, date: formatDate(r.signed_off_at, i18n.language, true) })}
              </span>
            )}
          </div>
          {running && job && (
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-700">{t("reviewDetail.running")}</span>
                {can("write") && !job.cancel_requested && (
                  <Button size="sm" variant="ghost" onClick={() => cancelRun.mutate(job.id)}>
                    {t("jobs.cancel")}
                  </Button>
                )}
              </div>
              <ProgressBar value={job.progress} label={t("jobs.progress")} />
            </div>
          )}
          {job && (job.status === "failed" || job.status === "cancelled") && (
            <p role="alert" className="flex items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-red-800">
              <span>
                {job.status === "failed" ? t("reviewDetail.runFailed", { error: job.error ?? "" }) : t("reviewDetail.runCancelled")}
              </span>
              {can("write") && r.status !== "signed_off" && (
                <Button size="sm" variant="outline" onClick={() => rerun.mutate()}>
                  <RotateCcw aria-hidden /> {t("common.retry")}
                </Button>
              )}
            </p>
          )}
          {warnings.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
              <p className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="size-4" aria-hidden /> {t("reviewDetail.warnings")}
              </p>
              <ul className="mt-1 list-disc ps-5">
                {warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-slate-500">{t("reviewDetail.disclaimer")}</p>
        </CardContent>
      </Card>

      <div role="tablist" aria-label={t("reviewDetail.sections")} className="mb-4 flex gap-1 border-b border-slate-200">
        {(["findings", "results", "reports"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "-mb-px border-b-2 px-4 py-2 text-sm",
              tab === k ? "border-teal-700 font-medium text-navy-900" : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            {t(`reviewDetail.tab.${k}`)}
            {k === "reports" && reports.data ? ` (${reports.data.total})` : ""}
          </button>
        ))}
      </div>

      {tab === "findings" && (
        <div className="space-y-4">
          {running ? (
            <LoadingState label={t("reviewDetail.running")} />
          ) : (
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
                <p className="text-sm text-slate-600">
                  {undecided > 0 ? t("reviewDetail.undecided", { count: undecided }) : t("reviewDetail.allDecided")}
                </p>
                <Select
                  aria-label={t("findings.statusFilter")}
                  className="w-56"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as FindingStatus | "open" | "")}
                >
                  <option value="">{t("findings.allStatuses")}</option>
                  <option value="open">{t("findings.needsDecision")}</option>
                  {(["confirmed", "dismissed", "accepted_risk", "remediation_in_progress", "ready_for_rereview", "resolved"] as const).map(
                    (s) => (
                      <option key={s} value={s}>
                        {t(`findingStatus.${s}`)}
                      </option>
                    ),
                  )}
                </Select>
              </div>
              {findings.isLoading && <LoadingState />}
              {findings.isError && <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />}
              {findings.data && items.length === 0 && <EmptyState title={t("reviewDetail.noFindings")} description={t("reviewDetail.noFindingsHint")} />}
              {items.length > 0 && (
                <ul className="divide-y divide-slate-100" aria-label={t("nav.findings")}>
                  {items.map((f) => (
                    <li key={f.id}>
                      <button
                        type="button"
                        onClick={() => select(f)}
                        aria-current={f.id === selectedId}
                        className={cn(
                          "flex w-full flex-wrap items-center gap-2 px-4 py-2.5 text-start text-sm hover:bg-slate-50",
                          f.id === selectedId && "bg-teal-50/70",
                        )}
                      >
                        <SeverityBadge severity={f.severity as Severity} />
                        <span className="min-w-0 flex-1 truncate font-medium text-navy-900">{f.title}</span>
                        <FindingStatusBadge status={f.status} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
          {selected && (
            <div className="grid gap-4 lg:grid-cols-2">
              <DocumentPanel versionId={r.document_version_id} highlight={highlight} />
              <Card>
                <CardContent className="py-5">
                  <FindingPanel finding={selected} onLocate={(e: Evidence) => setFocusBlock(e.block_id)} />
                </CardContent>
              </Card>
            </div>
          )}
          {!selected && items.length > 0 && <p className="text-center text-sm text-slate-500">{t("reviewDetail.selectFinding")}</p>}
        </div>
      )}

      {tab === "results" && (
        <Card>
          {results.isLoading && <LoadingState />}
          {results.isError && <ErrorState error={results.error} onRetry={() => void results.refetch()} />}
          {results.data?.length === 0 && <EmptyState title={t("reviewDetail.noResults")} />}
          {results.data && results.data.length > 0 && (
            <Table>
              <THead>
                <tr>
                  <TH>{t("reviewDetail.requirement")}</TH>
                  <TH>{t("reviewDetail.outcome")}</TH>
                  <TH>{t("reviewDetail.detail")}</TH>
                  <TH>{t("findings.evidence")}</TH>
                </tr>
              </THead>
              <TBody>
                {results.data.map((c) => (
                  <TR key={c.id}>
                    <TD>
                      <code className="text-xs">{c.requirement_code}</code> {c.requirement_title}
                    </TD>
                    <TD>
                      <OutcomeBadge outcome={c.outcome} />
                      {c.needs_attention && <span className="ms-1 text-xs text-amber-700">{t("reviewDetail.needsAttention")}</span>}
                    </TD>
                    <TD className="text-xs">{c.message}</TD>
                    <TD className="text-xs">{c.evidence.map((e) => evidenceLocation(e, t)).join(", ") || "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
          <p className="px-4 py-3 text-xs text-slate-500">{t("reviewDetail.outcomeNote")}</p>
        </Card>
      )}

      {tab === "reports" && (
        <Card>
          {reports.data?.items.length === 0 && <EmptyState title={t("reports.noneForReview")} description={t("reports.noneForReviewHint")} />}
          <ul className="divide-y divide-slate-100">
            {reports.data?.items.map((rep) => (
              <li key={rep.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="text-sm">
                  <p className="font-medium text-navy-900">{t("reports.version", { n: rep.version })}</p>
                  <p className="text-xs text-slate-500">
                    {t("reviewDetail.signedOffBy", { name: rep.signed_off_by_name, date: formatDate(rep.signed_off_at, i18n.language, true) })} ·{" "}
                    {t("reports.findingCount", { count: rep.finding_count })}
                  </p>
                </div>
                <ReportLinks report={rep} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      <ConfirmDialog
        open={confirmSignoff}
        onOpenChange={setConfirmSignoff}
        title={t("reviewDetail.signoffTitle")}
        description={t("reviewDetail.signoffDescription")}
        confirmLabel={t("reviewDetail.signoff")}
        busy={signoff.isPending}
        onConfirm={() => signoff.mutate()}
      />
      <ReopenDialog review={r} open={reopenOpen} onOpenChange={setReopenOpen} />
      <ManualFindingDialog review={r} open={manualOpen} onOpenChange={setManualOpen} />
    </>
  );
}
