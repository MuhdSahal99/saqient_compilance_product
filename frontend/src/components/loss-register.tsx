import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { History, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { LossEntry } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { lossRegisterKey, useLossRegister } from "@/lib/queries";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, errorMessage, LoadingState, useUnsavedChangesWarning } from "@/components/common";
import { Amount } from "@/components/calc-explain";

/** Positive decimal with up to 4 places, kept as a string (never a float). */
const POSITIVE_AMOUNT = /^(?!0+(\.0+)?$)\d{1,16}(\.\d{1,4})?$/;

const entrySchema = z
  .object({
    kind: z.enum(["incurred", "used", "forfeited"]),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
    amount: z.string().trim().regex(POSITIVE_AMOUNT),
    note: z.string().trim().min(1).max(4000),
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type EntryValues = z.infer<typeof entrySchema>;

function AddEntryForm({ entityId }: { entityId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<EntryValues>({
    resolver: zodResolver(entrySchema),
    defaultValues: { kind: "incurred", period_start: "", period_end: "", amount: "", note: "" },
  });
  useUnsavedChangesWarning(form.formState.isDirty);
  const add = useMutation({
    mutationFn: (v: EntryValues) => api<LossEntry>(`/entities/${entityId}/tax-losses`, { json: v }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: lossRegisterKey(entityId) });
      form.reset();
      toast.success(t("losses.added"));
    },
  });
  const err = form.formState.errors;
  return (
    <form className="space-y-3" onSubmit={form.handleSubmit((v) => add.mutate(v))} noValidate>
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor="loss-kind">{t("losses.kind")}</Label>
          <Select id="loss-kind" {...form.register("kind")}>
            {(["incurred", "used", "forfeited"] as const).map((k) => (
              <option key={k} value={k}>
                {t(`lossKind.${k}`)}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="loss-start">{t("workpapers.periodStart")}</Label>
          <Input id="loss-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
          <FieldError message={err.period_start ? t("rulePacks.dateRequired") : undefined} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="loss-end">{t("workpapers.periodEnd")}</Label>
          <Input id="loss-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
          <FieldError
            message={err.period_end ? (err.period_end.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired")) : undefined}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="loss-amount">{t("losses.amount")}</Label>
          <Input id="loss-amount" dir="ltr" inputMode="decimal" aria-invalid={!!err.amount} {...form.register("amount")} />
          <FieldError message={err.amount ? t("directTax.positiveAmountRule") : undefined} />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="loss-note">{t("losses.note")}</Label>
        <Textarea id="loss-note" rows={2} aria-invalid={!!err.note} aria-describedby="loss-note-hint" {...form.register("note")} />
        <p id="loss-note-hint" className="text-xs text-slate-500">
          {t("losses.noteHint")}
        </p>
        <FieldError message={err.note ? t("losses.noteRequired") : undefined} />
      </div>
      {add.isError && (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {errorMessage(add.error, t("common.genericError"))}
        </p>
      )}
      <div className="flex justify-end">
        <Button type="submit" variant="accent" disabled={add.isPending}>
          {add.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Plus aria-hidden />}
          {t("losses.add")}
        </Button>
      </div>
    </form>
  );
}

export function LossRegisterPanel({ entityId }: { entityId: string }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const reg = useLossRegister(entityId);
  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        {reg.isLoading && <LoadingState />}
        {reg.isError && <ErrorState error={reg.error} onRetry={() => void reg.refetch()} />}
        {reg.data && (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-100 p-4">
              <div>
                <p className="text-xs text-slate-500">{t("losses.balance")}</p>
                <p className="mt-0.5 text-2xl font-semibold">
                  <Amount value={reg.data.balance} currency={reg.data.currency} className="text-2xl" />
                </p>
              </div>
              <p className="max-w-md text-xs leading-relaxed text-slate-500">{t("losses.balanceHint")}</p>
            </div>
            {reg.data.entries.length === 0 ? (
              <EmptyState icon={History} title={t("losses.empty")} description={t("losses.emptyHint")} />
            ) : (
              <Table>
                <THead>
                  <tr>
                    <TH>{t("losses.kind")}</TH>
                    <TH>{t("workpapers.period")}</TH>
                    <TH className="text-end">{t("losses.amount")}</TH>
                    <TH>{t("losses.counterparty")}</TH>
                    <TH>{t("losses.note")}</TH>
                  </tr>
                </THead>
                <TBody>
                  {reg.data.entries.map((e) => (
                    <TR key={e.id}>
                      <TD className="align-top">
                        <Badge tone={e.signed_amount.startsWith("-") ? "amber" : "teal"}>{t(`lossKind.${e.kind}`)}</Badge>
                      </TD>
                      <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                        {formatDate(e.period_start, i18n.language)} – {formatDate(e.period_end, i18n.language)}
                      </TD>
                      <TD className="whitespace-nowrap text-end align-top">
                        <Amount value={e.signed_amount} />
                      </TD>
                      <TD className="align-top text-[13px] text-slate-600">{e.counterparty_name ?? "—"}</TD>
                      <TD className="max-w-80 align-top text-[13px] text-slate-600">{e.note || "—"}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </>
        )}
      </Card>
      {can("write") && reg.data && (
        <Card>
          <CardHeader>
            <CardTitle>{t("losses.addTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <AddEntryForm entityId={entityId} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
