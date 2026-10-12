import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import type { Dashboard, Severity } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { cn } from "@/lib/utils";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
const SEV_COLOR: Record<Severity, string> = { critical: "#b91c1c", high: "#d97706", medium: "#2a4675", low: "#94a3b8" };

function Metric({ label, value, to, warn }: { label: string; value: number; to?: string; warn?: boolean }) {
  const body = (
    <Card className={cn("h-full transition-shadow", to && "hover:shadow-md")}>
      <CardContent className="py-5">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
        <p className={cn("mt-2 text-3xl font-semibold tabular-nums", warn && value > 0 ? "text-red-700" : "text-navy-900")}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
  return to ? (
    <Link to={to} className="block rounded-lg focus-visible:outline-2 focus-visible:outline-teal-600">
      {body}
    </Link>
  ) : (
    body
  );
}

export function OverviewPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard") });

  return (
    <>
      <PageHeader
        title={t("overview.title")}
        description={t("overview.description")}
        actions={me?.org.is_demo ? <SyntheticBadge /> : undefined}
      />
      {q.isLoading && <LoadingState />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Metric label={t("overview.documentsProcessed")} value={q.data.documents_processed} to="/documents" />
            <Metric label={t("overview.activeReviews")} value={q.data.active_reviews} to="/reviews" />
            <Metric label={t("overview.findingsProposed")} value={q.data.findings_proposed} to="/findings?status=proposed" />
            <Metric label={t("overview.findingsConfirmed")} value={q.data.findings_confirmed} to="/findings" />
            <Metric label={t("overview.openTasks")} value={q.data.open_tasks} to="/tasks" />
            <Metric label={t("overview.overdueTasks")} value={q.data.overdue_tasks} to="/tasks?overdue=1" warn />
            <Metric label={t("overview.jobFailures")} value={q.data.job_failures} warn />
            <Metric label={t("overview.documentsFailed")} value={q.data.documents_failed} to="/documents?status=failed" warn />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>{t("overview.severityTitle")}</CardTitle>
                <CardDescription>{t("overview.severityHint")}</CardDescription>
              </CardHeader>
              <CardContent>
                {SEVERITIES.every((s) => !q.data.severity_distribution[s]) ? (
                  <p className="py-10 text-center text-sm text-slate-500">{t("overview.noFindings")}</p>
                ) : (
                  <div className="h-56" dir="ltr">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={SEVERITIES.map((s) => ({ name: t(`severity.${s}`), value: q.data.severity_distribution[s] ?? 0, s }))}
                      >
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                        <YAxis allowDecimals={false} tick={{ fontSize: 12 }} width={30} />
                        <Tooltip />
                        <Bar dataKey="value" name={t("overview.findings")} radius={[4, 4, 0, 0]} fill={SEV_COLOR.medium}
                          shape={(props: unknown) => {
                            const p = props as { x: number; y: number; width: number; height: number; payload: { s: Severity } };
                            return <rect x={p.x} y={p.y} width={p.width} height={p.height} rx={4} fill={SEV_COLOR[p.payload.s]} />;
                          }}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{t("overview.coverageTitle")}</CardTitle>
                <CardDescription>{t("overview.coverageDefinition")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {q.data.coverage.length === 0 && <p className="py-10 text-center text-sm text-slate-500">{t("overview.noReviews")}</p>}
                {q.data.coverage.map((c) => (
                  <div key={c.review_id}>
                    <div className="mb-1 flex justify-between gap-2 text-sm">
                      <Link to={`/reviews/${c.review_id}`} className="truncate text-navy-800 hover:underline">
                        {c.title}
                      </Link>
                      <span className="shrink-0 tabular-nums text-slate-600">
                        {t("overview.coverageCount", { reviewed: c.reviewed, total: c.total })}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-200">
                      <div className="h-2 rounded-full bg-teal-600" style={{ width: `${c.total ? (100 * c.reviewed) / c.total : 0}%` }} />
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
