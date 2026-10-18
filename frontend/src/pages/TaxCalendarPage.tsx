import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { BadgeCheck, CalendarClock, CalendarPlus, Loader2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { TaxCalendarResult, TaxObligation } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useEntities, useMembers, usePublishedRulePacks } from "@/lib/queries";
import { cn, formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, errorMessage, LoadingState, PageHeader, TaskStatusBadge, UnverifiedBadge } from "@/components/common";

const KEY_PATTERN = /^[a-z0-9_]+(\.[a-z0-9_]+)*$/;

const generateSchema = z
  .object({
    entity_id: z.string().min(1),
    rule_pack_version_id: z.string().min(1),
    prefix: z.string().trim().min(1).max(80).regex(KEY_PATTERN),
    start: z.string().min(1),
    end: z.string().min(1),
    owner_id: z.string(),
    include_einvoicing: z.boolean(),
    waves_rule: z.union([z.literal(""), z.string().trim().max(120).regex(KEY_PATTERN)]),
  })
  .refine((v) => !v.start || !v.end || v.end >= v.start, { path: ["end"], message: "order" });
type GenerateValues = z.infer<typeof generateSchema>;

function GenerateDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const entities = useEntities(open);
  const packs = usePublishedRulePacks(open);
  const members = useMembers(open);
  const [result, setResult] = useState<TaxCalendarResult | null>(null);
  const form = useForm<GenerateValues>({
    resolver: zodResolver(generateSchema),
    defaultValues: { entity_id: "", rule_pack_version_id: "", prefix: "", start: "", end: "", owner_id: "", include_einvoicing: true, waves_rule: "" },
  });
  const generate = useMutation({
    mutationFn: (v: GenerateValues) =>
      api<TaxCalendarResult>(`/entities/${v.entity_id}/tax-calendar/generate`, {
        json: {
          rule_pack_version_id: v.rule_pack_version_id,
          prefix: v.prefix,
          start: v.start,
          end: v.end,
          owner_id: v.owner_id || null,
          include_einvoicing: v.include_einvoicing,
          waves_rule: v.waves_rule || null,
        },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["tax-obligations"] });
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      void qc.invalidateQueries({ queryKey: ["tax-periods"] });
      setResult(r);
      toast.success(t("taxCalendar.generated"));
    },
  });
  const close = () => {
    setResult(null);
    form.reset();
    generate.reset();
    onOpenChange(false);
  };
  const err = form.formState.errors;
  const packId = useWatch({ control: form.control, name: "rule_pack_version_id" });
  const includeEinvoicing = useWatch({ control: form.control, name: "include_einvoicing" });
  const selectedPack = packs.items.find((x) => x.v.id === packId);
  const loading = entities.isLoading || packs.query.isLoading || members.isLoading;
  const failed = entities.isError || packs.query.isError || members.isError;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogTitle>{t("taxCalendar.generate")}</DialogTitle>
        <DialogDescription>{t("taxCalendar.generateHint")}</DialogDescription>
        {loading && <LoadingState rows={3} />}
        {failed && (
          <ErrorState
            error={entities.error ?? packs.query.error ?? members.error}
            onRetry={() => {
              void entities.refetch();
              void packs.query.refetch();
              void members.refetch();
            }}
          />
        )}
        {result && (
          <div className="mt-5 space-y-3" role="status">
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(["created", "updated", "unchanged", "periods_created"] as const).map((k) => (
                <div key={k} className="rounded-lg border border-slate-200 px-3 py-2">
                  <dt className="text-xs text-slate-500">{t(`taxCalendar.result.${k}`)}</dt>
                  <dd className="text-lg font-semibold tabular-nums text-navy-900">{result[k]}</dd>
                </div>
              ))}
            </dl>
            {result.warnings.length > 0 && (
              <div className="rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-orange-900">
                <p className="mb-1 flex items-center gap-1.5 font-medium">
                  <TriangleAlert className="size-3.5" aria-hidden />
                  {t("taxCalendar.warnings")}
                </p>
                <ul className="list-disc space-y-0.5 ps-5">
                  {result.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}
            <DialogFooter>
              <Button variant="accent" onClick={close}>
                {t("common.close")}
              </Button>
            </DialogFooter>
          </div>
        )}
        {!result && entities.data && packs.query.data && members.data && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => generate.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="tc-entity">{t("datasets.entity")}</Label>
                <Select id="tc-entity" aria-invalid={!!err.entity_id} {...form.register("entity_id")}>
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
                <Label htmlFor="tc-pack">{t("reviews.rulePack")}</Label>
                <Select id="tc-pack" aria-invalid={!!err.rule_pack_version_id} {...form.register("rule_pack_version_id")}>
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
            </div>
            {selectedPack && selectedPack.v.unverified_count > 0 && (
              <p className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-orange-900">
                <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
                {t("taxCalendar.unverifiedPack")}
              </p>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="tc-prefix">{t("taxCalendar.prefix")}</Label>
              <Input id="tc-prefix" dir="ltr" placeholder="ae.vat" aria-invalid={!!err.prefix} aria-describedby="tc-prefix-hint" {...form.register("prefix")} />
              <p id="tc-prefix-hint" className="text-xs text-slate-500">
                {t("taxCalendar.prefixHint")}
              </p>
              <FieldError message={err.prefix ? t("rulePacks.ruleKeyRule") : undefined} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="tc-start">{t("taxCalendar.start")}</Label>
                <Input id="tc-start" type="date" aria-invalid={!!err.start} {...form.register("start")} />
                <FieldError message={err.start ? t("rulePacks.dateRequired") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tc-end">{t("taxCalendar.end")}</Label>
                <Input id="tc-end" type="date" aria-invalid={!!err.end} {...form.register("end")} />
                <FieldError message={err.end ? (err.end.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired")) : undefined} />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tc-owner">{t("taxCalendar.owner")}</Label>
              <Select id="tc-owner" {...form.register("owner_id")}>
                <option value="">{t("findings.unassigned")}</option>
                {members.data.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.full_name}
                  </option>
                ))}
              </Select>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" className="size-4 rounded border-slate-300 accent-teal-600" {...form.register("include_einvoicing")} />
              {t("taxCalendar.includeEinvoicing")}
            </label>
            {includeEinvoicing && (
              <div className="space-y-1.5">
                <Label htmlFor="tc-waves">{t("taxCalendar.wavesRule")}</Label>
                <Input id="tc-waves" dir="ltr" aria-invalid={!!err.waves_rule} aria-describedby="tc-waves-hint" {...form.register("waves_rule")} />
                <p id="tc-waves-hint" className="text-xs text-slate-500">
                  {t("taxCalendar.wavesHint")}
                </p>
                <FieldError message={err.waves_rule ? t("rulePacks.ruleKeyRule") : undefined} />
              </div>
            )}
            {generate.isError && (
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {errorMessage(generate.error, t("common.genericError"))}
              </p>
            )}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={generate.isPending}>
                {generate.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t("taxCalendar.generate")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function TaxCalendarPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [entityId, setEntityId] = useState("");
  const [dueFrom, setDueFrom] = useState("");
  const [dueTo, setDueTo] = useState("");
  const entities = useEntities();
  const obligations = useQuery({
    queryKey: ["tax-obligations", { entityId, dueFrom, dueTo }],
    queryFn: () => api<TaxObligation[]>(`/tax-obligations${qs({ entity_id: entityId, due_from: dueFrom, due_to: dueTo })}`),
  });
  const anyUnverified = (obligations.data ?? []).some((o) => !o.rule_verified);
  return (
    <>
      <PageHeader
        title={t("taxCalendar.title")}
        description={t("taxCalendar.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.taxCalendar") }]}
        actions={
          can("decide") && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <CalendarPlus aria-hidden /> {t("taxCalendar.generate")}
            </Button>
          )
        }
      />
      <div className="space-y-4">
        <p
          className={cn(
            "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed",
            anyUnverified ? "border-orange-200 bg-orange-50 text-orange-900" : "border-slate-200 bg-slate-50 text-slate-600",
          )}
        >
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          {t("taxCalendar.draftNote")}
        </p>
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 p-3">
            <div className="space-y-1">
              <Label htmlFor="tc-filter-entity">{t("datasets.entity")}</Label>
              <Select id="tc-filter-entity" className="w-60" value={entityId} onChange={(e) => setEntityId(e.target.value)}>
                <option value="">{t("einvoices.allEntities")}</option>
                {(entities.data ?? []).map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="tc-from">{t("taxCalendar.dueFrom")}</Label>
              <Input id="tc-from" type="date" className="w-44" value={dueFrom} onChange={(e) => setDueFrom(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="tc-to">{t("taxCalendar.dueTo")}</Label>
              <Input id="tc-to" type="date" className="w-44" value={dueTo} onChange={(e) => setDueTo(e.target.value)} />
            </div>
          </div>
          {obligations.isLoading && <LoadingState />}
          {obligations.isError && <ErrorState error={obligations.error} onRetry={() => void obligations.refetch()} />}
          {obligations.data?.length === 0 && (
            <EmptyState
              icon={CalendarClock}
              title={t("taxCalendar.empty")}
              description={can("decide") ? t("taxCalendar.emptyHintDecider") : t("taxCalendar.emptyHint")}
            />
          )}
          {obligations.data && obligations.data.length > 0 && (
            <Table>
              <THead>
                <tr>
                  <TH>{t("taxCalendar.obligation")}</TH>
                  <TH>{t("taxCalendar.period")}</TH>
                  <TH>{t("taxCalendar.dueDate")}</TH>
                  <TH>{t("taxCalendar.formula")}</TH>
                  <TH>{t("taxCalendar.task")}</TH>
                </tr>
              </THead>
              <TBody>
                {obligations.data.map((o) => (
                  <TR key={o.id}>
                    <TD className="align-top">
                      <span className="font-medium text-navy-900">{o.label}</span>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        <span>{o.entity_name}</span>
                        <Badge tone="neutral">{t(`taxType.${o.tax_type}`, { defaultValue: o.tax_type })}</Badge>
                      </div>
                    </TD>
                    <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                      {formatDate(o.period_start, i18n.language)} – {formatDate(o.period_end, i18n.language)}
                    </TD>
                    <TD className="whitespace-nowrap align-top text-[13px] font-medium text-navy-900">
                      {formatDate(o.due_date, i18n.language)}
                      {o.task?.is_overdue && (
                        <Badge tone="red" className="ms-2">
                          {t("findings.overdue")}
                        </Badge>
                      )}
                    </TD>
                    <TD className="max-w-80 align-top">
                      <code className="block break-words font-mono text-[11.5px] text-slate-700" dir="ltr">
                        {o.formula}
                      </code>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <code className="font-mono text-[11px] text-slate-400" dir="ltr">
                          {o.rule_key}
                        </code>
                        {o.rule_verified ? (
                          <Badge tone="green">
                            <BadgeCheck className="size-3" aria-hidden />
                            {t("rulePacks.verifiedBadge")}
                          </Badge>
                        ) : (
                          <UnverifiedBadge />
                        )}
                      </div>
                    </TD>
                    <TD className="align-top text-[13px]">
                      {o.task ? (
                        <div className="space-y-1">
                          <TaskStatusBadge status={o.task.status} />
                          <p className="text-xs text-slate-500">{o.task.owner_name ?? t("findings.unassigned")}</p>
                        </div>
                      ) : (
                        "—"
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>
      <GenerateDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
