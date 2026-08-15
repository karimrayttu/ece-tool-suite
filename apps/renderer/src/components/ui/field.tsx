import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

const inputCls =
  "w-full rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm text-ink shadow-sm outline-none transition-colors placeholder:text-muted/50 focus:border-accent focus:ring-2 focus:ring-accent/20";

export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("text-[11px] font-medium uppercase tracking-wide text-muted", className)}>{children}</span>
  );
}

export function Field({ label, children, className }: { label?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn("flex flex-col gap-1", className)}>
      {label && <Label>{label}</Label>}
      {children}
    </label>
  );
}

export function TextField({ label, className, wrapClassName, ...props }:
  InputHTMLAttributes<HTMLInputElement> & { label?: ReactNode; wrapClassName?: string }) {
  return (
    <Field label={label} className={wrapClassName}>
      <input className={cn(inputCls, "font-mono", className)} {...props} />
    </Field>
  );
}

export function NumberField({ label, value, onValue, step = 1, className, wrapClassName }:
  { label?: ReactNode; value: number; onValue: (n: number) => void; step?: number | "any"; className?: string; wrapClassName?: string }) {
  return (
    <Field label={label} className={wrapClassName}>
      <input
        type="number"
        step={step}
        value={value}
        onChange={(e) => { const n = parseFloat(e.target.value); if (!Number.isNaN(n)) onValue(n); }}
        className={cn(inputCls, "font-mono tabular-nums", className)}
      />
    </Field>
  );
}

// Compact instrument-panel variant: bare label above a fixed-width numeric input.
export function NumField({ label, value, set, step = 0.1, width = "w-24" }:
  { label: string; value: number; set: (n: number) => void; step?: number; width?: string }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-muted">
      {label}
      <input type="number" step={step} value={value} onChange={(e) => set(parseFloat(e.target.value))}
        className={`${width} rounded-md border border-line bg-panel px-2 py-1 font-mono text-xs text-ink`} />
    </label>
  );
}

export function SelectField({ label, className, wrapClassName, children, ...props }:
  SelectHTMLAttributes<HTMLSelectElement> & { label?: ReactNode; wrapClassName?: string }) {
  return (
    <Field label={label} className={wrapClassName}>
      <select className={cn(inputCls, "cursor-pointer", className)} {...props}>{children}</select>
    </Field>
  );
}

export function Segmented<T extends string>({ value, onChange, options, className }:
  { value: T; onChange: (v: T) => void; options: readonly (T | { value: T; label: string })[]; className?: string }) {
  const norm = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  return (
    <div className={cn("inline-flex overflow-hidden rounded-lg border border-line bg-panel", className)}>
      {norm.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "px-2.5 py-1.5 text-xs font-medium transition-colors",
            value === o.value ? "bg-accent text-white" : "text-muted hover:bg-panel2 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
