import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useForm, type UseFormRegisterReturn } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertCircle, CheckCircle2, Loader2, MailCheck } from "lucide-react";
import { api, ApiError, setCsrfToken } from "@/lib/api";
import type { InvitationLookup, Me } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label } from "@/components/ui/input";
import { errorMessage, LoadingState } from "@/components/common";
import { LanguageSwitch, Logo } from "@/components/layout";

/** Read `#token=...` once, then drop it from the address bar so it is not left in history. */
function useHashToken(): string {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "");
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }, []);
  return token;
}

function AuthShell({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 px-6 py-6 sm:px-10">
      <div className="flex items-center justify-between">
        <Logo />
        <LanguageSwitch />
      </div>
      <main className="flex flex-1 items-center justify-center py-10">
        <div className="w-full max-w-sm animate-fade-up rounded-2xl border border-slate-200/80 bg-white p-7 shadow-xs">
          <h1 className="text-2xl font-semibold tracking-tight text-navy-950">{title}</h1>
          {description && <div className="mt-2 text-sm leading-relaxed text-slate-500">{description}</div>}
          <div className="mt-6">{children}</div>
        </div>
      </main>
      <p className="mx-auto max-w-md text-center text-xs leading-relaxed text-slate-400">{t("app.footerDisclaimer")}</p>
    </div>
  );
}

function Alert({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

function BackToSignIn() {
  const { t } = useTranslation();
  return (
    <p className="mt-6 text-center text-sm">
      <Link to="/login" className="font-medium text-teal-700 hover:underline">
        {t("auth.backToSignIn")}
      </Link>
    </p>
  );
}

const forgotSchema = z.object({ email: z.email() });

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [sent, setSent] = useState(false);
  const form = useForm<z.infer<typeof forgotSchema>>({ resolver: zodResolver(forgotSchema), defaultValues: { email: "" } });
  const request = useMutation({
    mutationFn: (v: z.infer<typeof forgotSchema>) => api("/auth/password-reset/request", { json: v }),
    onSuccess: () => setSent(true),
  });
  if (sent)
    return (
      <AuthShell title={t("auth.resetSentTitle")}>
        <p className="flex items-start gap-3 text-sm leading-relaxed text-slate-600">
          <MailCheck className="mt-0.5 size-5 shrink-0 text-teal-600" aria-hidden />
          {t("auth.resetSent")}
        </p>
        <BackToSignIn />
      </AuthShell>
    );
  return (
    <AuthShell title={t("auth.forgotTitle")} description={t("auth.forgotHint")}>
      <form className="space-y-5" onSubmit={form.handleSubmit((v) => request.mutate(v))} noValidate>
        <div className="space-y-1.5">
          <Label htmlFor="fp-email">{t("auth.email")}</Label>
          <Input id="fp-email" type="email" autoComplete="username" aria-invalid={!!form.formState.errors.email} {...form.register("email")} />
          <FieldError message={form.formState.errors.email ? t("auth.emailInvalid") : undefined} />
        </div>
        {request.isError && <Alert>{errorMessage(request.error, t("common.genericError"))}</Alert>}
        <Button type="submit" variant="accent" className="w-full" disabled={request.isPending}>
          {request.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {t("auth.sendResetLink")}
        </Button>
      </form>
      <BackToSignIn />
    </AuthShell>
  );
}

const newPasswordSchema = z
  .object({ password: z.string().min(12).max(256), confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "mismatch" });

function NewPasswordFields({
  idPrefix,
  password,
  confirm,
  passwordInvalid,
  confirmInvalid,
}: {
  idPrefix: string;
  password: UseFormRegisterReturn;
  confirm: UseFormRegisterReturn;
  passwordInvalid: boolean;
  confirmInvalid: boolean;
}) {
  const { t } = useTranslation();
  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-pw`}>{t("settings.newPassword")}</Label>
        <Input id={`${idPrefix}-pw`} type="password" autoComplete="new-password" aria-invalid={passwordInvalid} {...password} />
        <FieldError message={passwordInvalid ? t("settings.passwordRule") : undefined} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-confirm`}>{t("settings.confirmPassword")}</Label>
        <Input id={`${idPrefix}-confirm`} type="password" autoComplete="new-password" aria-invalid={confirmInvalid} {...confirm} />
        <FieldError message={confirmInvalid ? t("settings.passwordMismatch") : undefined} />
      </div>
    </>
  );
}

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const token = useHashToken();
  const [done, setDone] = useState(false);
  const form = useForm<z.infer<typeof newPasswordSchema>>({ resolver: zodResolver(newPasswordSchema), defaultValues: { password: "", confirm: "" } });
  const confirm = useMutation({
    mutationFn: (v: z.infer<typeof newPasswordSchema>) => api("/auth/password-reset/confirm", { json: { token, new_password: v.password } }),
    onSuccess: () => setDone(true),
  });
  if (!token)
    return (
      <AuthShell title={t("auth.resetTitle")}>
        <Alert>{t("auth.linkInvalid")}</Alert>
        <p className="mt-4 text-center text-sm">
          <Link to="/forgot-password" className="font-medium text-teal-700 hover:underline">
            {t("auth.requestNewLink")}
          </Link>
        </p>
      </AuthShell>
    );
  if (done)
    return (
      <AuthShell title={t("auth.resetDoneTitle")}>
        <p className="flex items-start gap-3 text-sm leading-relaxed text-slate-600">
          <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-teal-600" aria-hidden />
          {t("auth.resetDone")}
        </p>
        <BackToSignIn />
      </AuthShell>
    );
  return (
    <AuthShell title={t("auth.resetTitle")} description={t("auth.resetHint")}>
      <form className="space-y-5" onSubmit={form.handleSubmit((v) => confirm.mutate(v))} noValidate>
        <NewPasswordFields
          idPrefix="rp"
          password={form.register("password")}
          confirm={form.register("confirm")}
          passwordInvalid={!!form.formState.errors.password}
          confirmInvalid={!!form.formState.errors.confirm}
        />
        {confirm.isError && (
          <Alert>
            {errorMessage(confirm.error, t("common.genericError"))}{" "}
            {confirm.error instanceof ApiError && confirm.error.status === 400 && (
              <Link to="/forgot-password" className="font-medium underline">
                {t("auth.requestNewLink")}
              </Link>
            )}
          </Alert>
        )}
        <Button type="submit" variant="accent" className="w-full" disabled={confirm.isPending}>
          {confirm.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {t("auth.setPassword")}
        </Button>
      </form>
    </AuthShell>
  );
}

const newAccountSchema = z
  .object({ full_name: z.string().trim().min(1).max(200), password: z.string().min(12).max(256), confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "mismatch" });
const existingAccountSchema = z.object({ password: z.string().min(1) });

export function AcceptInvitePage() {
  const { t, i18n } = useTranslation();
  const { me } = useAuth();
  const token = useHashToken();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const lookup = useQuery({
    queryKey: ["invitation-lookup", token],
    queryFn: () => api<InvitationLookup>("/invitations/lookup", { json: { token } }),
    enabled: !!token,
    retry: false,
    staleTime: Infinity,
  });
  const accept = useMutation({
    mutationFn: (body: { password: string; full_name?: string }) => api<Me>("/invitations/accept", { json: { token, ...body } }),
    onSuccess: (result) => {
      setCsrfToken(result.csrf_token);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      qc.setQueryData(["me"], result);
      navigate("/", { replace: true });
    },
  });
  const newForm = useForm<z.infer<typeof newAccountSchema>>({ resolver: zodResolver(newAccountSchema), defaultValues: { full_name: "", password: "", confirm: "" } });
  const existingForm = useForm<z.infer<typeof existingAccountSchema>>({ resolver: zodResolver(existingAccountSchema), defaultValues: { password: "" } });

  if (!token || lookup.isError)
    return (
      <AuthShell title={t("invite.title")}>
        <Alert>{lookup.error instanceof ApiError && lookup.error.status === 429 ? lookup.error.message : t("invite.invalid")}</Alert>
        <BackToSignIn />
      </AuthShell>
    );
  if (lookup.isLoading || !lookup.data)
    return (
      <AuthShell title={t("invite.title")}>
        <LoadingState rows={2} />
      </AuthShell>
    );
  const inv = lookup.data;
  const signedInAsOther = me && me.user.email.toLowerCase() !== inv.email.toLowerCase();
  if (me && !signedInAsOther && me.memberships.some((m) => m.org.name === inv.organization_name)) return <Navigate to="/" replace />;

  return (
    <AuthShell
      title={t("invite.joinTitle", { org: inv.organization_name })}
      description={
        <span className="flex flex-wrap items-center gap-2">
          {t("invite.as")} <Badge tone="teal">{t(`roles.${inv.role}`)}</Badge>
          <span className="break-all">{inv.email}</span>
        </span>
      }
    >
      <p className="mb-5 text-xs text-slate-500">{t("invite.expires", { date: formatDate(inv.expires_at, i18n.language, true) })}</p>
      {signedInAsOther && (
        <p className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">{t("invite.signedInAsOther", { email: me.user.email })}</p>
      )}
      {inv.has_account ? (
        <form className="space-y-5" onSubmit={existingForm.handleSubmit((v) => accept.mutate({ password: v.password }))} noValidate>
          <p className="text-sm text-slate-600">{t("invite.existingHint")}</p>
          <div className="space-y-1.5">
            <Label htmlFor="inv-pw">{t("auth.password")}</Label>
            <Input id="inv-pw" type="password" autoComplete="current-password" aria-invalid={!!existingForm.formState.errors.password} {...existingForm.register("password")} />
            <FieldError message={existingForm.formState.errors.password ? t("auth.passwordRequired") : undefined} />
          </div>
          {accept.isError && <Alert>{errorMessage(accept.error, t("common.genericError"))}</Alert>}
          <Button type="submit" variant="accent" className="w-full" disabled={accept.isPending}>
            {accept.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {t("invite.accept")}
          </Button>
          <p className="text-center text-xs">
            <Link to="/forgot-password" className="text-teal-700 hover:underline">
              {t("auth.forgotLink")}
            </Link>
          </p>
        </form>
      ) : (
        <form className="space-y-5" onSubmit={newForm.handleSubmit((v) => accept.mutate({ password: v.password, full_name: v.full_name }))} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="inv-name">{t("settings.name")}</Label>
            <Input id="inv-name" autoComplete="name" aria-invalid={!!newForm.formState.errors.full_name} {...newForm.register("full_name")} />
            <FieldError message={newForm.formState.errors.full_name ? t("invite.nameRequired") : undefined} />
          </div>
          <NewPasswordFields
            idPrefix="inv"
            password={newForm.register("password")}
            confirm={newForm.register("confirm")}
            passwordInvalid={!!newForm.formState.errors.password}
            confirmInvalid={!!newForm.formState.errors.confirm}
          />
          {accept.isError && <Alert>{errorMessage(accept.error, t("common.genericError"))}</Alert>}
          <Button type="submit" variant="accent" className="w-full" disabled={accept.isPending}>
            {accept.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {t("invite.createAndJoin")}
          </Button>
        </form>
      )}
    </AuthShell>
  );
}
