import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Info, Loader2, MessageSquareText, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { type AILanguage, type AITaskKind, useAIAgents, useAITasks, useRunAITask } from "@/lib/ai-agents";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, errorMessage, LoadingState, PageHeader } from "@/components/common";
import { AITaskView } from "@/components/ai-task";

const KINDS: AITaskKind[] = ["pack_qa", "contract_tax", "finding_explain", "letter_draft"];
const MAX_QUESTION = 1000;

function AskForm() {
  const { t, i18n } = useTranslation();
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState<AILanguage>(i18n.language === "ar" ? "ar" : "en");
  const run = useRunAITask();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    run.mutate(
      { kind: "pack_qa", question: question.trim(), language },
      {
        onSuccess: () => setQuestion(""),
        onError: (err) => toast.error(errorMessage(err, t("common.genericError"))),
      },
    );
  };
  return (
    <form onSubmit={submit} className="space-y-3 p-5">
      <div>
        <Label htmlFor="ai-question">{t("agents.qa.label")}</Label>
        <Textarea
          id="ai-question"
          rows={3}
          dir="auto"
          maxLength={MAX_QUESTION}
          value={question}
          placeholder={t("agents.qa.placeholder")}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <p className="mt-1 text-xs text-slate-500">{t("agents.qa.hint")}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <Label htmlFor="ai-language">{t("agents.qa.language")}</Label>
          <Select id="ai-language" className="w-auto" value={language} onChange={(e) => setLanguage(e.target.value as AILanguage)}>
            <option value="en">English</option>
            <option value="ar">العربية</option>
          </Select>
        </div>
        <Button type="submit" variant="accent" disabled={run.isPending || !question.trim()}>
          {run.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <MessageSquareText aria-hidden />}
          {t("agents.qa.ask")}
        </Button>
      </div>
    </form>
  );
}

export function AIAssistantPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const agents = useAIAgents();
  const [kind, setKind] = useState<AITaskKind | "">("");
  const enabled = (agents.data ?? []).length > 0;
  const tasks = useAITasks({ kind: kind || undefined, limit: 20 }, enabled);

  return (
    <>
      <PageHeader
        title={t("agents.title")}
        description={t("agents.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.aiAssistant") }]}
      />
      {agents.isLoading ? (
        <LoadingState />
      ) : agents.isError ? (
        <ErrorState error={agents.error} onRetry={() => void agents.refetch()} />
      ) : !enabled ? (
        <Card>
          <EmptyState icon={Sparkles} title={t("agents.offTitle")} description={t("agents.offHint")} />
        </Card>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[1fr_340px]">
          <div className="space-y-6">
            <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
              <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
              {t("agents.explainer")}
            </p>
            {can("write") && (
              <Card className="overflow-hidden">
                <AskForm />
              </Card>
            )}
            <section className="space-y-3" aria-label={t("agents.history")}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-navy-950">{t("agents.history")}</h2>
                <Select aria-label={t("agents.filter")} className="w-auto" value={kind} onChange={(e) => setKind(e.target.value as AITaskKind | "")}>
                  <option value="">{t("agents.allKinds")}</option>
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {t(`agents.kind.${k}`)}
                    </option>
                  ))}
                </Select>
              </div>
              {tasks.isLoading ? (
                <LoadingState rows={2} />
              ) : tasks.isError ? (
                <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />
              ) : (tasks.data ?? []).length === 0 ? (
                <Card>
                  <EmptyState icon={Sparkles} title={t("agents.emptyTitle")} description={t("agents.emptyHint")} />
                </Card>
              ) : (
                <div className="space-y-3">
                  {tasks.data!.map((task) => (
                    <AITaskView key={task.id} task={task} />
                  ))}
                </div>
              )}
            </section>
          </div>
          <Card className="overflow-hidden">
            <div className="border-b border-slate-100 px-5 py-3">
              <h2 className="text-sm font-semibold text-navy-950">{t("agents.agentsTitle")}</h2>
              <p className="mt-0.5 text-xs text-slate-500">{t("agents.agentsHint")}</p>
            </div>
            <Table>
              <THead>
                <TR>
                  <TH>{t("agents.agentColumn")}</TH>
                  <TH>{t("agents.modelColumn")}</TH>
                </TR>
              </THead>
              <TBody>
                {agents.data!.map((a) => (
                  <TR key={a.name}>
                    <TD>
                      <span className="font-medium text-navy-900">{t(`agents.agent.${a.name}`, { defaultValue: a.name })}</span>
                      <span className="block text-xs text-slate-500">{t(`agents.tier.${a.tier}`)}</span>
                    </TD>
                    <TD>
                      <code className="font-mono text-[11px] text-slate-600" dir="ltr">
                        {a.model}
                      </code>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>
        </div>
      )}
    </>
  );
}
