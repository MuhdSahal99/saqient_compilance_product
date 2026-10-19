import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CalendarCheck, Loader2, Lock, MessageSquareText, Plus, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PREFIX_PATTERN } from "@/lib/audit";
import {
  closesKey,
  detailKey,
  fluxKey,
  useClosePeriod,
  useClosePeriods,
  useFluxReview,
  useFluxReviews,
  type CloseItemStatus,
  type ClosePeriod,
  type Flux,
  type FluxLine,
} from "@/lib/assurance";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { Amount, UnverifiedWarnings } from "@/components/calc-explain";
import { Field, MutationError, Share } from "@/components/audit/shared";
import {
  AssuranceNote,
  AssuranceStatusBadge,
  DatasetVersionSelect,
  EntitySelect,
  Facts,
  MemberSelect,
  PackFields,
  ReasonDialog,
  SignOffCard,
} from "@/components/assurance/shared";

const TABS = ["periods", "flux"] as const;
type Tab = (typeof TABS)[number];
const ITEM_STATUSES: CloseItemStatus[] = ["open", "in_progress", "done", "cancelled"];
const STATUS_TONE: Record<CloseItemStatus, "neutral" | "teal" | "green" | "amber"> = { open: "neutral", in_progress: "teal", done: "green", cancelled: "amber" };

const itemSchema = z.object({
  title: z.string().trim().min(1).max(300),
  day_offset: z.string().trim().regex(/^-?\d{1,3}$/).refine((v) => Number(v) >= -60 && Number(v) <= 120),
  owner_id: z.string(),
});
type ItemValues = z.infer<typeof itemSchema>;
const toItem = (v: ItemValues) => ({ title: v.title, day_offset: Number(v.day_offset), owner_id: v.owner_id || null });

const closeSchema = z.object({
  entity_id: z.string().min(1),
  name: z.string().trim().min(1).max(200),
  period_end: z.string().min(1),
  copy_from_id: z.string(),
  items: z.array(itemSchema),
});
type CloseValues = z.infer<typeof closeSchema>;

function NewCloseDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const closes = useClosePeriods();
  const form = useForm<CloseValues>({
    resolver: zodResolver(closeSchema),
    defaultValues: { entity_id: "", name: "", period_end: "", copy_from_id: "", items: [] },
  });
  const items = useFieldArray({ control: form.control, name: "items" });
  const create = useMutation({
    mutationFn: (v: CloseValues) =>
      api<ClosePeriod>("/close-periods", {
        json: { entity_id: v.entity_id, name: v.name, period_end: v.period_end, copy_from_id: v.copy_from_id || null, items: v.items.map(toItem) },
      }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: closesKey });
      close();
      navigate(`/close/periods/${p.id}`);
    },
  });
  function close() {
    form.reset();
    create.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{t("close.new")}</DialogTitle>
        <DialogDescription>{t("close.newHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <EntitySelect id="cp-entity" reg={form.register("entity_id")} error={!!err.entity_id} />
            <Field id="cp-name" label={t("recs.name")} error={err.name ? t("recs.nameRequired") : undefined}>
              <Input id="cp-name" aria-invalid={!!err.name} {...form.register("name")} />
            </Field>
            <Field id="cp-end" label={t("workpapers.periodEnd")} error={err.period_end ? t("rulePacks.dateRequired") : undefined}>
              <Input id="cp-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
            </Field>
            <Field id="cp-copy" label={t("close.copyFrom")} hint={t("close.copyFromHint")}>
              <Select id="cp-copy" {...form.register("copy_from_id")}>
                <option value="">{t("close.noCopy")}</option>
                {(closes.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} · {c.entity_name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="space-y-2">
            <p className="text-[13px] font-medium text-slate-700">{t("close.items")}</p>
            {items.fields.map((f, i) => (
              <div key={f.id} className="grid items-end gap-2 sm:grid-cols-[2fr_1fr_1.5fr_auto]">
                <Field id={`cpi-title-${i}`} label={t("close.itemTitle")} error={err.items?.[i]?.title ? t("recs.nameRequired") : undefined}>
                  <Input id={`cpi-title-${i}`} {...form.register(`items.${i}.title`)} />
                </Field>
                <Field id={`cpi-offset-${i}`} label={t("close.dayOffset")} error={err.items?.[i]?.day_offset ? t("close.dayOffsetRule") : undefined}>
                  <Input id={`cpi-offset-${i}`} dir="ltr" inputMode="numeric" {...form.register(`items.${i}.day_offset`)} />
                </Field>
                <MemberSelect id={`cpi-owner-${i}`} label={t("recs.owner")} reg={form.register(`items.${i}.owner_id`)} />
                <Button type="button" variant="ghost" size="icon" aria-label={t("close.removeItem")} onClick={() => items.remove(i)}>
                  <Trash2 aria-hidden />
                </Button>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" onClick={() => items.append({ title: "", day_offset: "0", owner_id: "" })}>
              <Plus aria-hidden /> {t("close.addItem")}
            </Button>
          </div>
          <MutationError error={create.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("close.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const fluxSchema = z
  .object({
    entity_id: z.string().min(1),
    name: z.string().trim().min(1).max(200),
    as_of: z.string().min(1),
    cy_tb_version_id: z.string().min(1),
    py_tb_version_id: z.string().min(1),
    rule_pack_version_id: z.string().min(1),
    rules_prefix: z.string().trim().min(1).max(80).regex(PREFIX_PATTERN),
  })
  .refine((v) => !v.cy_tb_version_id || v.cy_tb_version_id !== v.py_tb_version_id, { path: ["py_tb_version_id"], message: "same" });
type FluxValues = z.infer<typeof fluxSchema>;

function NewFluxDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<FluxValues>({
    resolver: zodResolver(fluxSchema),
    defaultValues: { entity_id: "", name: "", as_of: "", cy_tb_version_id: "", py_tb_version_id: "", rule_pack_version_id: "", rules_prefix: "" },
  });
  const create = useMutation({
    mutationFn: (v: FluxValues) => api<Flux>("/flux-reviews", { json: v }),
    onSuccess: (f) => {
      void qc.invalidateQueries({ queryKey: fluxKey });
      close();
      navigate(`/close/flux/${f.id}`);
    },
  });
  function close() {
    form.reset();
    create.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  const entityId = useWatch({ control: form.control, name: "entity_id" });
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{t("flux.new")}</DialogTitle>
        <DialogDescription>{t("flux.newHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <EntitySelect id="fx-entity" reg={form.register("entity_id")} error={!!err.entity_id} />
            <Field id="fx-name" label={t("recs.name")} error={err.name ? t("recs.nameRequired") : undefined}>
              <Input id="fx-name" aria-invalid={!!err.name} {...form.register("name")} />
            </Field>
            <Field id="fx-asof" label={t("recs.asOf")} error={err.as_of ? t("rulePacks.dateRequired") : undefined}>
              <Input id="fx-asof" type="date" aria-invalid={!!err.as_of} {...form.register("as_of")} />
            </Field>
            <span />
            <DatasetVersionSelect id="fx-cy" label={t("flux.currentTb")} entityId={entityId} kind="trial_balance" reg={form.register("cy_tb_version_id")} error={!!err.cy_tb_version_id} />
            <div>
              <DatasetVersionSelect
                id="fx-py"
                label={t("flux.priorTb")}
                entityId={entityId}
                kind="trial_balance"
                reg={form.register("py_tb_version_id")}
                error={!!err.py_tb_version_id && err.py_tb_version_id.message !== "same"}
              />
              {err.py_tb_version_id?.message === "same" && (
                <p role="alert" className="mt-1 text-xs font-medium text-red-600">
                  {t("flux.sameTb")}
                </p>
              )}
            </div>
          </div>
          <PackFields
            idPrefix="fx"
            packReg={form.register("rule_pack_version_id")}
            prefixReg={form.register("rules_prefix")}
            packError={!!err.rule_pack_version_id}
            prefixError={!!err.rules_prefix}
          />
          <MutationError error={create.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("flux.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CloseList() {
  const { t, i18n } = useTranslation();
  const list = useClosePeriods();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={CalendarCheck} title={t("close.empty")} description={t("close.emptyHint")} />;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("recs.name")}</TH>
          <TH>{t("workpapers.periodEnd")}</TH>
          <TH>{t("close.progress")}</TH>
          <TH>{t("recs.status")}</TH>
        </tr>
      </THead>
      <TBody>
        {list.data.map((p) => {
          const overdue = p.items.filter((i) => i.overdue).length;
          return (
            <TR key={p.id}>
              <TD className="align-top">
                <Link to={`/close/periods/${p.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                  {p.name}
                </Link>
                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                  <span>{p.entity_name}</span>
                  {p.is_demo && <SyntheticBadge />}
                </div>
              </TD>
              <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">{formatDate(p.period_end, i18n.language)}</TD>
              <TD className="align-top text-[13px] text-slate-600">
                {t("close.doneOf", { done: p.done, total: p.total })}
                {overdue > 0 && (
                  <Badge tone="red" className="ms-2">
                    {t("close.overdueCount", { count: overdue })}
                  </Badge>
                )}
              </TD>
              <TD className="align-top">
                <Badge tone={p.status === "closed" ? "green" : "teal"} dot>
                  {t(`close.status_${p.status}`)}
                </Badge>
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

function FluxList() {
  const { t, i18n } = useTranslation();
  const list = useFluxReviews();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={CalendarCheck} title={t("flux.empty")} description={t("flux.emptyHint")} />;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("recs.name")}</TH>
          <TH>{t("recs.asOf")}</TH>
          <TH>{t("flux.flagged")}</TH>
          <TH>{t("recs.status")}</TH>
        </tr>
      </THead>
      <TBody>
        {list.data.map((f) => (
          <TR key={f.id}>
            <TD className="align-top">
              <Link to={`/close/flux/${f.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                {f.name}
              </Link>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                <span>{f.entity_name}</span>
                {f.is_demo && <SyntheticBadge />}
              </div>
            </TD>
            <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">{formatDate(f.as_of, i18n.language)}</TD>
            <TD className="align-top text-[13px] text-slate-600">{t("flux.flaggedSummary", { exceeding: f.exceeding, unexplained: f.unexplained })}</TD>
            <TD className="align-top">
              <AssuranceStatusBadge status={f.sign_off.status} />
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function ClosePage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState<Tab | null>(null);
  const tab: Tab = params.get("tab") === "flux" ? "flux" : "periods";
  return (
    <>
      <PageHeader
        title={t("close.title")}
        description={t("close.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.close") }]}
        actions={
          can("write") && (
            <Button variant="accent" onClick={() => setOpen(tab)}>
              <Plus aria-hidden /> {tab === "flux" ? t("flux.new") : t("close.new")}
            </Button>
          )
        }
      />
      <div className="space-y-4">
        <Tabs
          label={t("close.title")}
          value={tab}
          onChange={(k) => setParams(k === "periods" ? {} : { tab: k }, { replace: true })}
          items={TABS.map((k) => ({ key: k, label: t(`close.tab.${k}`) }))}
        />
        <Card className="overflow-hidden">{tab === "periods" ? <CloseList /> : <FluxList />}</Card>
      </div>
      <NewCloseDialog open={open === "periods"} onOpenChange={(o) => setOpen(o ? "periods" : null)} />
      <NewFluxDialog open={open === "flux"} onOpenChange={(o) => setOpen(o ? "flux" : null)} />
    </>
  );
}

// ---------------------------------------------------------------- close detail

function AddItemForm({ p }: { p: ClosePeriod }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<ItemValues>({ resolver: zodResolver(itemSchema), defaultValues: { title: "", day_offset: "0", owner_id: "" } });
  const add = useMutation({
    mutationFn: (v: ItemValues) => api<ClosePeriod>(`/close-periods/${p.id}/items`, { json: toItem(v) }),
    onSuccess: (d) => {
      qc.setQueryData(detailKey(closesKey, p.id), d);
      void qc.invalidateQueries({ queryKey: [...closesKey, "list"] });
      form.reset();
      toast.success(t("close.itemAdded"));
    },
  });
  const err = form.formState.errors;
  return (
    <form className="grid items-end gap-3 sm:grid-cols-[2fr_1fr_1.5fr_auto]" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
      <Field id="ci-title" label={t("close.itemTitle")} error={err.title ? t("recs.nameRequired") : undefined}>
        <Input id="ci-title" aria-invalid={!!err.title} {...form.register("title")} />
      </Field>
      <Field id="ci-offset" label={t("close.dayOffset")} error={err.day_offset ? t("close.dayOffsetRule") : undefined}>
        <Input id="ci-offset" dir="ltr" inputMode="numeric" aria-invalid={!!err.day_offset} {...form.register("day_offset")} />
      </Field>
      <MemberSelect id="ci-owner" label={t("recs.owner")} reg={form.register("owner_id")} />
      <Button type="submit" variant="outline" disabled={add.isPending}>
        {add.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
        {t("close.addItem")}
      </Button>
      <div className="sm:col-span-4">
        <MutationError error={add.error} />
      </div>
    </form>
  );
}

export function ClosePeriodDetailPage() {
  const { periodId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useClosePeriod(periodId);
  const [closeOpen, setCloseOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [note, setNote] = useState("");
  const refresh = (d?: ClosePeriod) => {
    if (d) qc.setQueryData(detailKey(closesKey, d.id), d);
    else void qc.invalidateQueries({ queryKey: detailKey(closesKey, periodId ?? "") });
    void qc.invalidateQueries({ queryKey: [...closesKey, "list"] });
  };
  const setStatus = useMutation({
    mutationFn: (v: { taskId: string; status: CloseItemStatus }) => api(`/tasks/${v.taskId}`, { method: "PATCH", json: { status: v.status } }),
    onSuccess: () => {
      refresh();
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const closeIt = useMutation({
    mutationFn: () => api<ClosePeriod>(`/close-periods/${periodId}/close`, { json: { note } }),
    onSuccess: (d) => {
      refresh(d);
      setCloseOpen(false);
      setNote("");
      toast.success(t("close.closed"));
    },
  });
  const reopen = useMutation({
    mutationFn: (reason: string) => api<ClosePeriod>(`/close-periods/${periodId}/reopen`, { json: { reason } }),
    onSuccess: (d) => {
      refresh(d);
      setReopenOpen(false);
      toast.success(t("close.reopened"));
    },
  });
  if (q.isLoading) return <LoadingState />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const p = q.data;
  const isOpen = p.status === "open";
  const pendingItems = p.items.filter((i) => i.status !== "done" && i.status !== "cancelled").length;
  return (
    <>
      <PageHeader
        title={p.name}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {p.entity_name} · {formatDate(p.period_end, i18n.language)}
            {p.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.close"), to: "/close" }, { label: p.name }]}
        actions={
          <>
            <Badge tone={isOpen ? "teal" : "green"} dot>
              {t(`close.status_${p.status}`)}
            </Badge>
            {isOpen && can("decide") && (
              <Button variant="accent" disabled={pendingItems > 0} onClick={() => setCloseOpen(true)}>
                <Lock aria-hidden /> {t("close.closeAction")}
              </Button>
            )}
            {!isOpen && can("decide") && (
              <Button variant="outline" onClick={() => setReopenOpen(true)}>
                <RotateCcw aria-hidden /> {t("assurance.reopen")}
              </Button>
            )}
          </>
        }
      />
      <div className="space-y-5">
        {isOpen && pendingItems > 0 && can("decide") && <AssuranceNote>{t("close.pendingItems", { count: pendingItems })}</AssuranceNote>}
        {!isOpen && (
          <p className="text-[13px] text-slate-600">
            {t("close.closedBy", { name: p.closed_by_name ?? "—", date: formatDate(p.closed_at, i18n.language, true) })}
            {p.note && ` · ${p.note}`}
          </p>
        )}
        <MutationError error={setStatus.error} />
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{t("close.items")}</CardTitle>
            <CardDescription>{t("close.itemsHint", { done: p.done, total: p.total })}</CardDescription>
          </CardHeader>
          {p.items.length === 0 ? (
            <EmptyState icon={CalendarCheck} title={t("close.noItems")} />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("close.itemTitle")}</TH>
                  <TH>{t("close.due")}</TH>
                  <TH>{t("recs.owner")}</TH>
                  <TH>{t("recs.status")}</TH>
                </tr>
              </THead>
              <TBody>
                {p.items.map((it) => (
                  <TR key={it.id}>
                    <TD className="align-top text-[13px]">
                      <span className="font-medium text-navy-900">{it.title}</span>
                      {it.completion_note && <div className="text-xs text-slate-500">{it.completion_note}</div>}
                    </TD>
                    <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                      {formatDate(it.due_date, i18n.language)}
                      {it.overdue && (
                        <Badge tone="red" className="ms-2">
                          {t("close.overdue")}
                        </Badge>
                      )}
                    </TD>
                    <TD className="align-top text-[13px] text-slate-600">{it.owner_name ?? "—"}</TD>
                    <TD className="align-top">
                      {isOpen && can("write") ? (
                        <select
                          aria-label={t("close.itemStatus", { title: it.title })}
                          className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs"
                          value={it.status}
                          disabled={setStatus.isPending}
                          onChange={(e) => setStatus.mutate({ taskId: it.task_id, status: e.target.value as CloseItemStatus })}
                        >
                          {ITEM_STATUSES.map((s) => (
                            <option key={s} value={s}>
                              {t(`taskStatus.${s}`)}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <Badge tone={STATUS_TONE[it.status]} dot>
                          {t(`taskStatus.${it.status}`)}
                        </Badge>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
          {isOpen && can("write") && (
            <CardContent className="border-t border-slate-100">
              <AddItemForm p={p} />
            </CardContent>
          )}
        </Card>
      </div>
      <Dialog
        open={closeOpen}
        onOpenChange={(o) => {
          setCloseOpen(o);
          if (!o) closeIt.reset();
        }}
      >
        <DialogContent>
          <DialogTitle>{t("close.closeTitle")}</DialogTitle>
          <DialogDescription>{t("close.closeHint")}</DialogDescription>
          <form
            className="mt-5 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              closeIt.mutate();
            }}
          >
            <Field id="close-note" label={t("close.note")}>
              <Textarea id="close-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <MutationError error={closeIt.error} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCloseOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={closeIt.isPending}>
                {closeIt.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t("close.closeAction")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ReasonDialog
        open={reopenOpen}
        onOpenChange={(o) => {
          setReopenOpen(o);
          if (!o) reopen.reset();
        }}
        title={t("close.reopenTitle")}
        description={t("close.reopenHint")}
        confirmLabel={t("assurance.reopen")}
        busy={reopen.isPending}
        error={reopen.error}
        onConfirm={(reason) => reopen.mutate(reason)}
      />
    </>
  );
}

// ---------------------------------------------------------------- flux detail

function ExplainDialog({ f, line, onClose }: { f: Flux; line: FluxLine | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [forLine, setForLine] = useState<string | null>(null);
  if (line && forLine !== line.account_code) {
    setForLine(line.account_code);
    setText(line.explanation);
  }
  const save = useMutation({
    mutationFn: () => api<Flux>(`/flux-reviews/${f.id}/explanations`, { method: "PUT", json: { account_code: line?.account_code, explanation: text.trim() } }),
    onSuccess: (d) => {
      qc.setQueryData(detailKey(fluxKey, f.id), d);
      void qc.invalidateQueries({ queryKey: [...fluxKey, "list"] });
      toast.success(t("common.saved"));
      setForLine(null);
      onClose();
    },
  });
  return (
    <Dialog
      open={!!line}
      onOpenChange={(o) => {
        if (!o) {
          save.reset();
          setForLine(null);
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogTitle>{t("flux.explainTitle", { account: line ? `${line.account_code} ${line.account_name}` : "" })}</DialogTitle>
        <DialogDescription>{t("flux.explainHint")}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <Field id="flux-explanation" label={t("recs.explanation")}>
            <Textarea id="flux-explanation" rows={4} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function FluxDetailPage() {
  const { fluxId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const q = useFluxReview(fluxId);
  const [line, setLine] = useState<FluxLine | null>(null);
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  if (q.isLoading) return <LoadingState />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const f = q.data;
  const editable = can("write") && f.sign_off.status !== "signed_off";
  const lines = onlyFlagged ? f.lines.filter((l) => l.exceeds) : f.lines;
  return (
    <>
      <PageHeader
        title={f.name}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {f.entity_name} · {formatDate(f.as_of, i18n.language)}
            {f.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.close"), to: "/close?tab=flux" }, { label: f.name }]}
        actions={<AssuranceStatusBadge status={f.sign_off.status} />}
      />
      <div className="space-y-5">
        <AssuranceNote>{t("flux.note")}</AssuranceNote>
        <UnverifiedWarnings warnings={f.warnings} />
        <Card>
          <CardContent>
            <Facts
              items={[
                { label: t("flux.thresholdAbs"), value: <Amount value={f.threshold_abs} currency={f.currency} /> },
                { label: t("flux.thresholdPct"), value: <Share value={f.threshold_pct} /> },
                { label: t("flux.exceeding"), value: f.exceeding },
                { label: t("flux.unexplained"), value: f.unexplained },
              ]}
            />
          </CardContent>
        </Card>
        <Card className="overflow-hidden">
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle>{t("flux.lines")}</CardTitle>
            <label className="flex items-center gap-2 text-[13px] text-slate-600">
              <input type="checkbox" className="size-4 accent-teal-600" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} />
              {t("flux.onlyFlagged")}
            </label>
          </CardHeader>
          {lines.length === 0 ? (
            <EmptyState title={t("flux.noLines")} />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("recs.account.account")}</TH>
                  <TH className="text-end">{t("flux.current")}</TH>
                  <TH className="text-end">{t("flux.prior")}</TH>
                  <TH className="text-end">{t("flux.change")}</TH>
                  <TH className="text-end">{t("flux.changePct")}</TH>
                  <TH>{t("recs.explanation")}</TH>
                </tr>
              </THead>
              <TBody>
                {lines.map((l) => (
                  <TR key={l.account_code} className={l.exceeds && !l.explanation ? "bg-amber-50/50" : undefined}>
                    <TD className="align-top text-[13px]">
                      <span dir="ltr" className="font-medium text-navy-900">
                        {l.account_code}
                      </span>{" "}
                      {l.account_name}
                      {l.exceeds && (
                        <div className="mt-1">
                          <Badge tone="amber">{t("flux.overThreshold")}</Badge>
                        </div>
                      )}
                    </TD>
                    <TD className="align-top text-end">
                      <Amount value={l.current} />
                    </TD>
                    <TD className="align-top text-end">
                      <Amount value={l.prior} />
                    </TD>
                    <TD className="align-top text-end">
                      <Amount value={l.change} />
                    </TD>
                    <TD className="align-top text-end">
                      <Share value={l.change_pct} />
                    </TD>
                    <TD className="align-top text-[13px] text-slate-600">
                      {l.explanation ? (
                        <>
                          <p>{l.explanation}</p>
                          {l.explained_by_name && <p className="text-xs text-slate-400">{l.explained_by_name}</p>}
                        </>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                      {editable && (
                        <Button size="sm" variant="ghost" className="mt-1" onClick={() => setLine(l)} aria-label={t("flux.explainAccount", { account: l.account_code })}>
                          <MessageSquareText aria-hidden />
                          {l.explanation ? t("flux.edit") : t("flux.explain")}
                        </Button>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <SignOffCard base="/flux-reviews" listKey={fluxKey} obj={f} blocker={f.unexplained > 0 ? t("flux.unexplainedBlocks", { count: f.unexplained }) : null} />
      </div>
      <ExplainDialog f={f} line={line} onClose={() => setLine(null)} />
    </>
  );
}
