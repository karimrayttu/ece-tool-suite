import { useEffect, useRef, useState } from "react";
import {
  baseUrl, instrumentCaps, openWs, scopeBringup, scopeConfig, scopeMeasure,
  type InstrumentCaps, type ScopeChannelCfg, type ScopeConfig, type ScopeFrame,
} from "../lib/api";
import { downloadCanvasPng, downloadCsv, stamp } from "../lib/csv";
import { fmtEng } from "../lib/utils";
import { ConnectionBar } from "./ConnectionBar";
import { VendorBadge } from "./VendorBadge";
import { PresetButtons } from "./PresetButtons";
import { ScreenshotButton } from "./ScreenshotButton";

// Keysight InfiniiVision channel colours: CH1 yellow, CH2 green, CH3 cyan, CH4 magenta.
const CH_COLORS: Record<number, string> = { 1: "#FFD500", 2: "#00E13A", 3: "#19B9E8", 4: "#F45BD1" };

interface ChState {
  enabled: boolean; scale: number; offset: number;
  coupling: string; probe: number; bwlimit: boolean; invert: boolean;
}
const defaultCh = (ch: number): ChState => ({
  enabled: ch === 1, scale: 0.5, offset: 0, coupling: "DC", probe: 10, bwlimit: false, invert: false,
});

// --- small controls -------------------------------------------------------
function Knob({ label, value, set, step = 1, w = "w-full" }:
  { label: string; value: number; set: (n: number) => void; step?: number; w?: string }) {
  return (
    <label className="flex flex-col gap-0.5 text-[11px] uppercase tracking-wide text-muted">
      {label}
      <input type="number" step={step} value={value}
        onChange={(e) => { const n = parseFloat(e.target.value); if (!Number.isNaN(n)) set(n); }}
        className={`${w} rounded border border-line bg-panel2 px-1.5 py-1 font-mono text-xs text-ink`} />
    </label>
  );
}
function Seg<T extends string>({ label, value, set, options }:
  { label: string; value: T; set: (v: T) => void; options: readonly T[] }) {
  return (
    <label className="flex flex-col gap-0.5 text-[11px] uppercase tracking-wide text-muted">
      {label}
      <div className="flex overflow-hidden rounded border border-line">
        {options.map((o) => (
          <button key={o} onClick={() => set(o)}
            className={`px-2 py-1 text-[11px] ${value === o ? "bg-ks text-black font-semibold" : "bg-panel2 text-muted hover:text-ink"}`}>
            {o}
          </button>
        ))}
      </div>
    </label>
  );
}
function Toggle({ label, on, set }: { label: string; on: boolean; set: (b: boolean) => void }) {
  return (
    <button onClick={() => set(!on)}
      className={`rounded border px-2 py-1 text-[11px] ${on ? "border-ks bg-ks/20 text-ks" : "border-line bg-panel2 text-muted"}`}>
      {label} {on ? "ON" : "OFF"}
    </button>
  );
}

export function ScopeTab() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const gratRef = useRef<HTMLCanvasElement | null>(null);
  const [base, setBase] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const frameRef = useRef<ScopeFrame | null>(null);

  const [chans, setChans] = useState<Record<number, ChState>>({
    1: defaultCh(1), 2: defaultCh(2), 3: defaultCh(3), 4: defaultCh(4),
  });
  const [active, setActive] = useState(1);
  const [running, setRunning] = useState(true);

  const [tbScale, setTbScale] = useState(200e-6);
  const [tbPos, setTbPos] = useState(0);

  const [trigMode, setTrigMode] = useState<"EDGE" | "PULSE">("EDGE");
  const [trigSrc, setTrigSrc] = useState("CHAN1");
  const [trigSlope, setTrigSlope] = useState<"POS" | "NEG" | "EITH">("POS");
  const [trigLevel, setTrigLevel] = useState(0);
  const [trigCoup, setTrigCoup] = useState<"DC" | "AC" | "LFR">("DC");
  const [trigSweep, setTrigSweep] = useState<"AUTO" | "NORM">("AUTO");
  const [trigHoldoff, setTrigHoldoff] = useState(60e-9);

  const [acqType, setAcqType] = useState<"NORM" | "AVER" | "HRES" | "PEAK">("NORM");
  const [acqCount, setAcqCount] = useState(8);
  const [acqPoints, setAcqPoints] = useState(1000);

  const [meas, setMeas] = useState<Record<string, { value: number | null; unit: string }>>({});
  const [caps, setCaps] = useState<InstrumentCaps | null>(null);

  // the connected unit's real feature set drives which controls exist
  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      setCaps(await instrumentCaps(b, "scope"));
    })();
  }, [connected]);

  const push = async (cfg: ScopeConfig) => { if (base) await scopeConfig(base, cfg); };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    (async () => {
      const b = await baseUrl();
      if (stop) return;
      setBase(b);
      ws = openWs<ScopeFrame>(b, "/ws/scope", (f) => {
        if (stop) return;
        frameRef.current = f;
        setConnected(Boolean(f.connected));
        draw(f);
      }, () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);

  // poll the full measurement set for the active channel while connected
  useEffect(() => {
    if (!base || !connected) return;
    let stop = false;
    const tick = async () => {
      const r = await scopeMeasure(base, active);
      if (!stop && r.measurements) setMeas(r.measurements);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => { stop = true; clearInterval(id); };
  }, [base, connected, active]);

  // dpr-aware backing store so 1px graticule lines stay crisp on HiDPI (MDN canvas guide)
  function fit(cv: HTMLCanvasElement) {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, W: w, H: h };
  }

  function draw(f: ScopeFrame) {
    const grat = gratRef.current, cv = canvasRef.current;
    if (!grat || !cv) return;

    // --- static layer: graticule + status text (own canvas so persistence can't smear it)
    const g = fit(grat);
    g.ctx.fillStyle = "#04070b";
    g.ctx.fillRect(0, 0, g.W, g.H);
    g.ctx.strokeStyle = "#152232";
    g.ctx.lineWidth = 1;
    for (let i = 0; i <= 10; i++) { const x = Math.round((i / 10) * g.W) + 0.5; g.ctx.beginPath(); g.ctx.moveTo(x, 0); g.ctx.lineTo(x, g.H); g.ctx.stroke(); }
    for (let i = 0; i <= 8; i++) { const y = Math.round((i / 8) * g.H) + 0.5; g.ctx.beginPath(); g.ctx.moveTo(0, y); g.ctx.lineTo(g.W, y); g.ctx.stroke(); }
    g.ctx.strokeStyle = "#23374d";
    g.ctx.beginPath(); g.ctx.moveTo(g.W / 2, 0); g.ctx.lineTo(g.W / 2, g.H); g.ctx.moveTo(0, g.H / 2); g.ctx.lineTo(g.W, g.H / 2); g.ctx.stroke();

    g.ctx.font = "11px ui-monospace, monospace";
    g.ctx.textBaseline = "top";
    g.ctx.fillStyle = "#7da3b8";
    g.ctx.fillText(`H ${fmtEng(tbScale, "s")}/div`, 8, 6);
    g.ctx.fillStyle = CH_COLORS[Number(trigSrc.replace("CHAN", "")) || 1] ?? "#7da3b8";
    g.ctx.textAlign = "right";
    g.ctx.fillText(`T ${trigSlope} ${trigSrc} ${fmtEng(trigLevel, "V")}  ${trigSweep}`, g.W - 8, 6);
    g.ctx.textAlign = "left";
    if (!f.connected || !f.channels?.length) {
      g.ctx.fillStyle = "#54718a";
      g.ctx.font = "13px ui-sans-serif, system-ui";
      g.ctx.fillText(f.connected ? "no channels displayed" : "○ not connected — Discover → Connect above", 8, g.H - 22);
    }

    // --- trace layer: phosphor persistence + 3-pass glow (no shadowBlur — too slow)
    const t = fit(cv);
    t.ctx.globalCompositeOperation = "destination-out";
    t.ctx.fillStyle = "rgba(0,0,0,0.55)";          // prior traces decay exponentially
    t.ctx.fillRect(0, 0, t.W, t.H);
    t.ctx.globalCompositeOperation = "source-over";
    if (!f.connected || !f.channels?.length) return;

    for (const chan of f.channels) {
      const v = chan.v;
      if (!v?.length) continue;
      let min = Infinity, max = -Infinity;
      for (const val of v) { if (val < min) min = val; if (val > max) max = val; }
      const pad = (max - min) * 0.15 || 0.1;
      min -= pad; max += pad;
      const path = new Path2D();
      for (let i = 0; i < v.length; i++) {
        const x = (i / (v.length - 1)) * t.W;
        const y = t.H - ((v[i] - min) / (max - min)) * t.H;
        i === 0 ? path.moveTo(x, y) : path.lineTo(x, y);
      }
      const color = CH_COLORS[chan.ch] ?? "#fff";
      t.ctx.strokeStyle = color;
      t.ctx.lineJoin = "round";
      t.ctx.globalAlpha = 0.12; t.ctx.lineWidth = 6;   // bloom halo
      t.ctx.stroke(path);
      t.ctx.globalAlpha = 0.35; t.ctx.lineWidth = 2.8; // inner glow
      t.ctx.stroke(path);
      t.ctx.globalAlpha = 1;    t.ctx.lineWidth = 1.4; // beam
      t.ctx.stroke(path);
    }
  }

  // --- actions (live-apply, Keysight-style: change a knob, it takes effect) --
  function setCh(ch: number, patch: Partial<ChState>, cfgKey?: keyof ChState) {
    setChans((s) => ({ ...s, [ch]: { ...s[ch], ...patch } }));
    const cfg: ScopeChannelCfg = { ch };
    if (cfgKey) (cfg as unknown as Record<string, unknown>)[cfgKey] = patch[cfgKey];
    else Object.assign(cfg, patch);
    push({ channels: [cfg] });
  }
  async function toggleCh(ch: number) {
    const en = !chans[ch].enabled;
    setCh(ch, { enabled: en }, "enabled");
    setActive(ch);
  }
  async function runState(run: "run" | "stop" | "single") {
    setRunning(run === "run");
    await push({ run });
  }
  async function autoSetup() { if (base) { await scopeBringup(base); setRunning(true); } }

  function applyHorizontal() { push({ timebase_scale: tbScale, timebase_position: tbPos }); }
  function applyTrigger() {
    push({ trig_mode: trigMode, trig_source: trigSrc, trig_slope: trigSlope, trig_level: trigLevel,
      trig_coupling: trigCoup, trig_sweep: trigSweep, trig_holdoff: trigHoldoff });
  }
  function applyAcq() { push({ acq_type: acqType, acq_count: acqCount, acq_points: acqPoints }); }

  function exportCsv() {
    const chs = frameRef.current?.channels;
    if (!chs?.length) return;
    const t = chs[0].t;
    downloadCsv(`scope_${stamp()}.csv`, ["time_s", ...chs.map((c) => `ch${c.ch}_v`)],
      t.map((tv, i) => [tv, ...chs.map((c) => c.v[i] ?? "")]));
  }
  const a = chans[active];
  const accent = CH_COLORS[active];

  const measRows: [string, string][] = [
    ["vpp", "Vpp"], ["vamp", "Vampl"], ["vmax", "Vmax"], ["vmin", "Vmin"],
    ["vtop", "Vtop"], ["vbase", "Vbase"], ["vavg", "Vavg"], ["vrms", "Vrms"],
    ["freq", "Freq"], ["period", "Period"], ["duty", "Duty"], ["pwidth", "+Width"],
    ["nwidth", "−Width"], ["rise", "Rise"], ["fall", "Fall"], ["over", "Over"],
  ];

  return (
    <div className="flex flex-col gap-3">
      <ConnectionBar role="scope" onChange={setConnected} />

      <div className="overflow-hidden rounded-xl border border-line bg-panel shadow-panel">
        {/* Keysight top bar: model + acquisition state + run controls */}
        <div className="flex items-center gap-3 border-b border-line bg-panel2 px-3 py-2">
          <VendorBadge role="scope" />
          <span className="text-xs text-muted">{caps?.family ?? "Oscilloscope"} · {caps?.channels ?? 4} ch</span>
          <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${connected ? (running ? "bg-verified/20 text-verified" : "bg-danger/20 text-danger") : "bg-line text-muted"}`}>
            {connected ? (running ? "● RUN" : "■ STOP") : "○ OFFLINE"}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <button onClick={() => runState("run")} className="rounded bg-verified/20 px-3 py-1 text-xs font-semibold text-verified hover:bg-verified/30">Run</button>
            <button onClick={() => runState("stop")} className="rounded bg-danger/20 px-3 py-1 text-xs font-semibold text-danger hover:bg-danger/30">Stop</button>
            <button onClick={() => runState("single")} className="rounded bg-line px-3 py-1 text-xs text-ink hover:bg-line/70">Single</button>
            <button onClick={autoSetup} className="rounded bg-ks px-3 py-1 text-xs font-semibold text-black hover:opacity-90">Auto Setup</button>
          </div>
        </div>

        {/* graticule + channel column */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_270px]">
          <div className="relative border-b border-line lg:border-b-0 lg:border-r">
            <div className="crt-screen relative m-2.5 h-[360px]">
              <canvas ref={gratRef} className="absolute inset-0 h-full w-full" />
              <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
            </div>
            {/* measurement strip under the graticule */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line bg-panel2 px-3 py-1.5 text-[11px]">
              <span className="inline-flex items-center gap-1.5 font-semibold text-ink">
                <span className="h-2 w-2 rounded-full" style={{ background: accent }} /> CH{active}
              </span>
              {measRows.filter(([k]) => meas[k]?.value != null).slice(0, 8).map(([k, lbl]) => (
                <span key={k} className="text-muted">{lbl} <span className="font-mono font-semibold text-ink">
                  {fmtEng(meas[k].value as number, meas[k].unit)}</span></span>
              ))}
              {!Object.values(meas).some((m) => m.value != null) && <span className="text-muted">measurements appear on connect</span>}
            </div>
          </div>

          {/* right: channel select + active-channel controls */}
          <div className="flex flex-col gap-2 p-3">
            <div className="grid grid-cols-4 gap-1">
              {Array.from({ length: caps?.channels ?? 4 }, (_, i) => i + 1).map((ch) => (
                <button key={ch} onClick={() => (chans[ch].enabled ? setActive(ch) : toggleCh(ch))}
                  onDoubleClick={() => toggleCh(ch)}
                  style={active === ch ? { borderColor: CH_COLORS[ch], boxShadow: `inset 0 0 0 1px ${CH_COLORS[ch]}` } : undefined}
                  className={`flex items-center justify-center gap-1.5 rounded-lg border px-1 py-1.5 text-xs font-semibold ${chans[ch].enabled ? "border-line bg-panel text-ink" : "border-line bg-panel2 text-muted"}`}>
                  <span className="h-2 w-2 rounded-full" style={{ background: chans[ch].enabled ? CH_COLORS[ch] : "#cbd5e1" }} />
                  CH{ch}
                </button>
              ))}
            </div>
            <div className="text-[11px] text-muted">click = select · toggles on if off · dbl-click = on/off</div>

            <div className="rounded-lg border border-line bg-panel2/60 p-2">
              <div className="mb-2 flex items-center justify-between">
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: accent }} /> Channel {active}
                </span>
                <Toggle label="Disp" on={a.enabled} set={(b) => setCh(active, { enabled: b }, "enabled")} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Knob label="V/div" value={a.scale} step={0.01} set={(n) => setCh(active, { scale: n }, "scale")} />
                <Knob label="Offset V" value={a.offset} step={0.01} set={(n) => setCh(active, { offset: n }, "offset")} />
                <Seg label="Coupling" value={a.coupling as "DC"} set={(v) => setCh(active, { coupling: v }, "coupling")} options={(caps?.couplings ?? ["DC", "AC"]) as readonly string[]} />
                <Knob label="Probe ×" value={a.probe} set={(n) => setCh(active, { probe: n }, "probe")} />
              </div>
              <div className="mt-2 flex gap-2">
                <Toggle label="BW Lim" on={a.bwlimit} set={(b) => setCh(active, { bwlimit: b }, "bwlimit")} />
                <Toggle label="Invert" on={a.invert} set={(b) => setCh(active, { invert: b }, "invert")} />
              </div>
            </div>
          </div>
        </div>

        {/* bottom control groups: Horizontal / Trigger / Acquire */}
        <div className="grid grid-cols-1 gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
          <div className="bg-panel p-3">
            <div className="mb-2 text-xs font-semibold text-ink">Horizontal</div>
            <div className="grid grid-cols-2 gap-2">
              <Knob label="s/div" value={tbScale} step={1e-6} set={setTbScale} />
              <Knob label="Position s" value={tbPos} step={1e-6} set={setTbPos} />
            </div>
            <button onClick={applyHorizontal} className="mt-2 w-full rounded bg-ks/20 py-1 text-xs text-ks">Apply timebase</button>
          </div>

          <div className="bg-panel p-3">
            <div className="mb-2 text-xs font-semibold text-ink">Trigger</div>
            <div className="grid grid-cols-2 gap-2">
              <Seg label="Mode" value={trigMode} set={setTrigMode} options={["EDGE", "PULSE"] as const} />
              <Seg label="Sweep" value={trigSweep} set={setTrigSweep} options={["AUTO", "NORM"] as const} />
              <label className="flex flex-col gap-0.5 text-[11px] uppercase tracking-wide text-muted">Source
                <select value={trigSrc} onChange={(e) => setTrigSrc(e.target.value)} className="rounded border border-line bg-panel2 px-1.5 py-1 text-xs text-ink">
                  {["CHAN1", "CHAN2", "CHAN3", "CHAN4", "EXT", "LINE"].map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
              <Seg label="Slope" value={trigSlope} set={setTrigSlope} options={["POS", "NEG", "EITH"] as const} />
              <Knob label="Level V" value={trigLevel} step={0.01} set={setTrigLevel} />
              <Seg label="Coupling" value={trigCoup} set={setTrigCoup} options={["DC", "AC", "LFR"] as const} />
              <Knob label="Holdoff s" value={trigHoldoff} step={1e-9} set={setTrigHoldoff} />
            </div>
            <button onClick={applyTrigger} className="mt-2 w-full rounded bg-ks/20 py-1 text-xs text-ks">Apply trigger</button>
          </div>

          <div className="bg-panel p-3">
            <div className="mb-2 text-xs font-semibold text-ink">Acquire</div>
            <div className="grid grid-cols-2 gap-2">
              <Seg label="Type" value={acqType} set={(v) => setAcqType(v as typeof acqType)} options={(caps?.acq_types ?? ["NORM", "AVER", "HRES", "PEAK"]) as readonly string[]} />
              <Knob label="Averages" value={acqCount} set={setAcqCount} />
              <Knob label="Mem points" value={acqPoints} step={1000} set={setAcqPoints} />
            </div>
            <button onClick={applyAcq} className="mt-2 w-full rounded bg-ks/20 py-1 text-xs text-ks">Apply acquire</button>
          </div>
        </div>

        {/* presets + export */}
        <div className="border-t border-line p-3">
          <PresetButtons role="scope" />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ScreenshotButton role="scope" />
            <button onClick={exportCsv} className="rounded bg-line px-2.5 py-1 text-xs text-ink hover:bg-line/70">Export CSV</button>
            <button onClick={() => {
              const g = gratRef.current, t = canvasRef.current;
              if (!g || !t) return;
              const c = document.createElement("canvas");
              c.width = g.width; c.height = g.height;
              const x = c.getContext("2d")!;
              x.drawImage(g, 0, 0); x.drawImage(t, 0, 0);
              downloadCanvasPng(c, `scope_${stamp()}.png`);
            }} className="rounded bg-line px-2.5 py-1 text-xs text-ink hover:bg-line/70">Save PNG</button>
          </div>
        </div>
      </div>
    </div>
  );
}
