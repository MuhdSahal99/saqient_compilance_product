import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowLeftRight, Download, Loader2, Plus, Trash2, TriangleAlert, Users } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import {
  RELATED_PARTY_RELATIONS,
  RP_TRANSACTION_TYPES,
  TP_METHODS,
  type RelatedParty,
  type RPTransaction,
  type TPCheckResult,
} from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { relatedPartiesKey, rpTransactionsKey, usePublishedRulePacks, useRelatedParties, useRpTransactions } from "@/lib/queries";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, errorMessage, LoadingState, SyntheticBadge, useUnsavedChangesWarning } from "@/components/common";
import { Amount, ExplainedLine, LineValue, UnverifiedWarnings } from "@/components/calc-explain";

const POSITIVE_AMOUNT = /^(?!0+(\.0+)?$)\d{1,16}(\.\d{1,4})?$/;
const NON_NEGATIVE_AMOUNT = /^\d{1,16}(\.\d{1,4})?$/;
const RATIO = /^-?\d{1,14}(\.\d{1,6})?$/;
const PREFIX_PATTERN = /^[a-z0-9_]+(\.[a-z0-9_]+)*$/;

function ErrorNote({ error }: { error: unknown }) {
  const { t } = useTranslation();
  return (
    <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {errorMessage(error, t("common.genericError"))}
    </p>
  );
}

function dateOrderMessage(t: (k: string) => string, e?: { message?: string }) {
  if (!e) return undefined;
  return e.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired");
}

// ---------------------------------------------------------------- related parties

const partySchema = z.object({
  name: z.string().trim().min(1).max(200),
  relation: z.enum(RELATED_PARTY_RELATIONS),
  jurisdiction: z.string().trim().toUpperCase().regex(/^[A-Z]{2}$/),
  note: z.string().max(4000),
});
type PartyValues = z.input<typeof partySchema>;
type PartyParsed = z.output<typeof partySchema>;

function PartiesCard({ entityId }: { entityId: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const parties = useRelatedParties(entityId);
  const [removing, setRemoving] = useState<RelatedParty | null>(null);
  const form = useForm<PartyValues, unknown, PartyParsed>({
    resolver: zodResolver(partySchema),
    defaultValues: { name: "", relation: "parent", jurisdiction: "", note: "" },
  });
  useUnsavedChangesWarning(form.formState.isDirty);
  const add = useMutation({
    mutationFn: (v: PartyParsed) => api<RelatedParty>(`/entities/${entityId}/related-parties`, { json: v }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: relatedPartiesKey(entityId) });
      form.reset();
      toast.success(t("tp.partyAdded"));
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/related-parties/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: relatedPartiesKey(entityId) });
      void qc.invalidateQueries({ queryKey: rpTransactionsKey(entityId) });
      setRemoving(null);
      toast.success(t("tp.partyRemoved"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const err = form.formState.errors;
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("tp.parties")}</CardTitle>
        <CardDescription>{t("tp.partiesHint")}</CardDescription>
      </CardHeader>
      {parties.isLoading && <LoadingState rows={2} />}
      {parties.isError && <ErrorState error={parties.error} onRetry={() => void parties.refetch()} />}
      {parties.data?.length === 0 && <EmptyState icon={Users} title={t("tp.noParties")} />}
      {parties.data && parties.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("tp.partyName")}</TH>
              <TH>{t("tp.relation")}</TH>
              <TH>{t("tp.jurisdiction")}</TH>
              {can("write") && <TH className="w-12">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {parties.data.map((p) => (
              <TR key={p.id}>
                <TD>
                  <span className="font-medium text-navy-900">{p.name}</span>
                  {p.is_demo && <SyntheticBadge className="ms-2" />}
                  {p.note && <p className="mt-0.5 text-xs text-slate-500">{p.note}</p>}
                </TD>
                <TD className="text-[13px] text-slate-600">{t(`tpRelation.${p.relation}`)}</TD>
                <TD className="font-mono text-[13px] text-slate-600" dir="ltr">
                  {p.jurisdiction}
                </TD>
                {can("write") && (
                  <TD>
                    <Button variant="ghost" size="icon-sm" aria-label={t("tp.removePartyNamed", { name: p.name })} onClick={() => setRemoving(p)}>
                      <Trash2 aria-hidden />
                    </Button>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {can("write") && parties.data && (
        <CardContent className="border-t border-slate-100">
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor="rp-name">{t("tp.partyName")}</Label>
                <Input id="rp-name" aria-invalid={!!err.name} {...form.register("name")} />
                <FieldError message={err.name ? t("tp.partyNameRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rp-relation">{t("tp.relation")}</Label>
                <Select id="rp-relation" {...form.register("relation")}>
                  {RELATED_PARTY_RELATIONS.map((r) => (
                    <option key={r} value={r}>
                      {t(`tpRelation.${r}`)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rp-jur">{t("tp.jurisdiction")}</Label>
                <Input id="rp-jur" dir="ltr" maxLength={2} aria-invalid={!!err.jurisdiction} aria-describedby="rp-jur-hint" {...form.register("jurisdiction")} />
                <p id="rp-jur-hint" className="text-xs text-slate-500">
                  {t("tp.jurisdictionHint")}
                </p>
                <FieldError message={err.jurisdiction ? t("tp.jurisdictionRule") : undefined} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rp-note">{t("losses.note")}</Label>
              <Input id="rp-note" {...form.register("note")} />
            </div>
            {add.isError && <ErrorNote error={add.error} />}
            <div className="flex justify-end">
              <Button type="submit" variant="outline" disabled={add.isPending}>
                {add.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
                {t("tp.addParty")}
              </Button>
            </div>
          </form>
        </CardContent>
      )}
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("tp.removePartyTitle")}
        description={t("tp.removePartyDescription", { name: removing?.name ?? "" })}
        confirmLabel={t("common.delete")}
        destructive
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
      />
    </Card>
  );
}

// ---------------------------------------------------------------- transactions

const optRatio = z.union([z.literal(""), z.string().trim().regex(RATIO)]);
const txnSchema = z
  .object({
    related_party_id: z.string().min(1),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
    transaction_type: z.enum(RP_TRANSACTION_TYPES),
    direction: z.enum(["receipt", "payment"]),
    description: z.string().max(500),
    amount: z.string().trim().regex(POSITIVE_AMOUNT),
    method: z.enum(TP_METHODS),
    range_low: optRatio,
    range_high: optRatio,
    tested_value: optRatio,
    range_metric: z.string().max(80),
  })
  .superRefine((v, ctx) => {
    if (v.period_start && v.period_end && v.period_end < v.period_start)
      ctx.addIssue({ code: "custom", path: ["period_end"], message: "order" });
    if (!!v.range_low !== !!v.range_high) ctx.addIssue({ code: "custom", path: ["range_high"], message: "both" });
    if (v.tested_value && !v.range_low) ctx.addIssue({ code: "custom", path: ["tested_value"], message: "range" });
  });
type TxnValues = z.infer<typeof txnSchema>;

function TransactionsCard({ entityId }: { entityId: string }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const parties = useRelatedParties(entityId);
  const txns = useRpTransactions(entityId);
  const [removing, setRemoving] = useState<RPTransaction | null>(null);
  const form = useForm<TxnValues>({
    resolver: zodResolver(txnSchema),
    defaultValues: {
      related_party_id: "",
      period_start: "",
      period_end: "",
      transaction_type: "services",
      direction: "payment",
      description: "",
      amount: "",
      method: "not_set",
      range_low: "",
      range_high: "",
      tested_value: "",
      range_metric: "",
    },
  });
  useUnsavedChangesWarning(form.formState.isDirty);
  const add = useMutation({
    mutationFn: (v: TxnValues) =>
      api<RPTransaction>(`/entities/${entityId}/rp-transactions`, {
        json: {
          ...v,
          range_low: v.range_low || null,
          range_high: v.range_high || null,
          tested_value: v.tested_value || null,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: rpTransactionsKey(entityId) });
      form.reset();
      toast.success(t("tp.txnAdded"));
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/rp-transactions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: rpTransactionsKey(entityId) });
      setRemoving(null);
      toast.success(t("tp.txnRemoved"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const err = form.formState.errors;
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("tp.transactions")}</CardTitle>
        <CardDescription>{t("tp.transactionsHint")}</CardDescription>
      </CardHeader>
      {txns.isLoading && <LoadingState rows={2} />}
      {txns.isError && <ErrorState error={txns.error} onRetry={() => void txns.refetch()} />}
      {txns.data?.length === 0 && <EmptyState icon={ArrowLeftRight} title={t("tp.noTxns")} />}
      {txns.data && txns.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("tp.party")}</TH>
              <TH>{t("tp.type")}</TH>
              <TH>{t("workpapers.period")}</TH>
              <TH className="text-end">{t("losses.amount")}</TH>
              <TH>{t("tp.method")}</TH>
              <TH>{t("tp.range")}</TH>
              {can("write") && <TH className="w-12">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {txns.data.map((x) => (
              <TR key={x.id}>
                <TD className="align-top">
                  <span className="font-medium text-navy-900">{x.related_party_name}</span>
                  {x.is_demo && <SyntheticBadge className="ms-2" />}
                  {x.description && <p className="mt-0.5 text-xs text-slate-500">{x.description}</p>}
                </TD>
                <TD className="align-top text-[13px] text-slate-600">
                  {t(`tpType.${x.transaction_type}`)}
                  <Badge tone="neutral" className="ms-1.5">
                    {t(`tpDirection.${x.direction}`)}
                  </Badge>
                </TD>
                <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                  {formatDate(x.period_start, i18n.language)} – {formatDate(x.period_end, i18n.language)}
                </TD>
                <TD className="whitespace-nowrap text-end align-top">
                  <Amount value={x.amount} currency={x.currency} />
                </TD>
                <TD className="align-top text-[13px] text-slate-600">{t(`tpMethod.${x.method}`)}</TD>
                <TD className="align-top text-[13px] text-slate-600">
                  {x.range_low != null && x.range_high != null ? (
                    <span dir="ltr" className="font-mono text-xs">
                      {x.range_low} – {x.range_high}
                      {x.tested_value != null && ` · ${x.tested_value}`}
                      {x.range_metric && ` (${x.range_metric})`}
                    </span>
                  ) : (
                    "—"
                  )}
                </TD>
                {can("write") && (
                  <TD className="align-top">
                    <Button variant="ghost" size="icon-sm" aria-label={t("tp.removeTxnNamed", { name: x.related_party_name })} onClick={() => setRemoving(x)}>
                      <Trash2 aria-hidden />
                    </Button>
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      {can("write") && parties.data && parties.data.length > 0 && txns.data && (
        <CardContent className="border-t border-slate-100">
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor="tx-party">{t("tp.party")}</Label>
                <Select id="tx-party" aria-invalid={!!err.related_party_id} {...form.register("related_party_id")}>
                  <option value="">{t("tp.chooseParty")}</option>
                  {parties.data.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
                <FieldError message={err.related_party_id ? t("tp.partyRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-type">{t("tp.type")}</Label>
                <Select id="tx-type" {...form.register("transaction_type")}>
                  {RP_TRANSACTION_TYPES.map((k) => (
                    <option key={k} value={k}>
                      {t(`tpType.${k}`)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-direction">{t("tp.direction")}</Label>
                <Select id="tx-direction" {...form.register("direction")}>
                  {(["receipt", "payment"] as const).map((k) => (
                    <option key={k} value={k}>
                      {t(`tpDirection.${k}`)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-start">{t("workpapers.periodStart")}</Label>
                <Input id="tx-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
                <FieldError message={err.period_start ? t("rulePacks.dateRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-end">{t("workpapers.periodEnd")}</Label>
                <Input id="tx-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
                <FieldError message={dateOrderMessage(t, err.period_end)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-amount">{t("losses.amount")}</Label>
                <Input id="tx-amount" dir="ltr" inputMode="decimal" aria-invalid={!!err.amount} {...form.register("amount")} />
                <FieldError message={err.amount ? t("directTax.positiveAmountRule") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-method">{t("tp.method")}</Label>
                <Select id="tx-method" {...form.register("method")}>
                  {TP_METHODS.map((k) => (
                    <option key={k} value={k}>
                      {t(`tpMethod.${k}`)}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-low">{t("tp.rangeLow")}</Label>
                <Input id="tx-low" dir="ltr" inputMode="decimal" aria-invalid={!!err.range_low} {...form.register("range_low")} />
                <FieldError message={err.range_low ? t("tp.ratioRule") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-high">{t("tp.rangeHigh")}</Label>
                <Input id="tx-high" dir="ltr" inputMode="decimal" aria-invalid={!!err.range_high} {...form.register("range_high")} />
                <FieldError message={err.range_high ? (err.range_high.message === "both" ? t("tp.rangeBoth") : t("tp.ratioRule")) : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-tested">{t("tp.testedValue")}</Label>
                <Input id="tx-tested" dir="ltr" inputMode="decimal" aria-invalid={!!err.tested_value} {...form.register("tested_value")} />
                <FieldError message={err.tested_value ? (err.tested_value.message === "range" ? t("tp.testedNeedsRange") : t("tp.ratioRule")) : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tx-metric">{t("tp.rangeMetric")}</Label>
                <Input id="tx-metric" {...form.register("range_metric")} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tx-desc">{t("tp.description")}</Label>
              <Textarea id="tx-desc" rows={2} {...form.register("description")} />
            </div>
            {add.isError && <ErrorNote error={add.error} />}
            <div className="flex justify-end">
              <Button type="submit" variant="outline" disabled={add.isPending}>
                {add.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
                {t("tp.addTxn")}
              </Button>
            </div>
          </form>
        </CardContent>
      )}
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("tp.removeTxnTitle")}
        description={t("tp.removeTxnDescription", { name: removing?.related_party_name ?? "" })}
        confirmLabel={t("common.delete")}
        destructive
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
      />
    </Card>
  );
}

// ---------------------------------------------------------------- threshold check + disclosure

const checkSchema = z
  .object({
    rule_pack_version_id: z.string().min(1),
    rules_prefix: z.string().trim().min(1).max(80).regex(PREFIX_PATTERN),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
    entity_revenue: z.string().trim().regex(NON_NEGATIVE_AMOUNT),
    in_mne_group: z.enum(["", "yes", "no"]),
    group_revenue: z.union([z.literal(""), z.string().trim().regex(NON_NEGATIVE_AMOUNT)]),
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type CheckValues = z.infer<typeof checkSchema>;

function CheckCard({ entityId }: { entityId: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const packs = usePublishedRulePacks();
  const [result, setResult] = useState<TPCheckResult | null>(null);
  const form = useForm<CheckValues>({
    resolver: zodResolver(checkSchema),
    defaultValues: { rule_pack_version_id: "", rules_prefix: "", period_start: "", period_end: "", entity_revenue: "", in_mne_group: "", group_revenue: "" },
  });
  const check = useMutation({
    mutationFn: (v: CheckValues) =>
      api<TPCheckResult>(`/entities/${entityId}/tp/check`, {
        json: {
          rule_pack_version_id: v.rule_pack_version_id,
          rules_prefix: v.rules_prefix,
          period_start: v.period_start,
          period_end: v.period_end,
          entity_revenue: v.entity_revenue,
          in_mne_group: v.in_mne_group === "" ? null : v.in_mne_group === "yes",
          group_revenue: v.group_revenue || null,
        },
      }),
    onSuccess: setResult,
  });
  const err = form.formState.errors;
  const [start, end] = useWatch({ control: form.control, name: ["period_start", "period_end"] });
  const disclosureHref =
    start && end && end >= start ? `/api/entities/${entityId}/tp/disclosure.csv${qs({ period_start: start, period_end: end })}` : null;
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("tp.check")}</CardTitle>
        <CardDescription>{t("tp.checkHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {packs.query.isLoading && <LoadingState rows={2} />}
        {packs.query.isError && <ErrorState error={packs.query.error} onRetry={() => void packs.query.refetch()} />}
        {packs.query.data && (
          <form className="space-y-3" onSubmit={form.handleSubmit((v) => check.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="tpc-pack">{t("reviews.rulePack")}</Label>
                <Select id="tpc-pack" aria-invalid={!!err.rule_pack_version_id} {...form.register("rule_pack_version_id")}>
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
              <div className="space-y-1.5">
                <Label htmlFor="tpc-prefix">{t("directTax.rulesPrefix")}</Label>
                <Input id="tpc-prefix" dir="ltr" placeholder="syn.tp" aria-invalid={!!err.rules_prefix} {...form.register("rules_prefix")} />
                <FieldError message={err.rules_prefix ? t("rulePacks.ruleKeyRule") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpc-start">{t("workpapers.periodStart")}</Label>
                <Input id="tpc-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
                <FieldError message={err.period_start ? t("rulePacks.dateRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpc-end">{t("workpapers.periodEnd")}</Label>
                <Input id="tpc-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
                <FieldError message={dateOrderMessage(t, err.period_end)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpc-revenue">{t("tp.entityRevenue")}</Label>
                <Input id="tpc-revenue" dir="ltr" inputMode="decimal" aria-invalid={!!err.entity_revenue} {...form.register("entity_revenue")} />
                <FieldError message={err.entity_revenue ? t("directTax.amountRule") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpc-mne">{t("tp.inMneGroup")}</Label>
                <Select id="tpc-mne" {...form.register("in_mne_group")}>
                  <option value="">{t("tp.notStated")}</option>
                  <option value="yes">{t("directTax.yes")}</option>
                  <option value="no">{t("directTax.no")}</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpc-group">{t("tp.groupRevenue")}</Label>
                <Input id="tpc-group" dir="ltr" inputMode="decimal" aria-invalid={!!err.group_revenue} {...form.register("group_revenue")} />
                <FieldError message={err.group_revenue ? t("directTax.amountRule") : undefined} />
              </div>
            </div>
            {check.isError && <ErrorNote error={check.error} />}
            <div className="flex flex-wrap items-center justify-end gap-2">
              {disclosureHref ? (
                <Button asChild variant="outline">
                  <a href={disclosureHref}>
                    <Download aria-hidden /> {t("tp.disclosureCsv")}
                  </a>
                </Button>
              ) : (
                <span className="text-xs text-slate-500">{t("tp.disclosureNeedsPeriod")}</span>
              )}
              {can("write") && (
                <Button type="submit" variant="accent" disabled={check.isPending}>
                  {check.isPending && <Loader2 className="animate-spin" aria-hidden />}
                  {t("tp.runCheck")}
                </Button>
              )}
            </div>
          </form>
        )}
        {result && (
          <div className="space-y-3" aria-live="polite">
            <UnverifiedWarnings warnings={result.warnings} />
            <dl className="grid gap-2 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-200 px-3 py-2">
                <dt className="text-xs text-slate-500">{t("tp.rpTotal")}</dt>
                <dd className="text-lg font-semibold">
                  <Amount value={result.rp_total} currency={result.currency} className="text-lg" />
                </dd>
              </div>
              <div className="rounded-lg border border-slate-200 px-3 py-2">
                <dt className="text-xs text-slate-500">{t("tp.txnCount")}</dt>
                <dd className="text-lg font-semibold tabular-nums text-navy-900">{result.transaction_count}</dd>
              </div>
            </dl>
            <p className="flex items-start gap-2 text-xs text-slate-500">
              <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
              {t("directTax.indicationNote")}
            </p>
            <ul className="overflow-hidden rounded-lg border border-slate-200">
              {result.lines.map((l) => (
                <ExplainedLine
                  key={l.key}
                  label={l.label}
                  value={l.amount != null ? <Amount value={l.amount} /> : <LineValue value={l.value} />}
                  formulaId={l.formula_id}
                  steps={l.explanation}
                  rules={l.rule_snapshots}
                />
              ))}
            </ul>
            <p className="text-[11px] text-slate-400" dir="ltr">
              {result.calc_version} · {result.result_hash.slice(0, 16)}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function TransferPricingPanel({ entityId }: { entityId: string }) {
  return (
    <div className="space-y-4">
      <PartiesCard entityId={entityId} />
      <TransactionsCard entityId={entityId} />
      <CheckCard entityId={entityId} />
    </div>
  );
}
