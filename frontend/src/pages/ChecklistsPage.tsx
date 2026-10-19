import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { api } from "@/lib/api";
import { ChevronDown, ChevronRight, ClipboardList, FlaskConical, Info, ListChecks, Lock, type LucideIcon, ScrollText, Building2 } from "lucide-react";
import type { Checklist, ChecklistKind, ChecklistVersionDetail, Requirement, Severity } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  SeverityBadge,
  SyntheticBadge,
} from "@/components/common";

export function KindBadge({ kind }: { kind: ChecklistKind }) {
  const { t } = useTranslation();
  if (kind === "synthetic_demo") return <SyntheticBadge />;
  return <Badge tone={kind === "external_regulatory" ? "navy" : "teal"}>{t(`checklistKind.${kind}`)}</Badge>;
}

function StateBadge({ state }: { state: "draft" | "published" | "archived" }) {
  const { t } = useTranslation();
  return (
    <Badge tone={state === "published" ? "green" : state === "draft" ? "amber" : "neutral"} dot>
      {t(`checklistState.${state}`)}
    </Badge>
  );
}

const KIND_ICON: Record<ChecklistKind, { icon: LucideIcon; tile: string }> = {
  synthetic_demo: { icon: FlaskConical, tile: "bg-amber-50 text-amber-600 ring-amber-200/80" },
  internal_policy: { icon: Building2, tile: "bg-teal-50 text-teal-600 ring-teal-200/80" },
  external_regulatory: { icon: ScrollText, tile: "bg-indigo-50 text-indigo-600 ring-indigo-200/70" },
  audit_programme: { icon: ClipboardList, tile: "bg-slate-50 text-slate-600 ring-slate-200/80" },
};

function Notice({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "warning" }) {
  const Icon = tone === "warning" ? FlaskConical : Info;
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed",
        tone === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-600",
      )}
    >
      <Icon className={cn("mt-0.5 size-3.5 shrink-0", tone === "warning" ? "text-amber-600" : "text-slate-400")} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

export function ChecklistsPage() {
  const { t, i18n } = useTranslation();
  const lists = useQuery({ queryKey: ["checklists"], queryFn: () => api<Checklist[]>("/checklists") });
  return (
    <>
      <PageHeader
        title={t("checklists.title")}
        description={t("checklists.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.checklists") }]}
      />
      <div className="mb-6">
        <Notice>{t("checklists.kindsExplainer")}</Notice>
      </div>
      {lists.isLoading && (
        <Card>
          <LoadingState />
        </Card>
      )}
      {lists.isError && (
        <Card>
          <ErrorState error={lists.error} onRetry={() => void lists.refetch()} />
        </Card>
      )}
      {lists.data?.length === 0 && (
        <Card>
          <EmptyState icon={ListChecks} title={t("checklists.empty")} description={t("checklists.emptyHint")} />
        </Card>
      )}
      <div className="grid gap-5 lg:grid-cols-2">
        {lists.data?.map((c) => {
          const kind = KIND_ICON[c.kind];
          const KindIcon = kind.icon;
          return (
            <Card key={c.id} className="flex flex-col">
              <div className="flex items-start gap-3.5 px-5 pt-5 pb-4">
                <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg ring-1", kind.tile)} aria-hidden>
                  <KindIcon className="size-[18px]" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-base" dir="auto">
                      {c.name}
                    </CardTitle>
                    <KindBadge kind={c.kind} />
                  </div>
                  {c.description && (
                    <CardDescription className="mt-1 leading-relaxed" dir="auto">
                      {c.description}
                    </CardDescription>
                  )}
                </div>
              </div>
              {c.kind === "synthetic_demo" && !c.description.includes(t("common.syntheticNotice")) && (
                <div className="px-5 pb-4">
                  <Notice tone="warning">{t("common.syntheticNotice")}</Notice>
                </div>
              )}
              <div className="mt-auto border-t border-slate-100">
                <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-4 bg-slate-50/80 px-5 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                  <span>{t("checklists.version")}</span>
                  <span className="text-end">{t("checklists.requirements")}</span>
                  <span className="w-28 text-end">{t("checklists.published")}</span>
                </div>
                <ul className="divide-y divide-slate-100">
                  {[...c.versions].reverse().map((v) => (
                    <li key={v.id}>
                      <Link
                        to={`/checklists/versions/${v.id}`}
                        className="group grid grid-cols-[1fr_auto_auto] items-center gap-x-4 px-5 py-3 text-sm transition-colors hover:bg-slate-50/80"
                      >
                        <span className="flex items-center gap-2.5">
                          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-semibold tabular-nums text-navy-900 group-hover:text-teal-700">
                            v{v.version_number}
                          </span>
                          <StateBadge state={v.state} />
                        </span>
                        <span className="flex items-center justify-end gap-1.5 tabular-nums text-slate-700">
                          <ListChecks className="size-3.5 text-slate-400" aria-hidden />
                          {v.requirement_count}
                        </span>
                        <span className="flex w-28 items-center justify-end gap-1.5 text-[13px] whitespace-nowrap text-slate-500">
                          {formatDate(v.published_at, i18n.language)}
                          <ChevronRight className="size-3.5 text-slate-300 group-hover:text-slate-500 rtl-flip" aria-hidden />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}

function configSummary(config: Record<string, unknown> & { type: string }, t: TFunction): string {
  const list = (v: unknown) => (Array.isArray(v) ? v.map((x) => (Array.isArray(x) ? `(${x.join(" | ")})` : String(x))).join(", ") : "");
  switch (config.type) {
    case "required_text":
      return `${t("checkType.required_text")}: ${list(config.phrases)}`;
    case "phrase_groups":
      return `${t("checkType.phrase_groups")}: ${list(config.groups)}`;
    case "prohibited_terms":
      return `${t("checkType.prohibited_terms")}: ${list(config.terms)}`;
    case "pattern":
      return `${t("checkType.pattern")}: ${String(config.pattern)}`;
    case "metadata":
      return `${t("checkType.metadata")}: ${String(config.field)}${config.equals ? ` = ${String(config.equals)}` : ""}`;
    case "journal_entry_test":
      return `${t("checkType.journal_entry_test")}: ${t(`jeTest.${String(config.test)}`)} (${String(config.rules_prefix)})`;
    case "manual":
      return t("checkType.manual");
    default:
      return t(`checkType.${config.type}`, { defaultValue: config.type });
  }
}

const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

function RequirementRow({ r }: { r: Requirement }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const detailsId = `req-${r.id}`;
  return (
    <li className="group">
      <div className="flex items-start gap-3 px-5 py-4">
        <code className="mt-0.5 shrink-0 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-medium text-slate-700 ring-1 ring-slate-200/70">
          {r.code}
        </code>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
            <h3 className="font-medium text-navy-900" dir="auto">
              {r.title}
            </h3>
            <div className="flex shrink-0 items-center gap-1.5">
              <Badge tone="neutral" className="text-[11px]">
                {t(`checkType.${r.check_config.type}`, { defaultValue: r.check_config.type })}
              </Badge>
              <SeverityBadge severity={r.severity} />
            </div>
          </div>
          {r.description && (
            <p className="mt-1 text-sm leading-relaxed text-slate-600" dir="auto">
              {r.description}
            </p>
          )}
          {r.human_instructions && (
            <p className="mt-2 border-s-2 border-teal-200 ps-3 text-[13px] leading-relaxed text-slate-700" dir="auto">
              <span className="font-medium text-navy-900">{t("checklists.instructions")}:</span> {r.human_instructions}
            </p>
          )}
          <button
            type="button"
            className="mt-2 inline-flex items-center gap-1 rounded text-xs font-medium text-teal-700 hover:text-teal-800"
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={() => setOpen((o) => !o)}
          >
            <ChevronDown className={cn("size-3.5 transition-transform", open ? "rotate-0" : "-rotate-90 rtl:rotate-90")} aria-hidden />
            {t("checklists.check")} · {t("checklists.source")}
          </button>
          {open && (
            <div id={detailsId} className="mt-3 animate-fade-up rounded-lg border border-slate-200 bg-slate-50/70 p-3.5">
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-[13px]">
                <dt className="text-slate-500">{t("checklists.check")}</dt>
                <dd className="break-words text-slate-800">{configSummary(r.check_config, t)}</dd>
                <dt className="text-slate-500">{t("checklists.category")}</dt>
                <dd className="text-slate-800">{r.category}</dd>
                {r.jurisdiction && (
                  <>
                    <dt className="text-slate-500">{t("checklists.jurisdiction")}</dt>
                    <dd className="text-slate-800">{r.jurisdiction}</dd>
                  </>
                )}
                <dt className="text-slate-500">{t("checklists.source")}</dt>
                <dd className="flex flex-wrap items-center gap-1.5 text-slate-800">
                  {r.source_reference || "—"}
                  {r.source && (
                    <Badge tone={r.source.verification_status === "verified" ? "green" : "amber"}>
                      {t(`verification.${r.source.verification_status}`)}
                    </Badge>
                  )}
                </dd>
              </dl>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

export function ChecklistVersionPage() {
  const { versionId = "" } = useParams();
  const { t } = useTranslation();
  const v = useQuery({ queryKey: ["checklist-version", versionId], queryFn: () => api<ChecklistVersionDetail>(`/checklist-versions/${versionId}`) });

  if (v.isLoading) return <LoadingState />;
  if (v.isError) return <ErrorState error={v.error} onRetry={() => void v.refetch()} />;
  const d = v.data!;
  const counts = SEVERITY_ORDER.map((s) => [s, d.requirements.filter((r) => r.severity === s).length] as const).filter(([, n]) => n > 0);

  return (
    <>
      <PageHeader
        title={`${d.checklist_name} · v${d.version_number}`}
        crumbs={[{ label: t("nav.checklists"), to: "/checklists" }, { label: `v${d.version_number}` }]}
        description={
          <span className="mt-1 flex flex-wrap items-center gap-2">
            <KindBadge kind={d.checklist_kind} />
            <StateBadge state={d.state} />
            {d.state === "published" && (
              <span className="inline-flex items-center gap-1 text-[13px] text-slate-500">
                <Lock className="size-3.5" aria-hidden />
                {t("checklists.immutable")}
              </span>
            )}
          </span>
        }
      />
      <div className="mb-6 space-y-2">
        {d.disclaimer && (
          <p className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-sm font-medium text-amber-900">
            <FlaskConical className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
            {d.disclaimer}
          </p>
        )}
        <Notice>{t("checklists.authoringNote")}</Notice>
      </div>
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            {t("checklists.requirements")}
            <Badge className="tabular-nums">{d.requirements.length}</Badge>
          </CardTitle>
          <div className="flex flex-wrap items-center gap-1.5">
            {counts.map(([s, n]) => (
              <span key={s} className="inline-flex items-center gap-1">
                <SeverityBadge severity={s} />
                <span className="text-xs tabular-nums text-slate-500">×{n}</span>
              </span>
            ))}
          </div>
        </CardHeader>
        <ul className="divide-y divide-slate-100">
          {d.requirements.map((r) => (
            <RequirementRow key={r.id} r={r} />
          ))}
        </ul>
      </Card>
    </>
  );
}
