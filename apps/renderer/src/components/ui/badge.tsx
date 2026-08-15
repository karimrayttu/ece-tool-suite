import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badge = cva(
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold",
  {
    variants: {
      tone: {
        sim: "bg-sim text-bg",
        unverified: "bg-unverified text-bg",
        verified: "bg-verified text-bg",
        muted: "bg-line text-muted",
        accent: "bg-accent text-bg",
        danger: "bg-danger text-bg",
      },
    },
    defaultVariants: { tone: "muted" },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badge> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}
