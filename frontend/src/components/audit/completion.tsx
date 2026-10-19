import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowRightLeft, Loader2, MailCheck, Pencil, Plus, Scale, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { DocumentSummary, Page } from "@/lib/types";
import {
  AMOUNT_PATTERN,
  CONFIRMATION_TYPES,
  REF_PATTERN,
  SIGNED_AMOUNT_PATTERN,
  engKey,
  useAdjustments,
  useConfirmations,
  useSud,
  type Adjustment,
  type AdjustmentStatus,
  type Confirmation,
  type ConfirmationStatus,
  type Engagement,
} from "@/lib/audit";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState } from "@/components/common";
import { Amount, CalcSteps } from "@/components/calc-explain";
import { Field, Meta, MutationError } from "./shared";

// ---------------------------------------------------------------- confirmations

/** Allowed next statuses (mirrors the backend's transition table). */
const NEXT: Record<ConfirmationStatus, ConfirmationStatus[]> = {
  planned: ["sent"],
  sent: ["responded", "no_response"],
  responded: ["closed"],
  no_response: ["closed", "responded"],
  closed: [],
};

const CONF_TONE = { planned: "neutral", sent: "teal", responded: "teal", no_response: "amber", closed: "green" } as const;

const confSchema = z.object({
  type: z.enum(CONFIRMATION_TYPES),
  counterparty: z.string().trim().min(1).max(200),
  reference: z.string().trim().max(100),
  book_amount: z.string().trim().regex(SIGNED_AMOUNT_PATTERN),
});
type ConfValues = z.infer<typeof confSchema>;

function NewConfirmationDialog({ e, open, onOpenChange }: { e: Engagement; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<ConfValues>({ resolver: zodResolver(confSchema), defaultValues: { type: "bank", counterparty: "", reference: "", book_amount: "" } });
  const create = useMutation({
    mutationFn: (v: ConfValues) => api<Confirmation>(`/engagements/${e.id}/confirmations`, { json: v }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "confirmations") });
      toast.success(t("engagements.confirmations.created"));
      close();
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
      <DialogContent>
        <DialogTitle>{t("engagements.confirmations.new")}</DialogTitle>
        <DialogDescription>{t("engagements.confirmations.newHint", { currency: e.currency })}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="conf-type" label={t("engagements.confirmations.type")}>
              <Select id="conf-type" {...form.register("type")}>
                {CONFIRMATION_TYPES.map((c) => (
                  <option key={c} value={c}>
                    {t(`confirmationType.${c}`)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="conf-party" label={t("engagements.confirmations.counterparty")} error={err.counterparty ? t("engagements.nameRequired") : undefined}>
              <Input id="conf-party" aria-invalid={!!err.counterparty} {...form.register("counterparty")} />
            </Field>
            <Field id="conf-ref" label={t("engagements.confirmations.reference")} hint={t("engagements.confirmations.referenceHint")}>
              <Input id="conf-ref" dir="ltr" maxLength={100} {...form.register("reference")} />
            </Field>
            <Field id="conf-amount" label={t("engagements.confirmations.bookAmount")} error={err.book_amount ? t("directTax.signedAmountRule") : undefined}>
              <Input id="conf-amount" dir="ltr" inputMode="decimal" aria-invalid={!!err.book_amount} {...form.register("book_amount")} />
            </Field>
          </div>
          <MutationError error={create.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ConfirmationStatusDialog({ e, conf, onClose }: { e: Engagement; conf: Confirmation | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const next = conf ? NEXT[conf.status] : [];
  // The caller keys this dialog by confirmation, so the fields start fresh for each one.
  const [status, setStatus] = useState<ConfirmationStatus | "">(conf ? (NEXT[conf.status][0] ?? "") : "");
  const [sentOn, setSentOn] = useState("");
  const [respondedOn, setRespondedOn] = useState("");
  const [amount, setAmount] = useState("");
  const [docId, setDocId] = useState("");
  const [conclusion, setConclusion] = useState("");
  const docs = useQuery({
    queryKey: ["documents", "for-confirmation"],
    queryFn: () => api<Page<DocumentSummary>>("/documents?page_size=100"),
    enabled: status === "responded",
  });
  const save = useMutation({
    mutationFn: () =>
      api<Confirmation>(`/confirmations/${conf?.id}/status`, {
        json: {
          status,
          sent_on: status === "sent" ? sentOn || null : null,
          responded_on: status === "responded" ? respondedOn || null : null,
          confirmed_amount: status === "responded" ? amount || null : null,
          response_document_id: status === "responded" ? docId || null : null,
          conclusion: status === "closed" ? conclusion : "",
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "confirmations") });
      toast.success(t("engagements.confirmations.updated"));
      save.reset();
      onClose();
    },
  });
  const amountBad = status === "responded" && !!amount && !SIGNED_AMOUNT_PATTERN.test(amount);
  const missing =
    !status ||
    (status === "sent" && !sentOn) ||
    (status === "responded" && (!respondedOn || !amount || amountBad)) ||
    (status === "closed" && !conclusion.trim());
  return (
    <Dialog open={!!conf} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{t("engagements.confirmations.moveTitle", { party: conf?.counterparty ?? "" })}</DialogTitle>
        <DialogDescription>{t("engagements.confirmations.moveHint")}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (!missing) save.mutate();
          }}
        >
          <Field id="conf-status" label={t("engagements.status")}>
            <Select id="conf-status" value={status} onChange={(ev) => setStatus(ev.target.value as ConfirmationStatus)}>
              {next.map((s) => (
                <option key={s} value={s}>
                  {t(`confirmationStatus.${s}`)}
                </option>
              ))}
            </Select>
          </Field>
          {status === "sent" && (
            <Field id="conf-sent" label={t("engagements.confirmations.sentOn")}>
              <Input id="conf-sent" type="date" value={sentOn} onChange={(ev) => setSentOn(ev.target.value)} />
            </Field>
          )}
          {status === "responded" && (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="conf-resp" label={t("engagements.confirmations.respondedOn")}>
                  <Input id="conf-resp" type="date" value={respondedOn} onChange={(ev) => setRespondedOn(ev.target.value)} />
                </Field>
                <Field id="conf-confirmed" label={t("engagements.confirmations.confirmedAmount")} error={amountBad ? t("directTax.signedAmountRule") : undefined}>
                  <Input id="conf-confirmed" dir="ltr" inputMode="decimal" aria-invalid={amountBad} value={amount} onChange={(ev) => setAmount(ev.target.value)} />
                </Field>
              </div>
              <Field id="conf-doc" label={t("engagements.confirmations.responseDocument")}>
                <Select id="conf-doc" value={docId} onChange={(ev) => setDocId(ev.target.value)}>
                  <option value="">{t("engagements.confirmations.noDocument")}</option>
                  {(docs.data?.items ?? []).map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.title}
                    </option>
                  ))}
                </Select>
              </Field>
            </>
          )}
          {status === "closed" && (
            <Field id="conf-conclusion" label={t("engagements.procedures.conclusion")} hint={t("engagements.confirmations.conclusionHint")}>
              <Textarea id="conf-conclusion" rows={3} value={conclusion} onChange={(ev) => setConclusion(ev.target.value)} />
            </Field>
          )}
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={missing || save.isPending}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ConfirmationsTab({ e }: { e: Engagement }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const list = useConfirmations(e.id);
  const [open, setOpen] = useState(false);
  const [moving, setMoving] = useState<Confirmation | null>(null);
  const editable = can("write") && e.status !== "closed";
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{t("engagements.confirmations.title")}</CardTitle>
          <CardDescription>{t("engagements.confirmations.hint")}</CardDescription>
        </div>
        {editable && (
          <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
            <Plus aria-hidden /> {t("engagements.confirmations.new")}
          </Button>
        )}
      </CardHeader>
      {list.isLoading && <LoadingState rows={3} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.data?.length === 0 && <EmptyState icon={MailCheck} title={t("engagements.confirmations.empty")} />}
      {list.data && list.data.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{t("engagements.confirmations.counterparty")}</TH>
              <TH>{t("engagements.confirmations.type")}</TH>
              <TH className="text-end">{t("engagements.confirmations.bookAmount")}</TH>
              <TH className="text-end">{t("engagements.confirmations.confirmedAmount")}</TH>
              <TH className="text-end">{t("engagements.confirmations.difference")}</TH>
              <TH>{t("engagements.status")}</TH>
              {editable && <TH className="w-14">{t("common.actions")}</TH>}
            </tr>
          </THead>
          <TBody>
            {list.data.map((c) => (
              <TR key={c.id}>
                <TD className="max-w-72 align-top">
                  <span className="font-medium text-navy-900">{c.counterparty}</span>
                  {c.reference && (
                    <code dir="ltr" className="ms-2 font-mono text-[11px] text-slate-400">
                      {c.reference}
                    </code>
                  )}
                  <span className="block text-xs text-slate-500">
                    {c.sent_on && t("engagements.confirmations.sentOnDate", { date: formatDate(c.sent_on, i18n.language) })}
                    {c.responded_on && ` · ${t("engagements.confirmations.respondedOnDate", { date: formatDate(c.responded_on, i18n.language) })}`}
                  </span>
                  {c.conclusion && <p className="mt-1 text-xs text-slate-500">{c.conclusion}</p>}
                </TD>
                <TD className="align-top text-[13px]">{t(`confirmationType.${c.type}`)}</TD>
                <TD className="text-end align-top">
                  <Amount value={c.book_amount} currency={c.currency} />
                </TD>
                <TD className="text-end align-top">
                  <Amount value={c.confirmed_amount} />
                </TD>
                <TD className="text-end align-top">
                  <Amount value={c.difference} className={c.difference && !/^-?0(\.0+)?$/.test(c.difference) ? "text-red-700" : undefined} />
                </TD>
                <TD className="align-top">
                  <Badge tone={CONF_TONE[c.status]} dot>
                    {t(`confirmationStatus.${c.status}`)}
                  </Badge>
                </TD>
                {editable && (
                  <TD className="align-top">
                    {NEXT[c.status].length > 0 && (
                      <Button variant="ghost" size="icon-sm" aria-label={t("engagements.confirmations.moveNamed", { party: c.counterparty })} onClick={() => setMoving(c)}>
                        <ArrowRightLeft aria-hidden />
                      </Button>
                    )}
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
      )}
      <NewConfirmationDialog e={e} open={open} onOpenChange={setOpen} />
      <ConfirmationStatusDialog key={moving?.id ?? "none"} e={e} conf={moving} onClose={() => setMoving(null)} />
    </Card>
  );
}

// ---------------------------------------------------------------- adjustments and SUD

const adjSchema = z.object({
  ref: z.string().trim().regex(REF_PATTERN),
  description: z.string().trim().min(1).max(5000),
  lines: z
    .array(z.object({ account_code: z.string().trim().min(1).max(80), side: z.enum(["debit", "credit"]), amount: z.string().trim().regex(AMOUNT_PATTERN) }))
    .min(2)
    .max(50),
});
type AdjValues = z.infer<typeof adjSchema>;

function AdjustmentDialog({ e, adj, open, onOpenChange }: { e: Engagement; adj: Adjustment | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const isZero = (v: string) => /^0+(\.0+)?$/.test(v);
  const defaults = (): AdjValues => ({
    ref: adj?.ref ?? "",
    description: adj?.description ?? "",
    lines: adj
      ? adj.lines.map((l) => (isZero(l.debit) ? { account_code: l.account_code, side: "credit", amount: l.credit } : { account_code: l.account_code, side: "debit", amount: l.debit }))
      : [
          { account_code: "", side: "debit", amount: "" },
          { account_code: "", side: "credit", amount: "" },
        ],
  });
  const form = useForm<AdjValues>({ resolver: zodResolver(adjSchema), defaultValues: defaults() });
  const lines = useFieldArray({ control: form.control, name: "lines" });
  useEffect(() => {
    if (open) form.reset(defaults());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset each time the dialog opens
  }, [open, adj]);
  const save = useMutation({
    mutationFn: (v: AdjValues) =>
      api<Adjustment>(adj ? `/adjustments/${adj.id}` : `/engagements/${e.id}/adjustments`, {
        method: adj ? "PUT" : "POST",
        json: {
          ref: v.ref,
          description: v.description,
          finding_id: adj?.finding_id ?? null,
          lines: v.lines.map((l) => ({ account_code: l.account_code, debit: l.side === "debit" ? l.amount : "0", credit: l.side === "credit" ? l.amount : "0" })),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "adjustments") });
      void qc.invalidateQueries({ queryKey: engKey(e.id, "sud") });
      toast.success(t("engagements.adjustments.saved"));
      close();
    },
  });
  function close() {
    save.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl">
        <DialogTitle>{adj ? t("engagements.adjustments.edit") : t("engagements.adjustments.new")}</DialogTitle>
        <DialogDescription>{t("engagements.adjustments.dialogHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
            <Field id="adj-ref" label={t("engagements.ref")} error={err.ref ? t("engagements.refRule") : undefined}>
              <Input id="adj-ref" dir="ltr" aria-invalid={!!err.ref} {...form.register("ref")} />
            </Field>
            <Field id="adj-desc" label={t("engagements.descriptionField")} error={err.description ? t("engagements.descriptionRequired") : undefined}>
              <Input id="adj-desc" aria-invalid={!!err.description} {...form.register("description")} />
            </Field>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-[13px] font-medium text-slate-700">{t("engagements.adjustments.lines")}</legend>
            {lines.fields.map((f, i) => (
              <div key={f.id} className="flex flex-wrap items-end gap-2">
                <Field id={`adj-acc-${i}`} label={t("engagements.tb.accountRow", { n: i + 1 })}>
                  <Input id={`adj-acc-${i}`} dir="ltr" className="w-40" aria-invalid={!!err.lines?.[i]?.account_code} {...form.register(`lines.${i}.account_code`)} />
                </Field>
                <Field id={`adj-side-${i}`} label={t("engagements.adjustments.side")}>
                  <Select id={`adj-side-${i}`} className="w-32" {...form.register(`lines.${i}.side`)}>
                    <option value="debit">{t("engagements.adjustments.debit")}</option>
                    <option value="credit">{t("engagements.adjustments.credit")}</option>
                  </Select>
                </Field>
                <Field id={`adj-amt-${i}`} label={t("losses.amount")}>
                  <Input id={`adj-amt-${i}`} dir="ltr" inputMode="decimal" className="w-40" aria-invalid={!!err.lines?.[i]?.amount} {...form.register(`lines.${i}.amount`)} />
                </Field>
                <Button type="button" variant="ghost" size="icon-sm" disabled={lines.fields.length <= 2} aria-label={t("engagements.tb.removeRow", { n: i + 1 })} onClick={() => lines.remove(i)}>
                  <Trash2 aria-hidden />
                </Button>
              </div>
            ))}
            {err.lines && <p role="alert" className="text-xs font-medium text-red-600">{t("engagements.adjustments.linesRule")}</p>}
            <p className="text-xs text-slate-500">{t("engagements.adjustments.balanceHint")}</p>
            <Button type="button" variant="outline" size="sm" disabled={lines.fields.length >= 50} onClick={() => lines.append({ account_code: "", side: "debit", amount: "" })}>
              <Plus aria-hidden /> {t("engagements.adjustments.addLine")}
            </Button>
          </fieldset>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
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

function DecideDialog({ e, target, onClose }: { e: Engagement; target: { a: Adjustment; status: AdjustmentStatus } | null; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  // Keyed by the caller per adjustment and target status.
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => api<Adjustment>(`/adjustments/${target?.a.id}/status`, { json: { status: target?.status, reason } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: engKey(e.id, "adjustments") });
      void qc.invalidateQueries({ queryKey: engKey(e.id, "sud") });
      toast.success(t("engagements.adjustments.decided"));
      save.reset();
      onClose();
    },
  });
  const needsReason = target?.status === "passed" || target?.status === "proposed";
  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogTitle>{target ? t(`engagements.adjustments.to.${target.status}`, { ref: target.a.ref }) : ""}</DialogTitle>
        <DialogDescription>{target ? t(`engagements.adjustments.toHint.${target.status}`) : ""}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            save.mutate();
          }}
        >
          <Field id="adj-reason" label={t("workpapers.reason")}>
            <Textarea id="adj-reason" rows={3} value={reason} onChange={(ev) => setReason(ev.target.value)} />
          </Field>
          <MutationError error={save.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={save.isPending || (needsReason && !reason.trim())}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const ADJ_TONE = { proposed: "amber", recorded: "green", passed: "orange" } as const;

function SudCard({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const sud = useSud(e.id);
  const s = sud.data;
  const verdictTone = s?.total_vs_overall === "at_or_above" ? "red" : s?.total_vs_overall === "below" ? "green" : "neutral";
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t("engagements.sud.title")}</CardTitle>
        <CardDescription>{t("engagements.sud.hint")}</CardDescription>
      </CardHeader>
      {sud.isLoading && <LoadingState rows={2} />}
      {sud.isError && <ErrorState error={sud.error} onRetry={() => void sud.refetch()} />}
      {s && (
        <div className="space-y-4 px-5 py-4">
          <dl className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Meta label={t("engagements.sud.profitEffect")}>
              <Amount value={s.profit_effect} currency={e.currency} />
            </Meta>
            <Meta label={t("engagements.sud.netAssetsEffect")}>
              <Amount value={s.net_assets_effect} />
            </Meta>
            <Meta label={t("engagements.sud.overall")}>
              <Amount value={s.materiality?.overall ?? null} />
            </Meta>
            <Meta label={t("engagements.sud.trivial")}>
              <Amount value={s.materiality?.trivial ?? null} />
            </Meta>
            <Meta label={t("engagements.sud.verdict")}>
              <Badge tone={verdictTone} dot>
                {t(`engagements.sud.vs.${s.total_vs_overall}`)}
              </Badge>
            </Meta>
          </dl>
          {!s.materiality && <p className="text-xs text-slate-500">{t("engagements.sud.noMateriality")}</p>}
          {s.materiality?.version != null && <p className="text-xs text-slate-500">{t("engagements.sud.materialityFrom", { version: s.materiality.version })}</p>}
          {s.clearly_trivial.length > 0 && <p className="text-xs text-slate-600">{t("engagements.sud.clearlyTrivial", { refs: s.clearly_trivial.join(", ") })}</p>}
          <CalcSteps steps={s.steps} />
          <p className="text-xs text-slate-500">{t("engagements.sud.judgementNote")}</p>
        </div>
      )}
    </Card>
  );
}

export function AdjustmentsTab({ e }: { e: Engagement }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const list = useAdjustments(e.id);
  const [editing, setEditing] = useState<Adjustment | null>(null);
  const [open, setOpen] = useState(false);
  const [deciding, setDeciding] = useState<{ a: Adjustment; status: AdjustmentStatus } | null>(null);
  const editable = can("write") && e.status !== "closed";
  return (
    <div className="space-y-5">
      <Card className="overflow-hidden">
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>{t("engagements.adjustments.title")}</CardTitle>
            <CardDescription>{t("engagements.adjustments.hint")}</CardDescription>
          </div>
          {editable && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setEditing(null);
                setOpen(true);
              }}
            >
              <Plus aria-hidden /> {t("engagements.adjustments.new")}
            </Button>
          )}
        </CardHeader>
        {list.isLoading && <LoadingState rows={3} />}
        {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
        {list.data?.length === 0 && <EmptyState icon={Scale} title={t("engagements.adjustments.empty")} />}
        {list.data && list.data.length > 0 && (
          <Table>
            <THead>
              <tr>
                <TH>{t("engagements.ref")}</TH>
                <TH>{t("engagements.adjustments.lines")}</TH>
                <TH className="text-end">{t("engagements.sud.profitEffect")}</TH>
                <TH className="text-end">{t("engagements.sud.netAssetsEffect")}</TH>
                <TH>{t("engagements.status")}</TH>
                {editable && <TH>{t("common.actions")}</TH>}
              </tr>
            </THead>
            <TBody>
              {list.data.map((a) => (
                <TR key={a.id}>
                  <TD className="max-w-64 align-top">
                    <code dir="ltr" className="font-mono text-xs">
                      {a.ref}
                    </code>
                    <p className="mt-0.5 text-[13px] text-navy-900">{a.description}</p>
                    {a.reason && <p className="mt-0.5 text-xs text-slate-500">{a.reason}</p>}
                    {a.unmapped_accounts.length > 0 && (
                      <p className="mt-0.5 text-xs text-amber-700">{t("engagements.adjustments.unmapped", { accounts: a.unmapped_accounts.join(", ") })}</p>
                    )}
                  </TD>
                  <TD className="align-top">
                    <ul className="space-y-0.5 text-xs" dir="ltr">
                      {a.lines.map((l, i) => (
                        <li key={i} className="font-mono text-slate-600">
                          {l.account_code}
                          {l.lead_code ? ` [${l.lead_code}]` : ""} {/^0+(\.0+)?$/.test(l.debit) ? `Cr ${l.credit}` : `Dr ${l.debit}`}
                        </li>
                      ))}
                    </ul>
                  </TD>
                  <TD className="text-end align-top">
                    <Amount value={a.profit_effect} />
                  </TD>
                  <TD className="text-end align-top">
                    <Amount value={a.net_assets_effect} />
                  </TD>
                  <TD className="align-top">
                    <Badge tone={ADJ_TONE[a.status]} dot>
                      {t(`adjustmentStatus.${a.status}`)}
                    </Badge>
                  </TD>
                  {editable && (
                    <TD className="align-top">
                      <div className="flex flex-wrap gap-1">
                        {a.status === "proposed" && (
                          <>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={t("workpapers.editNamed", { name: a.ref })}
                              onClick={() => {
                                setEditing(a);
                                setOpen(true);
                              }}
                            >
                              <Pencil aria-hidden />
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => setDeciding({ a, status: "recorded" })}>
                              {t("engagements.adjustments.record")}
                            </Button>
                            {can("decide") && (
                              <Button variant="outline" size="sm" onClick={() => setDeciding({ a, status: "passed" })}>
                                {t("engagements.adjustments.pass")}
                              </Button>
                            )}
                          </>
                        )}
                        {a.status !== "proposed" && (
                          <Button variant="outline" size="sm" onClick={() => setDeciding({ a, status: "proposed" })}>
                            {t("engagements.adjustments.backToProposed")}
                          </Button>
                        )}
                      </div>
                    </TD>
                  )}
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
      <SudCard e={e} />
      <AdjustmentDialog e={e} adj={editing} open={open} onOpenChange={setOpen} />
      <DecideDialog key={deciding ? `${deciding.a.id}:${deciding.status}` : "none"} e={e} target={deciding} onClose={() => setDeciding(null)} />
    </div>
  );
}
