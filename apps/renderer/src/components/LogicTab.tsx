import { Binary, Download, FileUp, RadioTower, Waves } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  baseUrl, logicCapture, logicDecode, logicSample, logicSources,
  logicLaunchPulseview,
  type LogicCapture, type LogicFrame, type LogicSource,
} from "../lib/api";
import { fmtEng, openExternal } from "../lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const LANE_COLORS = ["#EAB308", "#16A34A", "#0EA5E9", "#DB2777", "#A855F7", "#F97316", "#14B8A6", "#F43F5E"];
const PROTOCOLS = ["spi", "i2c", "uart"] as const;
type Proto = (typeof PROTOCOLS)[number];
const ROLES: Record<Proto, string[]> = { spi: ["clk", "mosi", "miso", "cs"], i2c: ["scl", "sda"], uart: ["rx"] };

export function LogicTab() {
  const cv = useRef<HTMLCanvasElement | null>(null);
  const [base, setBase] = useState<string | null>(null);
  const [cap, setCap] = useState<LogicCapture | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [proto, setProto] = useState<Proto>("spi");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [opts, setOpts] = useState<Record<string, string | number>>({ cpol: 0, cpha: 0, bitorder: "msb", word_size: 8, baud: 9600, parity: "none" });
  const [frames, setFrames] = useState<LogicFrame[]>([]);
  const [sources, setSources] = useState<LogicSource[]>([]);
  const [note, setNote] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    (async () => {
      const b = await baseUrl(); setBase(b);
      setSources((await logicSources(b)).sources);
      loadSample(b, "spi");
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (cap) draw(); }, [cap, names]); // eslint-disable-line react-hooks/exhaustive-deps

  function applyCapture(c: LogicCapture, p?: Proto) {
    setCap(c);
    const chNames = Object.keys(c.channels);
    setNames(chNames);
    setFrames([]);
    if (p) setProto(p);
    // auto-map roles from the capture's suggested mapping or by name match
    const pr = p ?? proto;
    const m: Record<string, string> = {};
    for (const role of ROLES[pr]) m[role] = c.mapping?.[role] ?? chNames.find((n) => n.toLowerCase().includes(role)) ?? "";
    setMapping(m);
  }
  async function loadSample(b: string, p: Proto) {
    const c = await logicSample(b, p);
    applyCapture(c, p);
    setNote(`Loaded ${p.toUpperCase()} sample · ${Object.keys(c.channels).length} channels`);
  }
  async function decode() {
    if (!base || !cap) return;
    const r = await logicDecode(base, { protocol: proto, sample_rate: cap.sample_rate, channels: cap.channels, mapping, options: opts });
    if (r.ok && r.frames) { setFrames(r.frames); setNote(`Decoded ${r.count} ${proto.toUpperCase()} ${proto === "i2c" ? "events" : "frames/bytes"}`); }
    else setNote(`Decode failed: ${r.error}`);
  }
  async function capture() {
    if (!base) return;
    setNote("Capturing via sigrok…");
    const r = await logicCapture(base, { driver: "fx2lafw", channels: 8, sample_rate: 1_000_000, samples: 100_000 });
    if (r.ok && r.channels) { applyCapture({ sample_rate: r.sample_rate ?? 1e6, channels: r.channels }); setNote("Captured from device"); }
    else setNote(`Capture: ${r.error}`);
  }
  function importCsv(text: string) {
    const lines = text.trim().split(/\r?\n/).filter((l) => l && !l.startsWith(";"));
    if (lines.length < 2) { setNote("CSV needs a header + rows"); return; }
    const header = lines[0].split(",").map((s) => s.trim());
    const timeCol = header.findIndex((h) => /time|s$/i.test(h));
    const chans: Record<string, number[]> = {};
    header.forEach((h, i) => { if (i !== timeCol) chans[h] = []; });
    let sr = 1_000_000, t0: number | null = null, t1: number | null = null;
    lines.slice(1).forEach((ln) => {
      const cols = ln.split(",");
      header.forEach((h, i) => {
        if (i === timeCol) { const t = parseFloat(cols[i]); if (t0 === null) t0 = t; t1 = t; }
        else chans[h].push(cols[i]?.trim() === "1" ? 1 : 0);
      });
    });
    if (t0 !== null && t1 !== null && t1 > t0) sr = (lines.length - 2) / (t1 - t0);
    applyCapture({ sample_rate: sr, channels: chans });
    setNote(`Imported ${Object.keys(chans).length} channels, ${lines.length - 1} samples`);
  }

  function draw() {
    const c = cv.current; if (!c || !cap) return;
    const ctx = c.getContext("2d"); if (!ctx) return;
    const W = (c.width = c.clientWidth), H = (c.height = c.clientHeight);
    ctx.fillStyle = "#0a1220"; ctx.fillRect(0, 0, W, H);
    const chNames = Object.keys(cap.channels);
    const lanes = chNames.length || 1;
    const laneH = H / lanes;
    const pad = 8, labelW = 78;
    const first = cap.channels[chNames[0]] ?? [];
    const N = first.length || 1;
    chNames.forEach((nm, li) => {
      const y0 = li * laneH, mid = y0 + laneH / 2;
      ctx.strokeStyle = "#132033"; ctx.beginPath(); ctx.moveTo(0, y0); ctx.lineTo(W, y0); ctx.stroke();
      ctx.fillStyle = "#7c93a8"; ctx.font = "11px ui-monospace, monospace"; ctx.textBaseline = "middle";
      ctx.fillText(names[li] ?? nm, 6, mid);
      const sig = cap.channels[nm]; if (!sig?.length) return;
      const hi = y0 + pad, lo = y0 + laneH - pad;
      ctx.strokeStyle = LANE_COLORS[li % LANE_COLORS.length]; ctx.lineWidth = 1.5; ctx.beginPath();
      const plotW = W - labelW;
      let prevY = sig[0] ? hi : lo, started = false;
      for (let x = 0; x < plotW; x++) {
        const idx = Math.floor((x / plotW) * (N - 1));
        const y = sig[idx] ? hi : lo;
        const px = labelW + x;
        if (!started) { ctx.moveTo(px, y); started = true; }
        else { if (y !== prevY) { ctx.lineTo(px, prevY); ctx.lineTo(px, y); } else ctx.lineTo(px, y); }
        prevY = y;
      }
      ctx.stroke();
    });
    ctx.strokeStyle = "#132033"; ctx.beginPath(); ctx.moveTo(labelW, 0); ctx.lineTo(labelW, H); ctx.stroke();
  }

  const cols: Record<Proto, [string, string][]> = {
    spi: [["time_s", "Time"], ["mosi_hex", "MOSI"], ["miso_hex", "MISO"]],
    i2c: [["time_s", "Time"], ["type", "Event"], ["hex", "Value"], ["rw", "R/W"], ["ack", "ACK"]],
    uart: [["time_s", "Time"], ["hex", "Byte"], ["char", "ASCII"], ["framing_error", "Frame err"]],
  };
  const sigrok = sources.find((s) => s.id === "sigrok");
  const pulseview = sources.find((s) => s.id === "pulseview");
  const asciiRun = proto !== "i2c"
    ? frames.map((f) => (f.char as string) || "").join("")
    : frames.filter((f) => f.type === "data").map((f) => (f.char as string) || ".").join("");

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel px-4 py-3 shadow-panel">
        <div className="mr-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink"><Waves className="h-4 w-4 text-accent" /> Logic Analyzer</div>
          <div className="text-xs text-muted">Capture &amp; decode SPI / I²C / UART — any sigrok-supported or Saleae device.</div>
        </div>
        <select value={proto} onChange={(e) => base && loadSample(base, e.target.value as Proto)} className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm uppercase text-ink">
          {PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <Button variant="secondary" size="md" onClick={() => base && loadSample(base, proto)}><Binary className="h-4 w-4" /> Load sample</Button>
        <Button variant="secondary" size="md" onClick={() => fileRef.current?.click()}><FileUp className="h-4 w-4" /> Import CSV</Button>
        <Button variant="secondary" size="md" onClick={capture}><RadioTower className="h-4 w-4" /> Capture</Button>
        <Button variant="primary" size="md" className="ml-auto" onClick={decode}>Decode ▸</Button>
        <input ref={fileRef} type="file" accept=".csv,.txt" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) f.text().then(importCsv); e.target.value = ""; }} />
        {note && <span className="w-full text-[11px] text-muted">{note}</span>}
      </div>

      {sigrok && !sigrok.available && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel2/60 px-3 py-2 text-[12px] text-ink">
          <Download className="h-4 w-4 text-muted" />
          {pulseview?.available ? (
            <>
              <b>PulseView is installed</b> — capture there, export CSV, and import it here.
              <button onClick={async () => { const b = await baseUrl(); await logicLaunchPulseview(b); }}
                className="rounded-md bg-accent px-2.5 py-1 text-[11px] font-semibold text-bg hover:opacity-90">Launch PulseView</button>
              <span className="text-muted">For one-click in-app capture, add the sigrok-cli build:</span>
              <button onClick={() => sigrok.install && openExternal(sigrok.install.url)} className="font-semibold text-accent hover:underline">get sigrok-cli</button>
            </>
          ) : (
            <>
              In-app capture uses <b>sigrok-cli</b> (FX2LA + many brands).
              <button onClick={() => sigrok.install && openExternal(sigrok.install.url)} className="font-semibold text-accent hover:underline">Install sigrok</button>
              — decoding imported or sample captures works without it.
            </>
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Waveforms</CardTitle>
          <span className="text-xs text-muted">{cap ? `${Object.keys(cap.channels).length} ch · ${fmtEng(cap.sample_rate, "Sa/s")}` : "—"}</span>
        </CardHeader>
        <CardContent>
          <canvas ref={cv} className="h-[300px] w-full rounded-lg border border-line bg-screen" />
          {/* editable channel names */}
          <div className="mt-2 flex flex-wrap gap-2">
            {names.map((nm, i) => (
              <span key={i} className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: LANE_COLORS[i % LANE_COLORS.length] }} />
                <input value={nm} onChange={(e) => setNames((s) => s.map((x, j) => (j === i ? e.target.value : x)))}
                  className="w-24 rounded border border-line bg-panel px-1.5 py-0.5 font-mono text-[11px] text-ink" />
              </span>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{proto.toUpperCase()} decoder</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          {/* channel mapping */}
          <div className="flex flex-wrap items-end gap-2">
            {ROLES[proto].map((role) => (
              <label key={role} className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">{role}
                <select value={mapping[role] ?? ""} onChange={(e) => setMapping((m) => ({ ...m, [role]: e.target.value }))}
                  className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-ink">
                  <option value="">— none —</option>
                  {(cap ? Object.keys(cap.channels) : []).map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            ))}
            {proto === "spi" && <>
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Mode
                <select value={`${opts.cpol}${opts.cpha}`} onChange={(e) => setOpts((o) => ({ ...o, cpol: +e.target.value[0], cpha: +e.target.value[1] }))} className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-ink">
                  {["00", "01", "10", "11"].map((m) => <option key={m} value={m}>Mode {parseInt(m, 2)} ({m})</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Bit order
                <select value={opts.bitorder} onChange={(e) => setOpts((o) => ({ ...o, bitorder: e.target.value }))} className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-ink"><option value="msb">MSB</option><option value="lsb">LSB</option></select>
              </label>
            </>}
            {proto === "uart" && <>
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Baud
                <input type="number" value={opts.baud} onChange={(e) => setOpts((o) => ({ ...o, baud: +e.target.value }))} className="w-24 rounded-lg border border-line bg-panel px-2 py-1.5 font-mono text-sm text-ink" />
              </label>
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Parity
                <select value={opts.parity} onChange={(e) => setOpts((o) => ({ ...o, parity: e.target.value }))} className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-ink"><option>none</option><option>even</option><option>odd</option></select>
              </label>
            </>}
            <Button variant="primary" size="md" onClick={decode}>Decode</Button>
          </div>

          {asciiRun && <div className="rounded-lg border border-line bg-screen px-3 py-2 font-mono text-sm text-emerald-300">ASCII: {asciiRun}</div>}

          <div className="max-h-[280px] overflow-auto rounded-lg border border-line">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-panel2 text-[11px] uppercase tracking-wide text-muted">
                <tr>{cols[proto].map(([, l]) => <th key={l} className="px-3 py-2">{l}</th>)}</tr>
              </thead>
              <tbody className="font-mono">
                {frames.map((f, i) => (
                  <tr key={i} className={`border-t border-line ${i % 2 ? "bg-panel2/40" : ""}`}>
                    {cols[proto].map(([k]) => (
                      <td key={k} className="px-3 py-1 text-ink">
                        {k === "time_s" && typeof f[k] === "number" ? fmtEng(f[k] as number, "s")
                          : k === "ack" ? (f[k] ? "ACK" : f[k] === false ? "NAK" : "")
                          : k === "framing_error" ? (f[k] ? "⚠" : "")
                          : f[k] != null ? String(f[k]) : ""}
                      </td>
                    ))}
                  </tr>
                ))}
                {frames.length === 0 && <tr><td colSpan={cols[proto].length} className="px-3 py-6 text-center text-muted">Map channels and click Decode.</td></tr>}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
