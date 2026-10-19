import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Archive, ArchiveRestore, Building, Landmark, Loader2, Pencil, Plus, Receipt } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { LegalEntity, TaxGroup } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, errorMessage, LoadingState, PageHeader } from "@/components/common";
import { EntityTaxSetupDialog } from "@/components/entity-tax-setup";

/** IANA zones offered in the form; the backend accepts any valid zone. */
const TIMEZONES = ["Asia/Dubai", "Asia/Riyadh", "Asia/Qatar", "Asia/Bahrain", "Asia/Kuwait", "Asia/Muscat", "UTC"];
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

const optionalTrn = z.union([z.literal(""), z.string().regex(/^[A-Za-z0-9]{5,20}$/)]);

const entitySchema = z.object({
  name: z.string().trim().min(1).max(200),
  country: z.string().trim().toUpperCase().regex(/^[A-Z]{2}$/),
  trn: optionalTrn,
  fiscal_year_end_month: z.coerce.number().int().min(1).max(12),
  fiscal_year_end_day: z.coerce.number().int().min(1).max(31),
  functional_currency: z.string().trim().toUpperCase().regex(/^[A-Z]{3}$/),
  timezone: z.string().min(1).max(64),
  tax_group_id: z.string(),
  is_free_zone: z.boolean(),
});
type EntityValues = z.input<typeof entitySchema>;
type EntityParsed = z.output<typeof entitySchema>;

function monthName(m: number, locale: string): string {
  return new Intl.DateTimeFormat(locale, { month: "long" }).format(new Date(2024, m - 1, 1));
}

function EntityDialog({
  open,
  onOpenChange,
  entity,
  groups,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  entity?: LegalEntity;
  groups: TaxGroup[];
}) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const defaults = (): EntityValues => ({
    name: entity?.name ?? "",
    country: entity?.country ?? "AE",
    trn: "",
    fiscal_year_end_month: entity?.fiscal_year_end_month ?? 12,
    fiscal_year_end_day: entity?.fiscal_year_end_day ?? 31,
    functional_currency: entity?.functional_currency ?? "AED",
    timezone: entity?.timezone ?? "Asia/Dubai",
    tax_group_id: entity?.tax_group_id ?? "",
    is_free_zone: entity?.is_free_zone ?? false,
  });
  const form = useForm<EntityValues, unknown, EntityParsed>({ resolver: zodResolver(entitySchema), defaultValues: defaults() });
  useEffect(() => {
    if (open) form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the dialog opens
  }, [open, entity?.id]);

  const save = useMutation({
    mutationFn: (v: EntityParsed) => {
      const base = {
        name: v.name,
        fiscal_year_end_month: v.fiscal_year_end_month,
        fiscal_year_end_day: v.fiscal_year_end_day,
        functional_currency: v.functional_currency,
        timezone: v.timezone,
        is_free_zone: v.is_free_zone,
      };
      if (entity) {
        return api<LegalEntity>(`/entities/${entity.id}`, {
          method: "PATCH",
          json: {
            ...base,
            ...(v.trn ? { trn: v.trn } : {}),
            ...(v.tax_group_id ? { tax_group_id: v.tax_group_id } : { clear_tax_group: true }),
          },
        });
      }
      return api<LegalEntity>("/entities", {
        json: { ...base, country: v.country, trn: v.trn || null, tax_group_id: v.tax_group_id || null },
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["entities"] });
      void qc.invalidateQueries({ queryKey: ["tax-groups"] });
      toast.success(t(entity ? "entities.updated" : "entities.created"));
      onOpenChange(false);
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{entity ? t("entities.edit") : t("entities.new")}</DialogTitle>
        <DialogDescription>{t("entities.formHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="ent-name">{t("entities.name")}</Label>
            <Input id="ent-name" aria-invalid={!!err.name} {...form.register("name")} />
            <FieldError message={err.name ? t("entities.nameRequired") : undefined} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ent-country">{t("entities.country")}</Label>
              <Input id="ent-country" maxLength={2} dir="ltr" disabled={!!entity} aria-invalid={!!err.country} {...form.register("country")} />
              <FieldError message={err.country ? t("entities.countryRule") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ent-currency">{t("entities.currency")}</Label>
              <Input id="ent-currency" maxLength={3} dir="ltr" aria-invalid={!!err.functional_currency} {...form.register("functional_currency")} />
              <FieldError message={err.functional_currency ? t("entities.currencyRule") : undefined} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ent-trn">{t("entities.trn")}</Label>
            <Input
              id="ent-trn"
              dir="ltr"
              autoComplete="off"
              placeholder={entity?.trn_masked ?? ""}
              aria-invalid={!!err.trn}
              aria-describedby="ent-trn-hint"
              {...form.register("trn")}
            />
            <p id="ent-trn-hint" className="text-xs text-slate-500">
              {entity ? t("entities.trnKeep") : t("entities.trnHint")}
            </p>
            <FieldError message={err.trn ? t("entities.trnRule") : undefined} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ent-fy-month">{t("entities.fyEndMonth")}</Label>
              <Select id="ent-fy-month" {...form.register("fiscal_year_end_month")}>
                {MONTHS.map((m) => (
                  <option key={m} value={m}>
                    {monthName(m, i18n.language)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ent-fy-day">{t("entities.fyEndDay")}</Label>
              <Input id="ent-fy-day" type="number" min={1} max={31} aria-invalid={!!err.fiscal_year_end_day} {...form.register("fiscal_year_end_day")} />
              <FieldError message={err.fiscal_year_end_day ? t("entities.dayRule") : undefined} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="ent-tz">{t("entities.timezone")}</Label>
              <Select id="ent-tz" dir="ltr" {...form.register("timezone")}>
                {TIMEZONES.map((z) => (
                  <option key={z} value={z}>
                    {z}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="ent-group">{t("entities.taxGroup")}</Label>
              <Select id="ent-group" {...form.register("tax_group_id")}>
                <option value="">{t("entities.noTaxGroup")}</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" className="size-4 rounded border-slate-300 accent-teal-600" {...form.register("is_free_zone")} />
            {t("entities.freeZone")}
          </label>
          {save.isError && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {errorMessage(save.error, t("common.genericError"))}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const groupSchema = z.object({
  name: z.string().trim().min(1).max(200),
  country: z.string().trim().toUpperCase().regex(/^[A-Z]{2}$/),
  trn: optionalTrn,
});
type GroupValues = z.input<typeof groupSchema>;
type GroupParsed = z.output<typeof groupSchema>;

function TaxGroupDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<GroupValues, unknown, GroupParsed>({ resolver: zodResolver(groupSchema), defaultValues: { name: "", country: "AE", trn: "" } });
  const save = useMutation({
    mutationFn: (v: GroupParsed) => api<TaxGroup>("/tax-groups", { json: { name: v.name, country: v.country, trn: v.trn || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tax-groups"] });
      toast.success(t("entities.groupCreated"));
      form.reset();
      onOpenChange(false);
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{t("entities.newGroup")}</DialogTitle>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="grp-name">{t("entities.name")}</Label>
            <Input id="grp-name" aria-invalid={!!err.name} {...form.register("name")} />
            <FieldError message={err.name ? t("entities.nameRequired") : undefined} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="grp-country">{t("entities.country")}</Label>
              <Input id="grp-country" maxLength={2} dir="ltr" aria-invalid={!!err.country} {...form.register("country")} />
              <FieldError message={err.country ? t("entities.countryRule") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="grp-trn">{t("entities.groupTrn")}</Label>
              <Input id="grp-trn" dir="ltr" autoComplete="off" aria-invalid={!!err.trn} {...form.register("trn")} />
              <FieldError message={err.trn ? t("entities.trnRule") : undefined} />
            </div>
          </div>
          {save.isError && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {errorMessage(save.error, t("common.genericError"))}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EntitiesPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<LegalEntity | "new" | null>(null);
  const [groupOpen, setGroupOpen] = useState(false);
  const [archiving, setArchiving] = useState<LegalEntity | null>(null);
  const [taxSetupId, setTaxSetupId] = useState<string | null>(null);
  const entities = useQuery({
    queryKey: ["entities", { showInactive }],
    queryFn: () => api<LegalEntity[]>(`/entities${qs({ include_inactive: showInactive })}`),
  });
  const groups = useQuery({ queryKey: ["tax-groups"], queryFn: () => api<TaxGroup[]>("/tax-groups") });
  const toggleActive = useMutation({
    mutationFn: (e: LegalEntity) => api<LegalEntity>(`/entities/${e.id}`, { method: "PATCH", json: { is_active: !e.is_active } }),
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: ["entities"] });
      toast.success(t(e.is_active ? "entities.restored" : "entities.archived"));
      setArchiving(null);
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const admin = can("admin");

  return (
    <>
      <PageHeader
        title={t("entities.title")}
        description={t("entities.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.entities") }]}
        actions={
          admin && (
            <Button variant="accent" onClick={() => setEditing("new")}>
              <Plus aria-hidden /> {t("entities.new")}
            </Button>
          )
        }
      />
      <div className="space-y-6">
        <Card className="overflow-hidden">
          <div className="flex items-center justify-end border-b border-slate-100 px-4 py-2.5">
            <label className="flex items-center gap-2 text-[13px] text-slate-600">
              <input type="checkbox" className="size-4 rounded border-slate-300 accent-teal-600" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
              {t("entities.showArchived")}
            </label>
          </div>
          {entities.isLoading && <LoadingState />}
          {entities.isError && <ErrorState error={entities.error} onRetry={() => void entities.refetch()} />}
          {entities.data?.length === 0 && (
            <EmptyState
              icon={Building}
              title={t("entities.empty")}
              description={admin ? t("entities.emptyHintAdmin") : t("entities.emptyHint")}
              action={
                admin && (
                  <Button variant="accent" onClick={() => setEditing("new")}>
                    <Plus aria-hidden /> {t("entities.new")}
                  </Button>
                )
              }
            />
          )}
          {entities.data && entities.data.length > 0 && (
            <Table>
              <THead>
                <tr>
                  <TH>{t("entities.name")}</TH>
                  <TH>{t("entities.trn")}</TH>
                  <TH>{t("entities.currency")}</TH>
                  <TH>{t("entities.fiscalYearEnd")}</TH>
                  <TH>{t("entities.taxGroup")}</TH>
                  <TH className="text-end">{t("common.actions")}</TH>
                </tr>
              </THead>
              <TBody>
                {entities.data.map((e) => (
                  <TR key={e.id}>
                    <TD>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-navy-900">{e.name}</span>
                        <Badge tone="neutral">{e.country}</Badge>
                        {e.is_free_zone && <Badge tone="teal">{t("entities.freeZoneBadge")}</Badge>}
                        {!e.is_active && <Badge tone="neutral">{t("entities.archivedBadge")}</Badge>}
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500" dir="ltr">
                        {e.timezone}
                      </div>
                    </TD>
                    <TD className="font-mono text-[13px] text-slate-600" dir="ltr">
                      {e.trn_masked ?? "—"}
                    </TD>
                    <TD className="text-[13px] text-slate-700">{e.functional_currency}</TD>
                    <TD className="whitespace-nowrap text-[13px] text-slate-700">
                      {e.fiscal_year_end_day} {monthName(e.fiscal_year_end_month, i18n.language)}
                    </TD>
                    <TD className="text-[13px] text-slate-700">{e.tax_group_name ?? "—"}</TD>
                    <TD className="text-end">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" onClick={() => setTaxSetupId(e.id)} aria-label={t("taxSetup.openNamed", { name: e.name })}>
                          <Receipt aria-hidden /> {t("taxSetup.open")}
                        </Button>
                        {admin && (
                          <>
                            <Button size="icon-sm" variant="ghost" onClick={() => setEditing(e)} aria-label={t("entities.editNamed", { name: e.name })}>
                              <Pencil aria-hidden />
                            </Button>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              onClick={() => (e.is_active ? setArchiving(e) : toggleActive.mutate(e))}
                              aria-label={t(e.is_active ? "entities.archiveNamed" : "entities.restoreNamed", { name: e.name })}
                            >
                              {e.is_active ? <Archive aria-hidden /> : <ArchiveRestore aria-hidden />}
                            </Button>
                          </>
                        )}
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Landmark className="size-4 text-slate-400" aria-hidden />
                {t("entities.taxGroups")}
              </CardTitle>
              <CardDescription>{t("entities.taxGroupsHint")}</CardDescription>
            </div>
            {admin && (
              <Button size="sm" variant="outline" onClick={() => setGroupOpen(true)}>
                <Plus aria-hidden /> {t("entities.newGroup")}
              </Button>
            )}
          </CardHeader>
          {groups.isLoading && <LoadingState rows={2} />}
          {groups.isError && <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />}
          {groups.data?.length === 0 && <p className="px-5 pb-5 text-sm text-slate-500">{t("entities.noGroups")}</p>}
          {groups.data && groups.data.length > 0 && (
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
              {groups.data.map((g) => (
                <li key={g.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                  <span className="font-medium text-navy-900">{g.name}</span>
                  <Badge tone="neutral">{g.country}</Badge>
                  <span className="font-mono text-xs text-slate-500" dir="ltr">
                    {g.trn_masked ?? ""}
                  </span>
                  <span className="ms-auto text-xs text-slate-500">{t("entities.memberCount", { count: g.entity_count })}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <EntityDialog
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        entity={editing && editing !== "new" ? editing : undefined}
        groups={groups.data ?? []}
      />
      <TaxGroupDialog open={groupOpen} onOpenChange={setGroupOpen} />
      <EntityTaxSetupDialog
        key={taxSetupId ?? "none"}
        entity={entities.data?.find((x) => x.id === taxSetupId) ?? null}
        onOpenChange={(o) => !o && setTaxSetupId(null)}
      />
      <ConfirmDialog
        open={archiving !== null}
        onOpenChange={(o) => !o && setArchiving(null)}
        title={t("entities.archiveTitle")}
        description={t("entities.archiveDescription", { name: archiving?.name ?? "" })}
        confirmLabel={t("entities.archive")}
        destructive
        busy={toggleActive.isPending}
        onConfirm={() => archiving && toggleActive.mutate(archiving)}
      />
    </>
  );
}
