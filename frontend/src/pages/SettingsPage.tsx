import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Bot } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Member } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { LANGUAGES } from "@/i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ErrorState, errorMessage, LoadingState, PageHeader, SyntheticBadge, useUnsavedChangesWarning } from "@/components/common";

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
    <form className="space-y-3" onSubmit={form.handleSubmit((v) => change.mutate(v))} noValidate>
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
      <p className="text-xs text-slate-500">{t("settings.passwordSessionsNote")}</p>
      <Button type="submit" size="sm" disabled={change.isPending}>
        {t("settings.changePassword")}
      </Button>
    </form>
  );
}

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { me, switchOrg } = useAuth();
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members") });
  const ai = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api<{ enabled: boolean; provider: string; note: string }>("/ai/status"),
  });
  if (!me) return null;
  return (
    <>
      <PageHeader title={t("settings.title")} crumbs={[{ label: t("nav.overview"), to: "/" }, { label: t("nav.settings") }]} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.profile")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <dl className="grid grid-cols-[8rem_1fr] gap-y-2">
              <dt className="text-slate-500">{t("settings.name")}</dt>
              <dd>{me.user.full_name}</dd>
              <dt className="text-slate-500">{t("auth.email")}</dt>
              <dd>{me.user.email}</dd>
              <dt className="text-slate-500">{t("settings.organisation")}</dt>
              <dd className="flex items-center gap-2">
                {me.org.name} {me.org.is_demo && <SyntheticBadge />}
              </dd>
              <dt className="text-slate-500">{t("settings.role")}</dt>
              <dd>{t(`roles.${me.role}`)}</dd>
            </dl>
            <div className="space-y-1.5">
              <Label htmlFor="lang">{t("settings.language")}</Label>
              <Select id="lang" className="w-48" value={i18n.language} onChange={(e) => void i18n.changeLanguage(e.target.value)}>
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.label}
                  </option>
                ))}
              </Select>
            </div>
            {me.memberships.length > 1 && (
              <div className="space-y-1.5">
                <Label htmlFor="org">{t("settings.switchOrg")}</Label>
                <Select
                  id="org"
                  className="w-72"
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
            <CardTitle>{t("settings.security")}</CardTitle>
          </CardHeader>
          <CardContent>
            <PasswordForm />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.members")}</CardTitle>
            <CardDescription>{t("settings.membersHint")}</CardDescription>
          </CardHeader>
          {members.isLoading && <LoadingState />}
          {members.isError && <ErrorState error={members.error} onRetry={() => void members.refetch()} />}
          {members.data && (
            <Table>
              <THead>
                <tr>
                  <TH>{t("settings.name")}</TH>
                  <TH>{t("settings.role")}</TH>
                </tr>
              </THead>
              <TBody>
                {members.data.map((m) => (
                  <TR key={m.user_id}>
                    <TD>
                      {m.full_name}
                      <p className="text-xs text-slate-500">{m.email}</p>
                    </TD>
                    <TD>{t(`roles.${m.role}`)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="size-4" aria-hidden /> {t("settings.ai")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {ai.data && (
              <p className="flex items-center gap-2">
                <Badge tone={ai.data.enabled ? "teal" : "neutral"}>{ai.data.enabled ? t("settings.aiEnabled") : t("settings.aiDisabled")}</Badge>
                <span className="text-slate-600">{t("settings.aiProvider", { provider: ai.data.provider })}</span>
              </p>
            )}
            <p className="text-slate-600">{t("settings.aiExplainer")}</p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
