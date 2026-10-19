import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Bot, Building2, Info, KeyRound, Languages, Loader2, ShieldCheck, type LucideIcon } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { AIStatus } from "@/lib/types";
import { aiSettingsKey, useOrgAISettings, type OrgAISettings } from "@/lib/content-packs";
import { formatDate } from "@/lib/utils";
import { MembersCard } from "@/components/members-card";
import { MockNotice } from "@/components/ai-suggestions";
import { useAuth } from "@/lib/auth";
import { LANGUAGES } from "@/i18n";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { ConfirmDialog, ErrorState, errorMessage, LoadingState, PageHeader, SyntheticBadge, useUnsavedChangesWarning } from "@/components/common";

const pwSchema = z
  .object({
    current_password: z.string().min(1),
    new_password: z.string().min(12).max(256),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "mismatch" });
type PwValues = z.infer<typeof pwSchema>;

function PasswordForm() {
  const { t } = useTranslation();
  const form = useForm<PwValues>({ resolver: zodResolver(pwSchema), defaultValues: { current_password: "", new_password: "", confirm: "" } });
  useUnsavedChangesWarning(form.formState.isDirty);
  const change = useMutation({
    mutationFn: (v: PwValues) => api("/auth/change-password", { json: { current_password: v.current_password, new_password: v.new_password } }),
    onSuccess: () => {
      form.reset();
      toast.success(t("settings.passwordChanged"));
    },
    onError: (e) => toast.error(errorMessage(e, t("common.genericError"))),
  });
  const err = form.formState.errors;
  return (
    <form className="max-w-md space-y-4" onSubmit={form.handleSubmit((v) => change.mutate(v))} noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="pw-current">{t("settings.currentPassword")}</Label>
        <Input id="pw-current" type="password" autoComplete="current-password" {...form.register("current_password")} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pw-new">{t("settings.newPassword")}</Label>
        <Input id="pw-new" type="password" autoComplete="new-password" aria-invalid={!!err.new_password} {...form.register("new_password")} />
        <FieldError message={err.new_password ? t("settings.passwordRule") : undefined} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pw-confirm">{t("settings.confirmPassword")}</Label>
        <Input id="pw-confirm" type="password" autoComplete="new-password" aria-invalid={!!err.confirm} {...form.register("confirm")} />
        <FieldError message={err.confirm ? t("settings.passwordMismatch") : undefined} />
      </div>
      <p className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
        <Info className="mt-px size-3.5 shrink-0 text-slate-400" aria-hidden />
        {t("settings.passwordSessionsNote")}
      </p>
      <Button type="submit" disabled={change.isPending}>
        {change.isPending && <Loader2 className="animate-spin" aria-hidden />}
        {t("settings.changePassword")}
      </Button>
    </form>
  );
}

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { me, switchOrg } = useAuth();
  const ai = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api<AIStatus>("/ai/status"),
  });
  if (!me) return null;
  return (
    <>
      <PageHeader title={t("settings.title")} crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.settings") }]} />
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_360px]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <SectionTitle icon={ShieldCheck}>{t("settings.profile")}</SectionTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="flex items-center gap-4">
                <Avatar name={me.user.full_name} className="size-12 text-base" />
                <div className="min-w-0">
                  <p className="truncate font-semibold text-navy-900">{me.user.full_name}</p>
                  <Badge tone="navy" className="mt-1">
                    {t(`roles.${me.role}`)}
                  </Badge>
                </div>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 border-t border-slate-100 pt-4 text-sm">
                <dt className="text-slate-500">{t("settings.name")}</dt>
                <dd className="text-slate-800">{me.user.full_name}</dd>
                <dt className="text-slate-500">{t("auth.email")}</dt>
                <dd className="break-all text-slate-800">{me.user.email}</dd>
                <dt className="text-slate-500">{t("settings.role")}</dt>
                <dd className="text-slate-800">{t(`roles.${me.role}`)}</dd>
              </dl>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <SectionTitle icon={KeyRound}>{t("settings.security")}</SectionTitle>
            </CardHeader>
            <CardContent>
              <PasswordForm />
            </CardContent>
          </Card>
          <MembersCard />
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <SectionTitle icon={Languages}>{t("settings.language")}</SectionTitle>
            </CardHeader>
            <CardContent>
              <Label htmlFor="lang" className="sr-only">
                {t("settings.language")}
              </Label>
              <Select id="lang" value={i18n.language} onChange={(e) => void i18n.changeLanguage(e.target.value)}>
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </Select>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <SectionTitle icon={Building2}>{t("settings.organisation")}</SectionTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-50 ring-1 ring-slate-200/80">
                  <Building2 className="size-4 text-slate-500" aria-hidden />
                </span>
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-navy-900">
                    {me.org.name} {me.org.is_demo && <SyntheticBadge />}
                  </p>
                  <p className="text-xs text-slate-500">{t(`roles.${me.role}`)}</p>
                </div>
              </div>
              {me.memberships.length > 1 && (
                <div className="space-y-1.5">
                  <Label htmlFor="org">{t("settings.switchOrg")}</Label>
                  <Select
                    id="org"
                    value={me.org.id}
                    onChange={async (e) => {
                      try {
                        await switchOrg(e.target.value);
                        toast.success(t("settings.orgSwitched"));
                      } catch (err) {
                        toast.error(errorMessage(err, t("common.genericError")));
                      }
                    }}
                  >
                    {me.memberships.map((m) => (
                      <option key={m.org.id} value={m.org.id}>
                        {m.org.name} · {t(`roles.${m.role}`)}
                      </option>
                    ))}
                  </Select>
                </div>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-2">
                <SectionTitle icon={Bot}>{t("settings.ai")}</SectionTitle>
                {ai.data && (
                  <Badge tone={ai.data.enabled ? "teal" : "neutral"} dot>
                    {ai.data.enabled ? t("settings.aiEnabled") : t("settings.aiDisabled")}
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              {ai.isLoading && <LoadingState rows={1} />}
              {ai.isError && <ErrorState error={ai.error} onRetry={() => void ai.refetch()} />}
              {ai.data && <p className="text-[13px] text-slate-500">{t("settings.aiProvider", { provider: ai.data.provider })}</p>}
              <p className="leading-relaxed text-slate-600">{ai.data?.enabled ? t("settings.aiExplainerOn") : t("settings.aiExplainer")}</p>
              {ai.data?.is_mock && <MockNotice />}
              <OrgAIOptIn />
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

/** The organisation's own opt-in to AI suggestions, on top of the deployment switch. */
function OrgAIOptIn() {
  const { t, i18n } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const settings = useOrgAISettings();
  const [confirm, setConfirm] = useState(false);
  const save = useMutation({
    mutationFn: (opted_in: boolean) => api<OrgAISettings>("/org/ai-settings", { method: "PUT", json: { opted_in } }),
    onSuccess: (s) => {
      qc.setQueryData(aiSettingsKey, s);
      void qc.invalidateQueries({ queryKey: ["ai-status"] });
      void qc.invalidateQueries({ queryKey: ["me"] });
      setConfirm(false);
      toast.success(s.opted_in ? t("settings.aiOptedIn") : t("settings.aiOptedOut"));
    },
    onError: (e) => {
      setConfirm(false);
      toast.error(errorMessage(e, t("common.genericError")));
    },
  });
  return (
    <section aria-labelledby="ai-optin-title" className="space-y-3 border-t border-slate-100 pt-4">
      <h3 id="ai-optin-title" className="text-[13px] font-semibold text-navy-900">
        {t("settings.aiOrgTitle")}
      </h3>
      {settings.isLoading && <LoadingState rows={1} />}
      {settings.isError && <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />}
      {settings.data && (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[13px]">
            <dt className="text-slate-500">{t("settings.aiDeployment")}</dt>
            <dd className="flex flex-wrap items-center gap-1.5 text-slate-800">
              {settings.data.deployment_available ? t("settings.aiDeploymentAvailable") : t("settings.aiDeploymentUnavailable")}
              {settings.data.is_mock && <Badge tone="amber">{t("settings.aiMock")}</Badge>}
            </dd>
            {settings.data.deployment_available && (
              <>
                <dt className="text-slate-500">{t("settings.aiModel")}</dt>
                <dd className="break-all text-slate-800" dir="ltr">
                  {settings.data.provider}
                  {settings.data.model ? ` · ${settings.data.model}` : ""}
                </dd>
              </>
            )}
            <dt className="text-slate-500">{t("settings.aiOrgState")}</dt>
            <dd className="text-slate-800">
              {settings.data.opted_in
                ? settings.data.opted_in_at
                  ? t("settings.aiOptedInSince", { date: formatDate(settings.data.opted_in_at, i18n.language, true) })
                  : t("settings.aiOptedInState")
                : t("settings.aiNotOptedIn")}
            </dd>
          </dl>
          {can("admin") && (
            <div className="space-y-1.5">
              <Button
                size="sm"
                variant={settings.data.opted_in ? "outline" : "accent"}
                aria-pressed={settings.data.opted_in}
                aria-describedby={settings.data.deployment_available ? undefined : "ai-optin-reason"}
                disabled={save.isPending || (!settings.data.deployment_available && !settings.data.opted_in)}
                onClick={() => setConfirm(true)}
              >
                {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {settings.data.opted_in ? t("settings.aiOptOut") : t("settings.aiOptIn")}
              </Button>
              {!settings.data.deployment_available && (
                <p id="ai-optin-reason" className="text-xs text-slate-500">
                  {t("settings.aiUnavailableReason")}
                </p>
              )}
            </div>
          )}
          {!can("admin") && <p className="text-xs text-slate-500">{t("settings.aiAdminOnly")}</p>}
          <ConfirmDialog
            open={confirm}
            onOpenChange={setConfirm}
            title={settings.data.opted_in ? t("settings.aiOptOutTitle") : t("settings.aiOptInTitle")}
            description={settings.data.opted_in ? t("settings.aiOptOutConfirm") : t("settings.aiOptInConfirm")}
            confirmLabel={settings.data.opted_in ? t("settings.aiOptOut") : t("settings.aiOptIn")}
            busy={save.isPending}
            onConfirm={() => settings.data && save.mutate(!settings.data.opted_in)}
          />
        </>
      )}
    </section>
  );
}

function SectionTitle({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <CardTitle className="flex items-center gap-2">
      <Icon className="size-4 text-slate-400" aria-hidden />
      {children}
    </CardTitle>
  );
}
