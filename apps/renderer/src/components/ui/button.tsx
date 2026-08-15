import type { ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-40",
  {
    variants: {
      variant: {
        primary: "bg-accent text-white hover:bg-accent/90 shadow-sm",
        secondary: "border border-line bg-panel text-ink hover:bg-panel2",
        ghost: "text-muted hover:bg-panel2 hover:text-ink",
        subtle: "bg-accent/10 text-accent hover:bg-accent/20",
        danger: "bg-danger/10 text-danger hover:bg-danger/20",
        success: "bg-verified/10 text-verified hover:bg-verified/20",
      },
      size: {
        sm: "px-2.5 py-1 text-xs",
        md: "px-3.5 py-2 text-[13px]",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "secondary", size: "sm" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(button({ variant, size }), className)} {...props} />;
}
