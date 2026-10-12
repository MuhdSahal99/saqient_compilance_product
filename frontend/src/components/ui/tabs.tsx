import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Underline tabs with ARIA roles. Selection is controlled by the caller (often the URL). */
export function Tabs<K extends string>({
  value,
  onChange,
  items,
  label,
  className,
}: {
  value: K;
  onChange: (k: K) => void;
  items: { key: K; label: ReactNode; count?: number }[];
  label: string;
  className?: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={cn("flex gap-1 overflow-x-auto border-b border-slate-200", className)}>
      {items.map((it) => (
        <button
          key={it.key}
          role="tab"
          type="button"
          aria-selected={value === it.key}
          onClick={() => onChange(it.key)}
          className={cn(
            "relative -mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
            value === it.key ? "border-teal-600 text-navy-900" : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800",
          )}
        >
          {it.label}
          {it.count !== undefined && (
            <span
              className={cn(
                "rounded-full px-1.5 py-px text-[11px] tabular-nums",
                value === it.key ? "bg-teal-50 text-teal-700" : "bg-slate-100 text-slate-500",
              )}
            >
              {it.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
