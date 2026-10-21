import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Bot, Check, Loader2, ShieldCheck, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { type AITask, type AITaskKind, type AILanguage, useAIAgents, useAITasks, useDecideAITask, useRunAITask } from "@/lib/ai-agents";
import { useAuth } from "@/lib/auth";
import { cn, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage, ProgressBar } from "@/components/common";
import { EvidenceQuote } from "@/components/evidence";
import { MockNotice } from "@/components/ai-suggestions";

const STATUS_TONE: Record<AITask["status"], "neutral" | "teal" | "red" | "green" | "amber"> = {
  running: "neutral",
  ready: "amber",
  failed: "red",
  accepted: "green",
  dismissed: "neutral",
};

function Paragraphs({ text, dir }: { text: string; dir?: "rtl" | "ltr" | "auto" }) {
  return (
    <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700" dir={dir ?? "auto"}>
      {text}
    </p>
  );
}

function Unchecked() {
  const { t } = useTranslation();
  return (
    <Badge tone="amber">
      <AlertTriangle className="size-3" aria-hidden />
      {t("agents.unchecked")}
    </Badge>
  );
}

function TaskOutput({ task }: { task: AITask }) {
  const { t } = useTranslation();
  const o = task.output;
  if (task.kind === "contract_tax") {
    const items = o.items ?? [];
    if (items.length === 0) return <p className="text-sm text-slate-600">{t("agents.contract.none")}</p>;
    return (
      <ul className="space-y-4">
        {items.map((it, i) => (
          <li key={i} className="space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={it.topic === "vat_treatment" ? "teal" : "navy"}>{t(`agents.contract.topic.${it.topic}`)}</Badge>
              <code className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600" dir="ltr">
                {it.cue}
              </code>
              {!it.checked && <Unchecked />}
            </div>
            <Paragraphs text={it.summary} />
            {it.question_for_reviewer && (
              <p className="text-[13px] text-slate-600" dir="auto">
                <span className="font-medium text-navy-900">{t("agents.contract.question")}: </span>
                {it.question_for_reviewer}
              </p>
            )}
            {it.evidence.map((e, j) => (
              <EvidenceQuote key={`${e.block_id}-${j}`} evidence={e} />
            ))}
          </li>
        ))}
      </ul>
    );
  }
  if (task.kind === "finding_explain") {
    return (
      <div className="space-y-3">
        {o.checked === false && <Unchecked />}
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5" lang="en">
            <p className="text-xs font-medium text-slate-500">English</p>
            <Paragraphs text={o.explanation_en ?? ""} dir="ltr" />
            {(o.next_steps_en ?? []).length > 0 && (
              <ul className="list-disc space-y-0.5 ps-5 text-[13px] text-slate-600" dir="ltr">
                {o.next_steps_en!.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="space-y-1.5" lang="ar" dir="rtl">
            <p className="text-xs font-medium text-slate-500">العربية</p>
            <Paragraphs text={o.explanation_ar ?? ""} dir="rtl" />
            {(o.next_steps_ar ?? []).length > 0 && (
              <ul className="list-disc space-y-0.5 ps-5 text-[13px] text-slate-600">
                {o.next_steps_ar!.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    );
  }
  if (task.kind === "letter_draft") {
    return (
      <dl className="space-y-3">
        {o.checked === false && <Unchecked />}
        <div>
          <dt className="text-xs font-medium text-slate-500">{t("agents.letter.implication")}</dt>
          <dd>
            <Paragraphs text={o.implication ?? ""} />
          </dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-slate-500">{t("agents.letter.recommendation")}</dt>
          <dd>
            <Paragraphs text={o.recommendation ?? ""} />
          </dd>
        </div>
      </dl>
    );
  }
  // pack_qa
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-slate-500" dir="auto">
        <span className="font-medium text-navy-900">{t("agents.qa.question")}: </span>
        {task.question}
      </p>
      {o.insufficient ? (
        <p className="rounded-lg border border-dashed border-slate-300 px-3 py-2.5 text-sm text-slate-600">{t("agents.qa.insufficient")}</p>
      ) : (
        <>
          {o.checked === false && <Unchecked />}
          <Paragraphs text={o.answer ?? ""} dir={o.language === "ar" ? "rtl" : "auto"} />
        </>
      )}
      {(o.sources ?? []).length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-slate-500">{t("agents.qa.sources")}</p>
          <ul className="space-y-1 text-[13px] text-slate-700">
            {o.sources!.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-1.5">
                <ShieldCheck className="size-3.5 text-teal-600" aria-hidden />
                <Badge tone="green">{t(`agents.qa.sourceType.${s.type}`)}</Badge>
                <code className="font-mono text-[11px] text-slate-600" dir="ltr">
                  {s.key}
                </code>
                <span dir="auto">{s.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Decision({ task }: { task: AITask }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const decide = useDecideAITask(task, () => setNote(""));
  const run = (decision: "accept" | "dismiss") =>
    decide.mutate(
      { decision, note },
      {
        onSuccess: () => toast.success(t(decision === "accept" ? "agents.acceptedToast" : "agents.dismissedToast")),
        onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
      },
    );
  const canAccept = !(task.kind === "pack_qa" && task.output.insufficient);
  return (
    <div className="flex flex-wrap items-end gap-2 border-t border-slate-100 pt-3">
      <div className="min-w-48 flex-1">
        <label htmlFor={`note-${task.id}`} className="mb-1 block text-xs font-medium text-slate-600">
          {t("agents.note")}
        </label>
        <Input id={`note-${task.id}`} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </div>
      {canAccept && (
        <Button size="sm" variant="accent" disabled={decide.isPending} onClick={() => run("accept")}>
          {decide.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
          {task.kind === "letter_draft" ? t("agents.useWording") : t("agents.accept")}
        </Button>
      )}
      <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => run("dismiss")}>
        <X aria-hidden />
        {t("agents.dismiss")}
      </Button>
    </div>
  );
}

/** One AI task: draft output, guards' warnings, the agents and models that ran, and the decision. */
export function AITaskView({ task }: { task: AITask }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const working = task.status === "running";
  const models = [...new Set(task.steps.map((s) => s.model).filter(Boolean))];
  return (
    <article className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" aria-label={t(`agents.kind.${task.kind}`)}>
      <header className="flex flex-wrap items-center gap-1.5">
        <Sparkles className="size-4 text-teal-600" aria-hidden />
        <span className="text-sm font-semibold text-navy-950">{t(`agents.kind.${task.kind}`)}</span>
        <Badge tone={STATUS_TONE[task.status]} dot>
          {t(`agents.status.${task.status}`)}
        </Badge>
        <span className="text-xs text-slate-500">
          {t("agents.requestedBy", { name: task.requested_by_name ?? "—", date: formatDate(task.created_at, i18n.language, true) })}
        </span>
      </header>
      {task.status !== "failed" && <p className="text-xs font-medium text-amber-800">{t("agents.draftLabel")}</p>}
      {task.is_mock && <MockNotice />}
      {working && (
        <div className="space-y-2 rounded-lg border border-teal-200 bg-teal-50/60 px-4 py-3">
          <span className="flex items-center gap-2 text-sm font-medium text-teal-900">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {t("agents.working")}
          </span>
          <ProgressBar value={task.job.progress} label={t("jobs.progress")} />
        </div>
      )}
      {task.status === "failed" && (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800">
          {t("agents.failed", { error: task.error || task.job.error || "" })}
        </p>
      )}
      {task.warnings.length > 0 && (
        <ul className="list-disc space-y-0.5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 ps-8 text-xs text-amber-900">
          {task.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {!working && task.status !== "failed" && <TaskOutput task={task} />}
      {task.steps.length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer select-none">
            <Bot className="me-1 inline size-3.5" aria-hidden />
            {t("agents.stepsSummary", { count: task.steps.length, models: models.join(", ") })}
          </summary>
          <ol className="mt-2 space-y-1 ps-5">
            {task.steps.map((s) => (
              <li key={s.ordinal} className="list-decimal">
                <span className="font-medium text-slate-700">{t(`agents.agent.${s.agent}`, { defaultValue: s.agent })}</span>
                {" · "}
                {t(`agents.tier.${s.tier}`, { defaultValue: s.tier })} · <span dir="ltr">{s.model_version || s.model}</span> ·{" "}
                {t(`agents.stepStatus.${s.status}`, { defaultValue: s.status })} · {t("agents.duration", { ms: s.duration_ms })}
              </li>
            ))}
          </ol>
        </details>
      )}
      {task.status === "ready" && can("decide") && <Decision task={task} />}
      {task.decided_at && (
        <p className="text-xs text-slate-500">
          {t("agents.decidedBy", { name: task.decided_by_name ?? "—", date: formatDate(task.decided_at, i18n.language, true) })}
          {task.decision_note && <> — “{task.decision_note}”</>}
        </p>
      )}
    </article>
  );
}

/**
 * Runs one kind of AI task for a subject and shows the latest result.
 * Renders nothing when the deployment has no AI provider; explains the opt-in otherwise.
 */
export function AIAssist({
  kind,
  subjectId,
  language,
  disabledReason,
  className,
}: {
  kind: Exclude<AITaskKind, "pack_qa">;
  subjectId: string;
  language?: AILanguage;
  disabledReason?: string;
  className?: string;
}) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const agents = useAIAgents();
  const tasks = useAITasks({ kind, subjectId, limit: 1 }, (agents.data ?? []).length > 0);
  const runTask = useRunAITask();
  if (!agents.data || agents.data.length === 0) return null;
  const latest = tasks.data?.[0];
  const busy = runTask.isPending || latest?.status === "running";
  const lang: AILanguage = language ?? (i18n.language === "ar" ? "ar" : "en");
  return (
    <section className={cn("space-y-2.5", className)} aria-label={t(`agents.kind.${kind}`)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[13px] font-semibold text-navy-900">
          <Sparkles className="size-4 text-teal-600" aria-hidden />
          {t(`agents.kind.${kind}`)}
        </h3>
        {can("write") && !disabledReason && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() =>
              runTask.mutate(
                { kind, subject_id: subjectId, language: lang },
                { onError: (e) => toast.error(errorMessage(e, t("common.genericError"))) },
              )
            }
          >
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
            {latest ? t("agents.runAgain") : t(`agents.run.${kind}`)}
          </Button>
        )}
      </div>
      {disabledReason && <p className="text-xs text-slate-500">{disabledReason}</p>}
      {latest && <AITaskView task={latest} />}
    </section>
  );
}
