import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Building, ClipboardCheck, ClipboardList, ClipboardPlus, FileCode, FileText, Info, Loader2, Search, Table2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { Checklist, Dataset, DocumentSummary, EInvoiceBatch, Page, Review, ReviewStatus, RulePack } from "@/lib/types";
import { useEntities, useTaxPeriods } from "@/lib/queries";
import { useAuth } from "@/lib/auth";
import { cn, formatDate } from "@/lib/utils";
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

const schema = z
  .object({
    title: z.string().trim().min(1).max(300),
    document_version_id: z.string(),
    checklist_version_id: z.string().min(1),
    dataset_version_ids: z.array(z.string()).max(5),
    rule_pack_version_id: z.string(),
    as_of_date: z.string(),
    entity_id: z.string(),
    tax_period_id: z.string(),
    einvoice_batch_ids: z.array(z.string()).max(20),
  })
  .refine((v) => v.document_version_id || v.dataset_version_ids.length > 0 || v.einvoice_batch_ids.length > 0 || v.entity_id, {
    path: ["document_version_id"],
    message: "input",
  });
type Values = z.infer<typeof schema>;

function NewReviewDialog({ open, onOpenChange, initialVersionId }: { open: boolean; onOpenChange: (o: boolean) => void; initialVersionId?: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const docs = useQuery({
    queryKey: ["documents", "ready-for-review"],
    queryFn: () => api<Page<DocumentSummary>>(`/documents${qs({ status: "ready", page_size: 100 })}`),
    enabled: open,
  });
  const lists = useQuery({ queryKey: ["checklists"], queryFn: () => api<Checklist[]>("/checklists"), enabled: open });
  const datasets = useQuery({ queryKey: ["datasets", { kind: "" }], queryFn: () => api<Dataset[]>("/datasets"), enabled: open });
  const packs = useQuery({ queryKey: ["rule-packs"], queryFn: () => api<RulePack[]>("/rule-packs"), enabled: open });
  const entities = useEntities(open);
  const readyDatasets = (datasets.data ?? []).filter((d) => d.latest_version?.status === "ready");
  const publishedPacks = (packs.data ?? []).flatMap((p) => p.versions.filter((v) => v.state === "published").map((v) => ({ p, v })));
  const published = (lists.data ?? []).flatMap((c) => c.versions.filter((v) => v.state === "published").map((v) => ({ c, v })));
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: "",
      document_version_id: initialVersionId ?? "",
      checklist_version_id: "",
      dataset_version_ids: [],
      rule_pack_version_id: "",
      as_of_date: "",
      entity_id: "",
      tax_period_id: "",
      einvoice_batch_ids: [],
    },
  });
  useEffect(() => {
    if (initialVersionId) form.setValue("document_version_id", initialVersionId);
  }, [initialVersionId, form]);
  useEffect(() => {
    const first = published[0];
    if (first && !form.getValues("checklist_version_id")) form.setValue("checklist_version_id", first.v.id);
  }, [published, form]);

  const chosen = useWatch({ control: form.control, name: "dataset_version_ids" });
  const packId = useWatch({ control: form.control, name: "rule_pack_version_id" });
  const entityId = useWatch({ control: form.control, name: "entity_id" });
  const chosenBatches = useWatch({ control: form.control, name: "einvoice_batch_ids" });
  const periods = useTaxPeriods(entityId || null);
  const batches = useQuery({
    queryKey: ["einvoice-batches", { entityId }],
    queryFn: () => api<EInvoiceBatch[]>(`/einvoice-batches${qs({ entity_id: entityId })}`),
    enabled: open && !!entityId,
  });
  // Periods and batches belong to one entity; clear them when the entity changes.
  useEffect(() => {
    form.setValue("tax_period_id", "");
    form.setValue("einvoice_batch_ids", []);
  }, [entityId, form]);
  const selectedPack = publishedPacks.find((x) => x.v.id === packId);

  const create = useMutation({
    mutationFn: (v: Values) =>
      api<Review>("/reviews", {
        json: {
          title: v.title,
          checklist_version_id: v.checklist_version_id,
          document_version_id: v.document_version_id || null,
          dataset_version_ids: v.dataset_version_ids,
          rule_pack_version_id: v.rule_pack_version_id || null,
          as_of_date: v.as_of_date || null,
          ...(v.entity_id ? { entity_id: v.entity_id } : {}),
          ...(v.tax_period_id ? { tax_period_id: v.tax_period_id } : {}),
          ...(v.einvoice_batch_ids.length > 0 ? { einvoice_batch_ids: v.einvoice_batch_ids } : {}),
        },
      }),
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
        {(docs.isLoading || lists.isLoading || datasets.isLoading || packs.isLoading || entities.isLoading) && <LoadingState rows={3} />}
        {(docs.isError || lists.isError || datasets.isError || packs.isError || entities.isError) && (
          <ErrorState
            error={docs.error ?? lists.error ?? datasets.error ?? packs.error ?? entities.error}
            onRetry={() => {
              void docs.refetch();
              void lists.refetch();
              void datasets.refetch();
              void packs.refetch();
              void entities.refetch();
            }}
          />
        )}
        {docs.data && lists.data && datasets.data && packs.data && entities.data && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="review-title">{t("reviews.titleField")}</Label>
              <Input id="review-title" aria-invalid={!!form.formState.errors.title} {...form.register("title")} />
              <FieldError message={form.formState.errors.title ? t("reviews.titleRequired") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="review-doc">{t("reviews.document")}</Label>
              <Select id="review-doc" aria-invalid={!!form.formState.errors.document_version_id} {...form.register("document_version_id")}>
                <option value="">{t("reviews.noDocument")}</option>
                {docs.data.items.map((d) =>
                  d.latest_version ? (
                    <option key={d.id} value={d.latest_version.id}>
                      {d.title} (v{d.latest_version.version_number})
                    </option>
                  ) : null,
                )}
              </Select>
            </div>
            <fieldset className="space-y-1.5">
              <legend className="text-sm font-medium text-slate-700">{t("reviews.datasets")}</legend>
              {readyDatasets.length === 0 ? (
                <p className="text-xs text-slate-500">{t("reviews.noReadyDatasets")}</p>
              ) : (
                <ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2">
                  {readyDatasets.map((d) => {
                    const id = d.latest_version!.id;
                    const checked = chosen.includes(id);
                    const kindTaken = !checked && readyDatasets.some((o) => o.kind === d.kind && chosen.includes(o.latest_version!.id));
                    return (
                      <li key={d.id}>
                        <label className={cn("flex items-center gap-2 rounded-md px-2 py-1 text-sm", kindTaken ? "text-slate-400" : "text-slate-700 hover:bg-slate-50")}>
                          <input
                            type="checkbox"
                            className="size-4 rounded border-slate-300 accent-teal-600"
                            checked={checked}
                            disabled={kindTaken || (!checked && chosen.length >= 5)}
                            onChange={(e) =>
                              form.setValue("dataset_version_ids", e.target.checked ? [...chosen, id] : chosen.filter((x) => x !== id), {
                                shouldValidate: form.formState.isSubmitted,
                              })
                            }
                          />
                          <span className="min-w-0 flex-1 truncate">
                            {d.name} <span className="text-xs tabular-nums text-slate-400">v{d.latest_version!.version_number}</span>
                          </span>
                          <span className="shrink-0 text-xs text-slate-500">{t(`datasetKind.${d.kind}`)}</span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
              <p className="text-xs text-slate-500">{t("reviews.oneDatasetPerKind")}</p>
            </fieldset>
            {entities.data.length > 0 && (
              <fieldset className="space-y-3 rounded-lg border border-slate-200 p-3">
                <legend className="px-1 text-sm font-medium text-slate-700">{t("reviews.vatScope")}</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="review-entity">{t("datasets.entity")}</Label>
                    <Select id="review-entity" {...form.register("entity_id")}>
                      <option value="">{t("reviews.noEntity")}</option>
                      {entities.data.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="review-period">{t("reviews.taxPeriod")}</Label>
                    <Select id="review-period" disabled={!entityId || periods.isLoading} {...form.register("tax_period_id")}>
                      <option value="">{t("reviews.noTaxPeriod")}</option>
                      {(periods.data ?? []).map((p) => (
                        <option key={p.id} value={p.id}>
                          {formatDate(p.period_start, i18n.language)} – {formatDate(p.period_end, i18n.language)} · {t(`taxPeriodStatus.${p.status}`)}
                        </option>
                      ))}
                    </Select>
                  </div>
                </div>
                {entityId && (
                  <div className="space-y-1.5">
                    <p className="text-[13px] font-medium text-slate-700">{t("reviews.einvoiceBatches")}</p>
                    {batches.isLoading && <LoadingState rows={1} />}
                    {batches.isError && <ErrorState error={batches.error} onRetry={() => void batches.refetch()} />}
                    {batches.data?.length === 0 && <p className="text-xs text-slate-500">{t("reviews.noBatches")}</p>}
                    {batches.data && batches.data.length > 0 && (
                      <ul className="max-h-36 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2">
                        {batches.data.map((b) => {
                          const checked = chosenBatches.includes(b.id);
                          return (
                            <li key={b.id}>
                              <label className="flex items-center gap-2 rounded-md px-2 py-1 text-sm text-slate-700 hover:bg-slate-50">
                                <input
                                  type="checkbox"
                                  className="size-4 rounded border-slate-300 accent-teal-600"
                                  checked={checked}
                                  disabled={!checked && chosenBatches.length >= 20}
                                  onChange={(e) =>
                                    form.setValue(
                                      "einvoice_batch_ids",
                                      e.target.checked ? [...chosenBatches, b.id] : chosenBatches.filter((x) => x !== b.id),
                                      { shouldValidate: form.formState.isSubmitted },
                                    )
                                  }
                                />
                                <span className="min-w-0 flex-1 truncate">{b.name}</span>
                                <span className="shrink-0 text-xs tabular-nums text-slate-500">{t("einvoices.fileCount", { count: b.file_count })}</span>
                              </label>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                )}
                <p className="text-xs text-slate-500">{t("reviews.vatScopeHint")}</p>
              </fieldset>
            )}
            <FieldError message={form.formState.errors.document_version_id ? t("reviews.inputRequired") : undefined} />
            {docs.data.items.length === 0 && readyDatasets.length === 0 && (
              <p className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                <Info className="size-3.5 shrink-0" aria-hidden />
                {t("reviews.noReadyInputs")}
              </p>
            )}
            {(chosen.length > 0 || !!entityId || chosenBatches.length > 0) && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="review-pack">{t("reviews.rulePack")}</Label>
                  <Select id="review-pack" {...form.register("rule_pack_version_id")}>
                    <option value="">{t("reviews.noRulePack")}</option>
                    {publishedPacks.map(({ p, v }) => (
                      <option key={v.id} value={v.id}>
                        {p.name} · v{v.version_number}
                        {p.is_synthetic ? ` · ${t("common.synthetic")}` : ""}
                        {v.unverified_count > 0 ? ` · ${t("rulePacks.unverifiedCount", { count: v.unverified_count })}` : ""}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="review-asof">{t("reviews.asOfDate")}</Label>
                  <Input id="review-asof" type="date" aria-describedby="review-asof-hint" {...form.register("as_of_date")} />
                </div>
                <p id="review-asof-hint" className="text-xs text-slate-500 sm:col-span-2">
                  {t("reviews.asOfHint")}
                </p>
                {selectedPack && selectedPack.v.unverified_count > 0 && (
                  <p className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-orange-900 sm:col-span-2">
                    <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                    {t("reviews.unverifiedPackWarning")}
                  </p>
                )}
              </div>
            )}
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
                        {r.document_title && (
                          <div className="flex items-center gap-1.5 text-slate-700">
                            <FileText className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                            <span className="truncate">{r.document_title}</span>
                            <span className="shrink-0 text-xs tabular-nums text-slate-400">v{r.document_version_number}</span>
                          </div>
                        )}
                        {r.entity_name && (
                          <div className="flex items-center gap-1.5 text-slate-700">
                            <Building className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                            <span className="truncate">{r.entity_name}</span>
                          </div>
                        )}
                        {(r.einvoice_count ?? 0) > 0 && (
                          <div className="flex items-center gap-1.5 text-slate-700">
                            <FileCode className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                            <span className="truncate">{t("reviews.einvoiceCount", { count: r.einvoice_count })}</span>
                          </div>
                        )}
                        {r.datasets.map((d) => (
                          <div key={d.dataset_version_id} className="flex items-center gap-1.5 text-slate-700">
                            <Table2 className="size-3.5 shrink-0 text-slate-400" aria-hidden />
                            <span className="truncate">{d.dataset_name}</span>
                            <span className="shrink-0 text-xs tabular-nums text-slate-400">v{d.version_number}</span>
                          </div>
                        ))}
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
