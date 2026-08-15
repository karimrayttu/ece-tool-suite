import { useEffect, useState } from "react";
import { baseUrl, getHealth, PROVENANCE_TONE, type Health, type Provenance } from "../lib/api";
import { AgentPanel } from "./AgentPanel";
import { IoCenter } from "./IoCenter";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

export function SystemTab() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let stop = false;
    let id: number | undefined;
    (async () => {
      const base = await baseUrl();
      const tick = async () => {
        const h = await getHealth(base);
        if (!stop) setHealth(h);
      };
      await tick();
      id = window.setInterval(tick, 2000);
    })();
    return () => { stop = true; if (id) clearInterval(id); };
  }, []);

  const insts = health ? Object.entries(health.instruments) : [];
  const nConnected = insts.filter(([, s]) => s.connected).length;
  const nVerified = insts.filter(([, s]) => s.provenance === "VERIFIED_HW").length;

  const stats: { label: string; value: string; tone?: string }[] = [
    { label: "Connected", value: `${nConnected} / ${insts.length}` },
    { label: "Verified HW", value: String(nVerified), tone: nVerified ? "text-verified" : "text-muted" },
    { label: "Mode", value: health?.mode ?? "—" },
    { label: "Backend", value: health ? `v${health.version}` : "…" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <IoCenter />
      <Card>
        <CardHeader>
          <CardTitle>System overview</CardTitle>
          <span className="text-xs text-muted">live · refreshes every 2 s</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {stats.map((s) => (
              <div key={s.label} className="rounded-lg border border-line bg-panel2/60 px-3 py-2.5">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{s.label}</div>
                <div className={`mt-0.5 text-lg font-semibold capitalize ${s.tone ?? "text-ink"}`}>{s.value}</div>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
            {insts.map(([role, s]) => (
              <div key={role} className="flex items-center justify-between rounded-lg border border-line bg-panel px-3 py-2.5 shadow-sm">
                <div className="flex min-w-0 flex-col">
                  <span className="flex items-center gap-2 text-sm font-medium capitalize text-ink">
                    {role}
                    {s.vendor && s.vendor !== "unknown" && (
                      <span className="rounded bg-ks/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ks">{s.vendor}</span>
                    )}
                  </span>
                  <span className="truncate font-mono text-[11px] text-muted">{s.resource ?? "not connected"}</span>
                </div>
                {s.connected
                  ? <Badge tone={s.provenance ? PROVENANCE_TONE[s.provenance as Provenance] : "unverified"}>{s.provenance ?? "connected"}</Badge>
                  : <Badge tone="muted">disconnected</Badge>}
              </div>
            ))}
            {insts.length === 0 && <div className="text-xs text-muted">connecting…</div>}
          </div>
        </CardContent>
      </Card>
      <AgentPanel />
    </div>
  );
}
