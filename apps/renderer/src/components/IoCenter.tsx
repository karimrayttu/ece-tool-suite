import { CheckCircle2, Cpu, Download, Plug, RefreshCw, Usb, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { baseUrl, ioAutoconnect, ioEnvironment, type IoEnvironment } from "../lib/api";
import { openExternal } from "../lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const AUTO_KEY = "ece.autoconnect";
export const autoConnectEnabled = () => (localStorage.getItem(AUTO_KEY) ?? "1") === "1";

export function IoCenter() {
  const [base, setBase] = useState<string | null>(null);
  const [env, setEnv] = useState<IoEnvironment | null>(null);
  const [auto, setAuto] = useState(autoConnectEnabled());
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const connecting = useRef(false);

  const refresh = useCallback(async (b: string) => {
    const e = await ioEnvironment(b);
    setEnv(e);
    return e;
  }, []);

  const scan = useCallback(async (b: string, manual: boolean) => {
    if (connecting.current) return;
    connecting.current = true;
    try {
      const r = await ioAutoconnect(b, manual);  // manual scan also sweeps the LAN (mDNS/LXI)
      if (r.connected.length) {
        setNote(`Connected: ${r.connected.map((c) => `${c.vendor ?? ""} ${c.role}`).join(", ")}`);
        await refresh(b);
      } else if (manual) {
        const seen = r.detected.filter((d) => d.idn).length;
        setNote(seen ? "Found instruments but none matched a free role." : "No instruments found to connect.");
      }
    } finally {
      connecting.current = false;
    }
  }, [refresh]);

  useEffect(() => {
    let stop = false;
    let id: number | undefined;
    (async () => {
      const b = await baseUrl();
      setBase(b);
      await refresh(b);
      // Refresh the display; the global IoWatcher performs the actual auto-connect.
      id = window.setInterval(() => { if (!stop) refresh(b); }, 5000);
    })();
    return () => { stop = true; if (id) clearInterval(id); };
  }, [refresh]);

  function toggleAuto() {
    const next = !auto;
    setAuto(next);
    localStorage.setItem(AUTO_KEY, next ? "1" : "0");
  }
  async function scanNow() {
    if (!base) return;
    setBusy(true);
    await scan(base, true);
    setBusy(false);
  }

  const backends = env?.backends ?? [];
  const usb = env?.usb_instruments ?? [];
  const recs = env?.recommendations ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Plug className="h-4 w-4 text-accent" /> Instrument I/O</CardTitle>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted">
          <span className="font-medium">Auto-connect</span>
          <button onClick={toggleAuto} role="switch" aria-checked={auto}
            className={`relative h-5 w-9 rounded-full transition-colors ${auto ? "bg-accent" : "bg-line"}`}>
            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${auto ? "left-4" : "left-0.5"}`} />
          </button>
        </label>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {/* VISA drivers status */}
        <div className="flex flex-wrap gap-2">
          {backends.map((b) => (
            <div key={b.backend} className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${b.available ? "border-verified/30 bg-verified/5 text-ink" : "border-line bg-panel2 text-muted"}`}>
              {b.available ? <CheckCircle2 className="h-3.5 w-3.5 text-verified" /> : <XCircle className="h-3.5 w-3.5 text-muted" />}
              {b.label}
            </div>
          ))}
        </div>

        {/* install-software prompts (missing VISA for a plugged-in device) */}
        {recs.map((r, i) => (
          <div key={i} className="rounded-lg border border-unverified/40 bg-unverified/5 p-3">
            <div className="flex items-start gap-2">
              <Download className="mt-0.5 h-4 w-4 shrink-0 text-unverified" />
              <div className="flex flex-col gap-2">
                <div className="text-sm text-ink">{r.reason}</div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="primary" onClick={() => openExternal(r.url)}>
                    <Download className="h-3.5 w-3.5" /> Install {r.software}
                  </Button>
                  {r.alt && (
                    <button onClick={() => openExternal(r.alt!.url)} className="text-xs text-accent underline-offset-2 hover:underline">
                      or {r.alt.software}
                    </button>
                  )}
                  <span className="text-[11px] text-muted">then it auto-connects — no restart needed</span>
                </div>
              </div>
            </div>
          </div>
        ))}

        {/* detected USB instruments */}
        {usb.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">Detected on USB</div>
            {usb.map((d) => (
              <div key={`${d.vid}:${d.pid}`} className="flex items-center gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-sm shadow-sm">
                <Usb className="h-4 w-4 text-accent" />
                <span className="font-medium text-ink">{d.name}</span>
                <span className="rounded bg-ks/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ks">{d.vendor_name}</span>
                <span className="ml-auto font-mono text-[11px] text-muted">{d.vid}:{d.pid}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={scanNow} disabled={busy}>
            <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} /> Scan &amp; connect now
          </Button>
          {env && (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted">
              <Cpu className="h-3.5 w-3.5" />
              {env.ready ? "Ready to drive instruments" : "No VISA layer available"}
              {auto && <span className="text-verified">· watching</span>}
            </span>
          )}
          {note && <span className="text-[11px] text-muted">{note}</span>}
        </div>
      </CardContent>
    </Card>
  );
}
