import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Loader2, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label } from "@/components/ui/input";
import { errorMessage } from "@/components/common";

const schema = z.object({
  email: z.email(),
  password: z.string().min(1),
});
type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const { t, i18n } = useTranslation();
  const { me, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  if (me) return <Navigate to="/" replace />;

  const onSubmit = async (values: FormValues) => {
    setError(null);
    try {
      await login(values.email, values.password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (e) {
      setError(errorMessage(e, t("common.genericError")));
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-br from-navy-900 via-navy-800 to-teal-800 px-4">
      <div className="w-full max-w-sm rounded-xl bg-white p-8 shadow-2xl">
        <div className="mb-6 flex items-center gap-2">
          <ShieldCheck className="size-7 text-teal-700" aria-hidden />
          <div>
            <h1 className="text-lg font-semibold text-navy-900">{t("app.name")}</h1>
            <p className="text-xs text-slate-500">{t("auth.tagline")}</p>
          </div>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="email">{t("auth.email")}</Label>
            <Input id="email" type="email" autoComplete="username" aria-invalid={!!errors.email} {...register("email")} />
            <FieldError message={errors.email ? t("auth.emailInvalid") : undefined} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">{t("auth.password")}</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={!!errors.password}
              {...register("password")}
            />
            <FieldError message={errors.password ? t("auth.passwordRequired") : undefined} />
          </div>
          {error && (
            <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="animate-spin" aria-hidden />}
            {t("auth.signIn")}
          </Button>
        </form>
        <div className="mt-6 flex justify-center gap-3 text-xs">
          {(["en", "ar"] as const).map((l) => (
            <button
              key={l}
              type="button"
              lang={l}
              className={i18n.language === l ? "font-semibold text-navy-900" : "text-slate-500 hover:text-navy-900"}
              onClick={() => void i18n.changeLanguage(l)}
            >
              {l === "en" ? "English" : "العربية"}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-6 max-w-sm text-center text-xs text-navy-200">{t("app.footerDisclaimer")}</p>
    </div>
  );
}
