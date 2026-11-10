import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset whitespace-nowrap", {
  variants: {
    tone: {
      slate: "bg-slate-50 text-slate-600 ring-slate-200",
      teal: "bg-teal-50 text-teal-700 ring-teal-200",
      amber: "bg-amber-50 text-amber-800 ring-amber-200",
      rose: "bg-rose-50 text-rose-700 ring-rose-200",
      violet: "bg-violet-50 text-violet-700 ring-violet-200",
      sky: "bg-sky-50 text-sky-700 ring-sky-200",
      navy: "bg-navy-800 text-teal-200 ring-navy-600",
    },
  },
  defaultVariants: { tone: "slate" },
});
export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}
export const Badge = ({ className, tone, ...p }: BadgeProps) => <span className={cn(badgeVariants({ tone }), className)} {...p} />;
