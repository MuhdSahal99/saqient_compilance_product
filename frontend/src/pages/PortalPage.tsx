import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FileUp, Inbox, Loader2, Paperclip, Send } from "lucide-react";
import { toast } from "sonner";
import { api, uploadWithProgress } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { portalKey, usePortalRequests, type PbcRequest } from "@/lib/audit";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, errorMessage, LoadingState, PageHeader, ProgressBar } from "@/components/common";
import { Field, MutationError, PbcStatusBadge } from "@/components/audit/shared";

const ACCEPT = ".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain";

function RequestCard({ r }: { r: PbcRequest }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [note, setNote] = useState(r.client_note);
  const open = r.status === "requested" || r.status === "rejected";
  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      setProgress(0);
      return uploadWithProgress<PbcRequest>(`/portal/requests/${r.id}/files`, form, setProgress);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: portalKey });
      toast.success(t("portal.uploaded"));
    },
    onError: (err) => toast.error(errorMessage(err, t("common.genericError"))),
    onSettled: () => {
      setProgress(null);
      if (input.current) input.current.value = "";
    },
  });
  const submit = useMutation({
    mutationFn: () => api<PbcRequest>(`/portal/requests/${r.id}/submit`, { json: { note } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: portalKey });
      toast.success(t("portal.submitted"));
    },
  });
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>
            <code dir="ltr" className="me-2 font-mono text-xs text-slate-500">
              {r.ref}
            </code>
            {r.title}
          </CardTitle>
          <CardDescription>{r.due_date ? t("portal.dueOn", { date: formatDate(r.due_date, i18n.language) }) : t("portal.noDue")}</CardDescription>
        </div>
        <PbcStatusBadge status={r.status} />
      </CardHeader>
      <div className="space-y-4 px-5 py-4">
        {r.description && <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{r.description}</p>}
        {r.status === "rejected" && r.review_note && (
          <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {t("portal.rejectedNote", { note: r.review_note })}
          </p>
        )}
        <div>
          <p className="mb-1.5 text-[13px] font-medium text-slate-700">{t("portal.files")}</p>
          {r.files.length === 0 ? (
            <p className="text-sm text-slate-500">{t("portal.noFiles")}</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {r.files.map((f) => (
                <li key={f.document_id} className="flex items-center gap-2 text-slate-700">
                  <Paperclip className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                  <span className="truncate">{f.title}</span>
                  <span className="text-xs text-slate-400">{formatDate(f.uploaded_at, i18n.language, true)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {open && (
          <>
            <div className="space-y-2">
              <label htmlFor={`portal-file-${r.id}`} className="text-[13px] font-medium text-slate-700">
                {t("portal.addFile")}
              </label>
              <input
                ref={input}
                id={`portal-file-${r.id}`}
                type="file"
                accept={ACCEPT}
                disabled={upload.isPending}
                className="block w-full text-sm text-slate-600 file:me-3 file:rounded-md file:border file:border-slate-200 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-slate-800 hover:file:bg-slate-50"
                onChange={(ev) => {
                  const f = ev.target.files?.[0];
                  if (f) upload.mutate(f);
                }}
              />
              <p className="text-xs text-slate-500">{t("portal.fileHint")}</p>
              {progress != null && <ProgressBar value={progress * 100} label={t("portal.uploading")} />}
            </div>
            <Field id={`portal-note-${r.id}`} label={t("portal.note")}>
              <Textarea id={`portal-note-${r.id}`} rows={2} maxLength={5000} value={note} onChange={(ev) => setNote(ev.target.value)} />
            </Field>
            <MutationError error={submit.error} />
            <Button variant="accent" size="sm" disabled={r.files.length === 0 || submit.isPending || upload.isPending} onClick={() => submit.mutate()}>
              {submit.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
              {t("portal.submit")}
            </Button>
            {r.files.length === 0 && <p className="text-xs text-slate-500">{t("portal.needFile")}</p>}
          </>
        )}
        {!open && r.submitted_at && <p className="text-xs text-slate-500">{t("portal.submittedAt", { date: formatDate(r.submitted_at, i18n.language, true) })}</p>}
      </div>
    </Card>
  );
}

/** The client portal: the only screen a user with the `client` role can use. */
export function PortalPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const isClient = me?.role === "client";
  return (
    <>
      <PageHeader title={t("portal.title")} description={t("portal.description")} />
      {isClient ? (
        <PortalRequests />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title={t("portal.staffOnlyTitle")} description={t("portal.staffOnlyHint")} />
        </Card>
      )}
    </>
  );
}

function PortalRequests() {
  const { t } = useTranslation();
  const list = usePortalRequests();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data || list.data.length === 0)
    return (
      <Card>
        <EmptyState icon={FileUp} title={t("portal.empty")} description={t("portal.emptyHint")} />
      </Card>
    );
  return (
    <div className="space-y-4">
      {list.data.map((r) => (
        <RequestCard key={r.id} r={r} />
      ))}
    </div>
  );
}
