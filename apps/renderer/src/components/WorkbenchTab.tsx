import { RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  baseUrl, ioAutoconnect, openWs,
  type DmmReading, type SaFrame, type ScopeFrame,
} from "../lib/api";
import { drawTrace } from "../lib/canvas";
import { fmtEng } from "../lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { ConnectionBar } from "./ConnectionBar";

const CH_COLORS: Record<number, string> = { 1: "#EAB308", 2: "#16A34A", 3: "#0EA5E9", 4: "#DB2777" };

function LiveTag({ on }: { on: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs ${on ? "text-verified" : "text-muted"}`}>
      <span className={`h-2 w-2 rounded-full ${on ? "bg-verified" : "bg-line"}`} />
      {on ? "live" : "offline"}
    </span>
  );
}

// Each mini opens its OWN websocket, so scope + DMM + spectrum all stream at the same time.
function ScopeMini() {
  const cv = useRef<HTMLCanvasElement | null>(null);
  const [on, setOn] = useState(false);
  useEffect(() => {
    let ws: WebSocket | null = null, stop = false;
    (async () => {
      const b = await baseUrl();
      ws = openWs<ScopeFrame>(b, "/ws/scope", (f) => {
        if (stop) return;
        setOn(Boolean(f.connected));
        const c = cv.current; if (!c) return;
        const ctx = c.getContext("2d"); if (!ctx) return;
        const W = (c.width = c.clientWidth), H = (c.height = c.clientHeight);
        ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
        ctx.strokeStyle = "#17324a";
        for (let i = 0; i <= 10; i++) { const x = (i / 10) * W; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
        for (let i = 0; i <= 6; i++) { const y = (i / 6) * H; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
        for (const ch of f.channels ?? []) {
          const v = ch.v; if (!v?.length) continue;
          drawTrace(ctx, v, W, H, CH_COLORS[ch.ch] ?? "#fff");
        }
      }, () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);
  return (
    <Card>
      <CardHeader><CardTitle>Oscilloscope</CardTitle><LiveTag on={on} /></CardHeader>
      <CardContent><ConnectionBar role="scope" /><canvas ref={cv} className="mt-2 h-[150px] w-full rounded-lg border border-line bg-black" /></CardContent>
    </Card>
  );
}

function DmmMini() {
  const [r, setR] = useState<DmmReading | null>(null);
  useEffect(() => {
    let ws: WebSocket | null = null, stop = false;
    (async () => {
      const b = await baseUrl();
      ws = openWs<DmmReading>(b, "/ws/dmm", (f) => { if (!stop) setR(f); }, () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);
  const on = Boolean(r?.connected), val = r?.value, unit = r?.unit ?? "";
  return (
    <Card>
      <CardHeader><CardTitle>Multimeter</CardTitle><LiveTag on={on} /></CardHeader>
      <CardContent>
        <ConnectionBar role="dmm" />
        <div className="instr-screen mt-2 flex h-[150px] flex-col items-center justify-center rounded-lg border border-screenline bg-screen">
          <div className="font-mono text-4xl font-medium tabular-nums text-ch2 [text-shadow:0_0_12px_rgba(22,163,74,0.35)]">
            {on && typeof val === "number" && isFinite(val) ? fmtEng(val, unit) : on ? "— —" : "no DMM"}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">{r?.function ?? ""}</div>
        </div>
      </CardContent>
    </Card>
  );
}

function SaMini() {
  const cv = useRef<HTMLCanvasElement | null>(null);
  const [on, setOn] = useState(false);
  useEffect(() => {
    let ws: WebSocket | null = null, stop = false;
    (async () => {
      const b = await baseUrl();
      ws = openWs<SaFrame>(b, "/ws/sa", (f) => {
        if (stop) return;
        setOn(Boolean(f.connected));
        const c = cv.current; if (!c) return;
        const ctx = c.getContext("2d"); if (!ctx) return;
        const W = (c.width = c.clientWidth), H = (c.height = c.clientHeight);
        ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
        ctx.strokeStyle = "#17324a";
        for (let i = 0; i <= 10; i++) { const x = (i / 10) * W; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
        const a = f.amps; if (!a?.length) return;
        // dBm trace: 10% pad, and a 5 dB floor when the span is flat.
        drawTrace(ctx, a, W, H, "#16A34A", 0.1, 5);
      }, () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);
  return (
    <Card>
      <CardHeader><CardTitle>Spectrum</CardTitle><LiveTag on={on} /></CardHeader>
      <CardContent><ConnectionBar role="sa" /><canvas ref={cv} className="mt-2 h-[150px] w-full rounded-lg border border-line bg-black" /></CardContent>
    </Card>
  );
}

export function WorkbenchTab() {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  async function connectAll() {
    setBusy(true);
    const b = await baseUrl();
    const r = await ioAutoconnect(b, true);
    setNote(r.connected.length ? `Connected ${r.connected.length}: ${r.connected.map((c) => `${c.vendor ?? ""} ${c.role}`).join(", ")}` : "No new instruments matched a free role.");
    setBusy(false);
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-panel">
        <div>
          <div className="text-sm font-semibold text-ink">Workbench</div>
          <div className="text-xs text-muted">Scope, multimeter and spectrum analyzer streaming together — connect any combination at once.</div>
        </div>
        <Button variant="primary" size="md" className="ml-auto" onClick={connectAll} disabled={busy}>
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} /> Auto-connect all
        </Button>
        {note && <span className="w-full text-[11px] text-muted">{note}</span>}
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <ScopeMini />
        <DmmMini />
        <SaMini />
      </div>
    </div>
  );
}
