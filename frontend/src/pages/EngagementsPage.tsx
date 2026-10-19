import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { BriefcaseBusiness, Loader2, Plus, TriangleAlert } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEntities } from "@/lib/queries";
import { ENGAGEMENT_KINDS, ENGAGEMENT_STATUSES, engagementsKey, useEngagements, type Engagement } from "@/lib/audit";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState, ErrorState, LoadingState, PageHeader, SyntheticBadge } from "@/components/common";
import { EngagementStatusBadge, Field, MutationError } from "@/components/audit/shared";

const newSchema = z
  .object({
    entity_id: z.string().min(1),
    kind: z.enum(ENGAGEMENT_KINDS),
    name: z.string().trim().min(1).max(300),
    period_start: z.string().min(1),
    period_end: z.string().min(1),
  })
  .refine((v) => !v.period_start || !v.period_end || v.period_end >= v.period_start, { path: ["period_end"], message: "order" });
type NewValues = z.infer<typeof newSchema>;

function NewEngagementDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const entities = useEntities(open);
  const form = useForm<NewValues>({
    resolver: zodResolver(newSchema),
    defaultValues: { entity_id: "", kind: "external_audit", name: "", period_start: "", period_end: "" },
  });
  const create = useMutation({
    mutationFn: (v: NewValues) => api<Engagement>("/engagements", { json: v }),
    onSuccess: (e) => {
      void qc.invalidateQueries({ queryKey: engagementsKey });
      close();
      navigate(`/engagements/${e.id}`);
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
        <DialogTitle>{t("engagements.new")}</DialogTitle>
        <DialogDescription>{t("engagements.newHint")}</DialogDescription>
        {entities.isLoading && <LoadingState rows={3} />}
        {entities.isError && <ErrorState error={entities.error} onRetry={() => void entities.refetch()} />}
        {entities.data && entities.data.length === 0 && (
          <EmptyState title={t("engagements.noEntities")} description={t("engagements.noEntitiesHint")} />
        )}
        {entities.data && entities.data.length > 0 && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="eng-entity" label={t("datasets.entity")} error={err.entity_id ? t("datasets.entityRequired") : undefined}>
                <Select id="eng-entity" aria-invalid={!!err.entity_id} {...form.register("entity_id")}>
                  <option value="">{t("datasets.chooseEntity")}</option>
                  {entities.data.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="eng-kind" label={t("engagements.kind")}>
                <Select id="eng-kind" {...form.register("kind")}>
                  {ENGAGEMENT_KINDS.map((k) => (
                    <option key={k} value={k}>
                      {t(`engagementKind.${k}`)}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field id="eng-name" label={t("engagements.name")} error={err.name ? t("engagements.nameRequired") : undefined}>
              <Input id="eng-name" aria-invalid={!!err.name} {...form.register("name")} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="eng-start" label={t("workpapers.periodStart")} error={err.period_start ? t("rulePacks.dateRequired") : undefined}>
                <Input id="eng-start" type="date" aria-invalid={!!err.period_start} {...form.register("period_start")} />
              </Field>
              <Field
                id="eng-end"
                label={t("workpapers.periodEnd")}
                error={err.period_end ? (err.period_end.message === "order" ? t("rulePacks.dateOrder") : t("rulePacks.dateRequired")) : undefined}
              >
                <Input id="eng-end" type="date" aria-invalid={!!err.period_end} {...form.register("period_end")} />
              </Field>
            </div>
            <MutationError error={create.error} />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={close}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" variant="accent" disabled={create.isPending}>
                {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {t("engagements.create")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function EngagementsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(false);
  const status = params.get("status") ?? "";
  const list = useEngagements({ status });
  return (
    <>
      <PageHeader
        title={t("engagements.title")}
        description={t("engagements.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.engagements") }]}
        actions={
          can("decide") && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <Plus aria-hidden /> {t("engagements.new")}
            </Button>
          )
        }
      />
      <div className="space-y-4">
        <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
          {t("engagements.disclaimer")}
        </p>
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-end gap-3 border-b border-slate-100 p-3">
            <div className="space-y-1">
              <Label htmlFor="eng-filter-status">{t("engagements.status")}</Label>
              <Select
                id="eng-filter-status"
                className="w-56"
                value={status}
                onChange={(e) => {
                  const sp = new URLSearchParams(params);
                  if (e.target.value) sp.set("status", e.target.value);
                  else sp.delete("status");
                  setParams(sp, { replace: true });
                }}
              >
                <option value="">{t("reviews.allStatuses")}</option>
                {ENGAGEMENT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`engagementStatus.${s}`)}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          {list.isLoading && <LoadingState />}
          {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
          {list.data?.length === 0 && (
            <EmptyState
              icon={BriefcaseBusiness}
              title={t("engagements.empty")}
              description={can("decide") ? t("engagements.emptyHintDecider") : t("engagements.emptyHint")}
            />
          )}
          {list.data && list.data.length > 0 && (
            <Table>
              <THead>
                <tr>
                  <TH>{t("engagements.name")}</TH>
                  <TH>{t("engagements.kind")}</TH>
                  <TH>{t("workpapers.period")}</TH>
                  <TH>{t("engagements.status")}</TH>
                  <TH>{t("workpapers.currency")}</TH>
                </tr>
              </THead>
              <TBody>
                {list.data.map((e) => (
                  <TR key={e.id}>
                    <TD className="align-top">
                      <Link to={`/engagements/${e.id}`} className="font-medium text-navy-900 hover:text-teal-700 hover:underline">
                        {e.name}
                      </Link>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        <span>{e.entity_name}</span>
                        {e.is_demo && <SyntheticBadge />}
                      </div>
                    </TD>
                    <TD className="align-top">
                      <Badge tone="neutral">{t(`engagementKind.${e.kind}`)}</Badge>
                    </TD>
                    <TD className="whitespace-nowrap align-top text-[13px] text-slate-600">
                      {formatDate(e.period_start, i18n.language)} – {formatDate(e.period_end, i18n.language)}
                    </TD>
                    <TD className="align-top">
                      <EngagementStatusBadge status={e.status} />
                    </TD>
                    <TD className="align-top text-[13px] text-slate-600">{e.currency}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>
      <NewEngagementDialog open={open} onOpenChange={setOpen} />
    </>
  );
}
