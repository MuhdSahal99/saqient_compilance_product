import { useEffect, useState, type ReactNode } from "react";
import { Link, useBlocker } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle, ChevronLeft, ChevronRight, FlaskConical, Inbox, Loader2, RotateCw, ScanText, ShieldAlert, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { CheckOutcome, DatasetStatus, FindingStatus, JobStatus, ReviewStatus, Severity, TaskStatus, VersionStatus } from "@/lib/types";

export interface Crumb {
  label: string;
  to?: string;
}

export function PageHeader({
  title,
  description,
  crumbs,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  crumbs?: Crumb[];
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {crumbs && crumbs.length > 0 && (
          <nav aria-label={t("common.breadcrumbs")} className="mb-2">
            <ol className="flex flex-wrap items-center gap-1 text-[13px] text-slate-500">
              {crumbs.map((c, i) => (
                <li key={i} className="flex min-w-0 items-center gap-1">
                  {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-slate-300 rtl-flip" aria-hidden />}
                  {c.to ? (
                    <Link to={c.to} className="rounded transition-colors hover:text-navy-900">
                      {c.label}
                    </Link>
                  ) : (
                    <span aria-current="page" className="truncate font-medium text-slate-700">
                      {c.label}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </nav>
        )}
        {eyebrow && <div className="mb-1 text-sm text-slate-500">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-navy-950 sm:text-[28px] sm:leading-9">{title}</h1>
        {description && <div className="mt-1.5 max-w-3xl text-sm leading-relaxed text-slate-500">{description}</div>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function LoadingState({ label, rows = 4 }: { label?: string; rows?: number }) {
  const { t } = useTranslation();
  return (
    <div role="status" className="space-y-3 px-5 py-6">
      <span className="sr-only">{label ?? t("common.loading")}</span>
      {label && (
        <p className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="size-4 animate-spin text-teal-600" aria-hidden />
          {label}
        </p>
      )}
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-8 shrink-0 rounded-lg" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5" style={{ width: `${70 - i * 9}%` }} />
            <Skeleton className="h-3 w-1/4" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon: Icon = Inbox,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 px-6 py-14 text-center">
      <div className="mb-2 flex size-12 items-center justify-center rounded-2xl bg-gradient-to-b from-slate-50 to-slate-100 ring-1 ring-slate-200/80">
        <Icon className="size-5 text-slate-400" aria-hidden />
      </div>
      <p className="font-semibold text-navy-900">{title}</p>
      {description && <p className="max-w-sm text-sm leading-relaxed text-slate-500">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
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
      <div className="flex size-12 items-center justify-center rounded-2xl bg-amber-50 ring-1 ring-amber-200/80">
        <AlertTriangle className="size-5 text-amber-600" aria-hidden />
      </div>
      <p className="max-w-sm text-sm text-slate-700">{errorMessage(error, t("common.genericError"))}</p>
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

/** Text read by OCR from a scanned page: it may contain recognition errors. */
export function OcrBadge({ confidence, className }: { confidence?: number | null; className?: string }) {
  const { t } = useTranslation();
  return (
    <Badge
      tone="neutral"
      className={cn("me-2 align-middle", className)}
      title={confidence != null ? t("ocr.confidence", { pct: Math.round(confidence) }) : t("ocr.hint")}
    >
      <ScanText className="size-3" aria-hidden />
      {t("ocr.badge")}
    </Badge>
  );
}

/** A rule (or a pack containing rules) that no person has verified against its official source. */
export function UnverifiedBadge({ count, className }: { count?: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <Badge tone="orange" className={className} title={t("rulePacks.unverifiedHint")}>
      <ShieldAlert className="size-3" aria-hidden />
      {count !== undefined ? t("rulePacks.unverifiedCount", { count }) : t("rulePacks.unverified")}
    </Badge>
  );
}

export function DatasetStatusBadge({ status }: { status: DatasetStatus }) {
  const { t } = useTranslation();
  const tone = status === "ready" ? "green" : status === "failed" ? "red" : status === "needs_mapping" ? "amber" : "teal";
  return (
    <Badge tone={tone} dot>
      {t(`datasetStatus.${status}`)}
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
    <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-[13px] text-slate-500">
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

const SEVERITY_TONE: Record<Severity, "neutral" | "amber" | "red" | "navy" | "orange"> = {
  low: "neutral",
  medium: "amber",
  high: "orange",
  critical: "red",
};

const SEVERITY_BARS: Record<Severity, number> = { low: 1, medium: 2, high: 3, critical: 4 };

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation();
  const tone = SEVERITY_TONE[severity];
  return (
    <Badge tone={tone} className="gap-1.5">
      <span className="flex items-end gap-px" aria-hidden>
        {[1, 2, 3, 4].map((n) => (
          <span
            key={n}
            className={cn("w-[3px] rounded-[1px]", n <= SEVERITY_BARS[severity] ? "bg-current opacity-80" : "bg-current opacity-20")}
            style={{ height: 3 + n * 2 }}
          />
        ))}
      </span>
      {t(`severity.${severity}`)}
    </Badge>
  );
}

export const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "#dc2626",
  high: "#ea580c",
  medium: "#f59e0b",
  low: "#94a3b8",
};

const FINDING_TONE: Record<FindingStatus, "neutral" | "amber" | "red" | "navy" | "teal" | "green" | "violet"> = {
  proposed: "amber",
  in_review: "amber",
  confirmed: "red",
  dismissed: "neutral",
  remediation_in_progress: "navy",
  ready_for_rereview: "violet",
  resolved: "green",
  accepted_risk: "neutral",
};

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const { t } = useTranslation();
  return (
    <Badge tone={FINDING_TONE[status]} dot>
      {t(`findingStatus.${status}`)}
    </Badge>
  );
}

export function OutcomeBadge({ outcome }: { outcome: CheckOutcome }) {
  const { t } = useTranslation();
  const tone =
    outcome === "processing_error"
      ? "red"
      : outcome === "needs_human_review" || outcome === "exceptions_found"
        ? "amber"
        : outcome === "match_found" || outcome === "no_exceptions"
          ? "teal"
          : "neutral";
  return (
    <Badge tone={tone} dot>
      {t(`outcome.${outcome}`)}
    </Badge>
  );
}

export function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  const { t } = useTranslation();
  const tone = status === "signed_off" ? "green" : status === "running" ? "teal" : status === "in_review" ? "navy" : "neutral";
  return (
    <Badge tone={tone} dot>
      {t(`reviewStatus.${status}`)}
    </Badge>
  );
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const { t } = useTranslation();
  const tone = status === "done" ? "green" : status === "in_progress" ? "teal" : status === "cancelled" ? "amber" : "neutral";
  return (
    <Badge tone={tone} dot>
      {t(`taskStatus.${status}`)}
    </Badge>
  );
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
    <Badge tone={tone} dot={!spinning}>
      {spinning && <Loader2 className="size-3 animate-spin" aria-hidden />}
      {t(`processing.${status}`)}
    </Badge>
  );
}

export function ProgressBar({ value, label, className }: { value: number; label: string; className?: string }) {
  return (
    <div className={cn("w-full", className)}>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value)}
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-teal-500 to-teal-600 transition-[width] duration-500"
          style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
        />
      </div>
    </div>
  );
}

/** Circular progress for "items reviewed" coverage. Not a compliance score. */
export function ProgressRing({
  value,
  size = 44,
  stroke = 4,
  label,
  className,
}: {
  value: number;
  size?: number;
  stroke?: number;
  label: string;
  className?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={label}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-slate-100" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c - (pct / 100) * c}
          className={cn("transition-[stroke-dashoffset] duration-700", pct >= 100 ? "stroke-emerald-500" : "stroke-teal-500")}
        />
      </svg>
      <span className="absolute text-[11px] font-semibold tabular-nums text-navy-900" aria-hidden>
        {Math.round(pct)}%
      </span>
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
