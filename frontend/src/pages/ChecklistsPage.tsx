import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "@/lib/api";
import type { Checklist, ChecklistKind, ChecklistVersionDetail } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
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
  return <Badge tone={state === "published" ? "green" : state === "draft" ? "amber" : "neutral"}>{t(`checklistState.${state}`)}</Badge>;
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
      <div className="mb-4 rounded-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">{t("checklists.kindsExplainer")}</div>
      {lists.isLoading && <LoadingState />}
      {lists.isError && <ErrorState error={lists.error} onRetry={() => void lists.refetch()} />}
      {lists.data?.length === 0 && (
        <Card>
          <EmptyState title={t("checklists.empty")} description={t("checklists.emptyHint")} />
        </Card>
      )}
      <div className="space-y-4">
        {lists.data?.map((c) => (
          <Card key={c.id}>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle>{c.name}</CardTitle>
                <KindBadge kind={c.kind} />
              </div>
              <CardDescription>{c.description}</CardDescription>
            </CardHeader>
            <Table>
              <THead>
                <tr>
                  <TH>{t("checklists.version")}</TH>
                  <TH>{t("checklists.state")}</TH>
                  <TH>{t("checklists.requirements")}</TH>
                  <TH>{t("checklists.published")}</TH>
                </tr>
              </THead>
              <TBody>
                {[...c.versions].reverse().map((v) => (
                  <TR key={v.id}>
                    <TD>
                      <Link to={`/checklists/versions/${v.id}`} className="font-medium text-navy-900 hover:underline">
                        v{v.version_number}
                      </Link>
                    </TD>
                    <TD>
                      <StateBadge state={v.state} />
                    </TD>
                    <TD className="tabular-nums">{v.requirement_count}</TD>
                    <TD>{formatDate(v.published_at, i18n.language)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </Card>
        ))}
      </div>
    </>
  );
}

function configSummary(config: Record<string, unknown> & { type: string }, t: (k: string) => string): string {
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
    default:
      return t("checkType.manual");
  }
}

export function ChecklistVersionPage() {
  const { versionId = "" } = useParams();
  const { t } = useTranslation();
  const v = useQuery({ queryKey: ["checklist-version", versionId], queryFn: () => api<ChecklistVersionDetail>(`/checklist-versions/${versionId}`) });

  if (v.isLoading) return <LoadingState />;
  if (v.isError) return <ErrorState error={v.error} onRetry={() => void v.refetch()} />;
  const d = v.data!;

  return (
    <>
      <PageHeader
        title={`${d.checklist_name} · v${d.version_number}`}
        crumbs={[{ label: t("nav.checklists"), to: "/checklists" }, { label: `v${d.version_number}` }]}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <KindBadge kind={d.checklist_kind} />
            <StateBadge state={d.state} />
            {d.state === "published" && t("checklists.immutable")}
          </span>
        }
      />
      {d.disclaimer && (
        <p className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-900">{d.disclaimer}</p>
      )}
      <p className="mb-4 text-sm text-slate-600">{t("checklists.authoringNote")}</p>
      <div className="space-y-3">
        {d.requirements.map((r) => (
          <Card key={r.id}>
            <CardContent className="grid gap-3 md:grid-cols-[1fr_18rem]">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-700">{r.code}</code>
                  <h3 className="font-medium text-navy-900">{r.title}</h3>
                  <SeverityBadge severity={r.severity} />
                </div>
                <p className="mt-1 text-sm text-slate-600">{r.description}</p>
                {r.human_instructions && (
                  <p className="mt-2 text-sm text-slate-700">
                    <span className="font-medium">{t("checklists.instructions")}:</span> {r.human_instructions}
                  </p>
                )}
              </div>
              <dl className="space-y-1 text-xs text-slate-600">
                <div>
                  <dt className="inline font-medium">{t("checklists.check")}: </dt>
                  <dd className="inline">{configSummary(r.check_config, t)}</dd>
                </div>
                <div>
                  <dt className="inline font-medium">{t("checklists.category")}: </dt>
                  <dd className="inline">{r.category}</dd>
                </div>
                {r.jurisdiction && (
                  <div>
                    <dt className="inline font-medium">{t("checklists.jurisdiction")}: </dt>
                    <dd className="inline">{r.jurisdiction}</dd>
                  </div>
                )}
                <div>
                  <dt className="inline font-medium">{t("checklists.source")}: </dt>
                  <dd className="inline">
                    {r.source_reference || "—"}
                    {r.source && (
                      <Badge className="ms-1" tone={r.source.verification_status === "verified" ? "green" : "amber"}>
                        {t(`verification.${r.source.verification_status}`)}
                      </Badge>
                    )}
                  </dd>
                </div>
              </dl>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
