import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Upload } from "lucide-react";
import { toast } from "sonner";
import { ApiError, uploadWithProgress } from "@/lib/api";
import type { DocumentDetail } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { ProgressBar } from "./common";

const ACCEPT = ".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain";
export const DOCUMENT_TYPES = ["policy", "procedure", "contract", "evidence", "other"] as const;

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
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { title: "", description: "", document_type: "policy", tags: "" },
  });

  const reset = () => {
    setFile(null);
    setProgress(null);
    setError(null);
    setDuplicateId(null);
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
        <form className="mt-4 space-y-4" onSubmit={form.handleSubmit((v) => submit(v))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="upload-file">{t("upload.file")}</Label>
            <Input
              id="upload-file"
              type="file"
              accept={ACCEPT}
              className="py-1.5"
              disabled={busy}
              onChange={(e) => onFile(e.target.files?.[0])}
            />
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
            <div className="space-y-1">
              <ProgressBar value={progress * 100} label={t("upload.progress")} />
              <p className="text-xs text-slate-500">
                {progress < 1 ? t("upload.uploading", { pct: Math.round(progress * 100) }) : t("upload.finishing")}
              </p>
            </div>
          )}
          {error && (
            <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
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
              <Upload aria-hidden />
              {t("upload.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
