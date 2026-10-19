import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { KeyRound, Loader2, Plug, PlugZap, Plus, RefreshCw, TriangleAlert, Unplug } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  connectorsKey,
  useConnectors,
  useConnectorStatus,
  type Connector,
  type ConnectorProviderInfo,
  type ConnectorStatus,
  type ConnectorSync,
  type ConnectorSyncStatus,
} from "@/lib/assurance";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ConfirmDialog, EmptyState, ErrorState, LoadingState, PageHeader } from "@/components/common";
import { Field, MutationError } from "@/components/audit/shared";
import { EntitySelect } from "@/components/assurance/shared";

const STATUS_TONE: Record<ConnectorStatus, "neutral" | "green" | "red" | "amber"> = { pending: "neutral", connected: "green", error: "red", disconnected: "amber" };
const SYNC_TONE: Record<ConnectorSyncStatus, "neutral" | "green" | "red" | "teal"> = { queued: "teal", succeeded: "green", unchanged: "neutral", failed: "red" };

const schema = z
  .object({
    provider: z.enum(["zoho_books", "odoo"]),
    entity_id: z.string().min(1),
    name: z.string().trim().min(1).max(200),
    base_url: z.string().trim().max(300),
    database: z.string().trim().max(200),
    username: z.string().trim().max(200),
    api_key: z.string().max(500),
  })
  .superRefine((v, ctx) => {
    if (v.provider !== "odoo") return;
    if (!/^https:\/\/\S+$/.test(v.base_url)) ctx.addIssue({ code: "custom", path: ["base_url"], message: "url" });
    if (!v.database) ctx.addIssue({ code: "custom", path: ["database"], message: "required" });
    if (!v.username) ctx.addIssue({ code: "custom", path: ["username"], message: "required" });
    if (v.api_key.length < 8) ctx.addIssue({ code: "custom", path: ["api_key"], message: "key" });
  });
type Values = z.infer<typeof schema>;

function body(v: Values) {
  const base = { entity_id: v.entity_id, provider: v.provider, name: v.name };
  if (v.provider === "zoho_books") return base;
  return { ...base, config: { base_url: v.base_url, database: v.database, username: v.username }, api_key: v.api_key };
}

function AddConnectorDialog({ providers, open, onOpenChange }: { providers: ConnectorProviderInfo[]; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const first = providers.find((p) => p.configured)?.provider ?? "odoo";
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { provider: first, entity_id: "", name: "", base_url: "", database: "", username: "", api_key: "" },
  });
  const create = useMutation({
    mutationFn: (v: Values) => api<Connector>("/connectors", { json: body(v) }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: connectorsKey });
      toast.success(c.provider === "odoo" ? t("connectors.addedOdoo") : t("connectors.addedZoho"));
      close();
    },
  });
  function close() {
    form.reset();
    create.reset();
    onOpenChange(false);
  }
  const err = form.formState.errors;
  const provider = useWatch({ control: form.control, name: "provider" });
  const info = providers.find((p) => p.provider === provider);
  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())}>
      <DialogContent>
        <DialogTitle>{t("connectors.add")}</DialogTitle>
        <DialogDescription>{t("connectors.addHint")}</DialogDescription>
        <form className="mt-5 space-y-4" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate autoComplete="off">
          <Field id="cn-provider" label={t("connectors.provider")}>
            <Select id="cn-provider" {...form.register("provider")}>
              {providers.map((p) => (
                <option key={p.provider} value={p.provider} disabled={!p.configured}>
                  {p.label}
                  {!p.configured ? ` · ${t("connectors.notConfigured")}` : ""}
                </option>
              ))}
            </Select>
          </Field>
          {info && (
            <p className="text-xs text-slate-500">
              {t("connectors.providerKinds", { kinds: info.kinds.map((k) => t(`datasetKind.${k}`)).join(", ") })}
            </p>
          )}
          <EntitySelect id="cn-entity" reg={form.register("entity_id")} error={!!err.entity_id} />
          <Field id="cn-name" label={t("recs.name")} error={err.name ? t("recs.nameRequired") : undefined}>
            <Input id="cn-name" aria-invalid={!!err.name} {...form.register("name")} />
          </Field>
          {provider === "odoo" && (
            <>
              <Field id="cn-url" label={t("connectors.baseUrl")} hint={t("connectors.baseUrlHint")} error={err.base_url ? t("connectors.urlRule") : undefined}>
                <Input id="cn-url" dir="ltr" type="url" inputMode="url" aria-invalid={!!err.base_url} {...form.register("base_url")} />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id="cn-db" label={t("connectors.database")} error={err.database ? t("connectors.required") : undefined}>
                  <Input id="cn-db" dir="ltr" aria-invalid={!!err.database} {...form.register("database")} />
                </Field>
                <Field id="cn-user" label={t("connectors.username")} error={err.username ? t("connectors.required") : undefined}>
                  <Input id="cn-user" dir="ltr" autoComplete="off" aria-invalid={!!err.username} {...form.register("username")} />
                </Field>
              </div>
              <Field id="cn-key" label={t("connectors.apiKey")} hint={t("connectors.apiKeyHint")} error={err.api_key ? t("connectors.keyRule") : undefined}>
                <Input id="cn-key" dir="ltr" type="password" autoComplete="new-password" aria-invalid={!!err.api_key} {...form.register("api_key")} />
              </Field>
            </>
          )}
          {provider === "zoho_books" && <p className="text-xs text-slate-500">{t("connectors.zohoHint")}</p>}
          <MutationError error={create.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="accent" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t("connectors.addAction")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SyncTable({ c }: { c: Connector }) {
  const { t, i18n } = useTranslation();
  if (c.syncs.length === 0) return <p className="text-[13px] text-slate-500">{t("connectors.noSyncs")}</p>;
  return (
    <Table>
      <THead>
        <tr>
          <TH>{t("connectors.kind")}</TH>
          <TH>{t("recs.status")}</TH>
          <TH className="text-end">{t("connectors.rows")}</TH>
          <TH>{t("connectors.requested")}</TH>
          <TH>{t("connectors.dataset")}</TH>
        </tr>
      </THead>
      <TBody>
        {c.syncs.map((s: ConnectorSync) => {
          const datasetId = c.datasets[s.kind];
          return (
            <TR key={s.id}>
              <TD className="align-top text-[13px]">{t(`datasetKind.${s.kind}`)}</TD>
              <TD className="align-top">
                <Badge tone={SYNC_TONE[s.status]} dot>
                  {t(`syncStatus.${s.status}`)}
                </Badge>
                {s.message && <p className="mt-1 text-xs text-slate-500">{s.message}</p>}
              </TD>
              <TD className="align-top text-end text-[13px] tabular-nums">{s.rows}</TD>
              <TD className="align-top text-xs text-slate-600">
                {formatDate(s.created_at, i18n.language, true)}
                {s.requested_by_name && <div className="text-slate-400">{s.requested_by_name}</div>}
              </TD>
              <TD className="align-top text-[13px]">
                {s.dataset_version_id && datasetId ? (
                  <Link to={`/datasets/${datasetId}`} className="text-teal-700 hover:underline">
                    {t("connectors.openDataset")}
                  </Link>
                ) : (
                  "—"
                )}
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

function ConnectorCard({ c }: { c: Connector }) {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [kind, setKind] = useState(c.kinds[0] ?? "");
  const [confirm, setConfirm] = useState(false);
  const update = (d: Connector) => {
    qc.setQueryData([...connectorsKey, "list"], (old: Connector[] | undefined) => old?.map((x) => (x.id === d.id ? d : x)));
    void qc.invalidateQueries({ queryKey: [...connectorsKey, "list"] });
  };
  const authorize = useMutation({
    mutationFn: () => api<{ url: string }>(`/connectors/${c.id}/authorize`, { method: "POST" }),
    onSuccess: (r) => window.location.assign(r.url),
  });
  const test = useMutation({
    mutationFn: () => api<Connector>(`/connectors/${c.id}/test`, { method: "POST" }),
    onSuccess: (d) => {
      update(d);
      if (d.status === "connected") toast.success(t("connectors.testOk"));
      else toast.error(t("connectors.testFailed"));
    },
  });
  const disconnect = useMutation({
    mutationFn: () => api<Connector>(`/connectors/${c.id}/disconnect`, { method: "POST" }),
    onSuccess: (d) => {
      update(d);
      setConfirm(false);
      toast.success(t("connectors.disconnected"));
    },
  });
  const sync = useMutation({
    mutationFn: () => api<ConnectorSync>(`/connectors/${c.id}/sync`, { json: { kind } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...connectorsKey, "list"] });
      void qc.invalidateQueries({ queryKey: ["datasets"] });
      toast.success(t("connectors.syncQueued"));
    },
  });
  const config = c.config;
  const settings = (["base_url", "database", "username"] as const).filter((k) => typeof config[k] === "string" && config[k]);
  const canConnect = c.status !== "connected";
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>{c.name}</CardTitle>
          <CardDescription>
            {c.provider_label} · {c.entity_name}
            {c.last_sync_at && ` · ${t("connectors.lastSync", { date: formatDate(c.last_sync_at, i18n.language, true) })}`}
          </CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={STATUS_TONE[c.status]} dot>
            {t(`connectorStatus.${c.status}`)}
          </Badge>
          {c.has_credentials && (
            <Badge tone="neutral">
              <KeyRound className="size-3" aria-hidden />
              {t("connectors.credentialsStored")}
            </Badge>
          )}
          {c.mapping_status === "unverified" && <Badge tone="orange">{t("connectors.mappingUnverified")}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {settings.length > 0 && (
          <dl className="grid gap-3 text-[13px] sm:grid-cols-3">
            {settings.map((k) => (
              <div key={k} className="min-w-0">
                <dt className="text-xs text-slate-500">{t(`connectors.cfg_${k}`)}</dt>
                <dd className="mt-0.5 truncate text-navy-900" dir="ltr">
                  {String(config[k])}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {c.last_error && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
            {c.last_error}
          </p>
        )}
        <MutationError error={authorize.error ?? test.error ?? sync.error} />
        <div className="flex flex-wrap items-end gap-2">
          {can("admin") && canConnect && c.provider === "zoho_books" && (
            <Button size="sm" variant="accent" disabled={authorize.isPending} onClick={() => authorize.mutate()}>
              {authorize.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <PlugZap aria-hidden />}
              {t("connectors.connect")}
            </Button>
          )}
          {can("admin") && c.provider === "odoo" && (
            <Button size="sm" variant={canConnect ? "accent" : "outline"} disabled={test.isPending} onClick={() => test.mutate()}>
              {test.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <PlugZap aria-hidden />}
              {t("connectors.test")}
            </Button>
          )}
          {can("write") && c.status === "connected" && c.kinds.length > 0 && (
            <div className="flex items-end gap-2">
              <div className="space-y-1">
                <label htmlFor={`sync-kind-${c.id}`} className="text-xs font-medium text-slate-700">
                  {t("connectors.kind")}
                </label>
                <Select id={`sync-kind-${c.id}`} className="h-8 w-56 text-xs" value={kind} onChange={(e) => setKind(e.target.value)}>
                  {c.kinds.map((k) => (
                    <option key={k} value={k}>
                      {t(`datasetKind.${k}`)}
                    </option>
                  ))}
                </Select>
              </div>
              <Button size="sm" variant="outline" disabled={!kind || sync.isPending} onClick={() => sync.mutate()}>
                {sync.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
                {t("connectors.sync")}
              </Button>
            </div>
          )}
          {can("admin") && c.status !== "disconnected" && (
            <Button size="sm" variant="destructive-outline" onClick={() => setConfirm(true)}>
              <Unplug aria-hidden /> {t("connectors.disconnect")}
            </Button>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-[13px] font-semibold text-navy-900">{t("connectors.recentSyncs")}</h3>
          <SyncTable c={c} />
        </div>
      </CardContent>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t("connectors.disconnectTitle", { name: c.name })}
        description={t("connectors.disconnectHint")}
        confirmLabel={t("connectors.disconnect")}
        destructive
        busy={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
      />
    </Card>
  );
}

/** The OAuth provider returns the browser to /connectors?connector=<id>&result=connected|failed. */
function useOAuthReturn() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const result = params.get("result");
  useEffect(() => {
    if (!result) return;
    if (result === "connected") toast.success(t("connectors.oauthConnected"));
    else toast.error(t("connectors.oauthFailed"));
    void qc.invalidateQueries({ queryKey: connectorsKey });
    setParams({}, { replace: true });
  }, [result, t, qc, setParams]);
}

export function ConnectorsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  useOAuthReturn();
  const status = useConnectorStatus();
  const enabled = status.data?.enabled === true;
  const list = useConnectors(enabled);
  return (
    <>
      <PageHeader
        title={t("connectors.title")}
        description={t("connectors.description")}
        crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.connectors") }]}
        actions={
          enabled &&
          can("admin") && (
            <Button variant="accent" onClick={() => setOpen(true)}>
              <Plus aria-hidden /> {t("connectors.add")}
            </Button>
          )
        }
      />
      {status.isLoading && (
        <Card>
          <LoadingState />
        </Card>
      )}
      {status.isError && (
        <Card>
          <ErrorState error={status.error} onRetry={() => void status.refetch()} />
        </Card>
      )}
      {status.data && !enabled && (
        <Card>
          <EmptyState icon={Plug} title={t("connectors.notAvailable")} description={t("connectors.notAvailableHint")} />
        </Card>
      )}
      {enabled && (
        <div className="space-y-4">
          <p role="note" className="flex items-start gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-xs leading-relaxed text-orange-900">
            <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
            {t("connectors.mappingNote")}
          </p>
          {list.isLoading && (
            <Card>
              <LoadingState />
            </Card>
          )}
          {list.isError && (
            <Card>
              <ErrorState error={list.error} onRetry={() => void list.refetch()} />
            </Card>
          )}
          {list.data?.length === 0 && (
            <Card>
              <EmptyState icon={Plug} title={t("connectors.empty")} description={can("admin") ? t("connectors.emptyHintAdmin") : t("connectors.emptyHint")} />
            </Card>
          )}
          {list.data?.map((c) => <ConnectorCard key={c.id} c={c} />)}
        </div>
      )}
      {enabled && status.data && <AddConnectorDialog providers={status.data.providers} open={open} onOpenChange={setOpen} />}
    </>
  );
}

