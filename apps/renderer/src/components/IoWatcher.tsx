import { CheckCircle2, Download, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { baseUrl, ioAutoconnect, ioEnvironment, type IoRecommendation } from "../lib/api";
import { openExternal } from "../lib/utils";
import { autoConnectEnabled } from "./IoCenter";

// Headless-ish: polls the I/O environment on any tab, auto-connects newly plugged-in
// instruments the instant they're drivable, and shows an install prompt (with link) when a
// device is present but the VISA layer isn't.
export function IoWatcher() {
  const [recs, setRecs] = useState<IoRecommendation[]>([]);
  const [justConnected, setJustConnected] = useState<string>("");
  const [dismissed, setDismissed] = useState<string>("");
  const connecting = useRef(false);

  useEffect(() => {
    let stop = false;
    let id: number | undefined;
    (async () => {
      const b = await baseUrl();
      const tick = async () => {
        if (stop) return;
        const env = await ioEnvironment(b);
        setRecs(env.recommendations);
        if (autoConnectEnabled() && env.ready && !connecting.current) {
          connecting.current = true;
          try {
            const r = await ioAutoconnect(b);
            if (r.connected.length) {
              const names = r.connected.map((c) => `${c.vendor ?? ""} → ${c.role}`).join(", ");
              setJustConnected(names);
              window.setTimeout(() => setJustConnected(""), 6000);
            }
          } finally {
            connecting.current = false;
          }
        }
      };
      await tick();
      id = window.setInterval(tick, 5000);
    })();
    return () => { stop = true; if (id) clearInterval(id); };
  }, []);

  const rec = recs.find((r) => r.reason !== dismissed);

  if (!rec && !justConnected) return null;
  return (
    <div className="flex flex-col">
      {rec && (
        <div className="flex flex-wrap items-center gap-3 border-b border-unverified/40 bg-unverified/10 px-5 py-2 text-sm">
          <Download className="h-4 w-4 shrink-0 text-unverified" />
          <span className="text-ink">{rec.reason}</span>
          <button onClick={() => openExternal(rec.url)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1 text-xs font-semibold text-white shadow-sm hover:bg-accent/90">
            <Download className="h-3.5 w-3.5" /> Install {rec.software}
          </button>
          {rec.alt && (
            <button onClick={() => openExternal(rec.alt!.url)} className="text-xs text-accent underline-offset-2 hover:underline">
              or {rec.alt.software}
            </button>
          )}
          <span className="text-[11px] text-muted">then it auto-connects — no restart</span>
          <button onClick={() => setDismissed(rec.reason)} className="ml-auto text-muted hover:text-ink" aria-label="Dismiss">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {justConnected && (
        <div className="flex items-center gap-2 border-b border-verified/40 bg-verified/10 px-5 py-2 text-sm text-ink">
          <CheckCircle2 className="h-4 w-4 text-verified" />
          Auto-connected: <span className="font-medium capitalize">{justConnected}</span>
        </div>
      )}
    </div>
  );
}
