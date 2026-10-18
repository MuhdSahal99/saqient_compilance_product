import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, MailPlus, RefreshCw, UserMinus, Users, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Invitation, Member, Role } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label, Select } from "@/components/ui/input";
import { ConfirmDialog, ErrorState, errorMessage, LoadingState } from "./common";

const ROLES: Role[] = ["org_admin", "reviewer", "analyst", "viewer"];

const inviteSchema = z.object({ email: z.email(), role: z.enum(["org_admin", "reviewer", "analyst", "viewer"]) });
type InviteValues = z.infer<typeof inviteSchema>;

function InviteForm() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const form = useForm<InviteValues>({ resolver: zodResolver(inviteSchema), defaultValues: { email: "", role: "analyst" } });
  const invite = useMutation({
    mutationFn: (v: InviteValues) => api<Invitation>("/invitations", { json: v }),
    onSuccess: (inv) => {
      void qc.invalidateQueries({ queryKey: ["invitations"] });
      form.reset({ email: "", role: form.getValues("role") });
      if (inv.last_delivery === "failed") toast.warning(t("members.inviteNotDelivered"));
      else toast.success(t("members.invited", { email: inv.email }));
    },
  });
  return (
    <form className="grid gap-3 px-5 pb-4 sm:grid-cols-[minmax(0,1fr)_11rem_auto] sm:items-end" onSubmit={form.handleSubmit((v) => invite.mutate(v))} noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="invite-email">{t("auth.email")}</Label>
        <Input id="invite-email" type="email" autoComplete="off" aria-invalid={!!form.formState.errors.email} {...form.register("email")} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="invite-role">{t("settings.role")}</Label>
        <Select id="invite-role" {...form.register("role")}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t(`roles.${r}`)}
            </option>
          ))}
        </Select>
      </div>
      <Button type="submit" variant="accent" disabled={invite.isPending}>
        {invite.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <MailPlus aria-hidden />}
        {t("members.invite")}
      </Button>
      <div className="sm:col-span-3">
        <FieldError message={form.formState.errors.email ? t("auth.emailInvalid") : undefined} />
        {invite.isError && (
          <p role="alert" className="text-sm text-red-700">
            {errorMessage(invite.error, t("common.genericError"))}
          </p>
        )}
      </div>
    </form>
  );
}

function Invitations() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const invitations = useQuery({ queryKey: ["invitations"], queryFn: () => api<Invitation[]>("/invitations") });
  const onError = (e: unknown) => toast.error(errorMessage(e, t("common.genericError")));
  const resend = useMutation({
    mutationFn: (id: string) => api<Invitation>(`/invitations/${id}/resend`, { method: "POST" }),
    onSuccess: (inv) => {
      void qc.invalidateQueries({ queryKey: ["invitations"] });
      if (inv.last_delivery === "failed") toast.warning(t("members.inviteNotDelivered"));
      else toast.success(t("members.resent"));
    },
    onError,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/invitations/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["invitations"] });
      toast.success(t("members.revoked"));
    },
    onError,
  });
  if (invitations.isLoading) return <LoadingState rows={1} />;
  if (invitations.isError) return <ErrorState error={invitations.error} onRetry={() => void invitations.refetch()} />;
  if (!invitations.data?.length) return <p className="px-5 pb-4 text-xs text-slate-500">{t("members.noInvitations")}</p>;
  return (
    <ul className="divide-y divide-slate-100 border-t border-slate-100">
      {invitations.data.map((inv) => (
        <li key={inv.id} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-navy-900">{inv.email}</p>
            <p className="text-xs text-slate-500">
              {inv.is_expired ? t("members.expired") : t("members.expires", { date: formatDate(inv.expires_at, i18n.language) })}
              {inv.last_delivery === "failed" && <span className="ms-2 text-red-700">{t("members.deliveryFailed")}</span>}
            </p>
          </div>
          <Badge tone="neutral">{t(`roles.${inv.role}`)}</Badge>
          <Button size="sm" variant="ghost" disabled={resend.isPending} onClick={() => resend.mutate(inv.id)}>
            <RefreshCw aria-hidden /> {t("members.resend")}
          </Button>
          <Button size="icon-sm" variant="ghost" disabled={revoke.isPending} onClick={() => revoke.mutate(inv.id)} aria-label={t("members.revokeNamed", { email: inv.email })}>
            <X aria-hidden />
          </Button>
        </li>
      ))}
    </ul>
  );
}

export function MembersCard() {
  const { t } = useTranslation();
  const { me, can } = useAuth();
  const qc = useQueryClient();
  const admin = can("admin");
  const [removing, setRemoving] = useState<Member | null>(null);
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members") });
  const changeRole = useMutation({
    mutationFn: ({ m, role }: { m: Member; role: Role }) => api<Member>(`/members/${m.membership_id}`, { method: "PATCH", json: { role } }),
    onSuccess: (m) => {
      void qc.invalidateQueries({ queryKey: ["members"] });
      if (m.user_id === me?.user.id) void qc.invalidateQueries({ queryKey: ["me"] });
      toast.success(t("members.roleChanged"));
    },
    onError: (e) => {
      void qc.invalidateQueries({ queryKey: ["members"] });
      toast.error(errorMessage(e, t("common.genericError")));
    },
  });
  const remove = useMutation({
    mutationFn: (m: Member) => api(`/members/${m.membership_id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["members"] });
      setRemoving(null);
      toast.success(t("members.removed"));
    },
    onError: (e) => {
      setRemoving(null);
      toast.error(errorMessage(e, t("common.genericError")));
    },
  });

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Users className="size-4 text-slate-400" aria-hidden />
          {t("settings.members")}
        </CardTitle>
        <CardDescription>{admin ? t("members.hintAdmin") : t("members.hint")}</CardDescription>
      </CardHeader>
      {members.isLoading && <LoadingState rows={3} />}
      {members.isError && <ErrorState error={members.error} onRetry={() => void members.refetch()} />}
      {members.data && (
        <ul className="divide-y divide-slate-100">
          {members.data.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <Avatar name={m.full_name} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-navy-900">
                  {m.full_name}
                  {m.user_id === me?.user.id && <span className="ms-1.5 text-xs font-normal text-slate-400">{t("members.you")}</span>}
                </p>
                <p className="truncate text-xs text-slate-500">{m.email}</p>
              </div>
              {admin && m.membership_id ? (
                <>
                  <Select
                    aria-label={t("members.roleFor", { name: m.full_name })}
                    className="w-44"
                    value={m.role}
                    disabled={changeRole.isPending}
                    onChange={(e) => changeRole.mutate({ m, role: e.target.value as Role })}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {t(`roles.${r}`)}
                      </option>
                    ))}
                  </Select>
                  <Button size="icon-sm" variant="ghost" onClick={() => setRemoving(m)} aria-label={t("members.removeNamed", { name: m.full_name })}>
                    <UserMinus aria-hidden />
                  </Button>
                </>
              ) : (
                <Badge tone={m.role === "org_admin" ? "navy" : "neutral"}>{t(`roles.${m.role}`)}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      {admin && (
        <div className="border-t border-slate-100 pt-4">
          <p className="px-5 pb-2 text-[13px] font-semibold text-navy-900">{t("members.inviteTitle")}</p>
          <InviteForm />
          <Invitations />
        </div>
      )}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t("members.removeTitle")}
        description={t("members.removeDescription", { name: removing?.full_name ?? "" })}
        confirmLabel={t("members.remove")}
        destructive
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </Card>
  );
}
