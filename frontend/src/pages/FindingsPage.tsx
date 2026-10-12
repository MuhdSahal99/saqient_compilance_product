import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CalendarClock, ListChecks, Loader2, Search, UserPlus, X } from "lucide-react";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import type { Finding, FindingStatus, Member, Page, Severity } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { cn, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { IconInput, Input, Label, Select } from "@/components/ui/input";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import {
  EmptyState,
  ErrorState,
  errorMessage,
  FindingStatusBadge,
  LoadingState,
  PageHeader,
  Pagination,
  SeverityBadge,
  useDebounced,
} from "@/components/common";

const STATUSES: FindingStatus[] = [
  "proposed",
  "in_review",
  "confirmed",
  "dismissed",
  "remediation_in_progress",
  "ready_for_rereview",
  "resolved",
  "accepted_risk",
];
const ASSIGNABLE = new Set<FindingStatus>(["confirmed", "remediation_in_progress", "ready_for_rereview", "resolved", "accepted_risk"]);

function BulkAssignDialog({ ids, open, onOpenChange, onDone }: { ids: string[]; open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members"), enabled: open });
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const assign = useMutation({
    mutationFn: () => api<Finding[]>("/findings/bulk-assign", { json: { finding_ids: ids, owner_id: owner, due_date: due || null } }),
    onSuccess: () => {
      toast.success(t("findings.bulkAssigned", { count: ids.length }));
      void qc.invalidateQueries({ queryKey: ["findings"] });
      onDone();
      onOpenChange(false);
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-teal-50 ring-1 ring-teal-200/70">
            <UserPlus className="size-5 text-teal-700" aria-hidden />
          </span>
          <div className="min-w-0">
            <DialogTitle>{t("findings.bulkAssign")}</DialogTitle>
            <DialogDescription>{t("findings.bulkAssignHint", { count: ids.length })}</DialogDescription>
          </div>
        </div>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="bulk-owner">{t("findings.owner")}</Label>
            <Select id="bulk-owner" value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">{t("findings.chooseOwner")}</option>
              {members.data?.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.full_name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="bulk-due">{t("findings.dueDate")}</Label>
            <Input id="bulk-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="accent" disabled={!owner || assign.isPending} onClick={() => assign.mutate()}>
            {assign.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {t("findings.assign")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function FindingsPage() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const status = (params.get("status") as FindingStatus | null) ?? "";
  const severity = (params.get("severity") as Severity | null) ?? "";
  const sort = params.get("sort") ?? "severity";
  const page = Number(params.get("page") ?? 1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);

  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v);
    else next.delete(k);
    if (k !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const findings = useQuery({
    queryKey: ["findings", "all", { q, status, severity, sort, page }],
    queryFn: () => api<Page<Finding>>(`/findings${qs({ q, status: status || undefined, severity, sort, page, page_size: 25 })}`),
  });
  const items = findings.data?.items ?? [];
  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <>
      <PageHeader
        title={t("findings.title")}
        description={t("findings.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.findings") }]}
      />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3">
          <IconInput
            icon={Search}
            aria-label={t("findings.search")}
            placeholder={t("findings.search")}
            className="min-w-60 flex-1"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Select aria-label={t("findings.statusFilter")} className="w-52" value={status} onChange={(e) => setParam("status", e.target.value)}>
            <option value="">{t("findings.allStatuses")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`findingStatus.${s}`)}
              </option>
            ))}
          </Select>
          <Select aria-label={t("findings.severity")} className="w-40" value={severity} onChange={(e) => setParam("severity", e.target.value)}>
            <option value="">{t("findings.allSeverities")}</option>
            {(["critical", "high", "medium", "low"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`severity.${s}`)}
              </option>
            ))}
          </Select>
          <Select aria-label={t("findings.sort")} className="w-44" value={sort} onChange={(e) => setParam("sort", e.target.value)}>
            {(["severity", "due_date", "created_at", "status"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`findings.sortBy.${s}`)}
              </option>
            ))}
          </Select>
        </div>
        {findings.isLoading && <LoadingState />}
        {findings.isError && <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />}
        {findings.data && items.length === 0 && <EmptyState icon={ListChecks} title={t("findings.empty")} description={t("findings.emptyHint")} />}
        {items.length > 0 && (
          <>
            <Table>
              <THead>
                <tr>
                  {can("decide") && (
                    <TH className="w-10 pe-0">
                      <span className="sr-only">{t("findings.select")}</span>
                    </TH>
                  )}
                  <TH>{t("findings.titleField")}</TH>
                  <TH>{t("findings.severity")}</TH>
                  <TH>{t("findings.status")}</TH>
                  <TH>{t("findings.owner")}</TH>
                  <TH>{t("findings.dueDate")}</TH>
                </tr>
              </THead>
              <TBody>
                {items.map((f) => {
                  const isSelected = selected.has(f.id);
                  return (
                    <TR key={f.id} className={cn(isSelected && "bg-teal-50/50 hover:bg-teal-50/70")}>
                      {can("decide") && (
                        <TD className="pe-0">
                          <input
                            type="checkbox"
                            className="size-4 cursor-pointer rounded border-slate-300 accent-teal-600 disabled:cursor-not-allowed disabled:opacity-40"
                            aria-label={t("findings.selectOne", { title: f.title })}
                            disabled={!ASSIGNABLE.has(f.status)}
                            title={!ASSIGNABLE.has(f.status) ? t("findings.confirmFirst") : undefined}
                            checked={isSelected}
                            onChange={() => toggle(f.id)}
                          />
                        </TD>
                      )}
                      <TD className="max-w-md">
                        <Link to={`/reviews/${f.review_id}?finding=${f.id}`} className="font-medium text-navy-900 transition-colors hover:text-teal-700">
                          {f.title}
                        </Link>
                        <p className="mt-0.5 truncate text-xs text-slate-500">{f.review_title}</p>
                      </TD>
                      <TD>
                        <SeverityBadge severity={f.severity} />
                      </TD>
                      <TD>
                        <FindingStatusBadge status={f.status} />
                      </TD>
                      <TD>
                        {f.owner_name ? (
                          <span className="flex items-center gap-2 whitespace-nowrap text-[13px] text-slate-700">
                            <Avatar name={f.owner_name} className="size-6 text-[10px]" />
                            {f.owner_name}
                          </span>
                        ) : (
                          <span className="text-[13px] text-slate-400">{t("findings.unassigned")}</span>
                        )}
                      </TD>
                      <TD className="whitespace-nowrap text-[13px]">
                        {f.due_date ? (
                          <span className={cn("inline-flex items-center gap-1.5", f.is_overdue ? "font-medium text-red-700" : "text-slate-600")}>
                            <CalendarClock className={cn("size-3.5", f.is_overdue ? "text-red-500" : "text-slate-400")} aria-hidden />
                            {formatDate(f.due_date, i18n.language)}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                        {f.is_overdue && (
                          <Badge tone="red" className="ms-2">
                            {t("findings.overdue")}
                          </Badge>
                        )}
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
            <Pagination page={page} pageSize={25} total={findings.data!.total} onPage={(p) => setParam("page", String(p))} />
          </>
        )}
      </Card>
      {can("decide") && selected.size > 0 && (
        <div className="pointer-events-none sticky bottom-4 z-20 mt-4 flex justify-center">
          <div
            role="region"
            aria-label={t("findings.bulkAssign")}
            className="pointer-events-auto flex animate-fade-up items-center gap-3 rounded-xl bg-navy-950 py-2 ps-4 pe-2 text-sm text-white shadow-pop ring-1 ring-white/10"
          >
            <span className="flex items-center gap-2">
              <span className="flex size-6 items-center justify-center rounded-md bg-white/10 text-xs font-semibold tabular-nums">{selected.size}</span>
              <span className="text-slate-300">{t("findings.selected")}</span>
            </span>
            <span className="h-5 w-px bg-white/15" aria-hidden />
            <Button size="sm" variant="accent" onClick={() => setBulkOpen(true)}>
              <UserPlus aria-hidden /> {t("findings.bulkAssignN", { count: selected.size })}
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              className="text-slate-300 hover:bg-white/10 hover:text-white"
              aria-label={t("findings.clearSelection")}
              title={t("findings.clearSelection")}
              onClick={() => setSelected(new Set())}
            >
              <X aria-hidden />
            </Button>
          </div>
        </div>
      )}
      <BulkAssignDialog ids={[...selected]} open={bulkOpen} onOpenChange={setBulkOpen} onDone={() => setSelected(new Set())} />
    </>
  );
}
