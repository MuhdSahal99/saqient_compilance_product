import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Calculator, FilePlus2, Loader2, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { AUDIT_WORKPAPER_KINDS, WORKPAPER_KINDS, type Workpaper } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useEntities, usePublishedRulePacks, useWorkpapers, workpapersKey } from "@/lib/queries";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, errorMessage, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { LossRegisterPanel } from "@/components/loss-register";
import { TransferPricingPanel } from "@/components/transfer-pricing";

const PREFIX_PATTERN = /^[a-z0-9_]+(\.[a-z0-9_]+)*$/;

/** Placeholder text only; the prefix depends on the rule pack the user chose. */
const PREFIX_PLACEHOLDER: Record<(typeof WORKPAPER_KINDS)[number], string> = {
  corporate_tax: "syn.ct",
  sbr_test: "syn.ct",
  qfzp_test: "syn.ct",
  pillar_two: "syn.p2",
  zakat: "syn.zakat",
  lease_ifrs16: "syn.audit",
};

const newSchema = z
  .object({
    entity_id: z.string().min(1),
    kind: z.enum(WORKPAPER_KINDS),
    title: z.string().trim().min(1).max(300),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
    rule_pack_version_id: z.string().min(1),
    rules_prefix: z.string().trim().min(1).max(80).regex(PREFIX_PATTERN),
    currency: z.union([z.literal(""), z.string().trim().toUpperCase().regex(/^[A-Z]{3}$/)]),
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type NewValues = z.input<typeof newSchema>;
type NewParsed = z.output<typeof newSchema>;

function NewWorkpaperDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const entities = useEntities(open);
  const packs = usePublishedRulePacks(open);
  const form = useForm<NewValues, unknown, NewParsed>({
    resolver: zodResolver(newSchema),
    defaultValues: { entity_id: "", kind: "corporate_tax", title: "", period_start: "", period_end: "", rule_pack_version_id: "", rules_prefix: "", currency: "" },
  });
  const create = useMutation({
    mutationFn: (v: NewParsed) =>
      api<Workpaper>("/workpapers", {
        json: {
          entity_id: v.entity_id,
          kind: v.kind,
          title: v.title,
          period_start: v.period_start,
          period_end: v.period_end,
          rule_pack_version_id: v.rule_pack_version_id,
          rules_prefix: v.rules_prefix,
          ...(v.currency ? { currency: v.currency } : {}),
        },
      }),
    onSuccess: (wp) => {
      void qc.invalidateQueries({ queryKey: workpapersKey });
      close();
      navigate(`/workpapers/${wp.id}`);
    },
  });
  function close() {
    form.reset();
    create.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  const kind = useWatch({ control: form.control, name: "kind" });
  const packId = useWatch({ control: form.control, name: "rule_pack_version_id" });
  const selectedPack = packs.items.find((x) => x.v.id === packId);
  const loading = entities.isLoading || packs.query.isLoading;
  const failed = entities.isError || packs.query.isError;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogTitle>{t("workpapers.new")}</DialogTitle>
        <DialogDescription>{t("workpapers.newHint")}</DialogDescription>
        {loading && <LoadingState rows={3} />}
        {failed && (
          <ErrorState
            error={entities.error ?? packs.query.error}
            onRetry={() => {
              void entities.refetch();
              void packs.query.refetch();
            }}
          />
        )}
        {entities.data && packs.query.data && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="wp-entity">{t("datasets.entity")}</Label>
                <Select id="wp-entity" aria-invalid={!!err.entity_id} {...form.register("entity_id")}>
                  <option value="">{t("datasets.chooseEntity")}</option>
                  {entities.data.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </Select>
                <FieldError message={err.entity_id ? t("datasets.entityRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="wp-kind">{t("workpapers.kind")}</Label>
                <Select id="wp-kind" {...form.register("kind")}>
                  {WORKPAPER_KINDS.map((k) => (
                    <option key={k} value={k}>
                      {t(`workpaperKind.${k}`)}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="wp-title">{t("workpapers.titleField")}</Label>
              <Input id="wp-title" aria-invalid={!!err.title} {...form.register("title")} />
              <FieldError message={err.title ? t("workpapers.titleRequired") : undefined} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="wp-start">{t("workpapers.periodStart")}</Label>
                <Input id="wp-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
                <FieldError message={err.period_start ? t("rulePacks.dateRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="wp-end">{t("workpapers.periodEnd")}</Label>
                <Input id="wp-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
                <FieldError
                  message={err.period_end ? (err.period_end.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired")) : undefined}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="wp-pack">{t("reviews.rulePack")}</Label>
              <Select id="wp-pack" aria-invalid={!!err.rule_pack_version_id} {...form.register("rule_pack_version_id")}>
                <option value="">{t("taxCalendar.choosePack")}</option>
                {packs.items.map(({ p, v }) => (
                  <option key={v.id} value={v.id}>
                    {p.name} · v{v.version_number}
                    {p.is_synthetic ? ` · ${t("common.synthetic")}` : ""}
                    {v.unverified_count > 0 ? ` · ${t("rulePacks.unverifiedCount", { count: v.unverified_count })}` : ""}
                  </option>
                ))}
              </Select>
              <FieldError message={err.rule_pack_version_id ? t("taxCalendar.packRequired") : undefined} />
            </div>
            {selectedPack && selectedPack.v.unverified_count > 0 && (
              <p className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-orange-900">
                <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                {t("directTax.unverifiedPack")}
              </p>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="wp-prefix">{t("directTax.rulesPrefix")}</Label>
                <Input
                  id="wp-prefix"
                  dir="ltr"
                  placeholder={PREFIX_PLACEHOLDER[kind]}
                  aria-invalid={!!err.rules_prefix}
                  aria-describedby="wp-prefix-hint"
                  {...form.register("rules_prefix")}
                />
                <p id="wp-prefix-hint" className="text-xs text-slate-500">
                  {t("directTax.rulesPrefixHint")}
                </p>
                <FieldError message={err.rules_prefix ? t("rulePacks.ruleKeyRule") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="wp-currency">{t("workpapers.currency")}</Label>
                <Input id="wp-currency" dir="ltr" maxLength={3} aria-invalid={!!err.currency} aria-describedby="wp-currency-hint" {...form.register("currency")} />
                <p id="wp-currency-hint" className="text-xs text-slate-500">
                  {t("workpapers.currencyHint")}
                </p>
                <FieldError message={err.currency ? t("workpapers.currencyRule") : undefined} />
              </div>
            </div>
            {create.isError && (
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {errorMessage(create.error, t("common.genericError"))}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={create.isPending}>
                {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t("workpapers.create")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function WorkpaperStatusBadge({ status }: { status: Workpaper["status"] }) {
  const { t } = useTranslation();
  return (
    <Badge tone={status === "signed_off" ? "green" : "neutral"} dot>
      {t(`workpaperStatus.${status}`)}
    </Badge>
  );
}

function WorkpaperList({ entityId }: { entityId: string }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [kind, setKind] = useState("");
  const list = useWorkpapers({ entityId, kind });
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 p-3">
        <div className="space-y-1">
          <Label htmlFor="wp-filter-kind">{t("workpapers.kind")}</Label>
          <Select id="wp-filter-kind" className="w-56" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">{t("workpapers.allKinds")}</option>
            {[...WORKPAPER_KINDS, ...AUDIT_WORKPAPER_KINDS].map((k) => (
              <option key={k} value={k}>
                {t(`workpaperKind.${k}`)}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {list.isLoading && <LoadingState />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.data?.length === 0 && (
        <EmptyState icon={Calculator} title={t("workpapers.empty")} description={can("write") ? t("workpapers.emptyHintWriter") : t("workpapers.emptyHint")} />
      )}
      {list.data && list.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("workpapers.titleField")}</TH>
              <TH>{t("workpapers.kind")}</TH>
              <TH>{t("workpapers.period")}</TH>
              <TH>{t("workpapers.status")}</TH>
              <TH>{t("workpapers.computedAt")}</TH>
            </tr>
          </THead>
          <TBody>
            {list.data.map((w) => (
              <TR key={w.id}>
                <TD className="align-top">
                  <Link to={`/workpapers/${w.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                    {w.title}
                  </Link>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                    <span>{w.entity_name}</span>
                    {w.is_demo && <SyntheticBadge />}
                  </div>
                </TD>
                <TD className="align-top">
                  <Badge tone="neutral">{t(`workpaperKind.${w.kind}`)}</Badge>
                </TD>
                <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                  {formatDate(w.period_start, i18n.language)} – {formatDate(w.period_end, i18n.language)}
                </TD>
                <TD className="align-top">
                  <WorkpaperStatusBadge status={w.status} />
                </TD>
                <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                  {w.computed_at ? formatDate(w.computed_at, i18n.language, true) : t("workpapers.notComputed")}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}

type Tab = "workpapers" | "losses" | "tp";

export function WorkpapersPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(false);
  const tabParam = params.get("tab");
  const tab: Tab = tabParam === "losses" || tabParam === "tp" ? tabParam : "workpapers";
  const entityId = params.get("entity") ?? "";
  const entities = useEntities();
  const update = (next: { tab?: Tab; entity?: string }) => {
    const sp = new URLSearchParams(params);
    if (next.tab !== undefined) {
      if (next.tab === "workpapers") sp.delete("tab");
      else sp.set("tab", next.tab);
    }
    if (next.entity !== undefined) {
      if (next.entity) sp.set("entity", next.entity);
      else sp.delete("entity");
    }
    setParams(sp, { replace: true });
  };
  const needsEntity = tab !== "workpapers";
  return (
    <>
      <PageHeader
        title={t("directTax.title")}
        description={t("directTax.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.directTax") }]}
        actions={
          can("write") &&
          tab === "workpapers" && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <FilePlus2 aria-hidden /> {t("workpapers.new")}
            </Button>
          )
        }
      />
      <div className="space-y-4">
        <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          {t("directTax.disclaimer")}
        </p>
        <Tabs<Tab>
          label={t("directTax.title")}
          value={tab}
          onChange={(k) => update({ tab: k })}
          items={[
            { key: "workpapers", label: t("directTax.tabs.workpapers") },
            { key: "losses", label: t("directTax.tabs.losses") },
            { key: "tp", label: t("directTax.tabs.tp") },
          ]}
        />
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="dt-entity">{t("datasets.entity")}</Label>
            <Select id="dt-entity" className="w-64" value={entityId} onChange={(e) => update({ entity: e.target.value })}>
              <option value="">{needsEntity ? t("datasets.chooseEntity") : t("einvoices.allEntities")}</option>
              {(entities.data ?? []).map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name}
                </option>
              ))}
            </Select>
          </div>
          {entities.isError && (
            <Button variant="outline" size="sm" onClick={() => void entities.refetch()}>
              {t("common.retry")}
            </Button>
          )}
        </div>
        {tab === "workpapers" && <WorkpaperList entityId={entityId} />}
        {needsEntity && !entityId && (
          <Card>
            <EmptyState icon={Calculator} title={t("directTax.chooseEntity")} description={t("directTax.chooseEntityHint")} />
          </Card>
        )}
        {tab === "losses" && entityId && <LossRegisterPanel entityId={entityId} />}
        {tab === "tp" && entityId && <TransferPricingPanel entityId={entityId} />}
      </div>
      <NewWorkpaperDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
