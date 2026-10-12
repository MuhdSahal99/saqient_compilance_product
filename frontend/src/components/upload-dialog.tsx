import { useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CheckCircle2, FileText, Loader2, Upload, UploadCloud } from "lucide-react";
import { toast } from "sonner";
import { ApiError, uploadWithProgress } from "@/lib/api";
import type { DocumentDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { ProgressBar } from "./common";
import { cn, formatBytes } from "@/lib/utils";

const ACCEPT = ".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain";
export const DOCUMENT_TYPES = ["policy", "procedure", "contract", "evidence", "other"] as const;

const FORMAT_TONE: Record<string, string> = {
  pdf: "bg-red-50 text-red-600 ring-red-200/70",
  docx: "bg-blue-50 text-blue-600 ring-blue-200/70",
  txt: "bg-slate-50 text-slate-500 ring-slate-200/80",
};

/** Small tinted tile with a file icon and the format label (PDF / DOCX / TXT). */
export function FileTypeTile({ format, size = "md", className }: { format?: string | null; size?: "md" | "lg"; className?: string }) {
  const f = (format ?? "").toLowerCase();
  return (
    <span
      className={cn(
        "relative flex shrink-0 items-center justify-center rounded-lg ring-1",
        size === "lg" ? "size-12 rounded-xl" : "size-9",
        FORMAT_TONE[f] ?? FORMAT_TONE.txt,
        className,
      )}
      aria-hidden
    >
      <FileText className={size === "lg" ? "size-5" : "size-4"} />
      {f && (
        <span className="absolute -bottom-1 start-1/2 -translate-x-1/2 rounded-[4px] bg-white px-1 text-[8px] font-bold uppercase leading-3 tracking-wide ring-1 ring-current/20 rtl:translate-x-1/2">
          {f}
        </span>
      )}
    </span>
  );
}

function extOf(name: string): string {
  const m = /\.([^.]+)$/.exec(name);
  return m?.[1]?.toLowerCase() ?? "";
}

const schema = z.object({
  title: z.string().trim().min(1).max(300),
  description: z.string().max(5000),
  document_type: z.enum(DOCUMENT_TYPES),
  tags: z.string().max(1000),
});
type Values = z.infer<typeof schema>;

/** Upload a new document, or (with documentId) a new version of an existing one. */
export function UploadDialog({
  open,
  onOpenChange,
  documentId,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  documentId?: string;
  onUploaded?: (doc: DocumentDetail) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [duplicateId, setDuplicateId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { title: "", description: "", document_type: "policy", tags: "" },
  });

  const reset = () => {
    setFile(null);
    setProgress(null);
    setError(null);
    setDuplicateId(null);
    setDragging(false);
    setInputKey((k) => k + 1);
    form.reset();
  };

  const submit = async (values: Values, allowDuplicate = false) => {
    if (!file) {
      setError(t("upload.chooseFile"));
      return;
    }
    setError(null);
    setDuplicateId(null);
    const fd = new FormData();
    fd.append("file", file);
    if (allowDuplicate) fd.append("allow_duplicate", "true");
    if (!documentId) {
      fd.append("title", values.title);
      fd.append("description", values.description);
      fd.append("document_type", values.document_type);
      fd.append("tags", values.tags);
    }
    setProgress(0);
    try {
      const doc = await uploadWithProgress<DocumentDetail>(
        documentId ? `/documents/${documentId}/versions` : "/documents",
        fd,
        setProgress,
      );
      toast.success(t("upload.success"));
      void qc.invalidateQueries({ queryKey: ["documents"] });
      void qc.invalidateQueries({ queryKey: ["document", doc.id] });
      onUploaded?.(doc);
      reset();
      onOpenChange(false);
    } catch (e) {
      setProgress(null);
      if (e instanceof ApiError && e.status === 409 && typeof e.data.duplicate_document_id === "string") {
        setDuplicateId(e.data.duplicate_document_id);
      }
      setError(e instanceof ApiError ? e.message : t("common.genericError"));
    }
  };

  const busy = progress !== null;
  const onFile = (f: File | undefined) => {
    setFile(f ?? null);
    if (f) setError(null);
    if (f && !documentId && !form.getValues("title")) {
      form.setValue("title", f.name.replace(/\.[^.]+$/, ""), { shouldValidate: true });
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (busy) return;
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent>
        <DialogTitle>{documentId ? t("upload.newVersionTitle") : t("upload.title")}</DialogTitle>
        <DialogDescription>{t("upload.hint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => submit(v))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="upload-file">{t("upload.file")}</Label>
            <div
              onClick={() => !busy && inputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault();
                if (!busy) setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                if (!busy) onFile(e.dataTransfer.files?.[0]);
              }}
              className={cn(
                "group relative flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors",
                "has-[input:focus-visible]:border-teal-500 has-[input:focus-visible]:ring-4 has-[input:focus-visible]:ring-teal-500/15",
                dragging
                  ? "border-teal-500 bg-teal-50/60"
                  : file
                    ? "border-teal-300 bg-teal-50/30 hover:border-teal-400"
                    : "border-slate-200 bg-slate-50/60 hover:border-slate-300 hover:bg-slate-50",
                busy && "cursor-not-allowed opacity-80",
              )}
            >
              <input
                key={inputKey}
                ref={inputRef}
                id="upload-file"
                type="file"
                accept={ACCEPT}
                className="sr-only"
                disabled={busy}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => onFile(e.target.files?.[0])}
              />
              {file ? (
                <div className="flex w-full items-center gap-3 text-start">
                  <FileTypeTile format={extOf(file.name)} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-navy-900" dir="auto">
                      {file.name}
                    </p>
                    <p className="text-xs tabular-nums text-slate-500">{formatBytes(file.size)}</p>
                  </div>
                  {busy ? (
                    <Loader2 className="size-4 animate-spin text-teal-600" aria-hidden />
                  ) : (
                    <CheckCircle2 className="size-5 text-teal-600" aria-hidden />
                  )}
                </div>
              ) : (
                <>
                  <span className="flex size-10 items-center justify-center rounded-full bg-white shadow-xs ring-1 ring-slate-200 transition-transform group-hover:-translate-y-0.5">
                    <UploadCloud className="size-5 text-teal-600" aria-hidden />
                  </span>
                  <p className="text-sm font-medium text-navy-900">{t("upload.dropzone")}</p>
                  <p className="text-xs text-slate-500">PDF · DOCX · TXT</p>
                </>
              )}
            </div>
          </div>
          {!documentId && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="upload-title">{t("documents.titleField")}</Label>
                <Input id="upload-title" aria-invalid={!!form.formState.errors.title} disabled={busy} {...form.register("title")} />
                <FieldError message={form.formState.errors.title ? t("upload.titleRequired") : undefined} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="upload-type">{t("documents.type")}</Label>
                  <Select id="upload-type" disabled={busy} {...form.register("document_type")}>
                    {DOCUMENT_TYPES.map((d) => (
                      <option key={d} value={d}>
                        {t(`documentType.${d}`)}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="upload-tags">{t("documents.tags")}</Label>
                  <Input id="upload-tags" placeholder={t("upload.tagsPlaceholder")} disabled={busy} {...form.register("tags")} />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="upload-description">{t("documents.description")}</Label>
                <Textarea id="upload-description" rows={2} disabled={busy} {...form.register("description")} />
              </div>
            </>
          )}
          {progress !== null && (
            <div className="space-y-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="flex items-center gap-1.5 font-medium text-slate-700">
                  <Loader2 className="size-3.5 animate-spin text-teal-600" aria-hidden />
                  {progress < 1 ? t("upload.uploading", { pct: Math.round(progress * 100) }) : t("upload.finishing")}
                </span>
              </div>
              <ProgressBar value={progress * 100} label={t("upload.progress")} />
            </div>
          )}
          {error && (
            <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {error}
              {duplicateId && (
                <div className="mt-2 flex flex-wrap gap-3">
                  <Link className="font-medium underline" to={`/documents/${duplicateId}`} onClick={() => onOpenChange(false)}>
                    {t("upload.openExisting")}
                  </Link>
                  <button type="button" className="font-medium underline" onClick={() => void form.handleSubmit((v) => submit(v, true))()}>
                    {t("upload.uploadAnyway")}
                  </button>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Upload aria-hidden />}
              {t("upload.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
