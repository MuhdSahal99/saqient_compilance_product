import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { BadgeCheck, ExternalLink, FilePlus2, Info, Loader2, Pencil, Plus, Scale, Send, ShieldOff, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Rule, RulePack, RulePackVersionDetail, RuleValueType } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  errorMessage,
  LoadingState,
  PageHeader,
  SyntheticBadge,
  UnverifiedBadge,
  useUnsavedChangesWarning,
} from "@/components/common";

const VALUE_TYPES: RuleValueType[] = ["decimal", "integer", "string", "boolean", "date"];

function VersionStateBadge({ state }: { state: "draft" | "published" | "archived" }) {
  const { t } = useTranslation();
  return (
    <Badge tone={state === "published" ? "green" : state === "draft" ? "amber" : "neutral"} dot>
      {t(`checklistState.${state}`)}
    </Badge>
  );
}

const packSchema = z.object({
  name: z.string().trim().min(1).max(200),
  jurisdiction: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^[A-Z]{2}(-[A-Z0-9]{1,10})?$|^SYNTHETIC$/),
  description: z.string().max(4000),
});
type PackValues = z.input<typeof packSchema>;
type PackParsed = z.output<typeof packSchema>;

function NewPackDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const form = useForm<PackValues, unknown, PackParsed>({ resolver: zodResolver(packSchema), defaultValues: { name: "", jurisdiction: "AE", description: "" } });
  const create = useMutation({
    mutationFn: (v: PackParsed) => api<RulePack>("/rule-packs", { json: v }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ["rule-packs"] });
      toast.success(t("rulePacks.created"));
      onOpenChange(false);
      form.reset();
      const v = p.versions[0];
      if (v) navigate(`/rule-packs/versions/${v.id}`);
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{t("rulePacks.new")}</DialogTitle>
        <DialogDescription>{t("rulePacks.newHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="rp-name">{t("rulePacks.name")}</Label>
            <Input id="rp-name" aria-invalid={!!err.name} {...form.register("name")} />
            <FieldError message={err.name ? t("rulePacks.nameRequired") : undefined} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rp-jur">{t("rulePacks.jurisdiction")}</Label>
            <Input id="rp-jur" dir="ltr" aria-invalid={!!err.jurisdiction} aria-describedby="rp-jur-hint" {...form.register("jurisdiction")} />
            <p id="rp-jur-hint" className="text-xs text-slate-500">
              {t("rulePacks.jurisdictionHint")}
            </p>
            <FieldError message={err.jurisdiction ? t("rulePacks.jurisdictionRule") : undefined} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rp-desc">{t("documents.description")}</Label>
            <Textarea id="rp-desc" rows={2} {...form.register("description")} />
          </div>
          {create.isError && (
            <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {errorMessage(create.error, t("common.genericError"))}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("rulePacks.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function RulePacksPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const packs = useQuery({ queryKey: ["rule-packs"], queryFn: () => api<RulePack[]>("/rule-packs") });
  return (
    <>
      <PageHeader
        title={t("rulePacks.title")}
        description={t("rulePacks.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.rulePacks") }]}
        actions={
          can("decide") && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <Plus aria-hidden /> {t("rulePacks.new")}
            </Button>
          )
        }
      />
      <p className="mb-5 flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-[13px] leading-relaxed text-slate-600">
        <Info className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden />
        {t("rulePacks.verificationNote")}
      </p>
      <Card className="overflow-hidden">
        {packs.isLoading && <LoadingState />}
        {packs.isError && <ErrorState error={packs.error} onRetry={() => void packs.refetch()} />}
        {packs.data?.length === 0 && <EmptyState icon={Scale} title={t("rulePacks.empty")} description={t("rulePacks.emptyHint")} />}
        {packs.data && packs.data.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {packs.data.map((p) => (
              <li key={p.id} className="px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-navy-900">{p.name}</span>
                  <Badge tone="neutral">{p.jurisdiction}</Badge>
                  {p.is_synthetic && <SyntheticBadge />}
                </div>
                {p.description && <p className="mt-1 max-w-3xl text-[13px] text-slate-500">{p.description}</p>}
                <ul className="mt-3 flex flex-wrap gap-2">
                  {[...p.versions]
                    .sort((a, b) => b.version_number - a.version_number)
                    .map((v) => (
                      <li key={v.id}>
                        <Link
                          to={`/rule-packs/versions/${v.id}`}
                          className="flex items-center gap-2 rounded-lg bg-white px-3 py-1.5 text-[13px] ring-1 ring-slate-200 transition-colors hover:ring-slate-300"
                        >
                          <span className="font-medium tabular-nums text-navy-900">v{v.version_number}</span>
                          <VersionStateBadge state={v.state} />
                          <span className="text-xs text-slate-500">{t("rulePacks.ruleCount", { count: v.rule_count })}</span>
                          {v.unverified_count > 0 && <UnverifiedBadge count={v.unverified_count} />}
                          {v.published_at && <span className="text-xs text-slate-400">{formatDate(v.published_at, i18n.language)}</span>}
                        </Link>
                      </li>
                    ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <NewPackDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

// ---------------------------------------------------------------- version detail + rules editor

type RuleDraft = Omit<Rule, "id" | "verification_status" | "verified_by_name" | "verified_at"> & {
  id?: string;
  verification_status?: Rule["verification_status"];
};

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

function toDraft(r: Rule): RuleDraft {
  return { ...r };
}

function toPayload(r: RuleDraft) {
  return {
    rule_key: r.rule_key,
    title: r.title,
    value_type: r.value_type,
    value: r.value,
    unit: r.unit,
    effective_from: r.effective_from,
    effective_to: r.effective_to || null,
    source_url: r.source_url || null,
    source_note: r.source_note,
    todo: r.todo,
  };
}

const ruleSchema = z
  .object({
    rule_key: z
      .string()
      .trim()
      .min(1)
      .max(120)
      .regex(/^[a-z0-9]+(?:[._][a-z0-9]+)*$/),
    title: z.string().trim().min(1).max(300),
    value_type: z.enum(["decimal", "integer", "string", "boolean", "date"]),
    value: z.string().trim().min(1).max(200),
    unit: z.string().max(40),
    effective_from: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    effective_to: z.union([z.literal(""), z.string().regex(/^\d{4}-\d{2}-\d{2}$/)]),
    source_url: z.union([z.literal(""), z.string().max(500).startsWith("https://")]),
    source_note: z.string().max(4000),
    todo: z.string().max(4000),
  })
  .refine((v) => !v.effective_to || v.effective_to >= v.effective_from, { path: ["effective_to"], message: "order" });
type RuleValues = z.infer<typeof ruleSchema>;

function RuleDialog({
  open,
  onOpenChange,
  rule,
  onSave,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  rule?: RuleDraft;
  onSave: (r: RuleValues) => void;
}) {
  const { t } = useTranslation();
  const empty: RuleValues = {
    rule_key: "",
    title: "",
    value_type: "decimal",
    value: "",
    unit: "",
    effective_from: "",
    effective_to: "",
    source_url: "",
    source_note: "",
    todo: "",
  };
  const form = useForm<RuleValues>({ resolver: zodResolver(ruleSchema), defaultValues: empty });
  useEffect(() => {
    if (open)
      form.reset(
        rule
          ? { ...empty, ...rule, effective_to: rule.effective_to ?? "", source_url: rule.source_url ?? "" }
          : empty,
      );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the dialog opens
  }, [open, rule]);
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogTitle>{rule ? t("rulePacks.editRule") : t("rulePacks.addRule")}</DialogTitle>
        <DialogDescription>{t("rulePacks.ruleFormHint")}</DialogDescription>
        <form
          className="mt-5 space-y-4"
          onSubmit={form.handleSubmit((v) => {
            onSave(v);
            onOpenChange(false);
          })}
          noValidate
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="rule-key">{t("rulePacks.ruleKey")}</Label>
              <Input id="rule-key" dir="ltr" className="font-mono" aria-invalid={!!err.rule_key} {...form.register("rule_key")} />
              <FieldError message={err.rule_key ? t("rulePacks.ruleKeyRule") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule-title">{t("rulePacks.ruleTitle")}</Label>
              <Input id="rule-title" aria-invalid={!!err.title} {...form.register("title")} />
              <FieldError message={err.title ? t("rulePacks.ruleTitleRequired") : undefined} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="rule-type">{t("rulePacks.valueType")}</Label>
              <Select id="rule-type" {...form.register("value_type")}>
                {VALUE_TYPES.map((v) => (
                  <option key={v} value={v}>
                    {t(`rulePacks.type.${v}`)}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule-value">{t("rulePacks.value")}</Label>
              <Input id="rule-value" dir="ltr" aria-invalid={!!err.value} {...form.register("value")} />
              <FieldError message={err.value ? t("rulePacks.valueRequired") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule-unit">{t("rulePacks.unit")}</Label>
              <Input id="rule-unit" dir="ltr" {...form.register("unit")} />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="rule-from">{t("rulePacks.effectiveFrom")}</Label>
              <Input id="rule-from" type="date" aria-invalid={!!err.effective_from} {...form.register("effective_from")} />
              <FieldError message={err.effective_from ? t("rulePacks.dateRequired") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rule-to">{t("rulePacks.effectiveTo")}</Label>
              <Input id="rule-to" type="date" aria-invalid={!!err.effective_to} {...form.register("effective_to")} />
              <FieldError message={err.effective_to ? t("rulePacks.dateOrder") : undefined} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-url">{t("rulePacks.sourceUrl")}</Label>
            <Input id="rule-url" dir="ltr" type="url" placeholder="https://" aria-invalid={!!err.source_url} {...form.register("source_url")} />
            <FieldError message={err.source_url ? t("rulePacks.sourceUrlRule") : undefined} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-note">{t("rulePacks.sourceNote")}</Label>
            <Textarea id="rule-note" rows={2} {...form.register("source_note")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-todo">{t("rulePacks.todo")}</Label>
            <Textarea id="rule-todo" rows={2} aria-describedby="rule-todo-hint" {...form.register("todo")} />
            <p id="rule-todo-hint" className="text-xs text-slate-500">
              {t("rulePacks.todoHint")}
            </p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent">
              {t("rulePacks.applyRule")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function RulePackVersionPage() {
  const { versionId = "" } = useParams();
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const version = useQuery({
    queryKey: ["rule-pack-version", versionId],
    queryFn: () => api<RulePackVersionDetail>(`/rule-pack-versions/${versionId}`),
  });
  const v = version.data;
  const [drafts, setDrafts] = useState<RuleDraft[] | null>(null);
  const [editIndex, setEditIndex] = useState<number | "new" | null>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const editable = !!v && v.state === "draft" && can("decide");
  const dirty = drafts !== null;
  useUnsavedChangesWarning(dirty);
  const rules: RuleDraft[] = drafts ?? (v?.rules.map(toDraft) ?? []);

  const refresh = (detail: RulePackVersionDetail) => {
    qc.setQueryData(["rule-pack-version", versionId], detail);
    void qc.invalidateQueries({ queryKey: ["rule-packs"] });
  };
  const save = useMutation({
    mutationFn: (list: RuleDraft[]) =>
      api<RulePackVersionDetail>(`/rule-pack-versions/${versionId}/rules`, { method: "PUT", json: { rules: list.map(toPayload) } }),
    onSuccess: (d) => {
      refresh(d);
      setDrafts(null);
      toast.success(t("rulePacks.rulesSaved"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const publish = useMutation({
    mutationFn: () => api<RulePackVersionDetail>(`/rule-pack-versions/${versionId}/publish`, { method: "POST" }),
    onSuccess: (d) => {
      refresh(d);
      setConfirmPublish(false);
      toast.success(t("rulePacks.published"));
    },
    onError: (e) => {
      setConfirmPublish(false);
      toast.error(errorMessage(e, t("common.genericError")));
    },
  });
  const newDraft = useMutation({
    mutationFn: () => api<RulePackVersionDetail>(`/rule-packs/${v?.rule_pack_id}/drafts`, { method: "POST" }),
    onSuccess: (d) => {
      void qc.invalidateQueries({ queryKey: ["rule-packs"] });
      navigate(`/rule-packs/versions/${d.id}`);
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const verify = useMutation({
    mutationFn: ({ rule, on }: { rule: Rule; on: boolean }) => api<Rule>(`/rules/${rule.id}/${on ? "verify" : "unverify"}`, { method: "POST" }),
    onSuccess: (_, { on }) => {
      void qc.invalidateQueries({ queryKey: ["rule-pack-version", versionId] });
      void qc.invalidateQueries({ queryKey: ["rule-packs"] });
      toast.success(t(on ? "rulePacks.verified" : "rulePacks.unverifiedDone"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });

  if (version.isLoading) return <LoadingState />;
  if (version.isError || !v) return <ErrorState error={version.error} onRetry={() => void version.refetch()} />;
  const unverified = v.rules.filter((r) => r.verification_status !== "verified").length;

  return (
    <>
      <PageHeader
        title={`${v.pack_name} · v${v.version_number}`}
        crumbs={[{ label: t("nav.rulePacks"), to: "/rule-packs" }, { label: `${v.pack_name} v${v.version_number}` }]}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <VersionStateBadge state={v.state} />
            <Badge tone="neutral">{v.jurisdiction}</Badge>
            {v.is_synthetic && <SyntheticBadge />}
            {unverified > 0 && <UnverifiedBadge count={unverified} />}
          </span>
        }
        actions={
          <>
            {editable && dirty && (
              <>
                <Button variant="outline" onClick={() => setDrafts(null)} disabled={save.isPending}>
                  {t("rulePacks.discard")}
                </Button>
                <Button variant="accent" onClick={() => save.mutate(rules)} disabled={save.isPending}>
                  {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
                  {t("rulePacks.saveRules")}
                </Button>
              </>
            )}
            {editable && !dirty && (
              <Button variant="accent" onClick={() => setConfirmPublish(true)} disabled={v.rules.length === 0}>
                <Send aria-hidden /> {t("rulePacks.publish")}
              </Button>
            )}
            {v.state !== "draft" && can("decide") && (
              <Button variant="outline" onClick={() => newDraft.mutate()} disabled={newDraft.isPending}>
                <FilePlus2 aria-hidden /> {t("rulePacks.newDraft")}
              </Button>
            )}
          </>
        }
      />
      {unverified > 0 && (
        <p className="mb-5 flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-[13px] leading-relaxed text-orange-900">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {t("rulePacks.unverifiedBanner")}
        </p>
      )}
      <Card className="overflow-hidden">
        {editable && (
          <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5">
            <p className="text-xs text-slate-500">{t("rulePacks.draftHint")}</p>
            <Button size="sm" variant="outline" onClick={() => setEditIndex("new")}>
              <Plus aria-hidden /> {t("rulePacks.addRule")}
            </Button>
          </div>
        )}
        {rules.length === 0 ? (
          <EmptyState icon={Scale} title={t("rulePacks.noRules")} description={editable ? t("rulePacks.noRulesHint") : undefined} />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>{t("rulePacks.rule")}</TH>
                <TH>{t("rulePacks.value")}</TH>
                <TH>{t("rulePacks.effective")}</TH>
                <TH>{t("rulePacks.source")}</TH>
                <TH>{t("rulePacks.status")}</TH>
                {(editable || can("admin")) && <TH className="text-end">{t("common.actions")}</TH>}
              </tr>
            </THead>
            <TBody>
              {rules.map((r, i) => {
                const saved = !dirty ? v.rules[i] : undefined;
                return (
                  <TR key={r.id ?? `new-${i}`}>
                    <TD className="align-top">
                      <code className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600">{r.rule_key}</code>
                      <div className="mt-1 font-medium text-navy-900">{r.title}</div>
                      {r.todo && (
                        <p className="mt-1 flex items-start gap-1 text-xs text-amber-800">
                          <TriangleAlert className="mt-px size-3 shrink-0" aria-hidden />
                          {t("rulePacks.todoLabel")}: {r.todo}
                        </p>
                      )}
                    </TD>
                    <TD className="whitespace-nowrap align-top font-mono text-[13px] text-slate-800" dir="ltr">
                      {r.value} {r.unit}
                      <div className="font-sans text-[11px] text-slate-400">{t(`rulePacks.type.${r.value_type}`)}</div>
                    </TD>
                    <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                      {formatDate(r.effective_from, i18n.language)} – {r.effective_to ? formatDate(r.effective_to, i18n.language) : t("rulePacks.openEnded")}
                    </TD>
                    <TD className="max-w-60 align-top text-xs text-slate-600">
                      {r.source_url ? (
                        <a href={r.source_url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 break-all text-teal-700 hover:underline" dir="ltr">
                          {hostOf(r.source_url)}
                          <ExternalLink className="size-3 shrink-0" aria-hidden />
                        </a>
                      ) : (
                        <span className="text-slate-400">{t("rulePacks.noSource")}</span>
                      )}
                      {r.source_note && <p className="mt-0.5 line-clamp-2">{r.source_note}</p>}
                    </TD>
                    <TD className="align-top">
                      {r.verification_status === "verified" ? (
                        <div>
                          <Badge tone="green">
                            <BadgeCheck className="size-3" aria-hidden />
                            {t("rulePacks.verifiedBadge")}
                          </Badge>
                          {saved?.verified_by_name && (
                            <p className="mt-1 text-[11px] text-slate-500">
                              {saved.verified_by_name} · {formatDate(saved.verified_at, i18n.language)}
                            </p>
                          )}
                        </div>
                      ) : (
                        <UnverifiedBadge />
                      )}
                    </TD>
                    {(editable || can("admin")) && (
                      <TD className="text-end align-top">
                        <div className="flex justify-end gap-1">
                          {editable && (
                            <>
                              <Button size="icon-sm" variant="ghost" onClick={() => setEditIndex(i)} aria-label={t("rulePacks.editNamed", { key: r.rule_key })}>
                                <Pencil aria-hidden />
                              </Button>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                onClick={() => setDrafts(rules.filter((_, j) => j !== i))}
                                aria-label={t("rulePacks.removeNamed", { key: r.rule_key })}
                              >
                                <Trash2 aria-hidden />
                              </Button>
                            </>
                          )}
                          {can("admin") && saved && !v.is_synthetic && (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={verify.isPending}
                              onClick={() => verify.mutate({ rule: saved, on: saved.verification_status !== "verified" })}
                            >
                              {saved.verification_status === "verified" ? <ShieldOff aria-hidden /> : <BadgeCheck aria-hidden />}
                              {saved.verification_status === "verified" ? t("rulePacks.unverify") : t("rulePacks.verify")}
                            </Button>
                          )}
                        </div>
                      </TD>
                    )}
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
      <RuleDialog
        open={editIndex !== null}
        onOpenChange={(o) => !o && setEditIndex(null)}
        rule={typeof editIndex === "number" ? rules[editIndex] : undefined}
        onSave={(values) => {
          const next: RuleDraft = {
            ...values,
            effective_to: values.effective_to || null,
            source_url: values.source_url || null,
          };
          setDrafts(editIndex === "new" || editIndex === null ? [...rules, next] : rules.map((r, j) => (j === editIndex ? { ...r, ...next } : r)));
        }}
      />
      <ConfirmDialog
        open={confirmPublish}
        onOpenChange={setConfirmPublish}
        title={t("rulePacks.publishTitle")}
        description={unverified > 0 ? t("rulePacks.publishUnverified", { count: unverified }) : t("rulePacks.publishDescription")}
        confirmLabel={t("rulePacks.publish")}
        busy={publish.isPending}
        onConfirm={() => publish.mutate()}
      />
    </>
  );
}
