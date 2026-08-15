import { useEffect, useRef, useState } from "react";
import { baseUrl, openWs, saConfig, type SaFrame } from "../lib/api";
import { downloadCanvasPng, downloadCsv, stamp } from "../lib/csv";
import { fmtEng } from "../lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { NumField } from "./ui/field";
import { ConnectionBar } from "./ConnectionBar";
import { VendorBadge } from "./VendorBadge";
import { PresetButtons } from "./PresetButtons";
import { ScreenshotButton } from "./ScreenshotButton";

export function SaTab() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [base, setBase] = useState<string | null>(null);
  const [frame, setFrame] = useState<SaFrame | null>(null);
  const [center, setCenter] = useState(100e6);
  const [span, setSpan] = useState(10e6);
  const [rbw, setRbw] = useState(100e3);
  const [vbw, setVbw] = useState(100e3);
  const [ref, setRef] = useState(0);
  const [atten, setAtten] = useState(10);
  const [preamp, setPreamp] = useState(false);
  const [averages, setAverages] = useState(10);
  const [traceMode, setTraceMode] = useState("WRITE");
  const [detector, setDetector] = useState("NORM");

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    (async () => {
      const b = await baseUrl();
      if (stop) return;
      setBase(b);
      ws = openWs<SaFrame>(b, "/ws/sa", (f) => {
        if (stop) return;
        setFrame(f);
        draw(f);
      }, () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);

  function draw(f: SaFrame) {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth, H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#04070b";
    ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = "#152232";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 10; i++) { const x = Math.round((i / 10) * W) + 0.5; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
    for (let i = 0; i <= 8; i++) { const y = Math.round((i / 8) * H) + 0.5; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
    const amps = f.amps;
    if (!f.connected || !amps?.length) return;
    let min = Math.min(...amps), max = Math.max(...amps);
    const pad = (max - min) * 0.1 || 5;
    min -= pad; max += pad;
    // violet RF trace: gradient area fill under the curve + 3-pass glow stroke
    const path = new Path2D();
    for (let i = 0; i < amps.length; i++) {
      const x = (i / (amps.length - 1)) * W;
      const y = H - ((amps[i] - min) / (max - min)) * H;
      i === 0 ? path.moveTo(x, y) : path.lineTo(x, y);
    }
    const area = new Path2D(path);
    area.lineTo(W, H); area.lineTo(0, H); area.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, "rgba(167,139,250,0.28)");
    grad.addColorStop(1, "rgba(167,139,250,0.02)");
    ctx.fillStyle = grad;
    ctx.fill(area);
    ctx.strokeStyle = "#a78bfa";
    ctx.lineJoin = "round";
    ctx.globalAlpha = 0.14; ctx.lineWidth = 6; ctx.stroke(path);
    ctx.globalAlpha = 0.4;  ctx.lineWidth = 2.6; ctx.stroke(path);
    ctx.globalAlpha = 1;    ctx.lineWidth = 1.3; ctx.stroke(path);
  }

  async function apply() {
    if (!base) return;
    await saConfig(base, {
      center, span, rbw, vbw, ref_level: ref, atten, preamp, averages,
      trace_mode: traceMode, detector,
    });
  }
  async function push(cfg: Parameters<typeof saConfig>[1]) { if (base) await saConfig(base, cfg); }
  function exportCsv() {
    const freqs = frame?.freqs;
    const amps = frame?.amps;
    if (!freqs?.length || !amps?.length) return;
    const rows = freqs.map((fr, i) => [fr, amps[i] ?? ""]);
    downloadCsv(`spectrum_${stamp()}.csv`, ["freq_hz", "amp_dbm"], rows);
  }
  function savePng() { downloadCanvasPng(canvasRef.current, `spectrum_${stamp()}.png`); }

  const connected = Boolean(frame?.connected);
  const peak = frame?.peak;

  return (
    <div className="flex flex-col gap-3">
      <ConnectionBar role="sa" />
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <VendorBadge role="sa" />
            <CardTitle>Spectrum Analyzer</CardTitle>
          </div>
          <span className={connected ? "text-xs text-verified" : "text-xs text-muted"}>{connected ? "● live" : "○ not connected"}</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="crt-screen relative h-[300px]">
            <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
          </div>
          {/* trace mode + detector quick controls (live-apply) */}
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted">
            <span>Trace:</span>
            {["WRITE", "MAXHOLD", "MINHOLD", "AVERAGE"].map((m) => (
              <button key={m} onClick={() => { setTraceMode(m); push({ trace_mode: m }); }}
                className={`rounded px-2 py-0.5 ${traceMode === m ? "bg-ks text-black font-semibold" : "bg-line text-muted hover:text-ink"}`}>{m}</button>
            ))}
            <label className="ml-2 flex items-center gap-1">Detector
              <select value={detector} onChange={(e) => { setDetector(e.target.value); push({ detector: e.target.value }); }} className="rounded border border-line bg-panel px-1.5 py-0.5 text-ink">
                {["NORM", "POS", "NEG", "SAMP", "AVER", "RMS"].map((d) => <option key={d}>{d}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={preamp} onChange={(e) => { setPreamp(e.target.checked); push({ preamp: e.target.checked }); }} /> Preamp
            </label>
          </div>
          {peak && peak.amp != null && (
            <div className="text-xs text-muted">
              Peak marker: <span className="font-mono text-ink">{peak.freq != null ? fmtEng(peak.freq, "Hz") : "—"}</span>{" "}
              @ <span className="font-mono text-ink">{peak.amp.toFixed(2)} dBm</span>
            </div>
          )}
          <div className="flex flex-wrap items-end gap-3">
            <NumField label="Center (Hz)" value={center} set={setCenter} step={1e6} width="w-28" />
            <NumField label="Span (Hz)" value={span} set={setSpan} step={1e6} width="w-28" />
            <NumField label="RBW (Hz)" value={rbw} set={setRbw} step={1e3} width="w-28" />
            <NumField label="VBW (Hz)" value={vbw} set={setVbw} step={1e3} width="w-28" />
            <NumField label="Ref level (dBm)" value={ref} set={setRef} step={1} width="w-28" />
            <NumField label="Atten (dB)" value={atten} set={setAtten} step={1} width="w-28" />
            <NumField label="Averages" value={averages} set={setAverages} step={1} width="w-28" />
            <button onClick={apply} className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90">Apply</button>
            <button onClick={exportCsv} className="rounded-md bg-line px-2.5 py-1.5 text-xs text-ink hover:bg-line/70">Export CSV</button>
            <button onClick={savePng} className="rounded-md bg-line px-2.5 py-1.5 text-xs text-ink hover:bg-line/70">Save PNG</button>
          </div>
          <PresetButtons role="sa" />
          <ScreenshotButton role="sa" />
          {!connected && <div className="text-xs text-muted">Connect a Keysight signal analyzer above, then Apply settings.</div>}
        </CardContent>
      </Card>
    </div>
  );
}
