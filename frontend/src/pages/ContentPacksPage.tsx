import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { CircleHelp, Download, FlaskConical, Layers, Loader2, PackageCheck, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { contentPacksKey, requirementCount, useContentPack, useContentPacks, type ContentPack, type PackInstall } from "@/lib/content-packs";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, LoadingState, PageHeader, SeverityBadge } from "@/components/common";
import { MutationError } from "@/components/audit/shared";

/** "Draft · synthetic" (or whichever status the pack carries). */
function PackStateBadge({ p }: { p: ContentPack }) {
  const { t } = useTranslation();
  const status = t(`packs.status.${p.status}`, { defaultValue: p.status });
  return (
    <Badge tone="amber" title={p.synthetic ? t("common.syntheticNotice") : undefined}>
      <FlaskConical className="size-3" aria-hidden />
      {p.synthetic ? t("packs.statusSynthetic", { status }) : status}
    </Badge>
  );
}

const installedCurrent = (p: ContentPack) => p.installs.some((i) => i.pack_version === p.version);

function InstalledBadge({ p }: { p: ContentPack }) {
  const { t } = useTranslation();
  if (p.installs.length === 0) return <span className="text-[13px] text-slate-500">{t("packs.notInstalled")}</span>;
  const latest = p.installs[0]!;
  return (
    <Badge tone="teal" dot>
      {t("packs.installedVersion", { version: latest.pack_version })}
    </Badge>
  );
}

const shortSha = (sha: string) => (sha.length > 12 ? `${sha.slice(0, 12)}…` : sha);

export function ContentPacksPage() {
  const { t } = useTranslation();
  const list = useContentPacks();
  return (
    <>
      <PageHeader
        title={t("packs.title")}
        description={t("packs.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.contentPacks") }]}
      />
      <p role="note" className="mb-4 flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs leading-relaxed text-orange-900">
        <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
        {t("packs.listNote")}
      </p>
      <Card className="overflow-hidden">
        {list.isLoading && <LoadingState />}
        {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
        {list.data?.length === 0 && <EmptyState icon={Layers} title={t("packs.empty")} description={t("packs.emptyHint")} />}
        {list.data && list.data.length > 0 && (
          <Table>
            <THead>
              <tr>
                <TH>{t("packs.pack")}</TH>
                <TH>{t("packs.sector")}</TH>
                <TH>{t("packs.version")}</TH>
                <TH>{t("packs.state")}</TH>
                <TH className="text-end">{t("packs.requirements")}</TH>
                <TH className="text-end">{t("packs.rules")}</TH>
                <TH>{t("packs.installed")}</TH>
              </tr>
            </THead>
            <TBody>
              {list.data.map((p) => (
                <TR key={p.id}>
                  <TD className="align-top">
                    <Link to={`/content-packs/${encodeURIComponent(p.id)}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                      {p.title}
                    </Link>
                    <p className="mt-0.5 line-clamp-2 max-w-md text-xs text-slate-500">{p.description}</p>
                  </TD>
                  <TD className="align-top text-[13px]">{t(`packSector.${p.sector}`, { defaultValue: p.sector })}</TD>
                  <TD className="align-top text-[13px] tabular-nums" dir="ltr">
                    {p.version}
                  </TD>
                  <TD className="align-top">
                    <PackStateBadge p={p} />
                  </TD>
                  <TD className="align-top text-end text-[13px] tabular-nums">{requirementCount(p)}</TD>
                  <TD className="align-top text-end text-[13px] tabular-nums">{p.rule_count}</TD>
                  <TD className="align-top">
                    <InstalledBadge p={p} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}

function InstallHistory({ installs }: { installs: PackInstall[] }) {
  const { t, i18n } = useTranslation();
  if (installs.length === 0) return <p className="text-[13px] text-slate-500">{t("packs.noInstalls")}</p>;
  return (
    <ol className="space-y-4">
      {installs.map((i) => (
        <li key={i.id} className="border-b border-slate-100 pb-4 text-[13px] last:border-0 last:pb-0">
          <p className="font-medium text-navy-900">{t("packs.installedVersion", { version: i.pack_version })}</p>
          <p className="text-xs text-slate-500">
            {formatDate(i.created_at, i18n.language, true)}
            {i.installed_by_name && ` · ${i.installed_by_name}`}
          </p>
          <p className="mt-1 font-mono text-[11px] text-slate-500" dir="ltr" title={i.manifest_sha256}>
            SHA-256 {shortSha(i.manifest_sha256)}
          </p>
          <ul className="mt-2 space-y-1">
            {i.checklist_version_ids.map((id, n) => (
              <li key={id}>
                <Link to={`/checklists/versions/${id}`} className="text-teal-700 hover:underline">
                  {t("packs.openChecklist", { n: n + 1 })}
                </Link>
              </li>
            ))}
            {i.rule_pack_version_id && (
              <li>
                <Link to={`/rule-packs/versions/${i.rule_pack_version_id}`} className="text-teal-700 hover:underline">
                  {t("packs.openRulePack")}
                </Link>
              </li>
            )}
          </ul>
        </li>
      ))}
    </ol>
  );
}

export function ContentPackDetailPage() {
  const { packId } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const pack = useContentPack(packId);
  const [confirm, setConfirm] = useState(false);
  const install = useMutation({
    mutationFn: (id: string) => api<ContentPack>(`/content-packs/${encodeURIComponent(id)}/install`, { method: "POST" }),
    onSuccess: (p) => {
      qc.setQueryData([...contentPacksKey, "detail", p.id], p);
      void qc.invalidateQueries({ queryKey: contentPacksKey });
      void qc.invalidateQueries({ queryKey: ["checklists"] });
      void qc.invalidateQueries({ queryKey: ["rule-packs"] });
      setConfirm(false);
      toast.success(t("packs.installDone"));
    },
    onError: () => setConfirm(false),
  });

  if (pack.isLoading) return <LoadingState />;
  if (pack.isError || !pack.data) {
    if (pack.error instanceof ApiError && pack.error.status === 404)
      return <EmptyState icon={Layers} title={t("common.notFound")} description={t("common.notFoundHint")} />;
    return <ErrorState error={pack.error} onRetry={() => void pack.refetch()} />;
  }
  const p = pack.data;
  const done = installedCurrent(p);
  return (
    <>
      <PageHeader
        title={p.title}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <span>{t(`packSector.${p.sector}`, { defaultValue: p.sector })}</span>
            <PackStateBadge p={p} />
            {done && (
              <Badge tone="teal" dot>
                {t("packs.installed")}
              </Badge>
            )}
          </span>
        }
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.contentPacks"), to: "/content-packs" }, { label: p.title }]}
        actions={
          can("admin") &&
          !done && (
            <Button variant="accent" disabled={install.isPending} onClick={() => setConfirm(true)}>
              {install.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
              {t("packs.install")}
            </Button>
          )
        }
      />
      <div role="note" className="mb-6 flex items-start gap-2.5 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm leading-relaxed text-orange-900">
        <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div>
          <p className="font-semibold">{t("packs.disclaimer")}</p>
          <p className="mt-0.5">{p.disclaimer}</p>
        </div>
      </div>
      <MutationError error={install.error} />
      <div className="mt-4 grid items-start gap-6 lg:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("packs.about")}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="max-w-prose text-sm leading-relaxed text-slate-700">{p.description}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CircleHelp className="size-4 text-slate-400" aria-hidden />
                {t("packs.openQuestions")}
              </CardTitle>
              <CardDescription>{t("packs.openQuestionsHint")}</CardDescription>
            </CardHeader>
            <CardContent>
              {p.open_questions.length === 0 ? (
                <p className="text-[13px] text-slate-500">{t("packs.noOpenQuestions")}</p>
              ) : (
                <ol className="list-decimal space-y-1.5 ps-5 text-sm leading-relaxed text-slate-700">
                  {p.open_questions.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
          {p.checklists.map((c) => (
            <Card key={c.name} className="overflow-hidden">
              <CardHeader>
                <CardTitle>{c.name}</CardTitle>
                <CardDescription>{t("packs.checklistHint", { count: c.requirements.length })}</CardDescription>
              </CardHeader>
              {c.requirements.length === 0 ? (
                <CardContent>
                  <p className="text-[13px] text-slate-500">{t("packs.noRequirements")}</p>
                </CardContent>
              ) : (
                <Table>
                  <THead>
                    <tr>
                      <TH>{t("packs.code")}</TH>
                      <TH>{t("packs.requirement")}</TH>
                      <TH>{t("packs.category")}</TH>
                      <TH>{t("packs.severity")}</TH>
                      <TH>{t("packs.checkType")}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {c.requirements.map((r) => (
                      <TR key={r.code}>
                        <TD className="align-top font-mono text-xs text-slate-600" dir="ltr">
                          {r.code}
                        </TD>
                        <TD className="align-top text-[13px] text-navy-900">{r.title}</TD>
                        <TD className="align-top text-[13px] text-slate-600">{r.category}</TD>
                        <TD className="align-top">
                          <SeverityBadge severity={r.severity} />
                        </TD>
                        <TD className="align-top text-[13px] text-slate-600">{t(`checkType.${r.check_type}`, { defaultValue: r.check_type })}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </Card>
          ))}
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("packs.details")}</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-2.5 text-[13px]">
                <dt className="text-slate-500">{t("packs.version")}</dt>
                <dd className="text-slate-800" dir="ltr">
                  {p.version}
                </dd>
                <dt className="text-slate-500">{t("packs.jurisdiction")}</dt>
                <dd className="text-slate-800">{t(`packJurisdiction.${p.jurisdiction}`, { defaultValue: p.jurisdiction })}</dd>
                <dt className="text-slate-500">{t("packs.requirements")}</dt>
                <dd className="tabular-nums text-slate-800">{requirementCount(p)}</dd>
                <dt className="text-slate-500">{t("packs.rules")}</dt>
                <dd className="tabular-nums text-slate-800">{p.rule_count}</dd>
                <dt className="text-slate-500">SHA-256</dt>
                <dd className="truncate font-mono text-xs text-slate-700" dir="ltr" title={p.manifest_sha256}>
                  {shortSha(p.manifest_sha256)}
                </dd>
              </dl>
              <div className="mt-4 border-t border-slate-100 pt-4">
                <p className="mb-2 text-xs font-medium text-slate-500">{t("packs.datasetKinds")}</p>
                {p.dataset_kinds.length === 0 ? (
                  <p className="text-[13px] text-slate-500">{t("packs.noDatasetKinds")}</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {p.dataset_kinds.map((k) => (
                      <Badge key={k} tone="neutral">
                        {t(`datasetKind.${k}`, { defaultValue: k })}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <PackageCheck className="size-4 text-slate-400" aria-hidden />
                {t("packs.installHistory")}
              </CardTitle>
              <CardDescription>{t("packs.installExplainer")}</CardDescription>
            </CardHeader>
            <CardContent>
              <InstallHistory installs={p.installs} />
              {!can("admin") && !done && <p className="mt-3 text-xs text-slate-500">{t("packs.adminOnly")}</p>}
            </CardContent>
          </Card>
        </div>
      </div>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("packs.installTitle", { title: p.title })}
        description={t("packs.installConfirm")}
        confirmLabel={t("packs.install")}
        busy={install.isPending}
        onConfirm={() => install.mutate(p.id)}
      />
    </>
  );
}
