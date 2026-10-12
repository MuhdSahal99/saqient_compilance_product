import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ClipboardCheck, ClipboardList, ClipboardPlus, FileText, Info, Loader2, Search } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { Checklist, DocumentSummary, Page, Review, ReviewStatus } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, IconInput, Input, Label, Select } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  EmptyState,
  ErrorState,
  errorMessage,
  LoadingState,
  PageHeader,
  Pagination,
  ReviewStatusBadge,
  SyntheticBadge,
  useDebounced,
} from "@/components/common";

const schema = z.object({
  title: z.string().trim().min(1).max(300),
  document_version_id: z.string().min(1),
  checklist_version_id: z.string().min(1),
});
type Values = z.infer<typeof schema>;

function NewReviewDialog({ open, onOpenChange, initialVersionId }: { open: boolean; onOpenChange: (o: boolean) => void; initialVersionId?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const docs = useQuery({
    queryKey: ["documents", "ready-for-review"],
    queryFn: () => api<Page<DocumentSummary>>(`/documents${qs({ status: "ready", page_size: 100 })}`),
    enabled: open,
  });
  const lists = useQuery({ queryKey: ["checklists"], queryFn: () => api<Checklist[]>("/checklists"), enabled: open });
  const published = (lists.data ?? []).flatMap((c) => c.versions.filter((v) => v.state === "published").map((v) => ({ c, v })));
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { title: "", document_version_id: initialVersionId ?? "", checklist_version_id: "" },
  });
  useEffect(() => {
    if (initialVersionId) form.setValue("document_version_id", initialVersionId);
  }, [initialVersionId, form]);
  useEffect(() => {
    const first = published[0];
    if (first && !form.getValues("checklist_version_id")) form.setValue("checklist_version_id", first.v.id);
  }, [published, form]);

  const create = useMutation({
    mutationFn: (v: Values) => api<Review>("/reviews", { json: v }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["reviews"] });
      toast.success(t("reviews.created"));
      onOpenChange(false);
      navigate(`/reviews/${r.id}`);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-teal-50 ring-1 ring-teal-200/70">
            <ClipboardPlus className="size-5 text-teal-700" aria-hidden />
          </span>
          <div className="min-w-0">
            <DialogTitle>{t("reviews.new")}</DialogTitle>
            <DialogDescription>{t("reviews.newHint")}</DialogDescription>
          </div>
        </div>
        {(docs.isLoading || lists.isLoading) && <LoadingState rows={3} />}
        {(docs.isError || lists.isError) && <ErrorState error={docs.error ?? lists.error} onRetry={() => void (docs.isError ? docs.refetch() : lists.refetch())} />}
        {docs.data && lists.data && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="review-title">{t("reviews.titleField")}</Label>
              <Input id="review-title" aria-invalid={!!form.formState.errors.title} {...form.register("title")} />
              <FieldError message={form.formState.errors.title ? t("reviews.titleRequired") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="review-doc">{t("reviews.document")}</Label>
              <Select id="review-doc" aria-invalid={!!form.formState.errors.document_version_id} {...form.register("document_version_id")}>
                <option value="">{t("reviews.chooseDocument")}</option>
                {docs.data.items.map((d) =>
                  d.latest_version ? (
                    <option key={d.id} value={d.latest_version.id}>
                      {d.title} (v{d.latest_version.version_number})
                    </option>
                  ) : null,
                )}
              </Select>
              <FieldError message={form.formState.errors.document_version_id ? t("reviews.documentRequired") : undefined} />
              {docs.data.items.length === 0 && (
                <p className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  <Info className="size-3.5 shrink-0" aria-hidden />
                  {t("reviews.noReadyDocuments")}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="review-checklist">{t("reviews.checklist")}</Label>
              <Select id="review-checklist" aria-invalid={!!form.formState.errors.checklist_version_id} {...form.register("checklist_version_id")}>
                {published.map(({ c, v }) => (
                  <option key={v.id} value={v.id}>
                    {c.name} · v{v.version_number}
                    {c.kind === "synthetic_demo" ? ` · ${t("common.synthetic")}` : ""}
                  </option>
                ))}
              </Select>
              <FieldError message={form.formState.errors.checklist_version_id ? t("reviews.checklistRequired") : undefined} />
              <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
                {t("reviews.versionPinned")}
              </p>
            </div>
            {create.isError && (
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {errorMessage(create.error, t("common.genericError"))}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={create.isPending}>
                {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t("reviews.runChecks")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function ReviewsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  // `/reviews?new` (empty value) opens the dialog; `/reviews?new=<versionId>` also preselects the document version.
  const wantsNew = params.has("new");
  const initialVersionId = params.get("new") || undefined;
  const [manualOpen, setOpen] = useState(false);
  const open = manualOpen || wantsNew;
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [status, setStatus] = useState<ReviewStatus | "">("");
  const [page, setPage] = useState(1);
  const reviews = useQuery({
    queryKey: ["reviews", { q, status, page }],
    queryFn: () => api<Page<Review>>(`/reviews${qs({ q, status, page })}`),
  });

  return (
    <>
      <PageHeader
        title={t("reviews.title")}
        description={t("reviews.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.reviews") }]}
        actions={
          can("write") && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <ClipboardPlus aria-hidden /> {t("reviews.new")}
            </Button>
          )
        }
      />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <IconInput
            icon={Search}
            aria-label={t("reviews.search")}
            placeholder={t("reviews.search")}
            className="min-w-60 flex-1"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
          <Select
            aria-label={t("reviews.statusFilter")}
            className="w-44"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as ReviewStatus | "");
              setPage(1);
            }}
          >
            <option value="">{t("reviews.allStatuses")}</option>
            {(["draft", "running", "in_review", "signed_off"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`reviewStatus.${s}`)}
              </option>
            ))}
          </Select>
        </div>
        {reviews.isLoading && <LoadingState />}
        {reviews.isError && <ErrorState error={reviews.error} onRetry={() => void reviews.refetch()} />}
        {reviews.data?.items.length === 0 && (
          <EmptyState
            icon={ClipboardList}
            title={t("reviews.empty")}
            description={t("reviews.emptyHint")}
            action={
              can("write") && (
                <Button variant="accent" onClick={() => setOpen(true)}>
                  <ClipboardPlus aria-hidden /> {t("reviews.new")}
                </Button>
              )
            }
          />
        )}
        {reviews.data && reviews.data.items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("reviews.titleField")}</TH>
                  <TH>{t("reviews.scope")}</TH>
                  <TH>{t("reviews.status")}</TH>
                  <TH className="whitespace-nowrap text-end">{t("reviews.openFindings")}</TH>
                  <TH>{t("reviews.created_col")}</TH>
                </tr>
              </THead>
              <TBody>
                {reviews.data.items.map((r) => {
                  const awaiting = (r.finding_counts.proposed ?? 0) + (r.finding_counts.in_review ?? 0);
                  return (
                    <TR key={r.id}>
                      <TD>
                        <div className="flex items-center gap-3">
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-50 ring-1 ring-slate-200/80">
                            <ClipboardCheck className="size-4 text-slate-500" aria-hidden />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <Link to={`/reviews/${r.id}`} className="font-medium text-navy-900 transition-colors hover:text-teal-700">
                                {r.title}
                              </Link>
                              {r.is_demo && <SyntheticBadge />}
                            </div>
                          </div>
                        </div>
                      </TD>
                      <TD className="text-[13px]">
                        <div className="flex items-center gap-1.5 text-slate-700">
                          <FileText className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                          <span className="truncate">{r.document_title}</span>
                          <span className="shrink-0 text-xs tabular-nums text-slate-400">v{r.document_version_number}</span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-slate-500">
                          <ClipboardList className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                          <span className="truncate">{r.checklist_name}</span>
                          <span className="shrink-0 text-xs tabular-nums text-slate-400">v{r.checklist_version_number}</span>
                        </div>
                      </TD>
                      <TD>
                        <ReviewStatusBadge status={r.status} />
                      </TD>
                      <TD className="text-end">
                        {awaiting > 0 ? (
                          <Badge tone="amber" className="tabular-nums">
                            {awaiting}
                          </Badge>
                        ) : (
                          <span className="tabular-nums text-slate-400">0</span>
                        )}
                      </TD>
                      <TD className="whitespace-nowrap text-[13px] text-slate-500">{formatDate(r.created_at, i18n.language)}</TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={20} total={reviews.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <NewReviewDialog
        open={open}
        initialVersionId={initialVersionId}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o && params.has("new")) {
            const next = new URLSearchParams(params);
            next.delete("new");
            setParams(next, { replace: true });
          }
        }}
      />
    </>
  );
}
