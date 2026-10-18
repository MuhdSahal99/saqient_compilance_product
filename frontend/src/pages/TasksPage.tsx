import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { api, qs } from "@/lib/api";
import { TASK_STATUSES, type Finding, type Page, type Task, type TaskStatus } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useEntities, useMembers } from "@/lib/queries";
import { formatDate } from "@/lib/utils";
import { BellOff, CalendarClock, CheckCircle2, ChevronRight, ListTodo, Loader2, Pencil, Plus } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  errorMessage,
  FindingStatusBadge,
  LoadingState,
  PageHeader,
  Pagination,
  SEVERITY_COLOR,
  SeverityBadge,
  TaskStatusBadge,
} from "@/components/common";

type Scope = "mine" | "all";
type View = "remediation" | "general";

function FindingTasks() {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const [scope, setScope] = useState<Scope>("mine");
  const [overdue, setOverdue] = useState(params.get("overdue") === "1");
  const [page, setPage] = useState(1);
  const tasks = useQuery({
    queryKey: ["findings", "tasks", { scope, overdue, page }],
    queryFn: () =>
      api<Page<Finding>>(
        `/findings${qs({
          status: ["remediation_in_progress", "ready_for_rereview"],
          owner: scope === "mine" ? "me" : undefined,
          overdue,
          sort: "due_date",
          page,
          page_size: 25,
        })}`,
      ),
  });
  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-3">
          <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
            {(["mine", "all"] as const).map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={scope === s}
                onClick={() => {
                  setScope(s);
                  setPage(1);
                }}
                className={cn(
                  "rounded-md px-3 py-1.5 text-[13px] font-medium transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600",
                  scope === s ? "bg-white text-navy-900 shadow-xs ring-1 ring-slate-200/80" : "text-slate-600 hover:text-navy-900",
                )}
              >
                {t(`tasks.scope.${s}`)}
              </button>
            ))}
          </div>
          <label
            className={cn(
              "ms-auto flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] font-medium transition-colors",
              overdue ? "border-red-200 bg-red-50 text-red-700" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
            )}
          >
            <input
              type="checkbox"
              className="size-3.5 accent-red-600"
              checked={overdue}
              onChange={(e) => {
                setOverdue(e.target.checked);
                setPage(1);
              }}
            />
            {t("tasks.overdueOnly")}
          </label>
        </div>
        {tasks.isLoading && <LoadingState />}
        {tasks.isError && <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />}
        {tasks.data?.items.length === 0 && <EmptyState icon={CheckCircle2} title={t("tasks.empty")} description={t("tasks.emptyHint")} />}
        {tasks.data && tasks.data.items.length > 0 && (
          <>
            <ul className="divide-y divide-slate-100">
              {tasks.data.items.map((f) => (
                <li
                  key={f.id}
                  className={cn(
                    "group relative grid gap-3 px-5 py-4 transition-colors hover:bg-slate-50/80 md:grid-cols-[minmax(0,1fr)_auto_11rem_10rem] md:items-center md:gap-5",
                    f.is_overdue && "bg-red-50/40 hover:bg-red-50/60",
                  )}
                >
                  <span
                    className="absolute inset-y-3 start-0 w-[3px] rounded-e-full"
                    style={{ backgroundColor: SEVERITY_COLOR[f.severity] }}
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <Link
                      to={`/reviews/${f.review_id}?finding=${f.id}`}
                      className="font-medium text-navy-900 transition-colors after:absolute after:inset-0 hover:text-teal-700"
                    >
                      {f.title}
                    </Link>
                    <div className="mt-1 flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={f.severity} />
                      <span className="truncate text-xs text-slate-500">{f.review_title}</span>
                    </div>
                  </div>
                  <div>
                    <FindingStatusBadge status={f.status} />
                  </div>
                  <div className="flex min-w-0 items-center gap-2 text-[13px] text-slate-700">
                    <Avatar name={f.owner_name} className="size-6 text-[10px]" />
                    <span className="truncate">{f.owner_name ?? "—"}</span>
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px]",
                        f.is_overdue ? "font-medium text-red-700" : "text-slate-600",
                      )}
                    >
                      <CalendarClock className={cn("size-3.5", f.is_overdue ? "text-red-500" : "text-slate-400")} aria-hidden />
                      {formatDate(f.due_date, i18n.language)}
                      {f.is_overdue && <Badge tone="red">{t("findings.overdue")}</Badge>}
                    </span>
                    <ChevronRight className="hidden size-4 text-slate-300 transition-colors group-hover:text-slate-500 md:block rtl-flip" aria-hidden />
                  </div>
                </li>
              ))}
            </ul>
            <Pagination page={page} pageSize={25} total={tasks.data.total} onPage={setPage} />
          </>
        )}
      </Card>
      <p className="mt-3 flex items-center gap-2 text-xs text-slate-500">
        <BellOff className="size-3.5 shrink-0 text-slate-400" aria-hidden />
        {t("tasks.noNotifications")}
      </p>
    </>
  );
}

// ---------------------------------------------------------------- general tasks (tax obligations and manual)

const CLOSED: TaskStatus[] = ["done", "cancelled"];

const updateSchema = z
  .object({
    status: z.enum(["open", "in_progress", "done", "cancelled"]),
    owner_id: z.string(),
    due_date: z.string(),
    note: z.string().max(4000),
  })
  .superRefine((v, ctx) => {
    if (CLOSED.includes(v.status) && !v.note.trim()) ctx.addIssue({ code: "custom", path: ["note"], message: "required" });
  });
type UpdateValues = z.infer<typeof updateSchema>;

function TaskUpdateDialog({ task, onOpenChange }: { task: Task | null; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const decide = can("decide");
  const members = useMembers(!!task && decide);
  const form = useForm<UpdateValues>({
    resolver: zodResolver(updateSchema),
    defaultValues: { status: "open", owner_id: "", due_date: "", note: "" },
  });
  useEffect(() => {
    if (task) form.reset({ status: task.status, owner_id: task.owner_id ?? "", due_date: task.due_date ?? "", note: "" });
  }, [task, form]);
  const status = useWatch({ control: form.control, name: "status" });
  const save = useMutation({
    mutationFn: (v: UpdateValues) => {
      if (!task) throw new Error("no task");
      const body: Record<string, unknown> = {};
      if (v.status !== task.status) body.status = v.status;
      if (v.note.trim()) body.note = v.note.trim();
      if (decide && v.owner_id !== (task.owner_id ?? "")) {
        if (v.owner_id) body.owner_id = v.owner_id;
        else body.clear_owner = true;
      }
      if (task.source_kind === "manual" && v.due_date && v.due_date !== (task.due_date ?? "")) body.due_date = v.due_date;
      return api<Task>(`/tasks/${task.id}`, { method: "PATCH", json: body });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      void qc.invalidateQueries({ queryKey: ["tax-obligations"] });
      toast.success(t("generalTasks.updated"));
      onOpenChange(false);
    },
  });
  const err = form.formState.errors;
  const closing = CLOSED.includes(status);
  return (
    <Dialog open={task !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{t("generalTasks.update")}</DialogTitle>
        <DialogDescription>{task?.title}</DialogDescription>
        {task && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => save.mutate(v))} noValidate>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="task-status">{t("generalTasks.status")}</Label>
                <Select id="task-status" {...form.register("status")}>
                  {TASK_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {t(`taskStatus.${s}`)}
                    </option>
                  ))}
                </Select>
              </div>
              {task.source_kind === "manual" ? (
                <div className="space-y-1.5">
                  <Label htmlFor="task-due">{t("findings.dueDate")}</Label>
                  <Input id="task-due" type="date" {...form.register("due_date")} />
                </div>
              ) : (
                <div className="space-y-1.5">
                  <span className="text-[13px] font-medium text-slate-700">{t("findings.dueDate")}</span>
                  <p className="text-xs leading-relaxed text-slate-500">{t("generalTasks.dueFixed")}</p>
                </div>
              )}
            </div>
            {decide && (
              <div className="space-y-1.5">
                <Label htmlFor="task-owner">{t("findings.owner")}</Label>
                <Select id="task-owner" {...form.register("owner_id")}>
                  <option value="">{t("findings.unassigned")}</option>
                  {(members.data ?? []).map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="task-note">{closing ? t("generalTasks.closingNote") : t("generalTasks.note")}</Label>
              <Textarea id="task-note" rows={3} aria-invalid={!!err.note} aria-describedby="task-note-hint" {...form.register("note")} />
              <p id="task-note-hint" className="text-xs text-slate-500">
                {closing ? t("generalTasks.closingNoteHint") : t("generalTasks.noteHint")}
              </p>
              <FieldError message={err.note ? t("generalTasks.noteRequired") : undefined} />
            </div>
            {task.completion_note && (
              <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                <span className="font-medium">{t("generalTasks.previousNote")}</span> {task.completion_note}
              </p>
            )}
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
        )}
      </DialogContent>
    </Dialog>
  );
}

const newSchema = z.object({
  title: z.string().trim().min(1).max(300),
  description: z.string().max(4000),
  entity_id: z.string(),
  owner_id: z.string(),
  due_date: z.string(),
});
type NewValues = z.infer<typeof newSchema>;

function NewTaskDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const entities = useEntities(open);
  const members = useMembers(open);
  const form = useForm<NewValues>({
    resolver: zodResolver(newSchema),
    defaultValues: { title: "", description: "", entity_id: "", owner_id: "", due_date: "" },
  });
  const create = useMutation({
    mutationFn: (v: NewValues) =>
      api<Task>("/tasks", {
        json: {
          title: v.title,
          description: v.description,
          entity_id: v.entity_id || null,
          owner_id: v.owner_id || null,
          due_date: v.due_date || null,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      toast.success(t("generalTasks.created"));
      form.reset();
      onOpenChange(false);
    },
  });
  const err = form.formState.errors;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>{t("generalTasks.new")}</DialogTitle>
        <DialogDescription>{t("generalTasks.newHint")}</DialogDescription>
        {(entities.isLoading || members.isLoading) && <LoadingState rows={2} />}
        {(entities.isError || members.isError) && (
          <ErrorState
            error={entities.error ?? members.error}
            onRetry={() => {
              void entities.refetch();
              void members.refetch();
            }}
          />
        )}
        {entities.data && members.data && (
          <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="nt-title">{t("generalTasks.titleField")}</Label>
              <Input id="nt-title" aria-invalid={!!err.title} {...form.register("title")} />
              <FieldError message={err.title ? t("generalTasks.titleRequired") : undefined} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="nt-desc">{t("generalTasks.descriptionField")}</Label>
              <Textarea id="nt-desc" rows={3} {...form.register("description")} />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="nt-entity">{t("datasets.entity")}</Label>
                <Select id="nt-entity" {...form.register("entity_id")}>
                  <option value="">{t("generalTasks.noEntity")}</option>
                  {entities.data.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="nt-owner">{t("findings.owner")}</Label>
                <Select id="nt-owner" {...form.register("owner_id")}>
                  <option value="">{t("findings.unassigned")}</option>
                  {members.data.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="nt-due">{t("findings.dueDate")}</Label>
              <Input id="nt-due" type="date" className="sm:w-1/2" {...form.register("due_date")} />
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
                {t("generalTasks.create")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

type StatusFilter = "active" | "all" | TaskStatus;

function GeneralTasks() {
  const { t, i18n } = useTranslation();
  const { me, can } = useAuth();
  const [scope, setScope] = useState<Scope>("mine");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [entityId, setEntityId] = useState("");
  const [editing, setEditing] = useState<Task | null>(null);
  const [creating, setCreating] = useState(false);
  const entities = useEntities();
  const statuses: TaskStatus[] | undefined = status === "all" ? undefined : status === "active" ? ["open", "in_progress"] : [status];
  const tasks = useQuery({
    queryKey: ["tasks", { scope, status, entityId }],
    queryFn: () => api<Task[]>(`/tasks${qs({ mine: scope === "mine", status: statuses, entity_id: entityId })}`),
  });
  const canEdit = (task: Task) => can("decide") || (can("write") && !!me && task.owner_id === me.user.id);
  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-3">
          <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
            {(["mine", "all"] as const).map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={scope === s}
                onClick={() => setScope(s)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-[13px] font-medium transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600",
                  scope === s ? "bg-white text-navy-900 shadow-xs ring-1 ring-slate-200/80" : "text-slate-600 hover:text-navy-900",
                )}
              >
                {t(`generalTasks.scope.${s}`)}
              </button>
            ))}
          </div>
          <Select aria-label={t("generalTasks.status")} className="w-48" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
            <option value="active">{t("generalTasks.activeStatuses")}</option>
            {TASK_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`taskStatus.${s}`)}
              </option>
            ))}
            <option value="all">{t("generalTasks.allStatuses")}</option>
          </Select>
          <Select aria-label={t("datasets.entity")} className="w-56" value={entityId} onChange={(e) => setEntityId(e.target.value)}>
            <option value="">{t("einvoices.allEntities")}</option>
            {(entities.data ?? []).map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </Select>
          {can("write") && (
            <Button size="sm" variant="outline" className="ms-auto" onClick={() => setCreating(true)}>
              <Plus aria-hidden /> {t("generalTasks.new")}
            </Button>
          )}
        </div>
        {tasks.isLoading && <LoadingState />}
        {tasks.isError && <ErrorState error={tasks.error} onRetry={() => void tasks.refetch()} />}
        {tasks.data?.length === 0 && <EmptyState icon={ListTodo} title={t("generalTasks.empty")} description={t("generalTasks.emptyHint")} />}
        {tasks.data && tasks.data.length > 0 && (
          <ul className="divide-y divide-slate-100">
            {tasks.data.map((task) => (
              <li
                key={task.id}
                className={cn(
                  "grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_auto_11rem_10rem_auto] md:items-center md:gap-5",
                  task.is_overdue && "bg-red-50/40",
                )}
              >
                <div className="min-w-0">
                  <p className="font-medium text-navy-900">{task.title}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <Badge tone="neutral">{t(`taskSource.${task.source_kind}`)}</Badge>
                    {task.entity_name && <span>{task.entity_name}</span>}
                  </div>
                  {task.completion_note && <p className="mt-1 truncate text-xs text-slate-500">{task.completion_note}</p>}
                </div>
                <div>
                  <TaskStatusBadge status={task.status} />
                </div>
                <div className="flex min-w-0 items-center gap-2 text-[13px] text-slate-700">
                  <Avatar name={task.owner_name} className="size-6 text-[10px]" />
                  <span className="truncate">{task.owner_name ?? "—"}</span>
                </div>
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 whitespace-nowrap text-[13px]",
                    task.is_overdue ? "font-medium text-red-700" : "text-slate-600",
                  )}
                >
                  <CalendarClock className={cn("size-3.5", task.is_overdue ? "text-red-500" : "text-slate-400")} aria-hidden />
                  {formatDate(task.due_date, i18n.language)}
                  {task.is_overdue && <Badge tone="red">{t("findings.overdue")}</Badge>}
                </span>
                <div className="flex justify-end">
                  {canEdit(task) && (
                    <Button size="sm" variant="ghost" onClick={() => setEditing(task)} aria-label={t("generalTasks.updateNamed", { name: task.title })}>
                      <Pencil aria-hidden /> {t("generalTasks.update")}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <TaskUpdateDialog task={editing} onOpenChange={(o) => !o && setEditing(null)} />
      <NewTaskDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}

export function TasksPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "general" ? "general" : "remediation";
  return (
    <>
      <PageHeader
        title={t("tasks.title")}
        description={t("tasks.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.tasks") }]}
      />
      <Tabs<View>
        className="mb-4"
        label={t("tasks.title")}
        value={view}
        onChange={(v) =>
          setParams(
            (p) => {
              if (v === "general") p.set("view", "general");
              else p.delete("view");
              return p;
            },
            { replace: true },
          )
        }
        items={[
          { key: "remediation", label: t("tasks.tabRemediation") },
          { key: "general", label: t("tasks.tabGeneral") },
        ]}
      />
      {view === "remediation" ? <FindingTasks /> : <GeneralTasks />}
    </>
  );
}
