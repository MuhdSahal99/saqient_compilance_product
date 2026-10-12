import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import {
  AlertOctagon,
  ArrowRight,
  ArrowUpRight,
  ClipboardCheck,
  ClipboardPlus,
  Clock,
  FileSearch,
  FileWarning,
  FolderCheck,
  ServerCrash,
  SquareCheckBig,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { api, qs } from "@/lib/api";
import type { AuditEvent, Dashboard, Finding, Page, Severity } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Avatar } from "@/components/ui/avatar";
import { Skeleton } from "@/components/ui/skeleton";
import {
  EmptyState,
  ErrorState,
  FindingStatusBadge,
  PageHeader,
  ProgressRing,
  SEVERITY_COLOR,
  SeverityBadge,
  SyntheticBadge,
} from "@/components/common";
import { cn, formatRelative } from "@/lib/utils";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];

function greetingKey(): "morning" | "afternoon" | "evening" {
  const h = new Date().getHours();
  return h < 12 ? "morning" : h < 18 ? "afternoon" : "evening";
}

const TONES = {
  teal: "bg-teal-50 text-teal-600 ring-teal-100",
  indigo: "bg-indigo-50 text-indigo-600 ring-indigo-100",
  amber: "bg-amber-50 text-amber-600 ring-amber-100",
  sky: "bg-sky-50 text-sky-600 ring-sky-100",
} as const;

function StatCard({
  label,
  value,
  to,
  icon: Icon,
  tone,
  hint,
}: {
  label: string;
  value: number;
  to?: string;
  icon: LucideIcon;
  tone: keyof typeof TONES;
  hint?: string;
}) {
  const body = (
    <Card className={cn("group relative h-full overflow-hidden p-5 transition-all", to && "hover:-translate-y-0.5 hover:shadow-pop")}>
      <div className="flex items-start justify-between gap-3">
        <span className={cn("flex size-10 items-center justify-center rounded-xl ring-1", TONES[tone])}>
          <Icon className="size-5" aria-hidden />
        </span>
        {to && <ArrowUpRight className="size-4 text-slate-300 transition-colors group-hover:text-slate-500 rtl-flip" aria-hidden />}
      </div>
      <p className="mt-4 text-[32px] font-semibold leading-none tracking-tight text-navy-950 tabular-nums">{value}</p>
      <p className="mt-2 text-sm font-medium text-slate-600">{label}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-400">{hint}</p>}
    </Card>
  );
  return to ? (
    <Link to={to} className="block rounded-xl focus-visible:outline-2 focus-visible:outline-teal-600">
      {body}
    </Link>
  ) : (
    body
  );
}

function HealthItem({ label, value, to, icon: Icon }: { label: string; value: number; to?: string; icon: LucideIcon }) {
  const bad = value > 0;
  const inner = (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors",
        bad ? "border-red-200 bg-red-50/60" : "border-slate-200/80 bg-white",
        to && (bad ? "hover:bg-red-50" : "hover:bg-slate-50"),
      )}
    >
      <Icon className={cn("size-[18px] shrink-0", bad ? "text-red-600" : "text-slate-400")} aria-hidden />
      <span className={cn("flex-1 text-[13px] font-medium", bad ? "text-red-800" : "text-slate-600")}>{label}</span>
      <span className={cn("text-lg font-semibold tabular-nums", bad ? "text-red-700" : "text-navy-900")}>{value}</span>
    </div>
  );
  return to ? (
    <Link to={to} className="block rounded-xl">
      {inner}
    </Link>
  ) : (
    inner
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-6" role="status">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i} className="space-y-4 p-5">
            <Skeleton className="size-10 rounded-xl" />
            <Skeleton className="h-8 w-16" />
            <Skeleton className="h-3.5 w-32" />
          </Card>
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
        <Card className="h-72 lg:col-span-2" />
        <Card className="h-72" />
      </div>
    </div>
  );
}

function NeedsDecision() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ["findings", "overview-open"],
    queryFn: () => api<Page<Finding>>(`/findings${qs({ status: ["proposed", "in_review"], sort: "severity", page_size: 6 })}`),
  });
  return (
    <Card className="flex flex-col lg:col-span-2">
      <CardHeader className="flex-row items-center justify-between gap-3">
        <div>
          <CardTitle>{t("overview.needsDecision")}</CardTitle>
          <CardDescription>{t("overview.needsDecisionHint")}</CardDescription>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link to="/findings?status=proposed">
            {t("overview.viewAll")} <ArrowRight className="rtl-flip" aria-hidden />
          </Link>
        </Button>
      </CardHeader>
      {q.isLoading && (
        <div className="space-y-3 p-5">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      )}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && q.data.items.length === 0 && (
        <EmptyState icon={SquareCheckBig} title={t("overview.nothingToDecide")} description={t("overview.nothingToDecideHint")} />
      )}
      {q.data && q.data.items.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {q.data.items.map((f) => (
            <li key={f.id}>
              <Link
                to={`/reviews/${f.review_id}?finding=${f.id}`}
                className="group flex items-center gap-4 px-5 py-3 transition-colors hover:bg-slate-50/80"
              >
                <SeverityBadge severity={f.severity} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-navy-900 group-hover:text-teal-700">{f.title}</span>
                  <span className="block truncate text-xs text-slate-500">{f.review_title}</span>
                </span>
                <span className="hidden sm:block">
                  <FindingStatusBadge status={f.status} />
                </span>
                <ArrowRight className="size-4 shrink-0 text-slate-300 transition-transform group-hover:translate-x-0.5 group-hover:text-slate-500 rtl-flip" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function SeverityCard({ dist }: { dist: Dashboard["severity_distribution"] }) {
  const { t } = useTranslation();
  const data = SEVERITIES.map((s) => ({ s, name: t(`severity.${s}`), value: dist[s] ?? 0 }));
  const total = data.reduce((a, d) => a + d.value, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("overview.severityTitle")}</CardTitle>
        <CardDescription>{t("overview.severityHint")}</CardDescription>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <p className="py-10 text-center text-sm text-slate-500">{t("overview.noFindings")}</p>
        ) : (
          <div className="flex items-center gap-6">
            <div className="relative size-36 shrink-0" dir="ltr">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.filter((d) => d.value > 0)}
                    dataKey="value"
                    nameKey="name"
                    innerRadius="70%"
                    outerRadius="100%"
                    paddingAngle={3}
                    cornerRadius={4}
                    stroke="none"
                    isAnimationActive={false}
                  >
                    {data
                      .filter((d) => d.value > 0)
                      .map((d) => (
                        <Cell key={d.s} fill={SEVERITY_COLOR[d.s]} />
                      ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-2xl font-semibold tabular-nums text-navy-950">{total}</span>
                <span className="text-[11px] text-slate-500">{t("overview.findings")}</span>
              </div>
            </div>
            <ul className="flex-1 space-y-2.5">
              {data.map((d) => (
                <li key={d.s} className="flex items-center gap-2.5 text-sm">
                  <span className="size-2.5 rounded-full" style={{ background: SEVERITY_COLOR[d.s] }} aria-hidden />
                  <span className="flex-1 text-slate-600">{d.name}</span>
                  <span className="font-semibold tabular-nums text-navy-900">{d.value}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RecentActivity() {
  const { t, i18n } = useTranslation();
  const q = useQuery({
    queryKey: ["activity", "overview"],
    queryFn: () => api<Page<AuditEvent>>(`/audit-events${qs({ page_size: 6 })}`),
  });
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle>{t("overview.recentActivity")}</CardTitle>
        <Button asChild variant="ghost" size="sm">
          <Link to="/activity">
            {t("overview.viewAll")} <ArrowRight className="rtl-flip" aria-hidden />
          </Link>
        </Button>
      </CardHeader>
      <CardContent>
        {q.isLoading && <Skeleton className="h-32" />}
        {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
        {q.data?.items.length === 0 && <p className="py-8 text-center text-sm text-slate-500">{t("activity.empty")}</p>}
        <ol className="relative space-y-4">
          {q.data?.items.map((e, i, arr) => (
            <li key={e.id} className="relative flex gap-3">
              {i < arr.length - 1 && <span className="absolute start-[13px] top-8 h-[calc(100%-12px)] w-px bg-slate-200" aria-hidden />}
              <Avatar name={e.actor_name ?? t("activity.system")} className="size-7 text-[10px]" />
              <div className="min-w-0 flex-1 pt-0.5">
                <p className="text-[13px] leading-snug text-slate-700">
                  <span className="font-medium text-navy-900">{e.actor_name ?? t("activity.system")}</span>{" "}
                  <span className="text-slate-500">· {t(`audit.${e.action}`, { defaultValue: e.action })}</span>
                </p>
                <p className="mt-0.5 text-xs text-slate-400">{formatRelative(e.created_at, i18n.language)}</p>
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

export function OverviewPage() {
  const { t } = useTranslation();
  const { me, can } = useAuth();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard") });
  const firstName = (me?.user.full_name ?? "").split(" ")[0];

  return (
    <>
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-2">
            {t(`overview.greeting.${greetingKey()}`, { name: firstName })}
            {me?.org.is_demo && <SyntheticBadge />}
          </span>
        }
        title={t("overview.title")}
        description={t("overview.description")}
        actions={
          can("write") && (
            <>
              <Button asChild variant="outline">
                <Link to="/documents?upload=1">
                  <Upload aria-hidden /> {t("upload.title")}
                </Link>
              </Button>
              <Button asChild variant="accent">
                <Link to="/reviews?new">
                  <ClipboardPlus aria-hidden /> {t("reviews.new")}
                </Link>
              </Button>
            </>
          )
        }
      />
      {q.isLoading && <OverviewSkeleton />}
      {q.isError && (
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      )}
      {q.data && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard icon={ClipboardCheck} tone="teal" label={t("overview.activeReviews")} value={q.data.active_reviews} to="/reviews" />
            <StatCard
              icon={FileSearch}
              tone="amber"
              label={t("overview.findingsProposed")}
              value={q.data.findings_proposed}
              to="/findings?status=proposed"
            />
            <StatCard icon={SquareCheckBig} tone="indigo" label={t("overview.openTasks")} value={q.data.open_tasks} to="/tasks" />
            <StatCard
              icon={FolderCheck}
              tone="sky"
              label={t("overview.documentsProcessed")}
              value={q.data.documents_processed}
              to="/documents"
              hint={t("overview.confirmedHint", { count: q.data.findings_confirmed })}
            />
          </div>

          <section aria-labelledby="health-h">
            <h2 id="health-h" className="sr-only">
              {t("overview.health")}
            </h2>
            <div className="grid gap-3 md:grid-cols-3">
              <HealthItem icon={Clock} label={t("overview.overdueTasks")} value={q.data.overdue_tasks} to="/tasks?overdue=1" />
              <HealthItem icon={ServerCrash} label={t("overview.jobFailures")} value={q.data.job_failures} />
              <HealthItem icon={FileWarning} label={t("overview.documentsFailed")} value={q.data.documents_failed} to="/documents?status=failed" />
            </div>
          </section>

          <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
            <NeedsDecision />
            <SeverityCard dist={q.data.severity_distribution} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{t("overview.coverageTitle")}</CardTitle>
                <CardDescription>{t("overview.coverageDefinition")}</CardDescription>
              </CardHeader>
              {q.data.coverage.length === 0 ? (
                <EmptyState icon={AlertOctagon} title={t("overview.noReviews")} />
              ) : (
                <ul className="divide-y divide-slate-100">
                  {q.data.coverage.map((c) => {
                    const pct = c.total ? (100 * c.reviewed) / c.total : 0;
                    return (
                      <li key={c.review_id}>
                        <Link
                          to={`/reviews/${c.review_id}`}
                          className="group flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-slate-50/80"
                        >
                          <ProgressRing value={pct} label={t("overview.coverageCount", { reviewed: c.reviewed, total: c.total })} />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-navy-900 group-hover:text-teal-700">{c.title}</span>
                            <span className="block text-xs tabular-nums text-slate-500">
                              {t("overview.coverageCount", { reviewed: c.reviewed, total: c.total })}
                            </span>
                          </span>
                          <ArrowRight className="size-4 text-slate-300 transition-transform group-hover:translate-x-0.5 group-hover:text-slate-500 rtl-flip" aria-hidden />
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
            <RecentActivity />
          </div>
        </div>
      )}
    </>
  );
}
