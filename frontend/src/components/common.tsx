import { useEffect, useState, type ReactNode } from "react";
import { Link, useBlocker } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle, ChevronLeft, ChevronRight, FlaskConical, Inbox, Loader2, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import type { CheckOutcome, FindingStatus, JobStatus, ReviewStatus, Severity, VersionStatus } from "@/lib/types";

export interface Crumb {
  label: string;
  to?: string;
}

export function PageHeader({
  title,
  description,
  crumbs,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  crumbs?: Crumb[];
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {crumbs && crumbs.length > 0 && (
          <nav aria-label={t("common.breadcrumbs")} className="mb-1.5">
            <ol className="flex flex-wrap items-center gap-1 text-xs text-slate-500">
              {crumbs.map((c, i) => (
                <li key={i} className="flex items-center gap-1">
                  {i > 0 && <ChevronRight className="size-3 rtl-flip" aria-hidden />}
                  {c.to ? (
                    <Link to={c.to} className="hover:text-teal-700 hover:underline">
                      {c.label}
                    </Link>
                  ) : (
                    <span aria-current="page">{c.label}</span>
                  )}
                </li>
              ))}
            </ol>
          </nav>
        )}
        <h1 className="truncate text-2xl font-semibold tracking-tight text-navy-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function LoadingState({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label ?? t("common.loading")}
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <Inbox className="size-8 text-slate-300" aria-hidden />
      <p className="font-medium text-slate-800">{title}</p>
      {description && <p className="max-w-md text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  return fallback;
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <AlertTriangle className="size-7 text-amber-600" aria-hidden />
      <p className="text-sm text-slate-700">{errorMessage(error, t("common.genericError"))}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw aria-hidden /> {t("common.retry")}
        </Button>
      )}
    </div>
  );
}

export function SyntheticBadge({ className }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <Badge tone="amber" className={className} title={t("common.syntheticNotice")}>
      <FlaskConical className="size-3" aria-hidden />
      {t("common.synthetic")}
    </Badge>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return (
    <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm text-slate-600">
      <span>{t("common.pageOf", { page, pages, total })}</span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="rtl-flip" aria-hidden />
          {t("common.previous")}
        </Button>
        <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          {t("common.next")}
          <ChevronRight className="rtl-flip" aria-hidden />
        </Button>
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive,
  busy,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant={destructive ? "destructive" : "default"} disabled={busy} onClick={onConfirm}>
            {busy && <Loader2 className="animate-spin" aria-hidden />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Warn before leaving a page (in-app navigation and tab close) while a form is dirty. */
export function useUnsavedChangesWarning(dirty: boolean) {
  const { t } = useTranslation();
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (blocker.state === "blocked") {
      if (window.confirm(t("common.unsavedChanges"))) blocker.proceed();
      else blocker.reset();
    }
  }, [blocker, t]);
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
}

const SEVERITY_TONE: Record<Severity, "neutral" | "amber" | "red" | "navy"> = {
  low: "neutral",
  medium: "navy",
  high: "amber",
  critical: "red",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation();
  return <Badge tone={SEVERITY_TONE[severity]}>{t(`severity.${severity}`)}</Badge>;
}

const FINDING_TONE: Record<FindingStatus, "neutral" | "amber" | "red" | "navy" | "teal" | "green"> = {
  proposed: "amber",
  in_review: "amber",
  confirmed: "red",
  dismissed: "neutral",
  remediation_in_progress: "navy",
  ready_for_rereview: "teal",
  resolved: "green",
  accepted_risk: "neutral",
};

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const { t } = useTranslation();
  return <Badge tone={FINDING_TONE[status]}>{t(`findingStatus.${status}`)}</Badge>;
}

export function OutcomeBadge({ outcome }: { outcome: CheckOutcome }) {
  const { t } = useTranslation();
  const tone = outcome === "processing_error" ? "red" : outcome === "needs_human_review" ? "amber" : "neutral";
  return <Badge tone={tone}>{t(`outcome.${outcome}`)}</Badge>;
}

export function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  const { t } = useTranslation();
  const tone = status === "signed_off" ? "green" : status === "running" ? "teal" : status === "in_review" ? "navy" : "neutral";
  return <Badge tone={tone}>{t(`reviewStatus.${status}`)}</Badge>;
}

export function ProcessingBadge({ status }: { status: VersionStatus | JobStatus }) {
  const { t } = useTranslation();
  const tone =
    status === "ready" || status === "completed"
      ? "green"
      : status === "failed"
        ? "red"
        : status === "cancelled"
          ? "neutral"
          : "teal";
  const spinning = status === "processing" || status === "running" || status === "pending" || status === "queued";
  return (
    <Badge tone={tone}>
      {spinning && <Loader2 className="size-3 animate-spin" aria-hidden />}
      {t(`processing.${status}`)}
    </Badge>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  return (
    <div className="w-full">
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-slate-200"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value)}
      >
        <div className="h-full rounded-full bg-teal-600 transition-[width]" style={{ width: `${Math.max(2, value)}%` }} />
      </div>
    </div>
  );
}

/** Debounce a value (for search inputs). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}
