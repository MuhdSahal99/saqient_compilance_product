import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { UseFormRegisterReturn } from "react-hook-form";
import { FileCode2, FileText, Loader2, RotateCcw, Sheet, ShieldCheck, TriangleAlert, UserCheck } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEntityDatasets } from "@/lib/audit";
import { useEntities, useMembers, usePublishedRulePacks } from "@/lib/queries";
import { detailKey, exportUrl, type AssuranceStatus, type AssuranceVersion, type SignOff } from "@/lib/assurance";
import type { DatasetKind } from "@/lib/types";
import { cn, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { ShortHash, Field, MutationError } from "@/components/audit/shared";

const STATUS_TONE: Record<AssuranceStatus, "neutral" | "teal" | "green"> = { draft: "neutral", prepared: "teal", signed_off: "green" };

export function AssuranceStatusBadge({ status }: { status: AssuranceStatus }) {
  const { t } = useTranslation();
  return (
    <Badge tone={STATUS_TONE[status]} dot>
      {t(`assuranceStatus.${status}`)}
    </Badge>
  );
}

/** A note that automated results are inputs for a human decision, never a conclusion. */
export function AssuranceNote({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
      <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

const linkCls =
  "inline-flex h-8 items-center gap-1.5 px-2.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 hover:text-navy-900 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-slate-400";

export function ExportLinks({ base, id, version }: { base: string; id: string; version: number }) {
  const { t } = useTranslation();
  return (
    <div className="inline-flex items-stretch divide-x divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xs rtl:divide-x-reverse">
      <a className={linkCls} href={exportUrl(base, id, version, "html")} target="_blank" rel="noopener noreferrer">
        <FileCode2 aria-hidden />
        {t("reports.html")}
      </a>
      <a className={linkCls} href={exportUrl(base, id, version, "pdf")}>
        <FileText aria-hidden />
        {t("reports.pdf")}
      </a>
      <a className={linkCls} href={exportUrl(base, id, version, "csv")}>
        <Sheet aria-hidden />
        {t("reports.csv")}
      </a>
    </div>
  );
}

/** A dialog asking for a required reason (reopen, unmatch). */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  busy,
  error,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  error: unknown;
  onConfirm: (reason: string) => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const valid = reason.trim().length >= 3;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setReason("");
        onOpenChange(o);
      }}
    >
      <DialogContent>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) onConfirm(reason.trim());
          }}
        >
          <Field id="assurance-reason" label={t("assurance.reason")} hint={t("assurance.reasonHint")}>
            <Textarea id="assurance-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <MutationError error={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={!valid || busy}>
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Prepare, sign off and reopen for one assurance object, plus its immutable versions.
 * The server enforces roles and segregation (the preparer cannot sign off); the UI only hides
 * actions the current role can never use.
 */
export function SignOffCard<T extends { id: string; sign_off: SignOff; versions: AssuranceVersion[] }>({
  base,
  listKey,
  obj,
  blocker,
}: {
  base: string;
  listKey: readonly string[];
  obj: T;
  /** Why sign-off is not possible yet (e.g. an unexplained difference), shown next to the button. */
  blocker?: string | null;
}) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [reopenOpen, setReopenOpen] = useState(false);
  const s = obj.sign_off;
  const act = useMutation({
    mutationFn: (v: { action: "prepare" | "sign-off" | "reopen"; reason?: string }) =>
      api<T>(`${base}/${obj.id}/${v.action}`, v.reason !== undefined ? { json: { reason: v.reason } } : { method: "POST" }),
    onSuccess: (d, v) => {
      qc.setQueryData(detailKey(listKey, obj.id), d);
      void qc.invalidateQueries({ queryKey: [...listKey, "list"] });
      toast.success(t(`assurance.done.${v.action}`));
      setReopenOpen(false);
    },
  });
  const pending = act.isPending ? act.variables?.action : undefined;
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>{t("assurance.signOff")}</CardTitle>
        <AssuranceStatusBadge status={s.status} />
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid gap-3 text-[13px] sm:grid-cols-2">
          <div>
            <dt className="text-xs text-slate-500">{t("assurance.preparedBy")}</dt>
            <dd className="mt-0.5 text-navy-900">
              {s.prepared_by_name ? `${s.prepared_by_name} · ${formatDate(s.prepared_at, i18n.language, true)}` : t("assurance.notYet")}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">{t("assurance.signedOffBy")}</dt>
            <dd className="mt-0.5 text-navy-900">
              {s.signed_off_by_name ? `${s.signed_off_by_name} · ${formatDate(s.signed_off_at, i18n.language, true)}` : t("assurance.notYet")}
            </dd>
          </div>
        </dl>
        {s.reopen_reason && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">{t("assurance.reopenedBecause", { reason: s.reopen_reason })}</p>
        )}
        <p className="text-xs text-slate-500">{t("assurance.segregationHint")}</p>
        {act.error && !reopenOpen && <MutationError error={act.error} />}
        <div className="flex flex-wrap items-center gap-2">
          {s.status === "draft" && can("write") && (
            <Button variant="outline" size="sm" disabled={!!pending} onClick={() => act.mutate({ action: "prepare" })}>
              {pending === "prepare" ? <Loader2 className="animate-spin" aria-hidden /> : <UserCheck aria-hidden />}
              {t("assurance.prepare")}
            </Button>
          )}
          {s.status === "prepared" && can("decide") && (
            <Button variant="accent" size="sm" disabled={!!pending || !!blocker} onClick={() => act.mutate({ action: "sign-off" })}>
              {pending === "sign-off" ? <Loader2 className="animate-spin" aria-hidden /> : <ShieldCheck aria-hidden />}
              {t("assurance.signOffAction")}
            </Button>
          )}
          {s.status !== "draft" && can("decide") && (
            <Button variant="outline" size="sm" disabled={!!pending} onClick={() => setReopenOpen(true)}>
              <RotateCcw aria-hidden />
              {t("assurance.reopen")}
            </Button>
          )}
          {s.status === "prepared" && blocker && <span className="text-xs text-amber-800">{blocker}</span>}
        </div>
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-navy-900">{t("assurance.versions")}</h3>
          {obj.versions.length === 0 ? (
            <p className="text-xs text-slate-500">{t("assurance.noVersions")}</p>
          ) : (
            <ul className="space-y-2">
              {obj.versions.map((v) => (
                <li key={v.version} className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px]">
                  <span className="font-medium text-navy-900">{t("assurance.versionN", { n: v.version })}</span>
                  <span className="text-slate-500">
                    {v.signed_by_name ?? "—"} · {formatDate(v.signed_at, i18n.language, true)}
                  </span>
                  <ShortHash value={v.sha256} />
                  <ExportLinks base={base} id={obj.id} version={v.version} />
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-slate-500">{t("assurance.versionsHint")}</p>
        </div>
      </CardContent>
      <ReasonDialog
        open={reopenOpen}
        onOpenChange={(o) => {
          setReopenOpen(o);
          if (!o) act.reset();
        }}
        title={t("assurance.reopenTitle")}
        description={t("assurance.reopenHint")}
        confirmLabel={t("assurance.reopen")}
        busy={act.isPending}
        error={act.error}
        onConfirm={(reason) => act.mutate({ action: "reopen", reason })}
      />
    </Card>
  );
}

// ---------------------------------------------------------------- shared form fields (register-driven)

export function EntitySelect({ id, reg, error, label }: { id: string; reg: UseFormRegisterReturn; error?: boolean; label?: string }) {
  const { t } = useTranslation();
  const entities = useEntities();
  return (
    <Field id={id} label={label ?? t("datasets.entity")} error={error ? t("datasets.entityRequired") : undefined}>
      <Select id={id} aria-invalid={!!error} disabled={entities.isLoading} {...reg}>
        <option value="">{entities.isError ? t("common.genericError") : t("datasets.chooseEntity")}</option>
        {(entities.data ?? []).map((e) => (
          <option key={e.id} value={e.id}>
            {e.name}
          </option>
        ))}
      </Select>
    </Field>
  );
}

/** Published rule pack version + rule key prefix. Draft rules carry an "unverified" count. */
export function PackFields({
  idPrefix,
  packReg,
  prefixReg,
  packError,
  prefixError,
}: {
  idPrefix: string;
  packReg: UseFormRegisterReturn;
  prefixReg: UseFormRegisterReturn;
  packError?: boolean;
  prefixError?: boolean;
}) {
  const { t } = useTranslation();
  const packs = usePublishedRulePacks();
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field id={`${idPrefix}-pack`} label={t("reviews.rulePack")} error={packError ? t("taxCalendar.packRequired") : undefined}>
        <Select id={`${idPrefix}-pack`} aria-invalid={!!packError} {...packReg}>
          <option value="">{packs.query.isError ? t("common.genericError") : t("taxCalendar.choosePack")}</option>
          {packs.items.map(({ p, v }) => (
            <option key={v.id} value={v.id}>
              {p.name} · v{v.version_number}
              {p.is_synthetic ? ` · ${t("common.synthetic")}` : ""}
              {v.unverified_count > 0 ? ` · ${t("rulePacks.unverifiedCount", { count: v.unverified_count })}` : ""}
            </option>
          ))}
        </Select>
      </Field>
      <Field
        id={`${idPrefix}-prefix`}
        label={t("directTax.rulesPrefix")}
        hint={t("assurance.prefixHint")}
        error={prefixError ? t("rulePacks.ruleKeyRule") : undefined}
      >
        <Input id={`${idPrefix}-prefix`} dir="ltr" aria-invalid={!!prefixError} {...prefixReg} />
      </Field>
    </div>
  );
}

/** Ready versions of one dataset kind for an entity (latest version of each dataset). */
export function DatasetVersionSelect({
  id,
  label,
  entityId,
  kind,
  reg,
  error,
}: {
  id: string;
  label: string;
  entityId: string;
  kind: DatasetKind;
  reg: UseFormRegisterReturn;
  error?: boolean;
}) {
  const { t } = useTranslation();
  const ds = useEntityDatasets(entityId, kind);
  const ready = (ds.data ?? []).filter((d) => d.latest_version?.status === "ready");
  return (
    <Field id={id} label={label} error={error ? t("assurance.datasetRequired") : undefined}>
      <Select id={id} aria-invalid={!!error} disabled={!entityId} {...reg}>
        <option value="">{!entityId ? t("assurance.chooseEntityFirst") : ready.length === 0 && ds.data ? t("assurance.noReadyDatasets") : t("assurance.chooseDataset")}</option>
        {ready.map((d) => (
          <option key={d.id} value={d.latest_version!.id}>
            {d.name} · v{d.latest_version!.version_number}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function MemberSelect({ id, label, reg, optional = true }: { id: string; label: string; reg: UseFormRegisterReturn; optional?: boolean }) {
  const { t } = useTranslation();
  const members = useMembers();
  return (
    <Field id={id} label={label}>
      <Select id={id} {...reg}>
        <option value="">{optional ? t("assurance.noOwner") : t("assurance.chooseOwner")}</option>
        {(members.data ?? [])
          .filter((m) => m.role !== "client")
          .map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.full_name}
            </option>
          ))}
      </Select>
    </Field>
  );
}

/** A number of summary facts in a row. */
export function Facts({ items, className }: { items: { label: string; value: ReactNode }[]; className?: string }) {
  return (
    <dl className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {items.map((it) => (
        <div key={it.label} className="min-w-0">
          <dt className="text-xs text-slate-500">{it.label}</dt>
          <dd className="mt-0.5 text-[13px] text-navy-900">{it.value}</dd>
        </div>
      ))}
    </dl>
  );
}
