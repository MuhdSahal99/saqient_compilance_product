import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "border-slate-200 bg-slate-100 text-slate-700",
        navy: "border-navy-200 bg-navy-50 text-navy-800",
        teal: "border-teal-200 bg-teal-50 text-teal-800",
        amber: "border-amber-300 bg-amber-50 text-amber-900",
        red: "border-red-200 bg-red-50 text-red-800",
        green: "border-emerald-200 bg-emerald-50 text-emerald-800",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
