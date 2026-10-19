import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { GitCompareArrows, Link2, Link2Off, Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SIGNED_AMOUNT_PATTERN } from "@/lib/audit";
import {
  accountRecsKey,
  asCalcSteps,
  bankRecsKey,
  detailKey,
  icRecsKey,
  useAccountRec,
  useBankRec,
  useIcRec,
  type AccountRec,
  type BankRec,
  type Intercompany,
  type ReconItem,
  type ReconSide,
} from "@/lib/assurance";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { Amount, CalcSteps, UnverifiedWarnings } from "@/components/calc-explain";
import { Field, MutationError } from "@/components/audit/shared";
import { AssuranceNote, AssuranceStatusBadge, Facts, MemberSelect, ReasonDialog, SignOffCard } from "@/components/assurance/shared";

const ZERO = /^-?0+(\.0+)?$/;
const crumbs = (t: (k: string) => string, tab: string, label: string) => [
  { label: t("nav.overview"), to: "/" },
  { label: t("nav.reconciliations"), to: tab === "bank" ? "/reconciliations" : `/reconciliations?tab=${tab}` },
  { label },
];

// ---------------------------------------------------------------- bank reconciliation

function MatchDialog({
  rec,
  bank,
  book,
  open,
  onOpenChange,
  onDone,
}: {
  rec: BankRec;
  bank: number[];
  book: number[];
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const match = useMutation({
    mutationFn: () => api<BankRec>(`/bank-reconciliations/${rec.id}/matches`, { json: { bank_row_ids: bank, book_row_ids: book, reason: reason.trim() } }),
    onSuccess: (d) => {
      qc.setQueryData(detailKey(bankRecsKey, rec.id), d);
      toast.success(t("recs.bank.matched"));
      setReason("");
      onDone();
    },
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) match.reset();
        onOpenChange(o);
      }}
    >
      <DialogContent>
        <DialogTitle>{t("recs.bank.matchTitle")}</DialogTitle>
        <DialogDescription>{t("recs.bank.matchHint", { bank: bank.length, book: book.length })}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (reason.trim().length >= 3) match.mutate();
          }}
        >
          <Field id="match-reason" label={t("assurance.reason")} hint={t("assurance.reasonHint")}>
            <Textarea id="match-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <MutationError error={match.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={reason.trim().length < 3 || match.isPending}>
              {match.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("recs.bank.match")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function UnmatchedTable({
  side,
  items,
  currency,
  selectable,
  selected,
  onToggle,
}: {
  side: ReconSide;
  items: ReconItem[];
  currency: string;
  selectable: boolean;
  selected: Set<number>;
  onToggle: (id: number) => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>{t(`recs.bank.unmatched_${side}`)}</CardTitle>
        <CardDescription>{t("recs.bank.unmatchedHint")}</CardDescription>
      </CardHeader>
      {items.length === 0 ? (
        <EmptyState title={t("recs.bank.noUnmatched")} />
      ) : (
        <Table>
          <THead>
            <tr>
              {selectable && <TH className="w-8"><span className="sr-only">{t("recs.bank.select")}</span></TH>}
              <TH>{t("recs.bank.date")}</TH>
              <TH>{t("recs.bank.reference")}</TH>
              <TH className="text-end">{t("recs.bank.amount")}</TH>
              <TH>{t("recs.bank.age")}</TH>
            </tr>
          </THead>
          <TBody>
            {items.map((it) => (
              <TR key={it.row_id}>
                {selectable && (
                  <TD>
                    <input
                      type="checkbox"
                      className="size-4 accent-teal-600"
                      aria-label={t("recs.bank.selectRow", { row: it.row_id })}
                      checked={selected.has(it.row_id)}
                      onChange={() => onToggle(it.row_id)}
                    />
                  </TD>
                )}
                <TD className="whitespace-nowrap text-[13px] text-slate-600">{formatDate(it.date, i18n.language)}</TD>
                <TD className="text-[13px]">
                  <span className="font-medium text-navy-900">{it.reference || "—"}</span>
                  <div className="text-xs text-slate-500">
                    {it.description} · {t("recs.bank.row", { row: it.row_id })}
                  </div>
                </TD>
                <TD className="text-end">
                  <Amount value={it.amount} currency={currency} />
                </TD>
                <TD className="whitespace-nowrap text-[13px] text-slate-600">
                  {it.age_days != null ? t("recs.bank.days", { count: it.age_days }) : "—"}
                  {it.bucket && (
                    <Badge tone="neutral" className="ms-2">
                      <span dir="ltr">{it.bucket}</span>
                    </Badge>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </Card>
  );
}

export function BankRecDetailPage() {
  const { recId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useBankRec(recId);
  const [bankSel, setBankSel] = useState<Set<number>>(new Set());
  const [bookSel, setBookSel] = useState<Set<number>>(new Set());
  const [matchOpen, setMatchOpen] = useState(false);
  const [unmatchId, setUnmatchId] = useState<string | null>(null);
  const setData = (d: BankRec) => {
    qc.setQueryData(detailKey(bankRecsKey, d.id), d);
    void qc.invalidateQueries({ queryKey: [...bankRecsKey, "list"] });
  };
  const auto = useMutation({
    mutationFn: () => api<BankRec>(`/bank-reconciliations/${recId}/auto-match`, { method: "POST" }),
    onSuccess: (d) => {
      setData(d);
      toast.success(t("recs.bank.autoMatched"));
    },
  });
  const unmatch = useMutation({
    mutationFn: (v: { id: string; reason: string }) =>
      api<BankRec>(`/bank-reconciliations/${recId}/matches/${v.id}${qs({ reason: v.reason })}`, { method: "DELETE" }),
    onSuccess: (d) => {
      setData(d);
      setUnmatchId(null);
      toast.success(t("recs.bank.unmatched"));
    },
  });
  if (q.isLoading) return <LoadingState />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const r = q.data;
  const s = r.summary;
  const editable = can("write") && r.sign_off.status !== "signed_off";
  const unmatched = (side: ReconSide) => r.items.filter((i) => i.side === side && !i.match_id);
  const toggle = (set: Set<number>, fn: (s: Set<number>) => void) => (id: number) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    fn(next);
  };
  const blocker = s.difference == null ? t("recs.bank.noClosing") : ZERO.test(s.difference) ? null : t("recs.bank.differenceBlocks");
  return (
    <>
      <PageHeader
        title={r.name}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {r.entity_name} · {r.account_label} · {formatDate(r.period_start, i18n.language)} – {formatDate(r.period_end, i18n.language)}
            {r.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={crumbs(t, "bank", r.name)}
        actions={
          <>
            <AssuranceStatusBadge status={r.sign_off.status} />
            {editable && (
              <Button variant="outline" disabled={auto.isPending} onClick={() => auto.mutate()}>
                {auto.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
                {t("recs.bank.autoMatch")}
              </Button>
            )}
          </>
        }
      />
      <div className="space-y-5">
        <AssuranceNote>{t("recs.bank.note")}</AssuranceNote>
        <MutationError error={auto.error} />
        <UnverifiedWarnings warnings={r.warnings} />
        <Card>
          <CardHeader>
            <CardTitle>{t("recs.bank.proof")}</CardTitle>
            <CardDescription>{t("recs.bank.proofHint", { matcher: r.matcher_version })}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Facts
              items={[
                { label: t("recs.bank.closingBalance"), value: <Amount value={s.bank_closing_balance} currency={r.currency} /> },
                { label: t("recs.bank.bookClosing"), value: <Amount value={s.book_closing_balance} currency={r.currency} /> },
                { label: t("recs.bank.adjustedBank"), value: <Amount value={s.adjusted_bank} /> },
                { label: t("recs.bank.adjustedBook"), value: <Amount value={s.adjusted_book} /> },
                {
                  label: t("recs.difference"),
                  value: (
                    <span className="flex items-center gap-2">
                      <Amount value={s.difference} />
                      {s.difference != null && !ZERO.test(s.difference) && <Badge tone="amber">{t("recs.bank.notReconciled")}</Badge>}
                    </span>
                  ),
                },
                { label: t("recs.bank.matchedBank"), value: `${s.matched_bank_items} / ${s.bank_items}` },
                { label: t("recs.bank.matchedBook"), value: `${s.matched_book_items} / ${s.book_items}` },
                { label: t("recs.bank.closingSource"), value: t(`recs.bank.source_${s.bank_closing_source}`) },
              ]}
            />
            <CalcSteps steps={asCalcSteps(s.steps)} />
            {s.ageing.length > 0 && (
              <div>
                <h3 className="mb-2 text-[13px] font-semibold text-navy-900">{t("recs.bank.ageing")}</h3>
                <Table>
                  <THead>
                    <tr>
                      <TH>{t("recs.bank.side")}</TH>
                      <TH>{t("recs.bank.bucket")}</TH>
                      <TH className="text-end">{t("recs.bank.items")}</TH>
                      <TH className="text-end">{t("recs.bank.total")}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {s.ageing.map((a) => (
                      <TR key={`${a.side}-${a.bucket}`}>
                        <TD className="text-[13px]">{t(`recs.bank.side_${a.side}`)}</TD>
                        <TD className="text-[13px]" dir="ltr">
                          {a.bucket}
                        </TD>
                        <TD className="text-end text-[13px] tabular-nums">{a.count}</TD>
                        <TD className="text-end">
                          <Amount value={a.total} />
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        {editable && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-[13px]">
            <span className="text-slate-600">{t("recs.bank.selection", { bank: bankSel.size, book: bookSel.size })}</span>
            <Button size="sm" variant="accent" disabled={bankSel.size === 0 || bookSel.size === 0} onClick={() => setMatchOpen(true)}>
              <Link2 aria-hidden />
              {t("recs.bank.matchSelected")}
            </Button>
          </div>
        )}
        <div className="grid gap-5 xl:grid-cols-2">
          <UnmatchedTable side="bank" items={unmatched("bank")} currency={r.currency} selectable={editable} selected={bankSel} onToggle={toggle(bankSel, setBankSel)} />
          <UnmatchedTable side="book" items={unmatched("book")} currency={r.currency} selectable={editable} selected={bookSel} onToggle={toggle(bookSel, setBookSel)} />
        </div>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>{t("recs.bank.matches")}</CardTitle>
          </CardHeader>
          {r.matches.length === 0 ? (
            <EmptyState icon={GitCompareArrows} title={t("recs.bank.noMatches")} />
          ) : (
            <Table>
              <THead>
                <tr>
                  <TH>{t("recs.bank.method")}</TH>
                  <TH>{t("recs.bank.rows")}</TH>
                  <TH className="text-end">{t("recs.bank.bankTotal")}</TH>
                  <TH className="text-end">{t("recs.bank.bookTotal")}</TH>
                  <TH className="text-end">{t("recs.difference")}</TH>
                  <TH>{t("assurance.reason")}</TH>
                  {editable && <TH><span className="sr-only">{t("common.actions")}</span></TH>}
                </tr>
              </THead>
              <TBody>
                {r.matches.map((m) => (
                  <TR key={m.id}>
                    <TD className="align-top">
                      <Badge tone={m.method === "manual" ? "teal" : "neutral"}>{t(`reconMethod.${m.method}`)}</Badge>
                    </TD>
                    <TD className="align-top text-xs text-slate-600" dir="ltr">
                      {t("recs.bank.side_bank")}: {m.bank_row_ids.join(", ")} · {t("recs.bank.side_book")}: {m.book_row_ids.join(", ")}
                    </TD>
                    <TD className="align-top text-end">
                      <Amount value={m.bank_total} />
                    </TD>
                    <TD className="align-top text-end">
                      <Amount value={m.book_total} />
                    </TD>
                    <TD className="align-top text-end">
                      <Amount value={m.difference} />
                    </TD>
                    <TD className="align-top text-xs text-slate-600">
                      {m.reason || "—"}
                      {m.created_by_name && <div className="text-slate-400">{m.created_by_name}</div>}
                    </TD>
                    {editable && (
                      <TD className="align-top text-end">
                        <Button size="sm" variant="ghost" onClick={() => setUnmatchId(m.id)}>
                          <Link2Off aria-hidden />
                          {t("recs.bank.unmatch")}
                        </Button>
                      </TD>
                    )}
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>

        <SignOffCard base="/bank-reconciliations" listKey={bankRecsKey} obj={r} blocker={blocker} />
      </div>
      <MatchDialog
        rec={r}
        bank={[...bankSel]}
        book={[...bookSel]}
        open={matchOpen}
        onOpenChange={setMatchOpen}
        onDone={() => {
          setMatchOpen(false);
          setBankSel(new Set());
          setBookSel(new Set());
        }}
      />
      <ReasonDialog
        open={!!unmatchId}
        onOpenChange={(o) => {
          if (!o) {
            setUnmatchId(null);
            unmatch.reset();
          }
        }}
        title={t("recs.bank.unmatchTitle")}
        description={t("recs.bank.unmatchHint")}
        confirmLabel={t("recs.bank.unmatch")}
        busy={unmatch.isPending}
        error={unmatch.error}
        onConfirm={(reason) => unmatchId && unmatch.mutate({ id: unmatchId, reason })}
      />
    </>
  );
}

// ---------------------------------------------------------------- account reconciliation

const supportSchema = z.object({
  items: z.array(
    z.object({
      description: z.string().trim().min(1).max(500),
      amount: z.string().trim().regex(SIGNED_AMOUNT_PATTERN),
      note: z.string().max(2000),
      document_id: z.string().nullable(),
    }),
  ),
  explanation: z.string().max(5000),
  owner_id: z.string(),
});
type SupportValues = z.infer<typeof supportSchema>;

function toValues(r: AccountRec): SupportValues {
  return {
    items: r.items.map((i) => ({ description: i.description, amount: i.amount, note: i.note, document_id: i.document_id })),
    explanation: r.explanation,
    owner_id: r.owner_id ?? "",
  };
}

function SupportEditor({ r, editable }: { r: AccountRec; editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<SupportValues>({ resolver: zodResolver(supportSchema), defaultValues: toValues(r) });
  const items = useFieldArray({ control: form.control, name: "items" });
  useEffect(() => form.reset(toValues(r)), [r, form]);
  const save = useMutation({
    mutationFn: (v: SupportValues) => api<AccountRec>(`/account-reconciliations/${r.id}`, { method: "PUT", json: { ...v, owner_id: v.owner_id || null } }),
    onSuccess: (d) => {
      qc.setQueryData(detailKey(accountRecsKey, r.id), d);
      void qc.invalidateQueries({ queryKey: [...accountRecsKey, "list"] });
      toast.success(t("common.saved"));
    },
  });
  const err = form.formState.errors;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("recs.account.support")}</CardTitle>
        <CardDescription>{t("recs.account.supportHint")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
          {items.fields.length === 0 && <p className="text-[13px] text-slate-500">{t("recs.account.noSupport")}</p>}
          {items.fields.map((f, i) => (
            <div key={f.id} className="grid items-end gap-3 rounded-lg border border-slate-200 p-3 sm:grid-cols-[2fr_1fr_2fr_auto]">
              <Field id={`si-desc-${i}`} label={t("recs.account.itemDescription")} error={err.items?.[i]?.description ? t("recs.nameRequired") : undefined}>
                <Input id={`si-desc-${i}`} disabled={!editable} {...form.register(`items.${i}.description`)} />
              </Field>
              <Field id={`si-amount-${i}`} label={t("recs.bank.amount")} error={err.items?.[i]?.amount ? t("recs.amountInvalid") : undefined}>
                <Input id={`si-amount-${i}`} dir="ltr" inputMode="decimal" disabled={!editable} {...form.register(`items.${i}.amount`)} />
              </Field>
              <Field id={`si-note-${i}`} label={t("recs.account.itemNote")}>
                <Input id={`si-note-${i}`} disabled={!editable} {...form.register(`items.${i}.note`)} />
              </Field>
              {editable && (
                <Button type="button" variant="ghost" size="icon" aria-label={t("recs.account.removeItem")} onClick={() => items.remove(i)}>
                  <Trash2 aria-hidden />
                </Button>
              )}
              {r.items[i]?.document_title && <p className="text-xs text-slate-500 sm:col-span-4">{t("recs.account.document", { title: r.items[i]!.document_title })}</p>}
            </div>
          ))}
          {editable && (
            <Button type="button" variant="outline" size="sm" onClick={() => items.append({ description: "", amount: "", note: "", document_id: null })}>
              <Plus aria-hidden /> {t("recs.account.addItem")}
            </Button>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="ar-explanation" label={t("recs.explanation")} hint={r.check.explanation_required ? t("recs.explanationRequired") : undefined}>
              <Textarea id="ar-explanation" rows={3} disabled={!editable} {...form.register("explanation")} />
            </Field>
            {editable ? <MemberSelect id="ar-owner-edit" label={t("recs.owner")} reg={form.register("owner_id")} /> : null}
          </div>
          <MutationError error={save.error} />
          {editable && (
            <Button type="submit" disabled={save.isPending || !form.formState.isDirty}>
              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("common.save")}
            </Button>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

export function AccountRecDetailPage() {
  const { recId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const q = useAccountRec(recId);
  if (q.isLoading) return <LoadingState />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const r = q.data;
  const title = `${r.account_code} ${r.account_name}`;
  const blocker = r.check.explanation_required && !r.explanation.trim() ? t("recs.explanationBlocks") : null;
  return (
    <>
      <PageHeader
        title={title}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {r.entity_name} · {formatDate(r.as_of, i18n.language)} · {t("recs.owner")}: {r.owner_name ?? "—"}
            {r.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={crumbs(t, "account", title)}
        actions={<AssuranceStatusBadge status={r.sign_off.status} />}
      />
      <div className="space-y-5">
        <UnverifiedWarnings warnings={r.warnings} />
        <Card>
          <CardHeader>
            <CardTitle>{t("recs.account.varianceTitle")}</CardTitle>
            <CardDescription>{t("recs.account.varianceHint", { rows: r.tb_row_ids.join(", ") || "—" })}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Facts
              items={[
                { label: t("recs.account.tbBalance"), value: <Amount value={r.tb_balance} currency={r.currency} /> },
                { label: t("recs.account.supported"), value: <Amount value={r.supported} currency={r.currency} /> },
                {
                  label: t("recs.account.variance"),
                  value: (
                    <span className="flex items-center gap-2">
                      <Amount value={r.check.variance} />
                      {r.check.exceeds ? <Badge tone="amber">{t("recs.overThreshold")}</Badge> : <Badge tone="neutral">{t("recs.withinThreshold")}</Badge>}
                    </span>
                  ),
                },
                {
                  label: t("recs.account.thresholds"),
                  value: (
                    <span dir="ltr" className="font-mono text-[13px]">
                      {r.check.threshold_abs} · {r.check.threshold_pct}
                    </span>
                  ),
                },
              ]}
            />
            <CalcSteps steps={asCalcSteps(r.check.steps)} />
          </CardContent>
        </Card>
        <SupportEditor r={r} editable={can("write") && r.sign_off.status !== "signed_off"} />
        <SignOffCard base="/account-reconciliations" listKey={accountRecsKey} obj={r} blocker={blocker} />
      </div>
    </>
  );
}

// ---------------------------------------------------------------- intercompany

function IcExplanation({ r, editable }: { r: Intercompany; editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [text, setText] = useState(r.explanation);
  const save = useMutation({
    mutationFn: () => api<Intercompany>(`/intercompany-reconciliations/${r.id}/explanation`, { method: "PUT", json: { explanation: text } }),
    onSuccess: (d) => {
      qc.setQueryData(detailKey(icRecsKey, r.id), d);
      toast.success(t("common.saved"));
    },
  });
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Field id="ic-explanation" label={t("recs.explanation")} hint={r.exceeds ? t("recs.explanationRequired") : undefined}>
        <Textarea id="ic-explanation" rows={3} disabled={!editable} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <MutationError error={save.error} />
      {editable && (
        <Button type="submit" disabled={save.isPending || text === r.explanation}>
          {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {t("common.save")}
        </Button>
      )}
    </form>
  );
}

export function IntercompanyDetailPage() {
  const { recId } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const q = useIcRec(recId);
  if (q.isLoading) return <LoadingState />;
  if (q.isError || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const r = q.data;
  const blocker = r.exceeds && !r.explanation.trim() ? t("recs.explanationBlocks") : null;
  return (
    <>
      <PageHeader
        title={r.name}
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            {formatDate(r.as_of, i18n.language)}
            {r.is_demo && <SyntheticBadge />}
          </span>
        }
        crumbs={crumbs(t, "intercompany", r.name)}
        actions={<AssuranceStatusBadge status={r.sign_off.status} />}
      />
      <div className="space-y-5">
        <UnverifiedWarnings warnings={r.warnings} />
        <Card className="overflow-hidden">
          <Table>
            <THead>
              <tr>
                <TH>{t("recs.ic.side")}</TH>
                <TH>{t("datasets.entity")}</TH>
                <TH>{t("recs.ic.accounts")}</TH>
                <TH className="text-end">{t("recs.ic.balance")}</TH>
              </tr>
            </THead>
            <TBody>
              {(["a", "b"] as const).map((k) => {
                const side = k === "a" ? r.side_a : r.side_b;
                return (
                  <TR key={k}>
                    <TD className="text-[13px]">{t(`recs.ic.side_${k}`)}</TD>
                    <TD className="text-[13px]">{side.entity_name}</TD>
                    <TD className="text-[13px]" dir="ltr">
                      {side.accounts.join(", ")}
                    </TD>
                    <TD className="text-end">
                      <Amount value={side.balance} currency={r.currency} />
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </Card>
        <Card>
          <CardContent className="space-y-4">
            <Facts
              items={[
                {
                  label: t("recs.difference"),
                  value: (
                    <span className="flex items-center gap-2">
                      <Amount value={r.difference} currency={r.currency} />
                      {r.exceeds ? <Badge tone="amber">{t("recs.overThreshold")}</Badge> : <Badge tone="neutral">{t("recs.withinThreshold")}</Badge>}
                    </span>
                  ),
                },
                { label: t("recs.ic.threshold"), value: <Amount value={r.threshold} /> },
              ]}
            />
            <CalcSteps steps={asCalcSteps(r.steps)} />
            <IcExplanation key={r.explanation} r={r} editable={can("write") && r.sign_off.status !== "signed_off"} />
          </CardContent>
        </Card>
        <SignOffCard base="/intercompany-reconciliations" listKey={icRecsKey} obj={r} blocker={blocker} />
      </div>
    </>
  );
}
