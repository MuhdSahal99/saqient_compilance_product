import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertCircle, ArrowRight, Eye, EyeOff, FileSearch, ListChecks, Loader2, Lock, Mail, SquareCheckBig } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { FieldError, Label } from "@/components/ui/input";
import { errorMessage } from "@/components/common";
import { LanguageSwitch, Logo } from "@/components/layout";
import { cn } from "@/lib/utils";

const schema = z.object({
  email: z.email(),
  password: z.string().min(1),
});
type FormValues = z.infer<typeof schema>;

const inputCls =
  "h-11 w-full rounded-lg border border-slate-200 bg-white ps-10 pe-3 text-[15px] text-slate-900 shadow-xs transition-[border-color,box-shadow] placeholder:text-slate-400 hover:border-slate-300 focus-visible:border-teal-500 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-500/15 aria-[invalid=true]:border-red-400";

const FEATURES = [
  { icon: ListChecks, key: "checklists" },
  { icon: FileSearch, key: "evidence" },
  { icon: SquareCheckBig, key: "signoff" },
] as const;

export function LoginPage() {
  const { t } = useTranslation();
  const { me, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
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
    <div className="grid min-h-screen bg-white lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      {/* Brand panel */}
      <aside className="relative hidden overflow-hidden bg-navy-950 lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          aria-hidden
          className="absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(60% 50% at 15% 10%, rgb(16 181 148 / 0.28), transparent 70%), radial-gradient(50% 45% at 90% 85%, rgb(74 93 135 / 0.45), transparent 70%)",
          }}
        />
        <div
          aria-hidden
          className="absolute inset-0 opacity-[0.07]"
          style={{
            backgroundImage: "linear-gradient(rgb(255 255 255) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
            maskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
          }}
        />
        <Logo inverted className="relative" />
        <div className="relative max-w-md animate-fade-up">
          <h2 className="text-[34px] font-semibold leading-[1.15] tracking-tight text-white">{t("auth.heroTitle")}</h2>
          <p className="mt-4 text-[15px] leading-relaxed text-white/65">{t("auth.heroBody")}</p>
          <ul className="mt-10 space-y-5">
            {FEATURES.map(({ icon: Icon, key }) => (
              <li key={key} className="flex gap-4">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white/[0.07] ring-1 ring-inset ring-white/10">
                  <Icon className="size-[18px] text-teal-300" aria-hidden />
                </span>
                <div>
                  <p className="text-sm font-semibold text-white">{t(`auth.feature.${key}.title`)}</p>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-white/55">{t(`auth.feature.${key}.body`)}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative max-w-md text-xs leading-relaxed text-white/45">{t("app.footerDisclaimer")}</p>
      </aside>

      {/* Form */}
      <main className="flex flex-col px-6 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Logo className="lg:invisible" />
          <LanguageSwitch />
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-sm animate-fade-up">
            <h1 className="text-[28px] font-semibold tracking-tight text-navy-950">{t("auth.welcome")}</h1>
            <p className="mt-2 text-[15px] text-slate-500">{t("auth.signInHint")}</p>

            <form onSubmit={handleSubmit(onSubmit)} className="mt-8 space-y-5" noValidate>
              <div className="space-y-1.5">
                <Label htmlFor="email">{t("auth.email")}</Label>
                <div className="relative">
                  <Mail className="pointer-events-none absolute start-3.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
                  <input
                    id="email"
                    type="email"
                    autoComplete="username"
                    placeholder="name@organisation.example"
                    className={inputCls}
                    aria-invalid={!!errors.email}
                    {...register("email")}
                  />
                </div>
                <FieldError message={errors.email ? t("auth.emailInvalid") : undefined} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">{t("auth.password")}</Label>
                <div className="relative">
                  <Lock className="pointer-events-none absolute start-3.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    className={cn(inputCls, "pe-11")}
                    aria-invalid={!!errors.password}
                    {...register("password")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((s) => !s)}
                    aria-label={showPassword ? t("auth.hidePassword") : t("auth.showPassword")}
                    aria-controls="password"
                    className="absolute end-1.5 top-1/2 -translate-y-1/2 rounded-md p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                  >
                    {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                  </button>
                </div>
                <FieldError message={errors.password ? t("auth.passwordRequired") : undefined} />
              </div>
              {error && (
                <p
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800 animate-fade-in"
                >
                  <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {error}
                </p>
              )}
              <Button type="submit" variant="accent" size="lg" className="group w-full" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="animate-spin" aria-hidden />}
                {t("auth.signIn")}
                {!isSubmitting && <ArrowRight className="transition-transform group-hover:translate-x-0.5 rtl-flip" aria-hidden />}
              </Button>
            </form>
            <p className="mt-8 text-xs leading-relaxed text-slate-400 lg:hidden">{t("app.footerDisclaimer")}</p>
          </div>
        </div>
      </main>
    </div>
  );
}
