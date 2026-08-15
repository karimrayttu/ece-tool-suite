import { useEffect, useRef, useState } from "react";
import { baseUrl, dmmConfig, instrumentCaps, logClear, logExport, logStart, logStatus, logStop, openWs, PROVENANCE_TONE, type DmmReading, type InstrumentCaps, type Provenance } from "../lib/api";
import { downloadCsv, stamp } from "../lib/csv";
import { fmtEng } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { ConnectionBar } from "./ConnectionBar";
import { VendorBadge } from "./VendorBadge";
import { PresetButtons } from "./PresetButtons";

const FUNCTIONS = ["VDC", "VAC", "IDC", "IAC", "RES", "FRES", "FREQ", "CAP", "TEMP", "DIOD", "CONT"];
// Most-used functions get one-click front-panel buttons (with a short label).
const QUICK: [string, string][] = [
  ["VDC", "V⎓"], ["VAC", "V∼"], ["IDC", "A⎓"], ["IAC", "A∼"],
  ["RES", "Ω"], ["FRES", "4WΩ"], ["FREQ", "Hz"], ["CAP", "F"],
  ["DIOD", "▷|"], ["CONT", "•)))"],
];

export function DmmTab() {
  const [base, setBase] = useState<string | null>(null);
  const [reading, setReading] = useState<DmmReading | null>(null);
  const [fn, setFn] = useState("VDC");
  const [caps, setCaps] = useState<InstrumentCaps | null>(null);
  const [range, setRange] = useState("AUTO");
  const [nplc, setNplc] = useState(1);
  const [math, setMath] = useState("OFF");
  const [autozero, setAutozero] = useState(true);
  const histRef = useRef<number[]>([]);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [stats, setStats] = useState<{ min: number; max: number; avg: number } | null>(null);
  const recRef = useRef<{ t: number; v: number }[]>([]);
  const [logActive, setLogActive] = useState(false);
  const [logCount, setLogCount] = useState(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    (async () => {
      const b = await baseUrl();
      if (stop) return;
      setBase(b);
      ws = openWs<DmmReading>(b, "/ws/dmm", (f) => {
        if (stop) return;
        setReading(f);
        if (f.connected && typeof f.value === "number" && isFinite(f.value)) {
          const h = histRef.current;
          h.push(f.value);
          if (h.length > 240) h.shift();
          drawTrend();
          setStats({ min: Math.min(...h), max: Math.max(...h), avg: h.reduce((a, b) => a + b, 0) / h.length });
          recRef.current.push({ t: Date.now(), v: f.value });
          if (recRef.current.length > 200000) recRef.current.shift();
        }
      }, () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);

  function drawTrend() {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const W = (cv.width = cv.clientWidth);
    const H = (cv.height = cv.clientHeight);
    ctx.fillStyle = "#0e1422";
    ctx.fillRect(0, 0, W, H);
    const h = histRef.current;
    if (h.length < 2) return;
    let min = Math.min(...h), max = Math.max(...h);
    const pad = (max - min) * 0.15 || Math.abs(max) * 0.01 || 1;
    min -= pad; max += pad;
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    for (let i = 0; i < h.length; i++) {
      const x = (i / (h.length - 1)) * W;
      const y = H - ((h[i] - min) / (max - min)) * H;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  useEffect(() => {
    let stop = false;
    let id: number | undefined;
    (async () => {
      const b = await baseUrl();
      const tick = async () => {
        const s = await logStatus(b, "dmm");
        if (!stop) { setLogActive(s.active); setLogCount(s.count); }
      };
      await tick();
      id = window.setInterval(tick, 2000);
    })();
    return () => { stop = true; if (id) clearInterval(id); };
  }, []);

  async function toggleLog() {
    if (!base) return;
    if (logActive) { await logStop(base, "dmm"); setLogActive(false); }
    else { await logStart(base, "dmm"); setLogActive(true); }
  }
  async function clearLog() { if (base) { await logClear(base, "dmm"); setLogCount(0); } }

  async function apply(over?: { function?: string; math?: string; autozero?: boolean }) {
    if (!base) return;
    histRef.current = [];
    recRef.current = [];
    setStats(null);
    await dmmConfig(base, {
      function: over?.function ?? fn, range, nplc,
      math: over?.math ?? math, autozero: over?.autozero ?? autozero,
    });
  }
  async function pickFn(f: string) { setFn(f); await apply({ function: f }); }
  async function nullNow() { setMath("NULL"); await apply({ math: "NULL" }); }
  function exportCsv() {
    const rec = recRef.current;
    if (!rec.length) return;
    const t0 = rec[0].t;
    const rows = rec.map((p) => [new Date(p.t).toISOString(), ((p.t - t0) / 1000).toFixed(3), p.v, unit, reading?.function ?? fn]);
    downloadCsv(`dmm_${stamp()}.csv`, ["time_iso", "elapsed_s", "value", "unit", "function"], rows);
  }

  const connected = Boolean(reading?.connected);

  // capability profile of the connected meter (function set, math, NPLC support)
  useEffect(() => {
    (async () => setCaps(await instrumentCaps(await baseUrl(), "dmm")))();
  }, [connected]);
  const prov = reading?.provenance as Provenance | undefined;
  const val = reading?.value;
  const unit = reading?.unit ?? "";

  return (
    <div className="flex flex-col gap-3">
      <ConnectionBar role="dmm" />
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <VendorBadge role="dmm" />
            <CardTitle>Digital Multimeter</CardTitle>
          </div>
          {connected && prov && <Badge tone={PROVENANCE_TONE[prov]}>{prov}</Badge>}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {/* one-click function keys — only what the connected meter's dialect supports */}
          <div className="flex flex-wrap gap-1.5">
            {QUICK.filter(([f]) => !caps?.functions || caps.functions.includes(f)).map(([f, glyph]) => (
              <button key={f} onClick={() => pickFn(f)}
                className={`flex min-w-[52px] flex-col items-center rounded-md border px-2 py-1 ${fn === f ? "border-ks bg-ks/20 text-ks" : "border-line bg-panel text-muted hover:text-ink"}`}>
                <span className="text-sm leading-none">{glyph}</span>
                <span className="text-[10px] uppercase tracking-wide">{f}</span>
              </button>
            ))}
            {caps?.notes && <span className="self-center text-[10.5px] text-muted/80">{caps.family}: {caps.notes}</span>}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-muted">Function
              <select value={fn} onChange={(e) => pickFn(e.target.value)} className="rounded-md border border-line bg-panel px-2 py-1 text-sm text-ink">
                {FUNCTIONS.map((f) => <option key={f}>{f}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted">Range
              <input value={range} onChange={(e) => setRange(e.target.value)} className="w-24 rounded-md border border-line bg-panel px-2 py-1 text-sm text-ink" />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted">NPLC
              <input type="number" value={nplc} step={0.1} onChange={(e) => setNplc(parseFloat(e.target.value))} className="w-20 rounded-md border border-line bg-panel px-2 py-1 text-sm text-ink" />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted">Math
              <select value={math} onChange={(e) => { setMath(e.target.value); apply({ math: e.target.value }); }} className="rounded-md border border-line bg-panel px-2 py-1 text-sm text-ink">
                <option value="OFF">Off</option><option value="NULL">Null (rel)</option>
                <option value="DB">dB</option><option value="DBM">dBm</option>
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-[11px] text-muted">
              <input type="checkbox" checked={autozero} onChange={(e) => { setAutozero(e.target.checked); apply({ autozero: e.target.checked }); }} /> Auto-zero
            </label>
            <button onClick={nullNow} className="rounded-md bg-ks/20 px-2.5 py-1.5 text-xs text-ks hover:bg-ks/30">Null now</button>
            <button onClick={() => apply()} className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90">Apply</button>
            <button onClick={exportCsv} className="rounded-md bg-line px-2.5 py-1.5 text-xs text-ink hover:bg-line/70">Export CSV</button>
          </div>
          <PresetButtons role="dmm" />

          <div className="screen-frame">
          <div className="crt-screen instr-screen px-6 py-8 text-center">
            <div className="seg-readout text-5xl font-medium">
              {connected && typeof val === "number" && isFinite(val) ? `${fmtEng(val, unit)}` : connected ? "— —" : "no DMM"}
            </div>
            <div className="mt-2 text-[11px] uppercase tracking-[0.18em] text-muted">
              {reading?.function ?? fn}
              {math !== "OFF" ? ` · ${math}` : ""}
              {reading?.dialect ? ` · ${reading.dialect === "fluke-legacy" ? "Fluke legacy" : "Keysight/SCPI"}` : ""}
            </div>
          </div>
          </div>

          {stats && (
            <div className="flex flex-wrap gap-5 text-xs text-muted">
              <span>min <span className="font-mono text-ink">{fmtEng(stats.min, unit)}</span></span>
              <span>max <span className="font-mono text-ink">{fmtEng(stats.max, unit)}</span></span>
              <span>avg <span className="font-mono text-ink">{fmtEng(stats.avg, unit)}</span></span>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>Server log:</span>
            <button onClick={toggleLog} className={logActive ? "rounded-md bg-verified/20 px-2.5 py-1 text-verified" : "rounded-md bg-line px-2.5 py-1 text-ink hover:bg-line/70"}>
              {logActive ? "● Recording — Stop" : "Start recording"}
            </button>
            <span className="font-mono text-ink">{logCount} records</span>
            <button onClick={() => base && logExport(base, "dmm")} className="rounded-md bg-line px-2.5 py-1 text-ink hover:bg-line/70">Export server log</button>
            <button onClick={clearLog} className="rounded-md bg-line px-2.5 py-1 text-ink hover:bg-line/70">Clear</button>
          </div>
          <canvas ref={canvasRef} className="h-[140px] w-full rounded-lg border border-line" />
          {!connected && <div className="text-xs text-muted">Connect a Keysight DMM above, then Apply a function.</div>}
        </CardContent>
      </Card>
    </div>
  );
}
