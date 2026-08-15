import type { Health } from "../lib/api";
import { Led } from "./ui/instrument";

function Item({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-muted">
      {label}: <span className="font-mono text-ink/90">{value}</span>
    </span>
  );
}

export function StatusBar({ health }: { health: Health | null }) {
  const insts = health ? Object.values(health.instruments) : [];
  const n = insts.filter((i) => i.connected).length;
  const hw = health?.hardware_connected ? "verified" : n > 0 ? "connected (unverified)" : "none";
  return (
    <footer className="flex items-center gap-5 border-t border-line bg-panel2 px-4 py-1.5 text-[11.5px]">
      <span className="inline-flex items-center gap-1.5">
        <Led color={health ? "green" : "red"} on breathe={!health} />
        <Item label="backend" value={health ? `v${health.version} ok` : "connecting…"} />
      </span>
      <Item label="mode" value={health?.mode ?? "—"} />
      <Item label="connected" value={String(n)} />
      <span className="inline-flex items-center gap-1.5">
        <Led color={health?.hardware_connected ? "green" : n > 0 ? "amber" : "cyan"} on={Boolean(health)} />
        <Item label="hardware" value={hw} />
      </span>
      <span className="ml-auto font-mono text-[10.5px] uppercase tracking-wider text-muted/80">
        VISA: Keysight IO Libraries / pyvisa-py
      </span>
    </footer>
  );
}
