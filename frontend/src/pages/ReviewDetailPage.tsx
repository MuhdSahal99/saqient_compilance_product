import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  AlertTriangle,
  BadgeCheck,
  BookOpen,
  Building,
  CalendarDays,
  CalendarRange,
  Check,
  CheckCircle2,
  CircleDot,
  Clock,
  Cpu,
  FileCheck2,
  FileCode,
  FilePlus,
  FileText,
  Info,
  ListChecks,
  Loader2,
  MousePointerClick,
  Play,
  Quote,
  RotateCcw,
  Scale,
  SearchCheck,
  Sparkles,
  Table2,
  Unlock,
} from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import { isQuoteEvidence } from "@/lib/types";
import type { CheckResult, Evidence, Finding, FindingStatus, Job, Page, Report, Review, Severity, SourceBlock } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
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
  OcrBadge,
  OutcomeBadge,
  PageHeader,
  ProgressBar,
  ReviewStatusBadge,
  SeverityBadge,
  SyntheticBadge,
} from "@/components/common";
import { anyEvidenceLocation, evidenceLocation } from "@/lib/evidence";
import { FindingPanel } from "@/components/finding-panel";
import { ReportLinks } from "@/components/report-links";
import { AISuggestionsPanel, useAISuggestions } from "@/components/ai-suggestions";

type Tab = "findings" | "ai" | "results" | "reports";

function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

function DocumentPanel({
  versionId,
  highlight,
  className,
}: {
  versionId: string;
  highlight: { blockIds: Set<string>; focus?: string };
  className?: string;
}) {
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
    <Card className={cn("flex flex-col overflow-hidden", className)}>
      <CardHeader className="flex-row items-center justify-between gap-3 py-3">
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="size-4 text-slate-400" aria-hidden />
          {t("reviewDetail.document")}
        </CardTitle>
        {highlight.blockIds.size > 0 && (
          <span className="flex items-center gap-1.5 text-xs text-slate-500">
            <span className="size-2 rounded-sm bg-amber-300" aria-hidden />
            {t("reviewDetail.highlighted", { count: highlight.blockIds.size })}
          </span>
        )}
      </CardHeader>
      <div ref={containerRef} className="flex-1 overflow-y-auto bg-slate-50/50 px-4 py-4 sm:px-6">
        {blocks.isLoading && <LoadingState rows={6} />}
        {blocks.isError && <ErrorState error={blocks.error} onRetry={() => void blocks.refetch()} />}
        <div className="mx-auto max-w-2xl space-y-0.5 rounded-lg bg-white px-4 py-4 shadow-xs ring-1 ring-slate-200/70 sm:px-6">
          {blocks.data?.items.map((b) => {
            const pageBreak = b.page_number !== null && b.page_number !== lastPage;
            lastPage = b.page_number;
            const hit = highlight.blockIds.has(b.id);
            return (
              <div key={b.id}>
                {pageBreak && (
                  <div
                    className="sticky top-0 z-10 -mx-4 my-2 flex items-center gap-3 bg-white/95 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400 backdrop-blur sm:-mx-6 sm:px-6"
                    id={`page-${b.page_number}`}
                  >
                    {t("evidence.page", { page: b.page_number })}
                    <span className="h-px flex-1 bg-slate-100" aria-hidden />
                  </div>
                )}
                <div
                  data-block={b.id}
                  tabIndex={-1}
                  className={cn(
                    "rounded-md px-2 py-1 text-[13.5px] leading-relaxed outline-none transition-colors duration-300",
                    hit ? "bg-amber-100/80 text-slate-900 ring-1 ring-amber-300/70" : "text-slate-600",
                    highlight.focus === b.id && "ring-2 ring-teal-500",
                  )}
                >
                  {b.page_number === null && <span className="me-2 text-[10px] font-medium text-slate-400">{evidenceLocation(b, t)}</span>}
                  {b.is_ocr && <OcrBadge confidence={b.ocr_confidence} />}
                  <span className="whitespace-pre-wrap" dir="auto">
                    {b.text}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
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
    enabled: open && !!review.document_version_id,
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
          {review.document_version_id && (
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
          )}
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
  const aiSuggestions = useAISuggestions(reviewId, !!r);
  // AI suggestions read document text, so a dataset-only review never offers them.
  const showAI = !!(aiSuggestions.data?.run || (aiSuggestions.data?.available && r?.document_version_id));
  const aiPending = (aiSuggestions.data?.suggestions ?? []).filter(
    (s) => s.status === "pending" && (s.assessment === "not_addressed" || s.assessment === "unclear"),
  ).length;
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

  const items = useMemo(() => findings.data?.items ?? [], [findings.data]);
  // On wide screens the first finding opens by default so the workspace never starts empty.
  const wide = useMediaQuery("(min-width: 1280px)");
  const selected = items.find((f) => f.id === selectedId) ?? (wide && !selectedId ? (items[0] ?? null) : null);
  const highlight = useMemo(
    () => ({
      blockIds: new Set((selected?.evidence ?? []).flatMap((e) => (isQuoteEvidence(e) ? [e.block_id] : []))),
      focus: focusBlock,
    }),
    [selected, focusBlock],
  );
  const undecided = (r?.finding_counts.proposed ?? 0) + (r?.finding_counts.in_review ?? 0);

  const select = useCallback(
    (f: Finding, replace = false) => {
      const first = f.evidence[0];
      setFocusBlock(first && isQuoteEvidence(first) ? first.block_id : undefined);
      setParams(
        (p) => {
          p.set("finding", f.id);
          return p;
        },
        { replace },
      );
    },
    [setParams],
  );

  // j / k move between findings when focus is not in a form field.
  useEffect(() => {
    if (tab !== "findings" || items.length === 0) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const dir = e.key === "j" ? 1 : e.key === "k" ? -1 : 0;
      if (!dir) return;
      const idx = items.findIndex((f) => f.id === selected?.id);
      const next = items[Math.min(items.length - 1, Math.max(0, idx + dir))];
      if (next && next.id !== selected?.id) {
        e.preventDefault();
        select(next, true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, items, selected, select]);
  const setTab = (next: Tab) =>
    setParams((p) => {
      p.set("tab", next);
      return p;
    });
  const openFinding = (id: string) => {
    setStatusFilter("");
    setParams((p) => {
      p.set("tab", "findings");
      p.set("finding", id);
      return p;
    });
  };

  if (review.isLoading) return <LoadingState />;
  if (review.isError || !r) return <ErrorState error={review.error} onRetry={() => void review.refetch()} />;
  const job = r.latest_run?.job;
  const warnings = r.latest_run?.warnings ?? [];

  const totalFindings = Object.values(r.finding_counts).reduce((a, n) => a + (n ?? 0), 0);
  const decided = totalFindings - undecided;
  const stage = r.status === "signed_off" ? 3 : r.status === "in_review" ? (undecided === 0 ? 2 : 1) : 0;

  return (
    <>
      <PageHeader
        title={r.title}
        crumbs={[{ label: t("nav.reviews"), to: "/reviews" }, { label: r.title }]}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <ReviewStatusBadge status={r.status} />
            {(r.is_demo || r.checklist_kind === "synthetic_demo") && <SyntheticBadge />}
            {r.document_id && (
              <Link
                to={`/documents/${r.document_id}`}
                className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200 transition-colors hover:text-navy-900 hover:ring-slate-300"
              >
                <FileText className="size-3.5 text-slate-400" aria-hidden />
                {r.document_title} v{r.document_version_number}
              </Link>
            )}
            {r.datasets.map((d) => (
              <Link
                key={d.dataset_version_id}
                to={`/datasets/${d.dataset_id}`}
                className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200 transition-colors hover:text-navy-900 hover:ring-slate-300"
              >
                <Table2 className="size-3.5 text-slate-400" aria-hidden />
                {d.dataset_name} v{d.version_number}
              </Link>
            ))}
            {r.entity_name && (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
                <Building className="size-3.5 text-slate-400" aria-hidden />
                {r.entity_name}
              </span>
            )}
            {r.tax_period_start && r.tax_period_end && (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
                <CalendarRange className="size-3.5 text-slate-400" aria-hidden />
                {t("reviews.taxPeriodChip", {
                  start: formatDate(r.tax_period_start, i18n.language),
                  end: formatDate(r.tax_period_end, i18n.language),
                })}
              </span>
            )}
            {(r.einvoice_count ?? 0) > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
                <FileCode className="size-3.5 text-slate-400" aria-hidden />
                {t("reviews.einvoiceCount", { count: r.einvoice_count })}
              </span>
            )}
            {r.rule_pack_name && (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
                <Scale className="size-3.5 text-slate-400" aria-hidden />
                {r.rule_pack_name} v{r.rule_pack_version_number}
              </span>
            )}
            {r.as_of_date && (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
                <CalendarDays className="size-3.5 text-slate-400" aria-hidden />
                {t("reviews.asOf", { date: formatDate(r.as_of_date, i18n.language) })}
              </span>
            )}
            <span className="inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
              <ListChecks className="size-3.5 text-slate-400" aria-hidden />
              {r.checklist_name} v{r.checklist_version_number}
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
              <Button
                variant="accent"
                onClick={() => setConfirmSignoff(true)}
                disabled={undecided > 0}
                title={undecided > 0 ? t("reviewDetail.signoffBlocked", { count: undecided }) : undefined}
              >
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

      <Card className="mb-6 overflow-hidden">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="p-5">
            <ol className="flex items-center gap-2" aria-label={t("reviewDetail.progress")}>
              {(["checks", "decide", "signoff", "report"] as const).map((k, i) => {
                const done = i < stage || (i === 3 && stage === 3);
                const current = i === stage && !(i === 3 && stage === 3);
                return (
                  <li key={k} className="flex min-w-0 flex-1 items-center gap-2">
                    <span
                      className={cn(
                        "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1 transition-colors",
                        done && "bg-teal-600 text-white ring-teal-600",
                        current && "bg-teal-50 text-teal-700 ring-teal-300",
                        !done && !current && "bg-white text-slate-400 ring-slate-200",
                      )}
                      aria-current={current ? "step" : undefined}
                    >
                      {done ? <Check className="size-3.5" aria-hidden /> : i + 1}
                    </span>
                    <span
                      className={cn(
                        "hidden truncate text-[13px] font-medium sm:block",
                        done || current ? "text-navy-900" : "text-slate-400",
                      )}
                    >
                      {t(`reviewDetail.step.${k}`)}
                    </span>
                    {i < 3 && <span className={cn("h-px min-w-4 flex-1", done ? "bg-teal-500" : "bg-slate-200")} aria-hidden />}
                  </li>
                );
              })}
            </ol>
            <div className="mt-5 flex flex-wrap gap-x-6 gap-y-1.5 text-[13px] text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <Cpu className="size-3.5 text-slate-400" aria-hidden />
                {t("reviewDetail.engine")}: <strong className="font-medium text-slate-700">{r.latest_run?.engine_mode ?? "—"}</strong>
                <span className="text-slate-400">{r.latest_run?.engine_version}</span>
              </span>
              {r.latest_run?.finished_at && (
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="size-3.5 text-slate-400" aria-hidden />
                  {t("reviewDetail.lastRun")}: {formatDate(r.latest_run.finished_at, i18n.language, true)}
                </span>
              )}
              {r.signed_off_at && (
                <span className="inline-flex items-center gap-1.5 text-emerald-700">
                  <BadgeCheck className="size-3.5" aria-hidden />
                  {t("reviewDetail.signedOffBy", { name: r.signed_off_by_name, date: formatDate(r.signed_off_at, i18n.language, true) })}
                </span>
              )}
            </div>
          </div>
          <div className="border-t border-slate-100 bg-slate-50/60 p-5 lg:border-s lg:border-t-0">
            <div className="flex items-baseline justify-between">
              <p className="text-[13px] font-medium text-slate-600">{t("reviewDetail.decisionsRecorded")}</p>
              <p className="text-sm font-semibold tabular-nums text-navy-900">
                {decided}
                <span className="font-normal text-slate-400"> / {totalFindings}</span>
              </p>
            </div>
            <ProgressBar className="mt-2" value={totalFindings ? (100 * decided) / totalFindings : 0} label={t("reviewDetail.decisionsRecorded")} />
            <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
              {(
                [
                  ["awaiting", undecided, "text-amber-600"],
                  ["confirmed", (r.finding_counts.confirmed ?? 0) + (r.finding_counts.remediation_in_progress ?? 0) + (r.finding_counts.ready_for_rereview ?? 0), "text-red-600"],
                  ["closed", (r.finding_counts.dismissed ?? 0) + (r.finding_counts.resolved ?? 0) + (r.finding_counts.accepted_risk ?? 0), "text-slate-600"],
                ] as const
              ).map(([k, n, cls]) => (
                <div key={k} className="rounded-lg bg-white px-2 py-2 ring-1 ring-slate-200/70">
                  <dd className={cn("text-lg font-semibold tabular-nums", cls)}>{n}</dd>
                  <dt className="text-[11px] text-slate-500">{t(`reviewDetail.count.${k}`)}</dt>
                </div>
              ))}
            </dl>
          </div>
        </div>
        {(running || (job && (job.status === "failed" || job.status === "cancelled")) || warnings.length > 0) && (
          <div className="space-y-3 border-t border-slate-100 px-5 py-4 text-sm">
            {running && job && (
              <div className="space-y-2 rounded-lg border border-teal-200 bg-teal-50/60 px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 font-medium text-teal-800">
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                    {t("reviewDetail.running")}
                  </span>
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
              <p role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-red-800">
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
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900">
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
          </div>
        )}
        <p className="flex items-start gap-2 border-t border-slate-100 bg-slate-50/40 px-5 py-2.5 text-xs text-slate-500">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden />
          {t("reviewDetail.disclaimer")}
        </p>
      </Card>

      <Tabs
        className="mb-5"
        label={t("reviewDetail.sections")}
        value={tab}
        onChange={setTab}
        items={[
          { key: "findings", label: t("reviewDetail.tab.findings"), count: totalFindings },
          ...(showAI ? [{ key: "ai" as const, label: t("reviewDetail.tab.ai"), count: aiPending || undefined }] : []),
          { key: "results", label: t("reviewDetail.tab.results") },
          { key: "reports", label: t("reviewDetail.tab.reports"), count: reports.data?.total },
        ]}
      />

      {tab === "findings" &&
        (running ? (
          <Card>
            <LoadingState label={t("reviewDetail.running")} />
          </Card>
        ) : (
          <div className="grid items-start gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
            <Card className="overflow-hidden xl:sticky xl:top-20">
              <div className="space-y-3 border-b border-slate-100 p-4">
                <p
                  className={cn(
                    "flex items-center gap-2 text-[13px] font-medium",
                    undecided > 0 ? "text-amber-700" : "text-emerald-700",
                  )}
                >
                  {undecided > 0 ? <CircleDot className="size-4" aria-hidden /> : <CheckCircle2 className="size-4" aria-hidden />}
                  {undecided > 0 ? t("reviewDetail.undecided", { count: undecided }) : t("reviewDetail.allDecided")}
                </p>
                <Select
                  aria-label={t("findings.statusFilter")}
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as FindingStatus | "open" | "")}
                >
                  <option value="">{t("findings.allStatuses")}</option>
                  <option value="open">{t("findings.needsDecision")}</option>
                  {(["confirmed", "dismissed", "accepted_risk", "remediation_in_progress", "ready_for_rereview", "resolved"] as const).map((s) => (
                    <option key={s} value={s}>
                      {t(`findingStatus.${s}`)}
                    </option>
                  ))}
                </Select>
              </div>
              {findings.isLoading && <LoadingState />}
              {findings.isError && <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />}
              {findings.data && items.length === 0 && (
                <EmptyState icon={SearchCheck} title={t("reviewDetail.noFindings")} description={t("reviewDetail.noFindingsHint")} />
              )}
              {items.length > 0 && (
                <ul className="max-h-[calc(100vh-16rem)] divide-y divide-slate-100 overflow-y-auto" aria-label={t("nav.findings")}>
                  {items.map((f) => {
                    const active = f.id === selected?.id;
                    return (
                      <li key={f.id}>
                        <button
                          type="button"
                          onClick={() => select(f)}
                          aria-current={active}
                          className={cn(
                            "relative flex w-full flex-col gap-2 px-4 py-3 text-start transition-colors",
                            active ? "bg-teal-50/70" : "hover:bg-slate-50",
                          )}
                        >
                          <span
                            className={cn("absolute inset-y-0 start-0 w-[3px]", active ? "bg-teal-500" : "bg-transparent")}
                            aria-hidden
                          />
                          <span className="line-clamp-2 text-[13.5px] font-medium leading-snug text-navy-900">{f.title}</span>
                          <span className="flex flex-wrap items-center gap-1.5">
                            <SeverityBadge severity={f.severity as Severity} />
                            <FindingStatusBadge status={f.status} />
                            {f.ai_suggestion_id && (
                              <span className="inline-flex items-center gap-1 text-[11px] font-medium text-violet-600">
                                <Sparkles className="size-3" aria-hidden />
                                {t("ai.badge")}
                              </span>
                            )}
                            {f.evidence.length > 0 && (
                              <span className="inline-flex items-center gap-1 text-[11px] text-slate-400">
                                <Quote className="size-3" aria-hidden />
                                {f.evidence.length}
                              </span>
                            )}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
            <div className="min-w-0">
              {selected ? (
                <div className="grid items-start gap-5 2xl:grid-cols-2">
                  <Card className="p-5 sm:p-6" key={selected.id}>
                    <FindingPanel finding={selected} onLocate={(e: Evidence) => setFocusBlock(e.block_id)} />
                  </Card>
                  {r.document_version_id && (
                    <DocumentPanel
                      versionId={r.document_version_id}
                      highlight={highlight}
                      className="max-h-[36rem] 2xl:sticky 2xl:top-20 2xl:max-h-[calc(100vh-6rem)]"
                    />
                  )}
                </div>
              ) : (
                items.length > 0 && (
                  <Card className="border-dashed shadow-none">
                    <EmptyState icon={MousePointerClick} title={t("reviewDetail.selectFinding")} />
                  </Card>
                )
              )}
            </div>
          </div>
        ))}

      {tab === "ai" && showAI && <AISuggestionsPanel review={r} onOpenFinding={openFinding} />}

      {tab === "results" && (
        <Card className="overflow-hidden">
          {results.isLoading && <LoadingState />}
          {results.isError && <ErrorState error={results.error} onRetry={() => void results.refetch()} />}
          {results.data?.length === 0 && <EmptyState icon={SearchCheck} title={t("reviewDetail.noResults")} />}
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
                    <TD className="align-top">
                      <code className="me-1.5 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{c.requirement_code}</code>
                      <span className="font-medium text-navy-900">{c.requirement_title}</span>
                    </TD>
                    <TD className="align-top">
                      <div className="flex flex-col items-start gap-1">
                        <OutcomeBadge outcome={c.outcome} />
                        {c.needs_attention && <span className="text-[11px] font-medium text-amber-700">{t("reviewDetail.needsAttention")}</span>}
                      </div>
                    </TD>
                    <TD className="align-top text-xs leading-relaxed text-slate-600">{c.message}</TD>
                    <TD className="align-top text-xs text-slate-500">{c.evidence.map((e) => anyEvidenceLocation(e, t)).join("; ") || "—"}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
          <p className="flex items-start gap-2 border-t border-slate-100 bg-slate-50/50 px-5 py-3 text-xs text-slate-500">
            <Info className="mt-px size-3.5 shrink-0" aria-hidden />
            {t("reviewDetail.outcomeNote")}
          </p>
        </Card>
      )}

      {tab === "reports" && (
        <Card className="overflow-hidden">
          {reports.data?.items.length === 0 && (
            <EmptyState icon={FileText} title={t("reports.noneForReview")} description={t("reports.noneForReviewHint")} />
          )}
          <ul className="divide-y divide-slate-100">
            {reports.data?.items.map((rep) => (
              <li key={rep.id} className="flex flex-wrap items-center justify-between gap-4 px-5 py-4">
                <div className="flex items-center gap-3">
                  <span className="flex size-10 items-center justify-center rounded-xl bg-emerald-50 ring-1 ring-emerald-100">
                    <FileCheck2 className="size-5 text-emerald-600" aria-hidden />
                  </span>
                  <div className="text-sm">
                    <p className="font-semibold text-navy-900">{t("reports.version", { n: rep.version })}</p>
                    <p className="text-xs text-slate-500">
                      {t("reviewDetail.signedOffBy", { name: rep.signed_off_by_name, date: formatDate(rep.signed_off_at, i18n.language, true) })} ·{" "}
                      {t("reports.findingCount", { count: rep.finding_count })}
                    </p>
                  </div>
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
