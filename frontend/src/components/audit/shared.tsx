import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { errorMessage } from "@/components/common";
import type { EngagementStatus, PbcStatus } from "@/lib/audit";

const STATUS_TONE: Record<EngagementStatus, "neutral" | "teal" | "amber" | "orange" | "green"> = {
  planning: "neutral",
  fieldwork: "teal",
  completion: "amber",
  reporting: "orange",
  closed: "green",
};

export function EngagementStatusBadge({ status }: { status: EngagementStatus }) {
  const { t } = useTranslation();
  return (
    <Badge tone={STATUS_TONE[status]} dot>
      {t(`engagementStatus.${status}`)}
    </Badge>
  );
}

/** The server's message for a failed mutation, inside a form or dialog. */
export function MutationError({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {errorMessage(error, t("common.genericError"))}
    </p>
  );
}

/** A labelled field: label above the control, optional hint and error below. */
export function Field({
  id,
  label,
  hint,
  error,
  children,
  className,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className ?? "space-y-1.5"}>
      <label htmlFor={id} className="text-[13px] font-medium text-slate-700">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
      {error && (
        <p role="alert" className="text-xs font-medium text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

/** Small label/value pair for summary strips. */
export function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 truncate text-[13px] text-navy-900">{children}</dd>
    </div>
  );
}

/** A Decimal share (e.g. "0.1250") shown as stored; null as a dash. */
export function Share({ value }: { value: string | null }) {
  if (value == null) return <span className="text-slate-400">—</span>;
  return (
    <span dir="ltr" className="font-mono text-[13px] tabular-nums text-slate-600">
      {value}
    </span>
  );
}

/** Hash shortened for display, full value on hover. */
export function ShortHash({ value }: { value: string | null }) {
  if (!value) return <span className="text-slate-400">—</span>;
  return (
    <code dir="ltr" className="font-mono text-xs text-slate-600" title={value}>
      {value.slice(0, 16)}
    </code>
  );
}

const PBC_TONE: Record<PbcStatus, "neutral" | "teal" | "green" | "red"> = { requested: "neutral", submitted: "teal", accepted: "green", rejected: "red" };

export function PbcStatusBadge({ status }: { status: PbcStatus }) {
  const { t } = useTranslation();
  return (
    <Badge tone={PBC_TONE[status]} dot>
      {t(`pbcStatus.${status}`)}
    </Badge>
  );
}
