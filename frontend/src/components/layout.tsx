import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BriefcaseBusiness,
  Building,
  CalendarCheck,
  CalculatorIcon,
  CalendarClock,
  Check,
  ChevronsUpDown,
  ClipboardCheck,
  FileCode,
  FileSearch,
  FileText,
  FolderOpen,
  GitCompareArrows,
  Inbox,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Layers,
  Scale,
  Search,
  Plug,
  Settings,
  ShieldCheck,
  SquareCheckBig,
  Table2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Dashboard } from "@/lib/types";
import { cn } from "@/lib/utils";
import { LANGUAGES } from "@/i18n";
import { Avatar } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SyntheticBadge } from "./common";
import { CommandPalette, useCommandPaletteShortcut } from "./command-palette";

type NavKey =
  | "overview"
  | "reviews"
  | "documents"
  | "checklists"
  | "entities"
  | "datasets"
  | "einvoices"
  | "directTax"
  | "rulePacks"
  | "contentPacks"
  | "findings"
  | "tasks"
  | "taxCalendar"
  | "engagements"
  | "reconciliations"
  | "close"
  | "controls"
  | "connectors"
  | "portal"
  | "reports"
  | "activity"
  | "settings";

type NavGroup = { key: string; items: { to: string; key: NavKey; icon: typeof LayoutDashboard; end?: boolean }[] };

const NAV_GROUPS: NavGroup[] = [
  {
    key: "workspace",
    items: [{ to: "/", key: "overview", icon: LayoutDashboard, end: true }],
  },
  {
    key: "review",
    items: [
      { to: "/reviews", key: "reviews", icon: ClipboardCheck },
      { to: "/documents", key: "documents", icon: FolderOpen },
      { to: "/checklists", key: "checklists", icon: ListChecks },
    ],
  },
  {
    key: "finance",
    items: [
      { to: "/datasets", key: "datasets", icon: Table2 },
      { to: "/einvoices", key: "einvoices", icon: FileCode },
      { to: "/workpapers", key: "directTax", icon: CalculatorIcon },
      { to: "/entities", key: "entities", icon: Building },
      { to: "/rule-packs", key: "rulePacks", icon: Scale },
      { to: "/content-packs", key: "contentPacks", icon: Layers },
    ],
  },
  {
    key: "audit",
    items: [{ to: "/engagements", key: "engagements", icon: BriefcaseBusiness }],
  },
  {
    key: "assurance",
    items: [
      { to: "/reconciliations", key: "reconciliations", icon: GitCompareArrows },
      { to: "/close", key: "close", icon: CalendarCheck },
      { to: "/controls", key: "controls", icon: ShieldCheck },
    ],
  },
  {
    key: "followUp",
    items: [
      { to: "/findings", key: "findings", icon: FileSearch },
      { to: "/tasks", key: "tasks", icon: SquareCheckBig },
      { to: "/tax-calendar", key: "taxCalendar", icon: CalendarClock },
      { to: "/reports", key: "reports", icon: FileText },
    ],
  },
  {
    key: "admin",
    items: [
      { to: "/activity", key: "activity", icon: Activity },
      { to: "/connectors", key: "connectors", icon: Plug },
      { to: "/settings", key: "settings", icon: Settings },
    ],
  },
];

/** Client contacts reach only the request portal; the backend refuses them everywhere else. */
const CLIENT_NAV: NavGroup[] = [{ key: "workspace", items: [{ to: "/portal", key: "portal", icon: Inbox, end: true }] }];

export const CLIENT_HOME = "/portal";

const COLLAPSE_KEY = "saqient.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

export function Logo({ className, withText = true, inverted }: { className?: string; withText?: boolean; inverted?: boolean }) {
  const { t } = useTranslation();
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <span className="relative flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-gradient-to-br from-teal-400 to-teal-700 shadow-sm shadow-teal-900/20 ring-1 ring-inset ring-white/20">
        <svg viewBox="0 0 24 24" className="size-[18px] text-white" fill="none" aria-hidden>
          <path d="M12 3 5 6v5.5c0 4.2 2.9 7.9 7 9 4.1-1.1 7-4.8 7-9V6l-7-3Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
          <path d="m9 12 2.2 2.2L15.5 10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      {withText && (
        <span className="min-w-0 leading-tight">
          <span className={cn("block text-[15px] font-semibold tracking-tight", inverted ? "text-white" : "text-navy-950")}>Saqient</span>
          <span className={cn("block truncate text-[11px]", inverted ? "text-white/60" : "text-slate-500")}>{t("app.subtitle")}</span>
        </span>
      )}
    </span>
  );
}

export function LanguageSwitch({ className, tone = "light" }: { className?: string; tone?: "light" | "dark" }) {
  const { i18n, t } = useTranslation();
  return (
    <div
      className={cn("inline-flex rounded-lg p-0.5", tone === "light" ? "bg-slate-100" : "bg-white/10", className)}
      role="group"
      aria-label={t("settings.language")}
    >
      {LANGUAGES.map((l) => {
        const active = i18n.language === l.code;
        return (
          <button
            key={l.code}
            type="button"
            lang={l.code}
            aria-pressed={active}
            onClick={() => void i18n.changeLanguage(l.code)}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-all",
              tone === "light"
                ? active
                  ? "bg-white text-navy-900 shadow-xs"
                  : "text-slate-500 hover:text-navy-900"
                : active
                  ? "bg-white text-navy-900"
                  : "text-white/70 hover:text-white",
            )}
          >
            {l.label}
          </button>
        );
      })}
    </div>
  );
}

function useNavCounts(enabled: boolean): Partial<Record<NavKey, number>> {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard"), staleTime: 30_000, enabled });
  if (!q.data) return {};
  return { findings: q.data.findings_proposed, tasks: q.data.open_tasks };
}

function OrgSwitcher({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const { me, switchOrg } = useAuth();
  const navigate = useNavigate();
  if (!me) return null;
  const multi = me.memberships.length > 1;
  const body = (
    <>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-navy-900 text-xs font-semibold text-white">
        {me.org.name.slice(0, 1).toUpperCase()}
      </span>
      {!collapsed && (
        <span className="min-w-0 flex-1 text-start leading-tight">
          <span className="block truncate text-[13px] font-semibold text-navy-900">{me.org.name}</span>
          <span className="block truncate text-[11px] text-slate-500">{t(`roles.${me.role}`)}</span>
        </span>
      )}
      {!collapsed && multi && <ChevronsUpDown className="size-4 shrink-0 text-slate-400" aria-hidden />}
    </>
  );
  const cls = cn(
    "flex w-full items-center gap-2.5 rounded-xl border border-slate-200/80 bg-white p-2 shadow-xs",
    multi && "transition-colors hover:border-slate-300 hover:bg-slate-50",
    collapsed && "justify-center border-transparent bg-transparent p-1 shadow-none",
  );
  if (!multi) return <div className={cls} title={collapsed ? me.org.name : undefined}>{body}</div>;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className={cls} aria-label={t("settings.switchOrg")}>
        {body}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>{t("settings.switchOrg")}</DropdownMenuLabel>
        {me.memberships.map((m) => (
          <DropdownMenuItem
            key={m.org.id}
            onSelect={async () => {
              if (m.org.id === me.org.id) return;
              try {
                await switchOrg(m.org.id);
                navigate("/");
              } catch {
                toast.error(t("common.genericError"));
              }
            }}
          >
            <span className="flex size-6 items-center justify-center rounded-md bg-slate-100 text-[11px] font-semibold text-slate-700">
              {m.org.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate">{m.org.name}</span>
              <span className="block text-[11px] text-slate-500">{t(`roles.${m.role}`)}</span>
            </span>
            {m.org.id === me.org.id && <Check className="!text-teal-600" aria-hidden />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SidebarContents({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const { t } = useTranslation();
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const isClient = me?.role === "client";
  const counts = useNavCounts(!!me && !isClient);
  if (!me) return null;
  const groups = isClient ? CLIENT_NAV : NAV_GROUPS;
  return (
    <>
      <div className={cn("flex h-16 shrink-0 items-center px-4", collapsed && "justify-center px-2")}>
        <Link to={isClient ? CLIENT_HOME : "/"} onClick={onNavigate} className="rounded-lg" aria-label={t("app.name")}>
          <Logo withText={!collapsed} />
        </Link>
      </div>
      <div className={cn("px-3 pb-3", collapsed && "px-2")}>
        <OrgSwitcher collapsed={collapsed} />
      </div>
      <nav aria-label={t("nav.primary")} className={cn("flex-1 space-y-5 overflow-y-auto px-3 py-2", collapsed && "px-2")}>
        {groups.map((g) => (
          <div key={g.key}>
            {!collapsed && g.key !== "workspace" && (
              <p className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{t(`nav.group.${g.key}`)}</p>
            )}
            <ul className="space-y-0.5">
              {g.items.map(({ to, key, icon: Icon, end }) => {
                const count = counts[key];
                return (
                  <li key={to}>
                    <NavLink
                      to={to}
                      end={end}
                      onClick={onNavigate}
                      title={collapsed ? t(`nav.${key}`) : undefined}
                      className={({ isActive }) =>
                        cn(
                          "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors",
                          collapsed && "justify-center px-0",
                          isActive
                            ? "bg-white text-navy-950 shadow-xs ring-1 ring-slate-200/80"
                            : "text-slate-600 hover:bg-slate-200/50 hover:text-navy-900",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <Icon
                            className={cn("size-[18px] shrink-0", isActive ? "text-teal-600" : "text-slate-400 group-hover:text-slate-600")}
                            aria-hidden
                          />
                          {!collapsed && <span className="flex-1 truncate">{t(`nav.${key}`)}</span>}
                          {!collapsed && !!count && (
                            <span
                              className={cn(
                                "rounded-full px-1.5 py-px text-[11px] font-semibold tabular-nums",
                                isActive ? "bg-teal-50 text-teal-700" : "bg-slate-200/70 text-slate-600",
                              )}
                            >
                              <span className="sr-only">(</span>
                              {count}
                              <span className="sr-only">)</span>
                            </span>
                          )}
                          {collapsed && !!count && <span className="absolute end-1.5 top-1.5 size-1.5 rounded-full bg-teal-500" aria-hidden />}
                        </>
                      )}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <div className={cn("border-t border-slate-200/80 p-3", collapsed && "px-2")}>
        <div className={cn("flex items-center gap-2.5 rounded-xl p-1.5", collapsed && "flex-col")}>
          <Avatar name={me.user.full_name} />
          {!collapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-[13px] font-semibold text-navy-900" title={me.user.email}>
                {me.user.full_name}
              </p>
              <p className="truncate text-[11px] text-slate-500">{me.user.email}</p>
            </div>
          )}
          <button
            type="button"
            aria-label={t("auth.signOut")}
            title={t("auth.signOut")}
            className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-200/60 hover:text-navy-900"
            onClick={async () => {
              await logout();
              toast.success(t("auth.signedOut"));
              navigate("/login");
            }}
          >
            <LogOut className="size-4 rtl-flip" aria-hidden />
          </button>
        </div>
      </div>
    </>
  );
}

export function AppLayout() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  useCommandPaletteShortcut(() => setPaletteOpen(true));

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
  }, [collapsed]);

  if (!me) return null;
  const isClient = me.role === "client";
  if (isClient && location.pathname !== CLIENT_HOME) return <Navigate to={CLIENT_HOME} replace />;
  return (
    <div className="flex min-h-screen bg-slate-50">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-white focus:p-2 focus:shadow-pop"
      >
        {t("common.skipToContent")}
      </a>

      <aside
        className={cn(
          "no-print sticky top-0 hidden h-screen shrink-0 flex-col border-e border-slate-200/80 bg-slate-100/60 transition-[width] duration-200 lg:flex",
          collapsed ? "w-[68px]" : "w-64",
        )}
      >
        <SidebarContents collapsed={collapsed} />
      </aside>

      {/* Mobile drawer */}
      <DialogPrimitive.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-navy-950/40 backdrop-blur-[2px] data-[state=open]:animate-fade-in lg:hidden" />
          <DialogPrimitive.Content className="fixed inset-y-0 start-0 z-50 flex w-72 max-w-[85vw] flex-col bg-slate-50 shadow-pop data-[state=open]:animate-fade-in lg:hidden">
            <DialogPrimitive.Title className="sr-only">{t("nav.primary")}</DialogPrimitive.Title>
            <DialogPrimitive.Close className="absolute end-3 top-4 rounded-lg p-1.5 text-slate-500 hover:bg-slate-200/60" aria-label={t("common.close")}>
              <X className="size-4" aria-hidden />
            </DialogPrimitive.Close>
            <SidebarContents collapsed={false} onNavigate={() => setMobileOpen(false)} />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200/70 bg-white/80 px-4 backdrop-blur-md sm:px-6">
          <button
            type="button"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 lg:hidden"
            aria-label={t("nav.openMenu")}
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="size-5" aria-hidden />
          </button>
          <button
            type="button"
            className="hidden rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 lg:inline-flex"
            aria-label={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
            title={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
            onClick={() => setCollapsed((c) => !c)}
          >
            {collapsed ? <PanelLeftOpen className="size-[18px] rtl-flip" aria-hidden /> : <PanelLeftClose className="size-[18px] rtl-flip" aria-hidden />}
          </button>
          {!isClient && (
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="group flex h-9 w-full min-w-0 max-w-md items-center gap-2.5 rounded-lg border border-slate-200 bg-slate-50/80 px-3 text-sm text-slate-400 transition-colors hover:border-slate-300 hover:bg-white"
          >
            <Search className="size-4" aria-hidden />
            <span className="flex-1 truncate text-start">{t("palette.trigger")}</span>
            <kbd className="hidden rounded-md border border-slate-200 bg-white px-1.5 py-0.5 font-sans text-[11px] font-medium text-slate-500 sm:inline">
              Ctrl K
            </kbd>
          </button>
          )}
          <div className="ms-auto flex items-center gap-2">
            {me.demo_mode && <SyntheticBadge className="hidden md:inline-flex" />}
            <LanguageSwitch />
            {!isClient && <AccountMenu />}
          </div>
        </header>
        {me.demo_mode && (
          <div className="no-print border-b border-amber-200/70 bg-gradient-to-r from-amber-50 via-amber-50/70 to-amber-50 px-6 py-1.5 text-center text-xs text-amber-900">
            {t("app.demoBanner")}
          </div>
        )}
        <main id="main" key={location.pathname} className="mx-auto w-full max-w-[1400px] flex-1 animate-fade-up px-4 py-7 sm:px-8">
          <Outlet />
        </main>
        <footer className="no-print px-8 pb-5 pt-2 text-center text-[11px] text-slate-400">{t("app.footerDisclaimer")}</footer>
      </div>
      {!isClient && <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />}
    </div>
  );
}

function AccountMenu() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const navigate = useNavigate();
  if (!me) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="rounded-full ring-offset-2 transition-shadow hover:ring-2 hover:ring-slate-200" aria-label={t("nav.account")}>
        <Avatar name={me.user.full_name} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <div className="px-2.5 py-2">
          <p className="truncate text-sm font-semibold text-navy-900">{me.user.full_name}</p>
          <p className="truncate text-xs text-slate-500">{me.user.email}</p>
          <p className="mt-1 truncate text-xs text-slate-500">
            {me.org.name} · {t(`roles.${me.role}`)}
          </p>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/settings")}>
          <Settings aria-hidden /> {t("nav.settings")}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate("/activity")}>
          <Activity aria-hidden /> {t("nav.activity")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
