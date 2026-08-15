import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

// Module panel: a rack unit — dark surface, faint top edge-light, deep drop shadow.
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl2 border border-line bg-panel shadow-panel", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-b border-line/70 px-5 py-3",
        className,
      )}
      {...props}
    />
  );
}

// Diva-style module title: small-caps, letter-spaced, with a neon tick.
export function CardTitle({ className, children, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn(
        "flex items-center gap-2 text-[11.5px] font-semibold uppercase tracking-[0.12em] text-ink/90",
        className,
      )}
      {...props}
    >
      <span className="h-3 w-[3px] rounded-full bg-accent shadow-glow-cyan" aria-hidden />
      {children}
    </h3>
  );
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 py-4", className)} {...props} />;
}
