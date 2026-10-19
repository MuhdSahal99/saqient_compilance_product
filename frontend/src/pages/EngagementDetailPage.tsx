import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ArrowRight, BriefcaseBusiness, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { engagementKey, nextStatus, previousStatus, useEngagement, type Engagement, type EngagementStatus } from "@/lib/audit";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { ConfirmDialog, EmptyState, ErrorState, errorMessage, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { Amount } from "@/components/calc-explain";
import { EngagementStatusBadge, Field, Meta, MutationError } from "@/components/audit/shared";
import { OverviewTab } from "@/components/audit/overview";
import { TrialBalanceTab } from "@/components/audit/trial-balance";
import { RisksTab } from "@/components/audit/risks";
import { SamplingTab } from "@/components/audit/sampling";
import { AdjustmentsTab, ConfirmationsTab } from "@/components/audit/completion";
import { LetterTab, PbcTab } from "@/components/audit/pbc-letter";

const TABS = ["overview", "tb", "risks", "sampling", "confirmations", "adjustments", "pbc", "letter"] as const;
type Tab = (typeof TABS)[number];

function BackDialog({ e, to, open, onOpenChange }: { e: Engagement; to: EngagementStatus; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const move = useMutation({
    mutationFn: () => api<Engagement>(`/engagements/${e.id}/status`, { json: { status: to, reason } }),
    onSuccess: (d) => {
      qc.setQueryData(engagementKey(e.id), d);
      void qc.invalidateQueries({ queryKey: ["engagements", "list"] });
      toast.success(t("engagements.statusChanged", { status: t(`engagementStatus.${d.status}`) }));
      close();
    },
  });
  function close() {
    setReason("");
    move.reset();
    onOpenChange(false);
  }
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogTitle>{e.status === "closed" ? t("engagements.reopenTitle") : t("engagements.backTitle", { status: t(`engagementStatus.${to}`) })}</DialogTitle>
        <DialogDescription>{t("engagements.backHint")}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (reason.trim()) move.mutate();
          }}
        >
          <Field id="eng-back-reason" label={t("workpapers.reason")}>
            <Textarea id="eng-back-reason" rows={3} value={reason} onChange={(ev) => setReason(ev.target.value)} />
          </Field>
          <MutationError error={move.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={!reason.trim() || move.isPending}>
              {move.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {e.status === "closed" ? t("engagements.reopen") : t("engagements.moveBack")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EngagementDetailPage() {
  const { engagementId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const eng = useEngagement(engagementId);
  const [confirmNext, setConfirmNext] = useState(false);
  const [backOpen, setBackOpen] = useState(false);
  const tabParam = params.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(tabParam ?? "") ? (tabParam as Tab) : "overview";
  const forward = useMutation({
    mutationFn: (to: EngagementStatus) => api<Engagement>(`/engagements/${engagementId}/status`, { json: { status: to, reason: "" } }),
    onSuccess: (d) => {
      setConfirmNext(false);
      qc.setQueryData(engagementKey(d.id), d);
      void qc.invalidateQueries({ queryKey: ["engagements", "list"] });
      toast.success(t("engagements.statusChanged", { status: t(`engagementStatus.${d.status}`) }));
    },
    onError: (err) => toast.error(errorMessage(err, t("common.genericError"))),
  });

  if (eng.isLoading) return <LoadingState />;
  if (eng.isError || !eng.data) {
    if (eng.error instanceof ApiError && eng.error.status === 404)
      return <EmptyState icon={BriefcaseBusiness} title={t("common.notFound")} description={t("common.notFoundHint")} />;
    return <ErrorState error={eng.error} onRetry={() => void eng.refetch()} />;
  }
  const e = eng.data;
  const next = nextStatus(e.status);
  const prev = previousStatus(e.status);
  const setTab = (k: Tab) => {
    const sp = new URLSearchParams(params);
    if (k === "overview") sp.delete("tab");
    else sp.set("tab", k);
    setParams(sp, { replace: true });
  };
  return (
    <>
      <PageHeader
        title={e.name}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <span>{e.entity_name}</span>
            <Badge tone="neutral">{t(`engagementKind.${e.kind}`)}</Badge>
            <EngagementStatusBadge status={e.status} />
            {e.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.engagements"), to: "/engagements" }, { label: e.name }]}
        actions={
          can("decide") && (
            <>
              {prev && (
                <Button variant="outline" onClick={() => setBackOpen(true)}>
                  <ArrowLeft className="rtl-flip" aria-hidden />
                  {e.status === "closed" ? t("engagements.reopen") : t("engagements.moveBack")}
                </Button>
              )}
              {next && (
                <Button variant="accent" disabled={forward.isPending} onClick={() => setConfirmNext(true)}>
                  {forward.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight className="rtl-flip" aria-hidden />}
                  {t("engagements.moveTo", { status: t(`engagementStatus.${next}`) })}
                </Button>
              )}
            </>
          )
        }
      />
      <div className="space-y-5">
        <Card className="px-5 py-4">
          <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Meta label={t("workpapers.period")}>
              {formatDate(e.period_start, i18n.language)} – {formatDate(e.period_end, i18n.language)}
            </Meta>
            <Meta label={t("workpapers.currency")}>{e.currency}</Meta>
            <Meta label={t("engagements.hours.budget")}>
              <Amount value={e.budget_hours} />
            </Meta>
            <Meta label={t("engagements.hours.actual")}>
              <Amount value={e.actual_hours} />
            </Meta>
            <Meta label={t("engagements.closedAt")}>{e.closed_at ? formatDate(e.closed_at, i18n.language, true) : "—"}</Meta>
          </dl>
        </Card>
        <Tabs<Tab> label={e.name} value={tab} onChange={setTab} items={TABS.map((k) => ({ key: k, label: t(`engagements.tabs.${k}`) }))} />
        {tab === "overview" && <OverviewTab e={e} />}
        {tab === "tb" && <TrialBalanceTab e={e} />}
        {tab === "risks" && <RisksTab e={e} />}
        {tab === "sampling" && <SamplingTab e={e} />}
        {tab === "confirmations" && <ConfirmationsTab e={e} />}
        {tab === "adjustments" && <AdjustmentsTab e={e} />}
        {tab === "pbc" && <PbcTab e={e} />}
        {tab === "letter" && <LetterTab e={e} />}
      </div>
      {next && (
        <ConfirmDialog
          open={confirmNext}
          onOpenChange={setConfirmNext}
          title={t("engagements.moveTo", { status: t(`engagementStatus.${next}`) })}
          description={next === "closed" ? t("engagements.closeDescription") : t("engagements.moveDescription")}
          confirmLabel={t("engagements.moveTo", { status: t(`engagementStatus.${next}`) })}
          busy={forward.isPending}
          onConfirm={() => forward.mutate(next)}
        />
      )}
      {prev && <BackDialog e={e} to={prev} open={backOpen} onOpenChange={setBackOpen} />}
    </>
  );
}
