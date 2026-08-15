import { Waves } from "lucide-react";
import type { Health } from "../lib/api";
import { Led } from "./ui/instrument";

export function ProvenanceBar({ health }: { health: Health | null }) {
  const insts = health ? Object.values(health.instruments) : [];
  const nConnected = insts.filter((i) => i.connected).length;
  const verified = Boolean(health?.hardware_connected);

  const state = verified
    ? { led: "green" as const, tone: "text-verified", label: "VERIFIED HW",
        msg: "Live instruments confirmed via *IDN? + read-back." }
    : nConnected > 0
      ? { led: "amber" as const, tone: "text-unverified", label: `${nConnected} CONNECTED`,
          msg: "Verify each instrument to confirm it's really there." }
      : { led: "cyan" as const, tone: "text-muted", label: "STANDBY",
          msg: "Connect a scope, DMM or analyzer to begin." };

  return (
    <header className="grille flex items-center gap-4 border-b border-line bg-panel px-5 py-2.5 shadow-panel">
      <div className="flex items-center gap-2.5">
        <div
          className="grid h-8 w-8 place-items-center rounded-lg border border-accent/40 bg-gradient-to-br from-[#10202a] to-[#0a1016] text-accent"
          style={{ boxShadow: "0 0 10px rgba(45,212,234,0.25), inset 0 1px 0 rgba(255,255,255,0.06)" }}
        >
          <Waves className="h-4.5 w-4.5" strokeWidth={2.25} />
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight text-ink">ECE Tool Suite</div>
          <div className="text-[10px] font-medium uppercase tracking-[0.22em] text-muted">Bench &amp; Design Rack</div>
        </div>
      </div>

      <div className={`ml-3 inline-flex items-center gap-2 rounded-md border border-line bg-panel2 px-2.5 py-1.5 text-[11px] font-semibold tracking-wider ${state.tone}`}>
        <Led color={state.led} on breathe={!verified && nConnected === 0} />
        {state.label}
      </div>
      <span className="hidden text-[12.5px] text-muted md:inline">{state.msg}</span>

      <div className="ml-auto flex items-center gap-3 text-xs text-muted">
        <span className="hidden font-mono text-[11px] lg:inline">VISA · Keysight IO Libs / pyvisa-py</span>
        <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-panel2 px-2 py-1 font-mono text-[11px]">
          <Led color={health ? "green" : "amber"} on breathe={!health} />
          {health ? `backend v${health.version}` : "connecting…"}
        </span>
      </div>
    </header>
  );
}
