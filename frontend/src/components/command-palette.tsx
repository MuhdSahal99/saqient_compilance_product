import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import {
  CalculatorIcon,
  Activity,
  Building,
  CalendarClock,
  ClipboardCheck,
  CornerDownLeft,
  FileCode,
  FileSearch,
  FileText,
  FolderOpen,
  LayoutDashboard,
  ListChecks,
  Loader2,
  Scale,
  Search,
  Settings,
  SquareCheckBig,
  Table2,
  Upload,
} from "lucide-react";
import { api, qs } from "@/lib/api";
import type { DocumentSummary, Finding, Page, Review } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useDebounced } from "./common";

const PAGES = [
  { to: "/", key: "overview", icon: LayoutDashboard },
  { to: "/reviews", key: "reviews", icon: ClipboardCheck },
  { to: "/documents", key: "documents", icon: FolderOpen },
  { to: "/checklists", key: "checklists", icon: ListChecks },
  { to: "/datasets", key: "datasets", icon: Table2 },
  { to: "/einvoices", key: "einvoices", icon: FileCode },
  { to: "/workpapers", key: "directTax", icon: CalculatorIcon },
  { to: "/entities", key: "entities", icon: Building },
  { to: "/rule-packs", key: "rulePacks", icon: Scale },
  { to: "/findings", key: "findings", icon: FileSearch },
  { to: "/tasks", key: "tasks", icon: SquareCheckBig },
  { to: "/tax-calendar", key: "taxCalendar", icon: CalendarClock },
  { to: "/reports", key: "reports", icon: FileText },
  { to: "/activity", key: "activity", icon: Activity },
  { to: "/settings", key: "settings", icon: Settings },
] as const;

/** Open the palette with Ctrl+K / Cmd+K or "/" outside text fields. */
// eslint-disable-next-line react-refresh/only-export-components
export function useCommandPaletteShortcut(open: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = !!target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        open();
      } else if (e.key === "/" && !typing) {
        e.preventDefault();
        open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
}

const itemCls =
  "flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-700 data-[selected=true]:bg-slate-100 data-[selected=true]:text-navy-950 [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-slate-400";
const groupCls =
  "px-2 pb-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-slate-400";

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [query, setQuery] = useState("");
  const q = useDebounced(query.trim(), 200);
  const enabled = open && q.length >= 2;

  const reviews = useQuery({
    queryKey: ["palette", "reviews", q],
    queryFn: () => api<Page<Review>>(`/reviews${qs({ q, page_size: 5 })}`),
    enabled,
  });
  const documents = useQuery({
    queryKey: ["palette", "documents", q],
    queryFn: () => api<Page<DocumentSummary>>(`/documents${qs({ q, page_size: 5 })}`),
    enabled,
  });
  const findings = useQuery({
    queryKey: ["palette", "findings", q],
    queryFn: () => api<Page<Finding>>(`/findings${qs({ q, page_size: 5 })}`),
    enabled,
  });
  const searching = enabled && (reviews.isFetching || documents.isFetching || findings.isFetching);

  const go = (to: string) => {
    setQuery("");
    onOpenChange(false);
    navigate(to);
  };

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(o) => {
        if (!o) setQuery("");
        onOpenChange(o);
      }}
    >
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-navy-950/30 backdrop-blur-[2px] data-[state=open]:animate-fade-in" />
        <DialogPrimitive.Content
          className="fixed inset-x-4 top-[12vh] z-50 mx-auto max-w-xl overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-pop data-[state=open]:animate-scale-in"
          aria-describedby={undefined}
        >
          <DialogPrimitive.Title className="sr-only">{t("palette.title")}</DialogPrimitive.Title>
          <Command shouldFilter={!enabled} loop label={t("palette.title")}>
            <div className="flex items-center gap-3 border-b border-slate-100 px-4">
              {searching ? (
                <Loader2 className="size-4 animate-spin text-teal-600" aria-hidden />
              ) : (
                <Search className="size-4 text-slate-400" aria-hidden />
              )}
              <Command.Input
                value={query}
                onValueChange={setQuery}
                placeholder={t("palette.placeholder")}
                className="h-12 flex-1 bg-transparent text-[15px] text-navy-950 outline-none placeholder:text-slate-400"
              />
              <kbd className="rounded-md border border-slate-200 px-1.5 py-0.5 text-[11px] text-slate-400">Esc</kbd>
            </div>
            <Command.List className="max-h-[min(60vh,420px)] overflow-y-auto py-1">
              <Command.Empty className="px-4 py-10 text-center text-sm text-slate-500">
                {searching ? t("common.loading") : t("palette.noResults")}
              </Command.Empty>
              {enabled && (reviews.data?.items.length ?? 0) > 0 && (
                <Command.Group heading={t("nav.reviews")} className={groupCls}>
                  {reviews.data!.items.map((r) => (
                    <Command.Item key={r.id} value={`review-${r.id}`} onSelect={() => go(`/reviews/${r.id}`)} className={itemCls}>
                      <ClipboardCheck aria-hidden />
                      <span className="flex-1 truncate">{r.title}</span>
                      <span className="truncate text-xs text-slate-400">{r.document_title ?? r.datasets[0]?.dataset_name}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {enabled && (documents.data?.items.length ?? 0) > 0 && (
                <Command.Group heading={t("nav.documents")} className={groupCls}>
                  {documents.data!.items.map((d) => (
                    <Command.Item key={d.id} value={`doc-${d.id}`} onSelect={() => go(`/documents/${d.id}`)} className={itemCls}>
                      <FolderOpen aria-hidden />
                      <span className="flex-1 truncate">{d.title}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {enabled && (findings.data?.items.length ?? 0) > 0 && (
                <Command.Group heading={t("nav.findings")} className={groupCls}>
                  {findings.data!.items.map((f) => (
                    <Command.Item
                      key={f.id}
                      value={`finding-${f.id}`}
                      onSelect={() => go(`/reviews/${f.review_id}?finding=${f.id}`)}
                      className={itemCls}
                    >
                      <FileSearch aria-hidden />
                      <span className="flex-1 truncate">{f.title}</span>
                      <span className="truncate text-xs text-slate-400">{f.review_title}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
              {!enabled && (
                <>
                  {can("write") && (
                    <Command.Group heading={t("palette.actions")} className={groupCls}>
                      <Command.Item value={t("upload.title")} onSelect={() => go("/documents?upload=1")} className={itemCls}>
                        <Upload aria-hidden />
                        {t("upload.title")}
                      </Command.Item>
                      <Command.Item value={t("reviews.new")} onSelect={() => go("/reviews?new")} className={itemCls}>
                        <ClipboardCheck aria-hidden />
                        {t("reviews.new")}
                      </Command.Item>
                    </Command.Group>
                  )}
                  <Command.Group heading={t("palette.goTo")} className={groupCls}>
                    {PAGES.map(({ to, key, icon: Icon }) => (
                      <Command.Item key={to} value={t(`nav.${key}`)} onSelect={() => go(to)} className={itemCls}>
                        <Icon aria-hidden />
                        {t(`nav.${key}`)}
                      </Command.Item>
                    ))}
                  </Command.Group>
                </>
              )}
            </Command.List>
            <div className="flex items-center gap-4 border-t border-slate-100 bg-slate-50/70 px-4 py-2 text-[11px] text-slate-500">
              <span className="flex items-center gap-1">
                <kbd className="rounded border border-slate-200 bg-white px-1">↑</kbd>
                <kbd className="rounded border border-slate-200 bg-white px-1">↓</kbd>
                {t("palette.navigate")}
              </span>
              <span className="flex items-center gap-1">
                <kbd className="rounded border border-slate-200 bg-white px-1">
                  <CornerDownLeft className="inline size-3" aria-hidden />
                </kbd>
                {t("palette.open")}
              </span>
              <span className="ms-auto">{t("palette.hint")}</span>
            </div>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
