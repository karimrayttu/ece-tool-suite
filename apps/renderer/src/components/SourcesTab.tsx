import { useState } from "react";
import { cn } from "../lib/utils";
import { EloadPanel } from "./EloadPanel";
import { FuncGenPanel } from "./FuncGenPanel";
import { PsuPanel } from "./PsuPanel";

const SUBS = [
  { key: "psu", label: "Power Supply" },
  { key: "awg", label: "Function Gen" },
  { key: "eload", label: "Electronic Load" },
];

export function SourcesTab() {
  const [sub, setSub] = useState("psu");
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2 border-b border-line pb-2">
        {SUBS.map((s) => (
          <button
            key={s.key}
            onClick={() => setSub(s.key)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm",
              sub === s.key ? "bg-panel text-ink shadow-panel" : "text-muted hover:text-ink",
            )}
          >
            {s.label}
          </button>
        ))}
      </div>
      {sub === "psu" && <PsuPanel />}
      {sub === "awg" && <FuncGenPanel />}
      {sub === "eload" && <EloadPanel />}
    </div>
  );
}
