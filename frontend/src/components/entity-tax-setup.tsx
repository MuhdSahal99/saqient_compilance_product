import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CalendarCheck, CalendarRange, Info, Loader2, Plus, RotateCcw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import {
  PERIOD_FREQUENCIES,
  TAX_ACCOUNT_ROLES,
  VAT_TREATMENTS,
  type LegalEntity,
  type TaxPeriod,
  type VatSetup,
} from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { taxPeriodsKey, useTaxPeriods } from "@/lib/queries";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ErrorState, errorMessage, LoadingState, useUnsavedChangesWarning } from "@/components/common";

type Section = "basis" | "codes" | "periods";

function ErrorNote({ error }: { error: unknown }) {
  const { t } = useTranslation();
  return (
    <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {errorMessage(error, t("common.genericError"))}
    </p>
  );
}

// ---------------------------------------------------------------- e-invoicing basis (size and go-live override)

const basisSchema = z
  .object({
    size_basis_amount: z.union([z.literal(""), z.string().trim().regex(/^\d{1,16}(\.\d{1,4})?$/)]),
    size_basis_currency: z.union([z.literal(""), z.string().trim().toUpperCase().regex(/^[A-Z]{3}$/)]),
    size_basis_year: z.union([z.literal(""), z.string().regex(/^(20\d\d|2100)$/)]),
    einvoice_go_live_override: z.string(),
    einvoice_go_live_note: z.string().max(2000),
  })
  .superRefine((v, ctx) => {
    if (v.size_basis_amount && !v.size_basis_currency) ctx.addIssue({ code: "custom", path: ["size_basis_currency"], message: "required" });
    if (v.einvoice_go_live_override && !v.einvoice_go_live_note.trim())
      ctx.addIssue({ code: "custom", path: ["einvoice_go_live_note"], message: "required" });
  });
type BasisValues = z.input<typeof basisSchema>;
type BasisParsed = z.output<typeof basisSchema>;

function BasisSection({ entity, admin }: { entity: LegalEntity; admin: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const defaults = (): BasisValues => ({
    size_basis_amount: entity.size_basis_amount ?? "",
    size_basis_currency: entity.size_basis_currency ?? entity.functional_currency,
    size_basis_year: entity.size_basis_year ? String(entity.size_basis_year) : "",
    einvoice_go_live_override: entity.einvoice_go_live_override ?? "",
    einvoice_go_live_note: entity.einvoice_go_live_note ?? "",
  });
  const form = useForm<BasisValues, unknown, BasisParsed>({ resolver: zodResolver(basisSchema), defaultValues: defaults() });
  useEffect(() => {
    form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the entity record changes
  }, [entity.updated_at]);
  const save = useMutation({
    mutationFn: (v: BasisParsed) => {
      const body: Record<string, unknown> = {};
      if (v.size_basis_amount) {
        body.size_basis_amount = v.size_basis_amount;
        body.size_basis_currency = v.size_basis_currency;
        if (v.size_basis_year) body.size_basis_year = Number(v.size_basis_year);
      } else if (entity.size_basis_amount != null) {
        body.clear_size_basis = true;
      }
      if (v.einvoice_go_live_override) {
        body.einvoice_go_live_override = v.einvoice_go_live_override;
        body.einvoice_go_live_note = v.einvoice_go_live_note.trim();
      } else if (entity.einvoice_go_live_override) {
        body.clear_go_live_override = true;
      }
      return api<LegalEntity>(`/entities/${entity.id}`, { method: "PATCH", json: body });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["entities"] });
      toast.success(t("entities.updated"));
    },
  });
  const err = form.formState.errors;

  if (!admin) {
    return (
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <dt className="text-slate-500">{t("taxSetup.sizeBasis")}</dt>
        <dd className="font-mono tabular-nums text-slate-800" dir="ltr">
          {entity.size_basis_amount ? `${entity.size_basis_amount} ${entity.size_basis_currency ?? ""} (${entity.size_basis_year ?? "—"})` : "—"}
        </dd>
        <dt className="text-slate-500">{t("taxSetup.goLiveOverride")}</dt>
        <dd className="text-slate-800">
          {entity.einvoice_go_live_override ? formatDate(entity.einvoice_go_live_override, i18n.language) : "—"}
          {entity.einvoice_go_live_note && <p className="text-xs text-slate-500">{entity.einvoice_go_live_note}</p>}
        </dd>
      </dl>
    );
  }
  return (
    <form className="mt-4 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
      <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
        {t("taxSetup.basisHint")}
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="ts-amount">{t("taxSetup.sizeBasisAmount")}</Label>
          <Input id="ts-amount" dir="ltr" inputMode="decimal" aria-invalid={!!err.size_basis_amount} {...form.register("size_basis_amount")} />
          <FieldError message={err.size_basis_amount ? t("taxSetup.amountRule") : undefined} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ts-currency">{t("entities.currency")}</Label>
          <Input id="ts-currency" dir="ltr" maxLength={3} aria-invalid={!!err.size_basis_currency} {...form.register("size_basis_currency")} />
          <FieldError message={err.size_basis_currency ? t("entities.currencyRule") : undefined} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ts-year">{t("taxSetup.sizeBasisYear")}</Label>
          <Input id="ts-year" dir="ltr" inputMode="numeric" maxLength={4} aria-invalid={!!err.size_basis_year} {...form.register("size_basis_year")} />
          <FieldError message={err.size_basis_year ? t("taxSetup.yearRule") : undefined} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="ts-golive">{t("taxSetup.goLiveOverride")}</Label>
        <Input id="ts-golive" type="date" className="sm:w-1/2" aria-describedby="ts-golive-hint" {...form.register("einvoice_go_live_override")} />
        <p id="ts-golive-hint" className="text-xs text-slate-500">
          {t("taxSetup.goLiveHint")}
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="ts-golive-note">{t("taxSetup.goLiveNote")}</Label>
        <Textarea id="ts-golive-note" rows={2} aria-invalid={!!err.einvoice_go_live_note} {...form.register("einvoice_go_live_note")} />
        <FieldError message={err.einvoice_go_live_note ? t("taxSetup.goLiveNoteRequired") : undefined} />
      </div>
      {save.isError && <ErrorNote error={save.error} />}
      <div className="flex justify-end">
        <Button type="submit" variant="accent" disabled={save.isPending || !form.formState.isDirty}>
          {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {t("common.save")}
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- VAT codes and accounts

const setupSchema = z.object({
  tax_codes: z
    .array(
      z.object({
        register: z.enum(["sales_register", "purchase_register"]),
        tax_code: z.string().trim().min(1).max(40),
        treatment: z.enum(VAT_TREATMENTS),
        recoverable: z.boolean(),
        description: z.string().max(300),
      }),
    )
    .max(500),
  tax_accounts: z
    .array(
      z.object({
        role: z.enum(TAX_ACCOUNT_ROLES),
        account_code: z.string().trim().min(1).max(60),
      }),
    )
    .max(100),
});
type SetupValues = z.infer<typeof setupSchema>;

function CodesSection({ entity, admin, onDirty }: { entity: LegalEntity; admin: boolean; onDirty: (d: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const setup = useQuery({ queryKey: ["vat-setup", entity.id], queryFn: () => api<VatSetup>(`/entities/${entity.id}/vat-setup`) });
  const form = useForm<SetupValues>({ resolver: zodResolver(setupSchema), defaultValues: { tax_codes: [], tax_accounts: [] } });
  const codes = useFieldArray({ control: form.control, name: "tax_codes" });
  const accounts = useFieldArray({ control: form.control, name: "tax_accounts" });
  useEffect(() => {
    if (setup.data) form.reset({ tax_codes: setup.data.tax_codes, tax_accounts: setup.data.tax_accounts });
  }, [setup.data, form]);
  const dirty = form.formState.isDirty;
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  const save = useMutation({
    mutationFn: (v: SetupValues) => api<VatSetup>(`/entities/${entity.id}/vat-setup`, { method: "PUT", json: v }),
    onSuccess: (data) => {
      qc.setQueryData(["vat-setup", entity.id], data);
      form.reset({ tax_codes: data.tax_codes, tax_accounts: data.tax_accounts });
      toast.success(t("taxSetup.setupSaved"));
    },
  });
  if (setup.isLoading) return <LoadingState rows={3} />;
  if (setup.isError) return <ErrorState error={setup.error} onRetry={() => void setup.refetch()} />;
  const err = form.formState.errors;
  return (
    <form className="mt-4 space-y-5" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
      <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
        {t("taxSetup.codesHint")}
      </p>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-navy-900">{t("taxSetup.taxCodes")}</legend>
        {codes.fields.length === 0 ? (
          <p className="text-xs text-slate-500">{t("taxSetup.noCodes")}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <Table>
              <THead>
                <tr>
                  <TH>{t("taxSetup.register")}</TH>
                  <TH>{t("taxSetup.taxCode")}</TH>
                  <TH>{t("taxSetup.treatment")}</TH>
                  <TH>{t("taxSetup.recoverable")}</TH>
                  <TH>{t("taxSetup.codeDescription")}</TH>
                  {admin && (
                    <TH>
                      <span className="sr-only">{t("common.actions")}</span>
                    </TH>
                  )}
                </tr>
              </THead>
              <TBody>
                {codes.fields.map((f, i) => (
                  <TR key={f.id}>
                    <TD>
                      <Select aria-label={t("taxSetup.register")} className="min-w-36" disabled={!admin} {...form.register(`tax_codes.${i}.register`)}>
                        <option value="sales_register">{t("datasetKind.sales_register")}</option>
                        <option value="purchase_register">{t("datasetKind.purchase_register")}</option>
                      </Select>
                    </TD>
                    <TD>
                      <Input
                        aria-label={t("taxSetup.taxCode")}
                        dir="ltr"
                        className="min-w-24"
                        disabled={!admin}
                        aria-invalid={!!err.tax_codes?.[i]?.tax_code}
                        {...form.register(`tax_codes.${i}.tax_code`)}
                      />
                    </TD>
                    <TD>
                      <Select aria-label={t("taxSetup.treatment")} className="min-w-40" disabled={!admin} {...form.register(`tax_codes.${i}.treatment`)}>
                        {VAT_TREATMENTS.map((x) => (
                          <option key={x} value={x}>
                            {t(`vatTreatment.${x}`)}
                          </option>
                        ))}
                      </Select>
                    </TD>
                    <TD>
                      <input
                        type="checkbox"
                        aria-label={t("taxSetup.recoverable")}
                        className="size-4 rounded border-slate-300 accent-teal-600"
                        disabled={!admin}
                        {...form.register(`tax_codes.${i}.recoverable`)}
                      />
                    </TD>
                    <TD>
                      <Input aria-label={t("taxSetup.codeDescription")} className="min-w-40" disabled={!admin} {...form.register(`tax_codes.${i}.description`)} />
                    </TD>
                    {admin && (
                      <TD>
                        <Button type="button" size="icon-sm" variant="ghost" onClick={() => codes.remove(i)} aria-label={t("taxSetup.removeRow")}>
                          <Trash2 aria-hidden />
                        </Button>
                      </TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
          </div>
        )}
        {err.tax_codes && <FieldError message={t("taxSetup.rowsInvalid")} />}
        {admin && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => codes.append({ register: "sales_register", tax_code: "", treatment: "standard", recoverable: true, description: "" })}
          >
            <Plus aria-hidden /> {t("taxSetup.addCode")}
          </Button>
        )}
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-navy-900">{t("taxSetup.taxAccounts")}</legend>
        {accounts.fields.length === 0 ? (
          <p className="text-xs text-slate-500">{t("taxSetup.noAccounts")}</p>
        ) : (
          <ul className="space-y-2">
            {accounts.fields.map((f, i) => (
              <li key={f.id} className="flex flex-wrap items-center gap-2">
                <Select aria-label={t("taxSetup.accountRole")} className="w-56" disabled={!admin} {...form.register(`tax_accounts.${i}.role`)}>
                  {TAX_ACCOUNT_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {t(`taxAccountRole.${r}`)}
                    </option>
                  ))}
                </Select>
                <Input
                  aria-label={t("taxSetup.accountCode")}
                  placeholder={t("taxSetup.accountCode")}
                  dir="ltr"
                  className="w-40"
                  disabled={!admin}
                  aria-invalid={!!err.tax_accounts?.[i]?.account_code}
                  {...form.register(`tax_accounts.${i}.account_code`)}
                />
                {admin && (
                  <Button type="button" size="icon-sm" variant="ghost" onClick={() => accounts.remove(i)} aria-label={t("taxSetup.removeRow")}>
                    <Trash2 aria-hidden />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {err.tax_accounts && <FieldError message={t("taxSetup.rowsInvalid")} />}
        {admin && (
          <Button type="button" size="sm" variant="outline" onClick={() => accounts.append({ role: "output_vat", account_code: "" })}>
            <Plus aria-hidden /> {t("taxSetup.addAccount")}
          </Button>
        )}
      </fieldset>
      {save.isError && <ErrorNote error={save.error} />}
      {admin && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          {dirty && (
            <Button type="button" variant="ghost" onClick={() => setup.data && form.reset({ tax_codes: setup.data.tax_codes, tax_accounts: setup.data.tax_accounts })}>
              <RotateCcw aria-hidden /> {t("rulePacks.discard")}
            </Button>
          )}
          <Button type="submit" variant="accent" disabled={save.isPending || !dirty}>
            {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {t("taxSetup.saveSetup")}
          </Button>
        </div>
      )}
    </form>
  );
}

// ---------------------------------------------------------------- tax periods

const periodSchema = z
  .object({
    frequency: z.enum(["monthly", "quarterly", "annual", "custom"]),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type PeriodValues = z.infer<typeof periodSchema>;

function PeriodsSection({ entity }: { entity: LegalEntity }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const decide = can("decide");
  const periods = useTaxPeriods(entity.id);
  const form = useForm<PeriodValues>({ resolver: zodResolver(periodSchema), defaultValues: { frequency: "quarterly", period_start: "", period_end: "" } });
  const create = useMutation({
    mutationFn: (v: PeriodValues) => api<TaxPeriod>(`/entities/${entity.id}/tax-periods`, { json: { tax_type: "vat", ...v } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: taxPeriodsKey(entity.id) });
      toast.success(t("taxSetup.periodCreated"));
      form.reset();
    },
  });
  const patch = useMutation({
    mutationFn: (p: TaxPeriod) =>
      api<TaxPeriod>(`/tax-periods/${p.id}`, { method: "PATCH", json: { status: p.status === "open" ? "filed" : "open" } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: taxPeriodsKey(entity.id) });
      toast.success(t("taxSetup.periodUpdated"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const err = form.formState.errors;
  return (
    <div className="mt-4 space-y-4">
      {periods.isLoading && <LoadingState rows={2} />}
      {periods.isError && <ErrorState error={periods.error} onRetry={() => void periods.refetch()} />}
      {periods.data?.length === 0 && <p className="text-sm text-slate-500">{t("taxSetup.noPeriods")}</p>}
      {periods.data && periods.data.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {periods.data.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <CalendarRange className="size-4 text-slate-400" aria-hidden />
              <span className="font-medium text-navy-900">
                {formatDate(p.period_start, i18n.language)} – {formatDate(p.period_end, i18n.language)}
              </span>
              <Badge tone="neutral">{t(`taxType.${p.tax_type}`)}</Badge>
              <span className="text-xs text-slate-500">{t(`frequency.${p.frequency}`)}</span>
              <Badge tone={p.status === "filed" ? "green" : "teal"} dot className="ms-auto">
                {t(`taxPeriodStatus.${p.status}`)}
              </Badge>
              {decide && (
                <Button size="sm" variant="ghost" disabled={patch.isPending} onClick={() => patch.mutate(p)}>
                  <CalendarCheck aria-hidden />
                  {p.status === "open" ? t("taxSetup.markFiled") : t("taxSetup.reopenPeriod")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {decide && (
        <form className="space-y-3 rounded-lg border border-slate-200 p-3" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <p className="text-sm font-medium text-navy-900">{t("taxSetup.addPeriod")}</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="tp-frequency">{t("taxSetup.frequency")}</Label>
              <Select id="tp-frequency" {...form.register("frequency")}>
                {PERIOD_FREQUENCIES.map((f) => (
                  <option key={f} value={f}>
                    {t(`frequency.${f}`)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tp-start">{t("datasets.periodStart")}</Label>
              <Input id="tp-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
              <FieldError message={err.period_start ? t("rulePacks.dateRequired") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tp-end">{t("datasets.periodEnd")}</Label>
              <Input id="tp-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
              <FieldError message={err.period_end ? (err.period_end.message === "order" ? t("datasets.periodOrder") : t("rulePacks.dateRequired")) : undefined} />
            </div>
          </div>
          {create.isError && <ErrorNote error={create.error} />}
          <div className="flex justify-end">
            <Button type="submit" size="sm" variant="accent" disabled={create.isPending}>
              {create.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
              {t("taxSetup.addPeriod")}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

/** Per-entity VAT and e-invoicing setup: size basis and go-live override, tax code mapping, tax periods.
 * Give it a `key` of the entity id so its tab and unsaved state start fresh for each entity. */
export function EntityTaxSetupDialog({ entity, onOpenChange }: { entity: LegalEntity | null; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const admin = can("admin");
  const [section, setSection] = useState<Section>("basis");
  const [codesDirty, setCodesDirty] = useState(false);
  useUnsavedChangesWarning(codesDirty);
  return (
    <Dialog
      open={entity !== null}
      onOpenChange={(o) => {
        if (!o && codesDirty && !window.confirm(t("common.unsavedChanges"))) return;
        onOpenChange(o);
      }}
    >
      <DialogContent className="max-w-3xl">
        <DialogTitle>{t("taxSetup.title", { name: entity?.name ?? "" })}</DialogTitle>
        <DialogDescription>{t("taxSetup.description")}</DialogDescription>
        {entity && (
          <>
            <Tabs<Section>
              className="mt-4"
              label={t("taxSetup.sections")}
              value={section}
              onChange={setSection}
              items={[
                { key: "basis", label: t("taxSetup.tabBasis") },
                { key: "codes", label: t("taxSetup.tabCodes") },
                { key: "periods", label: t("taxSetup.tabPeriods") },
              ]}
            />
            {/* Sections stay mounted so unsaved edits survive switching tabs. */}
            <div hidden={section !== "basis"}>
              <BasisSection entity={entity} admin={admin} />
            </div>
            <div hidden={section !== "codes"}>
              <CodesSection entity={entity} admin={admin} onDirty={setCodesDirty} />
            </div>
            <div hidden={section !== "periods"}>
              <PeriodsSection entity={entity} />
            </div>
          </>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
