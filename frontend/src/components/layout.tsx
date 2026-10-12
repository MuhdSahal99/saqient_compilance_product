import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Activity,
  ClipboardCheck,
  FileSearch,
  FileText,
  FolderOpen,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Settings,
  ShieldCheck,
  SquareCheckBig,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { SyntheticBadge } from "./common";
import { LANGUAGES } from "@/i18n";
import { toast } from "sonner";

const NAV = [
  { to: "/", key: "overview", icon: LayoutDashboard, end: true },
  { to: "/reviews", key: "reviews", icon: ClipboardCheck },
  { to: "/documents", key: "documents", icon: FolderOpen },
  { to: "/checklists", key: "checklists", icon: ListChecks },
  { to: "/findings", key: "findings", icon: FileSearch },
  { to: "/tasks", key: "tasks", icon: SquareCheckBig },
  { to: "/reports", key: "reports", icon: FileText },
  { to: "/activity", key: "activity", icon: Activity },
  { to: "/settings", key: "settings", icon: Settings },
] as const;

export function LanguageSwitch({ className }: { className?: string }) {
  const { i18n, t } = useTranslation();
  return (
    <div className={cn("flex gap-1", className)} role="group" aria-label={t("settings.language")}>
      {LANGUAGES.map((l) => (
        <button
          key={l.code}
          type="button"
          lang={l.code}
          aria-pressed={i18n.language === l.code}
          onClick={() => void i18n.changeLanguage(l.code)}
          className={cn(
            "rounded px-2 py-1 text-xs",
            i18n.language === l.code ? "bg-white/15 font-semibold text-white" : "text-navy-200 hover:text-white",
          )}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}

export function AppLayout() {
  const { t } = useTranslation();
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  if (!me) return null;
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-2">
        {t("common.skipToContent")}
      </a>
      <aside className="no-print sticky top-0 hidden h-screen w-60 shrink-0 flex-col bg-navy-900 text-navy-100 md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <ShieldCheck className="size-6 text-teal-500" aria-hidden />
          <div>
            <p className="text-sm font-semibold text-white">Saqient</p>
            <p className="text-[11px] text-navy-300">{t("app.subtitle")}</p>
          </div>
        </div>
        <nav aria-label={t("nav.primary")} className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ to, key, icon: Icon, ...rest }) => (
            <NavLink
              key={to}
              to={to}
              end={"end" in rest}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive ? "bg-white/10 font-medium text-white" : "text-navy-200 hover:bg-white/5 hover:text-white",
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {t(`nav.${key}`)}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-white/10 px-5 py-4 text-xs">
          <LanguageSwitch />
          <p className="mt-3 truncate font-medium text-white" title={me.user.email}>
            {me.user.full_name}
          </p>
          <p className="truncate text-navy-300">
            {me.org.name} · {t(`roles.${me.role}`)}
          </p>
          {me.org.is_demo && <SyntheticBadge className="mt-2" />}
          <button
            type="button"
            className="mt-3 flex items-center gap-1.5 text-navy-200 hover:text-white"
            onClick={async () => {
              await logout();
              toast.success(t("auth.signedOut"));
              navigate("/login");
            }}
          >
            <LogOut className="size-3.5 rtl-flip" aria-hidden /> {t("auth.signOut")}
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Compact top navigation for small screens */}
        <header className="no-print flex items-center gap-2 overflow-x-auto bg-navy-900 px-3 py-2 md:hidden">
          <ShieldCheck className="size-5 shrink-0 text-teal-500" aria-hidden />
          {NAV.map(({ to, key, ...rest }) => (
            <NavLink
              key={to}
              to={to}
              end={"end" in rest}
              className={({ isActive }) => cn("shrink-0 rounded px-2 py-1 text-xs", isActive ? "bg-white/15 text-white" : "text-navy-200")}
            >
              {t(`nav.${key}`)}
            </NavLink>
          ))}
          <LanguageSwitch className="ms-auto shrink-0" />
        </header>
        {me.demo_mode && (
          <div className="no-print border-b border-amber-200 bg-amber-50 px-6 py-1.5 text-center text-xs text-amber-900">
            {t("app.demoBanner")}
          </div>
        )}
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-8">
          <Outlet />
        </main>
        <footer className="no-print px-8 py-4 text-center text-[11px] text-slate-400">{t("app.footerDisclaimer")}</footer>
      </div>
    </div>
  );
}
