import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ClipboardPlus, Search } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { Checklist, DocumentSummary, Page, Review, ReviewStatus } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
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
        <DialogTitle>{t("reviews.new")}</DialogTitle>
        <DialogDescription>{t("reviews.newHint")}</DialogDescription>
        {(docs.isLoading || lists.isLoading) && <LoadingState />}
        {docs.data && lists.data && (
          <form className="mt-4 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
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
              {docs.data.items.length === 0 && <p className="text-xs text-slate-500">{t("reviews.noReadyDocuments")}</p>}
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
              <p className="text-xs text-slate-500">{t("reviews.versionPinned")}</p>
            </div>
            {create.isError && (
              <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {errorMessage(create.error, t("common.genericError"))}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={create.isPending}>
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
  const initialVersionId = params.get("new") ?? undefined;
  const [open, setOpen] = useState(!!initialVersionId);
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
      <Card>
        <div className="flex flex-wrap gap-3 border-b border-slate-100 p-4">
          <div className="relative min-w-60 flex-1">
            <Search className="pointer-events-none absolute start-3 top-2.5 size-4 text-slate-400" aria-hidden />
            <Input
              aria-label={t("reviews.search")}
              placeholder={t("reviews.search")}
              className="ps-9"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <Select
            aria-label={t("reviews.statusFilter")}
            className="w-48"
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
        {reviews.data?.items.length === 0 && <EmptyState title={t("reviews.empty")} description={t("reviews.emptyHint")} />}
        {reviews.data && reviews.data.items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  <TH>{t("reviews.titleField")}</TH>
                  <TH>{t("reviews.scope")}</TH>
                  <TH>{t("reviews.status")}</TH>
                  <TH>{t("reviews.openFindings")}</TH>
                  <TH>{t("reviews.created_col")}</TH>
                </tr>
              </THead>
              <TBody>
                {reviews.data.items.map((r) => (
                  <TR key={r.id}>
                    <TD>
                      <Link to={`/reviews/${r.id}`} className="font-medium text-navy-900 hover:underline">
                        {r.title}
                      </Link>
                      {r.is_demo && <SyntheticBadge className="ms-2" />}
                    </TD>
                    <TD className="text-xs">
                      <div>
                        {r.document_title} · v{r.document_version_number}
                      </div>
                      <div className="text-slate-500">
                        {r.checklist_name} · v{r.checklist_version_number}
                      </div>
                    </TD>
                    <TD>
                      <ReviewStatusBadge status={r.status} />
                    </TD>
                    <TD className="tabular-nums">{(r.finding_counts.proposed ?? 0) + (r.finding_counts.in_review ?? 0)}</TD>
                    <TD className="whitespace-nowrap">{formatDate(r.created_at, i18n.language)}</TD>
                  </TR>
                ))}
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
            params.delete("new");
            setParams(params, { replace: true });
          }
        }}
      />
    </>
  );
}
