import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function openExternal(url: string): void {
  // Prefer the OS browser (Electron), fall back to a new tab.
  if (window.ece?.openExternal) window.ece.openExternal(url);
  else window.open(url, "_blank", "noreferrer");
}

export function fmtEng(value: number, unit: string): string {
  const abs = Math.abs(value);
  const table: [number, string][] = [
    [1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"],
  ];
  for (const [scale, prefix] of table) {
    if (abs >= scale) return `${(value / scale).toFixed(3)} ${prefix}${unit}`;
  }
  return `${value.toExponential(2)} ${unit}`;
}
