import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset",
  {
    variants: {
      tone: {
        neutral: "bg-slate-50 text-slate-700 ring-slate-200",
        navy: "bg-indigo-50 text-indigo-700 ring-indigo-200/70",
        teal: "bg-teal-50 text-teal-800 ring-teal-200/80",
        amber: "bg-amber-50 text-amber-800 ring-amber-200/80",
        orange: "bg-orange-50 text-orange-800 ring-orange-200/80",
        red: "bg-red-50 text-red-700 ring-red-200/80",
        green: "bg-emerald-50 text-emerald-700 ring-emerald-200/80",
        violet: "bg-violet-50 text-violet-700 ring-violet-200/80",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

const DOT: Record<NonNullable<VariantProps<typeof badgeVariants>["tone"]>, string> = {
  neutral: "bg-slate-400",
  navy: "bg-indigo-500",
  teal: "bg-teal-500",
  amber: "bg-amber-500",
  orange: "bg-orange-500",
  red: "bg-red-500",
  green: "bg-emerald-500",
  violet: "bg-violet-500",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  /** Show a small coloured status dot before the label. */
  dot?: boolean;
}

export function Badge({ className, tone, dot, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {dot && <span className={cn("size-1.5 shrink-0 rounded-full", DOT[tone ?? "neutral"])} aria-hidden />}
      {children}
    </span>
  );
}
