import { useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { GitCompareArrows, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PREFIX_PATTERN, SIGNED_AMOUNT_PATTERN } from "@/lib/audit";
import {
  accountRecsKey,
  bankRecsKey,
  CODES_PATTERN,
  icRecsKey,
  parseCodes,
  useAccountRecs,
  useBankRecs,
  useIcRecs,
  type AccountRec,
  type BankRec,
  type Intercompany,
} from "@/lib/assurance";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { EmptyState, ErrorState, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { Amount } from "@/components/calc-explain";
import { Field, MutationError } from "@/components/audit/shared";
import { AssuranceNote, AssuranceStatusBadge, DatasetVersionSelect, EntitySelect, MemberSelect, PackFields } from "@/components/assurance/shared";

const TABS = ["bank", "account", "intercompany"] as const;
type Tab = (typeof TABS)[number];

const pack = {
  rule_pack_version_id: z.string().min(1),
  rules_prefix: z.string().trim().min(1).max(80).regex(PREFIX_PATTERN),
};
const codes = z.string().trim().regex(CODES_PATTERN);

const bankSchema = z
  .object({
    entity_id: z.string().min(1),
    name: z.string().trim().min(1).max(200),
    account_label: z.string().trim().min(1).max(100),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
    statement_version_id: z.string().min(1),
    ledger_version_id: z.string().min(1),
    gl_accounts: codes,
    bank_closing_balance: z.string().trim().refine((v) => v === "" || SIGNED_AMOUNT_PATTERN.test(v)),
    book_opening_balance: z.string().trim().regex(SIGNED_AMOUNT_PATTERN),
    ...pack,
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type BankValues = z.infer<typeof bankSchema>;

function DialogShell({
  open,
  onClose,
  title,
  hint,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{hint}</DialogDescription>
        {children}
      </DialogContent>
    </Dialog>
  );
}

function Footer({ onCancel, busy, label }: { onCancel: () => void; busy: boolean; label: string }) {
  const { t } = useTranslation();
  return (
    <DialogFooter>
      <Button type="button" variant="outline" onClick={onCancel}>
        {t("common.cancel")}
      </Button>
      <Button type="submit" variant="accent" disabled={busy}>
        {busy && <Loader2 className="animate-spin" aria-hidden />}
        {label}
      </Button>
    </DialogFooter>
  );
}

function NewBankRecDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<BankValues>({
    resolver: zodResolver(bankSchema),
    defaultValues: {
      entity_id: "",
      name: "",
      account_label: "",
      period_start: "",
      period_end: "",
      statement_version_id: "",
      ledger_version_id: "",
      gl_accounts: "",
      bank_closing_balance: "",
      book_opening_balance: "0",
      rule_pack_version_id: "",
      rules_prefix: "",
    },
  });
  const create = useMutation({
    mutationFn: (v: BankValues) =>
      api<BankRec>("/bank-reconciliations", {
        json: {
          ...v,
          gl_accounts: parseCodes(v.gl_accounts),
          bank_closing_balance: v.bank_closing_balance === "" ? null : v.bank_closing_balance,
        },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: bankRecsKey });
      close();
      navigate(`/reconciliations/bank/${r.id}`);
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
    <DialogShell open={open} onClose={close} title={t("recs.bank.new")} hint={t("recs.bank.newHint")}>
      <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          <EntitySelect id="br-entity" reg={form.register("entity_id")} error={!!err.entity_id} />
          <Field id="br-name" label={t("recs.name")} error={err.name ? t("recs.nameRequired") : undefined}>
            <Input id="br-name" aria-invalid={!!err.name} {...form.register("name")} />
          </Field>
        </div>
        <Field id="br-label" label={t("recs.bank.accountLabel")} hint={t("recs.bank.accountLabelHint")} error={err.account_label ? t("recs.nameRequired") : undefined}>
          <Input id="br-label" aria-invalid={!!err.account_label} {...form.register("account_label")} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id="br-start" label={t("workpapers.periodStart")} error={err.period_start ? t("rulePacks.dateRequired") : undefined}>
            <Input id="br-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
          </Field>
          <Field
            id="br-end"
            label={t("workpapers.periodEnd")}
            error={err.period_end ? (err.period_end.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired")) : undefined}
          >
            <Input id="br-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
          </Field>
          <DatasetVersionSelect
            id="br-statement"
            label={t("recs.bank.statement")}
            entityId={entityId}
            kind="bank_statement"
            reg={form.register("statement_version_id")}
            error={!!err.statement_version_id}
          />
          <DatasetVersionSelect
            id="br-ledger"
            label={t("recs.bank.ledger")}
            entityId={entityId}
            kind="general_ledger"
            reg={form.register("ledger_version_id")}
            error={!!err.ledger_version_id}
          />
        </div>
        <Field id="br-gl" label={t("recs.bank.glAccounts")} hint={t("recs.codesHint")} error={err.gl_accounts ? t("recs.codesRequired") : undefined}>
          <Input id="br-gl" dir="ltr" aria-invalid={!!err.gl_accounts} {...form.register("gl_accounts")} />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            id="br-closing"
            label={t("recs.bank.closingBalance")}
            hint={t("recs.bank.closingBalanceHint")}
            error={err.bank_closing_balance ? t("recs.amountInvalid") : undefined}
          >
            <Input id="br-closing" dir="ltr" inputMode="decimal" aria-invalid={!!err.bank_closing_balance} {...form.register("bank_closing_balance")} />
          </Field>
          <Field id="br-opening" label={t("recs.bank.openingBalance")} error={err.book_opening_balance ? t("recs.amountInvalid") : undefined}>
            <Input id="br-opening" dir="ltr" inputMode="decimal" aria-invalid={!!err.book_opening_balance} {...form.register("book_opening_balance")} />
          </Field>
        </div>
        <PackFields
          idPrefix="br"
          packReg={form.register("rule_pack_version_id")}
          prefixReg={form.register("rules_prefix")}
          packError={!!err.rule_pack_version_id}
          prefixError={!!err.rules_prefix}
        />
        <MutationError error={create.error} />
        <Footer onCancel={close} busy={create.isPending} label={t("recs.bank.create")} />
      </form>
    </DialogShell>
  );
}

const accountSchema = z.object({
  entity_id: z.string().min(1),
  tb_version_id: z.string().min(1),
  as_of: z.string().min(1),
  account_codes: codes,
  owner_id: z.string(),
  ...pack,
});
type AccountValues = z.infer<typeof accountSchema>;

function NewAccountRecDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<AccountValues>({
    resolver: zodResolver(accountSchema),
    defaultValues: { entity_id: "", tb_version_id: "", as_of: "", account_codes: "", owner_id: "", rule_pack_version_id: "", rules_prefix: "" },
  });
  const create = useMutation({
    mutationFn: (v: AccountValues) =>
      api<AccountRec[]>("/account-reconciliations", {
        json: { ...v, account_codes: parseCodes(v.account_codes), owner_id: v.owner_id || null },
      }),
    onSuccess: (rows) => {
      void qc.invalidateQueries({ queryKey: accountRecsKey });
      toast.success(t("recs.account.created", { count: rows.length }));
      close();
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
    <DialogShell open={open} onClose={close} title={t("recs.account.new")} hint={t("recs.account.newHint")}>
      <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          <EntitySelect id="ar-entity" reg={form.register("entity_id")} error={!!err.entity_id} />
          <DatasetVersionSelect
            id="ar-tb"
            label={t("recs.trialBalance")}
            entityId={entityId}
            kind="trial_balance"
            reg={form.register("tb_version_id")}
            error={!!err.tb_version_id}
          />
          <Field id="ar-asof" label={t("recs.asOf")} error={err.as_of ? t("rulePacks.dateRequired") : undefined}>
            <Input id="ar-asof" type="date" aria-invalid={!!err.as_of} {...form.register("as_of")} />
          </Field>
          <MemberSelect id="ar-owner" label={t("recs.owner")} reg={form.register("owner_id")} />
        </div>
        <Field id="ar-codes" label={t("recs.account.codes")} hint={t("recs.account.codesHint")} error={err.account_codes ? t("recs.codesRequired") : undefined}>
          <Input id="ar-codes" dir="ltr" aria-invalid={!!err.account_codes} {...form.register("account_codes")} />
        </Field>
        <PackFields
          idPrefix="ar"
          packReg={form.register("rule_pack_version_id")}
          prefixReg={form.register("rules_prefix")}
          packError={!!err.rule_pack_version_id}
          prefixError={!!err.rules_prefix}
        />
        <MutationError error={create.error} />
        <Footer onCancel={close} busy={create.isPending} label={t("recs.account.create")} />
      </form>
    </DialogShell>
  );
}

const icSchema = z
  .object({
    name: z.string().trim().min(1).max(200),
    as_of: z.string().min(1),
    entity_a_id: z.string().min(1),
    tb_a_version_id: z.string().min(1),
    accounts_a: codes,
    entity_b_id: z.string().min(1),
    tb_b_version_id: z.string().min(1),
    accounts_b: codes,
    ...pack,
  })
  .refine((v) => !v.entity_a_id || v.entity_a_id !== v.entity_b_id, { path: ["entity_b_id"], message: "same" });
type IcValues = z.infer<typeof icSchema>;

function NewIcDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<IcValues>({
    resolver: zodResolver(icSchema),
    defaultValues: {
      name: "",
      as_of: "",
      entity_a_id: "",
      tb_a_version_id: "",
      accounts_a: "",
      entity_b_id: "",
      tb_b_version_id: "",
      accounts_b: "",
      rule_pack_version_id: "",
      rules_prefix: "",
    },
  });
  const create = useMutation({
    mutationFn: (v: IcValues) =>
      api<Intercompany>("/intercompany-reconciliations", {
        json: { ...v, accounts_a: parseCodes(v.accounts_a), accounts_b: parseCodes(v.accounts_b) },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: icRecsKey });
      close();
      navigate(`/reconciliations/intercompany/${r.id}`);
    },
  });
  function close() {
    form.reset();
    create.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  const [a, b] = useWatch({ control: form.control, name: ["entity_a_id", "entity_b_id"] });
  return (
    <DialogShell open={open} onClose={close} title={t("recs.ic.new")} hint={t("recs.ic.newHint")}>
      <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id="ic-name" label={t("recs.name")} error={err.name ? t("recs.nameRequired") : undefined}>
            <Input id="ic-name" aria-invalid={!!err.name} {...form.register("name")} />
          </Field>
          <Field id="ic-asof" label={t("recs.asOf")} error={err.as_of ? t("rulePacks.dateRequired") : undefined}>
            <Input id="ic-asof" type="date" aria-invalid={!!err.as_of} {...form.register("as_of")} />
          </Field>
        </div>
        {(["a", "b"] as const).map((side) => (
          <fieldset key={side} className="space-y-3 rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-[13px] font-semibold text-navy-900">{t(`recs.ic.side_${side}`)}</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <EntitySelect id={`ic-entity-${side}`} reg={form.register(`entity_${side}_id`)} error={!!err[`entity_${side}_id`]} />
              <DatasetVersionSelect
                id={`ic-tb-${side}`}
                label={t("recs.trialBalance")}
                entityId={side === "a" ? a : b}
                kind="trial_balance"
                reg={form.register(`tb_${side}_version_id`)}
                error={!!err[`tb_${side}_version_id`]}
              />
            </div>
            {side === "b" && err.entity_b_id?.message === "same" && (
              <p role="alert" className="text-xs font-medium text-red-600">
                {t("recs.ic.sameEntity")}
              </p>
            )}
            <Field id={`ic-accounts-${side}`} label={t("recs.ic.accounts")} hint={t("recs.codesHint")} error={err[`accounts_${side}`] ? t("recs.codesRequired") : undefined}>
              <Input id={`ic-accounts-${side}`} dir="ltr" aria-invalid={!!err[`accounts_${side}`]} {...form.register(`accounts_${side}`)} />
            </Field>
          </fieldset>
        ))}
        <PackFields
          idPrefix="ic"
          packReg={form.register("rule_pack_version_id")}
          prefixReg={form.register("rules_prefix")}
          packError={!!err.rule_pack_version_id}
          prefixError={!!err.rules_prefix}
        />
        <MutationError error={create.error} />
        <Footer onCancel={close} busy={create.isPending} label={t("recs.ic.create")} />
      </form>
    </DialogShell>
  );
}

function BankList() {
  const { t, i18n } = useTranslation();
  const list = useBankRecs();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={GitCompareArrows} title={t("recs.bank.empty")} description={t("recs.bank.emptyHint")} />;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("recs.name")}</TH>
          <TH>{t("recs.bank.accountLabel")}</TH>
          <TH>{t("workpapers.period")}</TH>
          <TH>{t("recs.status")}</TH>
        </tr>
      </THead>
      <TBody>
        {list.data.map((r) => (
          <TR key={r.id}>
            <TD className="align-top">
              <Link to={`/reconciliations/bank/${r.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                {r.name}
              </Link>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                <span>{r.entity_name}</span>
                {r.is_demo && <SyntheticBadge />}
              </div>
            </TD>
            <TD className="align-top text-[13px] text-slate-600">{r.account_label}</TD>
            <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
              {formatDate(r.period_start, i18n.language)} – {formatDate(r.period_end, i18n.language)}
            </TD>
            <TD className="align-top">
              <AssuranceStatusBadge status={r.status} />
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function AccountList() {
  const { t, i18n } = useTranslation();
  const list = useAccountRecs();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={GitCompareArrows} title={t("recs.account.empty")} description={t("recs.account.emptyHint")} />;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("recs.account.account")}</TH>
          <TH>{t("recs.asOf")}</TH>
          <TH className="text-end">{t("recs.account.tbBalance")}</TH>
          <TH className="text-end">{t("recs.account.variance")}</TH>
          <TH>{t("recs.owner")}</TH>
          <TH>{t("recs.status")}</TH>
        </tr>
      </THead>
      <TBody>
        {list.data.map((r) => (
          <TR key={r.id}>
            <TD className="align-top">
              <Link to={`/reconciliations/account/${r.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                <span dir="ltr">{r.account_code}</span> {r.account_name}
              </Link>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                <span>{r.entity_name}</span>
                {r.is_demo && <SyntheticBadge />}
              </div>
            </TD>
            <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">{formatDate(r.as_of, i18n.language)}</TD>
            <TD className="align-top text-end">
              <Amount value={r.tb_balance} currency={r.currency} />
            </TD>
            <TD className="align-top text-end">
              <Amount value={r.variance} />
              {r.exceeds && (
                <Badge tone="amber" className="ms-2">
                  {t("recs.overThreshold")}
                </Badge>
              )}
            </TD>
            <TD className="align-top text-[13px] text-slate-600">{r.owner_name ?? "—"}</TD>
            <TD className="align-top">
              <AssuranceStatusBadge status={r.status} />
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function IcList() {
  const { t, i18n } = useTranslation();
  const list = useIcRecs();
  if (list.isLoading) return <LoadingState />;
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  if (!list.data?.length) return <EmptyState icon={GitCompareArrows} title={t("recs.ic.empty")} description={t("recs.ic.emptyHint")} />;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("recs.name")}</TH>
          <TH>{t("recs.ic.entities")}</TH>
          <TH>{t("recs.asOf")}</TH>
          <TH className="text-end">{t("recs.difference")}</TH>
          <TH>{t("recs.status")}</TH>
        </tr>
      </THead>
      <TBody>
        {list.data.map((r) => (
          <TR key={r.id}>
            <TD className="align-top">
              <Link to={`/reconciliations/intercompany/${r.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                {r.name}
              </Link>
              {r.is_demo && <SyntheticBadge className="ms-2" />}
            </TD>
            <TD className="align-top text-[13px] text-slate-600">
              {r.side_a.entity_name} · {r.side_b.entity_name}
            </TD>
            <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">{formatDate(r.as_of, i18n.language)}</TD>
            <TD className="align-top text-end">
              <Amount value={r.difference} currency={r.currency} />
              {r.exceeds && (
                <Badge tone="amber" className="ms-2">
                  {t("recs.overThreshold")}
                </Badge>
              )}
            </TD>
            <TD className="align-top">
              <AssuranceStatusBadge status={r.sign_off.status} />
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function ReconciliationsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState<Tab | null>(null);
  const raw = params.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(raw ?? "") ? (raw as Tab) : "bank";
  return (
    <>
      <PageHeader
        title={t("recs.title")}
        description={t("recs.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.reconciliations") }]}
        actions={
          can("write") && (
            <Button variant="accent" onClick={() => setOpen(tab)}>
              <Plus aria-hidden /> {t(`recs.${tab === "intercompany" ? "ic" : tab}.new`)}
            </Button>
          )
        }
      />
      <div className="space-y-4">
        <AssuranceNote>{t("recs.disclaimer")}</AssuranceNote>
        <Tabs
          label={t("recs.title")}
          value={tab}
          onChange={(k) => setParams(k === "bank" ? {} : { tab: k }, { replace: true })}
          items={TABS.map((k) => ({ key: k, label: t(`recs.tab.${k}`) }))}
        />
        <Card className="overflow-hidden">
          {tab === "bank" && <BankList />}
          {tab === "account" && <AccountList />}
          {tab === "intercompany" && <IcList />}
        </Card>
      </div>
      <NewBankRecDialog open={open === "bank"} onOpenChange={(o) => setOpen(o ? "bank" : null)} />
      <NewAccountRecDialog open={open === "account"} onOpenChange={(o) => setOpen(o ? "account" : null)} />
      <NewIcDialog open={open === "intercompany"} onOpenChange={(o) => setOpen(o ? "intercompany" : null)} />
    </>
  );
}
