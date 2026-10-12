import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Check, FlaskConical, Info, Loader2, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { AIAssessment, AISuggestion, AISuggestions, Finding, Review } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { cn, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { EmptyState, ErrorState, errorMessage, LoadingState, ProgressBar, SeverityBadge } from "@/components/common";
import { EvidenceQuote } from "@/components/evidence";

const POSSIBLE_GAPS: AIAssessment[] = ["not_addressed", "unclear"];

const ASSESSMENT_TONE: Record<AIAssessment, "amber" | "neutral" | "green" | "red"> = {
  not_addressed: "amber",
  unclear: "neutral",
  addressed: "green",
  invalid_output: "red",
};

// eslint-disable-next-line react-refresh/only-export-components
export function aiSuggestionsKey(reviewId: string) {
  return ["ai-suggestions", reviewId] as const;
}

/** Latest AI suggestion run for a review. Polls while the run is in progress. */
// eslint-disable-next-line react-refresh/only-export-components
export function useAISuggestions(reviewId: string, enabled = true) {
  return useQuery({
    queryKey: aiSuggestionsKey(reviewId),
    queryFn: () => api<AISuggestions>(`/reviews/${reviewId}/ai-suggestions`),
    enabled,
    refetchInterval: (q) => {
      const status = q.state.data?.run?.job.status;
      return status === "queued" || status === "running" ? 1500 : false;
    },
  });
}

export function MockNotice({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <p className={cn("flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900", className)}>
      <FlaskConical className="mt-px size-3.5 shrink-0" aria-hidden />
      {t("ai.mockNotice")}
    </p>
  );
}

function SuggestionCard({
  suggestion,
  review,
  onOpenFinding,
}: {
  suggestion: AISuggestion;
  review: Review;
  onOpenFinding: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const done = () => {
    void qc.invalidateQueries({ queryKey: aiSuggestionsKey(review.id) });
    void qc.invalidateQueries({ queryKey: ["findings"] });
    void qc.invalidateQueries({ queryKey: ["review", review.id] });
  };
  const accept = useMutation({
    mutationFn: () => api<Finding>(`/ai-suggestions/${suggestion.id}/accept`, { json: {} }),
    onSuccess: () => {
      toast.success(t("ai.acceptedToast"));
      done();
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const reject = useMutation({
    mutationFn: () => api<AISuggestion>(`/ai-suggestions/${suggestion.id}/reject`, { json: {} }),
    onSuccess: () => {
      toast.success(t("ai.rejectedToast"));
      done();
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const open = suggestion.status === "pending" && review.status !== "signed_off" && can("decide");
  const busy = accept.isPending || reject.isPending;

  return (
    <li className="space-y-3 p-5">
      <div className="flex flex-wrap items-center gap-1.5">
        <code className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{suggestion.requirement_code}</code>
        <Badge tone={ASSESSMENT_TONE[suggestion.assessment]} dot>
          {t(`ai.assessment.${suggestion.assessment}`)}
        </Badge>
        <SeverityBadge severity={suggestion.severity} />
        {suggestion.status !== "pending" && (
          <Badge tone={suggestion.status === "accepted" ? "teal" : "neutral"}>{t(`ai.status.${suggestion.status}`)}</Badge>
        )}
      </div>
      <h3 className="text-[15px] font-semibold leading-snug text-navy-950">{suggestion.requirement_title}</h3>
      {suggestion.summary && (
        <p className="text-sm leading-relaxed text-slate-600" dir="auto">
          {suggestion.summary}
        </p>
      )}
      {suggestion.evidence.length > 0 ? (
        <div className="space-y-2">
          {suggestion.evidence.map((e, i) => (
            <EvidenceQuote key={`${e.block_id}-${i}`} evidence={e} />
          ))}
        </div>
      ) : (
        suggestion.assessment !== "invalid_output" && <p className="text-xs text-slate-500">{t("ai.noQuotes")}</p>
      )}
      {suggestion.rejected_citations > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-amber-800">
          <AlertTriangle className="size-3.5" aria-hidden />
          {t("ai.rejectedCitations", { count: suggestion.rejected_citations })}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {open && POSSIBLE_GAPS.includes(suggestion.assessment) && (
          <Button size="sm" variant="accent" disabled={busy} onClick={() => accept.mutate()}>
            {accept.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
            {t("ai.accept")}
          </Button>
        )}
        {open && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => reject.mutate()}>
            {reject.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <X aria-hidden />}
            {t("ai.reject")}
          </Button>
        )}
        {suggestion.finding_id && (
          <Button size="sm" variant="ghost" onClick={() => onOpenFinding(suggestion.finding_id!)}>
            {t("ai.openFinding")}
          </Button>
        )}
        {suggestion.decided_at && (
          <span className="text-xs text-slate-500">
            {t("ai.decidedBy", { name: suggestion.decided_by_name ?? "—", date: formatDate(suggestion.decided_at, i18n.language, true) })}
          </span>
        )}
      </div>
    </li>
  );
}

export function AISuggestionsPanel({ review, onOpenFinding }: { review: Review; onOpenFinding: (id: string) => void }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"gaps" | "all">("gaps");
  const query = useAISuggestions(review.id);
  const generate = useMutation({
    mutationFn: () => api<AISuggestions>(`/reviews/${review.id}/ai-suggestions`, { method: "POST" }),
    onSuccess: (data) => qc.setQueryData(aiSuggestionsKey(review.id), data),
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const { run, suggestions, available } = query.data;
  const job = run?.job;
  const working = job?.status === "queued" || job?.status === "running";
  const canGenerate = available && can("write") && review.status !== "signed_off" && review.status !== "running" && !working;
  const shown = filter === "gaps" ? suggestions.filter((s) => POSSIBLE_GAPS.includes(s.assessment)) : suggestions;

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 border-b border-slate-100 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <p className="flex items-center gap-2 text-sm font-semibold text-navy-950">
              <Sparkles className="size-4 text-violet-500" aria-hidden />
              {t("ai.title")}
            </p>
            {run && (
              <p className="text-xs text-slate-500">
                {t("ai.runMeta", {
                  model: run.is_mock ? t("ai.mockModel") : `${run.provider} · ${run.model}`,
                  date: formatDate(run.created_at, i18n.language, true),
                })}
              </p>
            )}
          </div>
          {canGenerate && (
            <Button variant={run ? "outline" : "accent"} disabled={generate.isPending} onClick={() => generate.mutate()}>
              {generate.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
              {run ? t("ai.generateAgain") : t("ai.generate")}
            </Button>
          )}
        </div>
        <p className="flex items-start gap-2 text-xs leading-relaxed text-slate-500">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden />
          {t("ai.explainer")}
        </p>
        {run?.is_mock && <MockNotice />}
        {!available && run && <p className="text-xs text-slate-500">{t("ai.nowDisabled")}</p>}
        {working && job && (
          <div className="space-y-2 rounded-lg border border-violet-200 bg-violet-50/60 px-4 py-3">
            <span className="flex items-center gap-2 text-sm font-medium text-violet-800">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              {t("ai.working")}
            </span>
            <ProgressBar value={job.progress} label={t("jobs.progress")} />
          </div>
        )}
        {job && (job.status === "failed" || job.status === "cancelled") && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800">
            {t("ai.failed", { error: job.error ?? "" })}
          </p>
        )}
        {run && run.warnings.length > 0 && (
          <ul className="list-disc space-y-0.5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 ps-8 text-xs text-amber-900">
            {run.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </div>

      {!run && (
        <EmptyState
          icon={Sparkles}
          title={available ? t("ai.emptyTitle") : t("ai.disabledTitle")}
          description={!available ? t("ai.disabledHint") : review.status === "signed_off" ? t("ai.signedOffHint") : t("ai.emptyHint")}
        />
      )}
      {run && job?.status === "completed" && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
            <p className="text-[13px] text-slate-600">
              {t("ai.pendingCount", { count: suggestions.filter((s) => s.status === "pending" && POSSIBLE_GAPS.includes(s.assessment)).length })}
            </p>
            <Select aria-label={t("ai.filter")} value={filter} onChange={(e) => setFilter(e.target.value as "gaps" | "all")} className="w-auto">
              <option value="gaps">{t("ai.filterGaps")}</option>
              <option value="all">{t("ai.filterAll")}</option>
            </Select>
          </div>
          {shown.length === 0 ? (
            <EmptyState icon={Check} title={t("ai.noneShown")} />
          ) : (
            <ul className="divide-y divide-slate-100">
              {shown.map((s) => (
                <SuggestionCard key={s.id} suggestion={s} review={review} onOpenFinding={onOpenFinding} />
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
