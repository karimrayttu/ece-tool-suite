import { CheckCircle2, Cpu, ExternalLink, FileUp, FlaskConical, Play, Save, Sparkles, XCircle, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  baseUrl, capacitorBank, digikeyConnect, digikeySearch, digikeyStatus, iocEdit, iocParse, loopStatus,
  loopVerify, magneticsAdvise, magneticsStatus, powerDesign, powerStage, spiceStatus, spiceVerify,
  toolsDetect, toolsLaunch, webenchUrl,
  type CapBankResult, type DesignTool, type DigikeyStatus, type DkPart, type IocParsed, type LoopVerify,
  type MagneticsDb, type MagneticsResult, type PowerDesign, type PowerStage, type SpiceVerifyResult,
} from "../lib/api";
import { drawTrace } from "../lib/canvas";
import { downloadBlob } from "../lib/csv";
import { openExternal } from "../lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
const KIND_LABEL: Record<string, string> = { stm32: "STM32", "ti-power": "TI Power", "ti-mcu": "TI MCU", eda: "EDA", sim: "SPICE" };

export function Stm32Tab() {
  const [base, setBase] = useState<string | null>(null);
  const [tools, setTools] = useState<DesignTool[]>([]);
  const [note, setNote] = useState("");

  // .ioc editor state
  const [iocText, setIocText] = useState("");
  const [ioc, setIoc] = useState<IocParsed | null>(null);
  const [edits, setEdits] = useState<Record<string, string | null>>({});
  const fileRef = useRef<HTMLInputElement | null>(null);

  // power stage
  const [topo, setTopo] = useState<"buck" | "boost">("buck");
  const [ps, setPs] = useState({ vin: 12, vout: 3.3, iout: 2, fsw_khz: 500, ripple_pct: 30 });
  const [psOut, setPsOut] = useState<PowerStage | null>(null);
  // SPICE verification
  const [sim, setSim] = useState({ L_uH: 10, Cout_uF: 47 });
  const [spiceEngine, setSpiceEngine] = useState<string>("");
  const [sv, setSv] = useState<SpiceVerifyResult | null>(null);
  const [simBusy, setSimBusy] = useState(false);
  const svCanvas = useRef<HTMLCanvasElement | null>(null);
  // closed-loop margin (python-control)
  const [loop, setLoop] = useState<LoopVerify | null>(null);
  const [loopAvail, setLoopAvail] = useState(false);
  const [loopBusy, setLoopBusy] = useState(false);
  const bodeCanvas = useRef<HTMLCanvasElement | null>(null);
  // magnetics (OpenMagnetics)
  const [magDb, setMagDb] = useState<MagneticsDb | null>(null);
  const [mag, setMag] = useState<MagneticsResult | null>(null);
  const [magBusy, setMagBusy] = useState(false);
  // capacitor bank
  const [caps, setCaps] = useState<CapBankResult | null>(null);
  // native WEBENCH-class design
  const [design, setDesign] = useState<PowerDesign | null>(null);
  const [isolated, setIsolated] = useState(false);
  // Digi-Key WEBENCH adapter
  const [dk, setDk] = useState<DigikeyStatus | null>(null);
  const [dkId, setDkId] = useState(""); const [dkSecret, setDkSecret] = useState("");
  const [dkParts, setDkParts] = useState<DkPart[]>([]);
  const [dkQuery, setDkQuery] = useState("TPS54560");

  useEffect(() => { (async () => {
    const b = await baseUrl(); setBase(b);
    setTools((await toolsDetect(b)).tools);
    const eng = (await spiceStatus(b)).engines; setSpiceEngine(eng[0]?.name ?? "");
    setDk(await digikeyStatus(b));
    setLoopAvail((await loopStatus(b)).available);
    setMagDb(await magneticsStatus(b));
  })(); }, []);

  async function designMagnetics() {
    if (!base) return;
    setMagBusy(true);
    try {
      const ripple = (psOut && psOut.ok && topo === "buck" ? psOut.ripple_current_A : undefined) ?? (ps.ripple_pct / 100) * ps.iout;
      const r = await magneticsAdvise(base, { inductance_uH: sim.L_uH, i_dc: ps.iout, i_ripple_pp: ripple, fsw_khz: ps.fsw_khz });
      setMag(r);
    } finally { setMagBusy(false); }
  }
  async function sizeCaps() {
    if (!base) return;
    const ripple = (psOut && psOut.ok && topo === "buck" ? psOut.ripple_current_A : undefined) ?? (ps.ripple_pct / 100) * ps.iout;
    setCaps(await capacitorBank(base, { topology: topo, vin: ps.vin, vout: ps.vout, iout: ps.iout, fsw_khz: ps.fsw_khz, il_ripple_pp_a: ripple }));
  }

  async function verifyLoop() {
    if (!base) return;
    setLoopBusy(true);
    try {
      const r = await loopVerify(base, { vin: ps.vin, vout: ps.vout, iout: ps.iout, L_uH: sim.L_uH, Cout_uF: sim.Cout_uF, fsw_khz: ps.fsw_khz });
      setLoop(r);
    } finally { setLoopBusy(false); }
  }

  async function autoDesign() {
    if (!base) return;
    const r = await powerDesign(base, { ...ps, isolated });
    setDesign(r);
    if (r.ok && r.recommendation) {
      const t = r.recommendation.topology;
      if (t === "buck" || t === "boost") setTopo(t);
      const L = r.sizing?.inductor_uH as number | undefined;
      const C = r.sizing?.output_cap_uF as number | undefined;
      if (L) setSim((s) => ({ ...s, L_uH: Math.round(L * 100) / 100, Cout_uF: C ? Math.max(10, C) : s.Cout_uF }));
    }
  }
  async function dkConnect() {
    if (!base || !dkId || !dkSecret) return;
    const r = await digikeyConnect(base, dkId, dkSecret);
    setDk(await digikeyStatus(base));
    if (!r.ok) setNote(`Digi-Key: ${r.error}`);
  }
  async function dkSearch() {
    if (!base) return;
    const r = await digikeySearch(base, dkQuery);
    setDkParts(r.ok ? (r.parts ?? []) : []);
    if (!r.ok) setNote(`Digi-Key: ${r.error}`);
  }

  async function launch(t: DesignTool) {
    if (!base) return;
    const r = await toolsLaunch(base, t.id);
    setNote(r.ok ? `Launched ${r.launched}` : `${t.name}: ${r.error}`);
  }
  async function loadIoc(text: string) {
    if (!base) return;
    setIocText(text); setEdits({});
    const p = await iocParse(base, text);
    setIoc(p.ok ? p : null);
    setNote(p.ok ? `Loaded ${p.mcu} · ${p.pins.length} pins · ${p.timers.length} timers` : `Parse failed: ${p.error}`);
  }
  function setEdit(key: string, value: string) { setEdits((e) => ({ ...e, [key]: value })); }
  async function saveIoc() {
    if (!base || !iocText) return;
    const r = await iocEdit(base, iocText, edits);
    if (r.ok && r.text) {
      downloadBlob((ioc?.mcu || "project") + ".ioc", new Blob([r.text], { type: "text/plain" }));
      setNote(`Saved ${Object.keys(edits).length} edit(s)`);
    }
    else setNote(`Save failed: ${r.error}`);
  }
  async function computePower() {
    if (!base) return;
    const r = await powerStage(base, topo, ps);
    setPsOut(r);
    if (r.ok && r.inductor_uH) setSim({ L_uH: Math.round(r.inductor_uH * 100) / 100, Cout_uF: Math.max(10, r.output_cap_uF_for_1pct ?? 47) });
  }
  async function verifyInSpice() {
    if (!base) return;
    setSimBusy(true); setSv(null);
    const r = await spiceVerify(base, { topology: topo, vin: ps.vin, vout: ps.vout, iout: ps.iout,
      L_uH: sim.L_uH, Cout_uF: sim.Cout_uF, fsw_khz: ps.fsw_khz });
    setSv(r);
    setSimBusy(false);
    if (r.ok && r.metrics?.waveform) drawWave(r.metrics.waveform);
  }
  function drawWave(w: { t: number[]; vout: number[] }) {
    const c = svCanvas.current; if (!c) return;
    const ctx = c.getContext("2d"); if (!ctx) return;
    const W = (c.width = c.clientWidth), H = (c.height = c.clientHeight);
    ctx.fillStyle = "#0a1220"; ctx.fillRect(0, 0, W, H);
    const v = w.vout; if (!v.length) return;
    const { min: mn, max: mx } = drawTrace(ctx, v, W, H, "#16A34A");
    ctx.fillStyle = "#64748b"; ctx.font = "10px ui-monospace"; ctx.fillText(`${mx.toFixed(2)}V`, 4, 10); ctx.fillText(`${mn.toFixed(2)}V`, 4, H - 4);
  }
  async function openWebench() {
    if (!base) return;
    const r = await webenchUrl(base, { vin_min: ps.vin * 0.9, vin_max: ps.vin * 1.1, vout: ps.vout, iout: ps.iout });
    if (r.url) openExternal(r.url);
  }

  useEffect(() => {
    const c = bodeCanvas.current; if (!c || !loop?.bode?.length) return;
    const ctx = c.getContext("2d"); if (!ctx) return;
    const W = (c.width = c.clientWidth), H = (c.height = c.clientHeight);
    ctx.fillStyle = "#0a1220"; ctx.fillRect(0, 0, W, H);
    const b = loop.bode;
    const lf = b.map((p) => Math.log10(Math.max(p.f_hz, 0.1)));
    const xmn = Math.min(...lf), xmx = Math.max(...lf);
    const X = (lx: number) => ((lx - xmn) / (xmx - xmn)) * (W - 4) + 2;
    // magnitude (dB), left axis -80..100
    const mmn = -80, mmx = 100;
    const Ym = (db: number) => H * 0.5 - ((Math.max(mmn, Math.min(mmx, db)) - mmn) / (mmx - mmn) - 0.5) * H * 0.9;
    // 0 dB line
    ctx.strokeStyle = "#334155"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(0, Ym(0)); ctx.lineTo(W, Ym(0)); ctx.stroke(); ctx.setLineDash([]);
    // phase -180..0 mapped to full height
    const Yp = (deg: number) => H - ((Math.max(-270, Math.min(90, deg)) + 270) / 360) * H;
    ctx.strokeStyle = "#64748b"; ctx.lineWidth = 1; ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(0, Yp(-180)); ctx.lineTo(W, Yp(-180)); ctx.stroke(); ctx.setLineDash([]);
    // gain trace
    ctx.strokeStyle = "#38BDF8"; ctx.lineWidth = 1.5; ctx.beginPath();
    b.forEach((p, i) => { const x = X(lf[i]), y = Ym(p.mag_db); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
    // phase trace
    ctx.strokeStyle = "#F59E0B"; ctx.lineWidth = 1.5; ctx.beginPath();
    b.forEach((p, i) => { const x = X(lf[i]), y = Yp(p.phase_deg); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
    // crossover marker
    const fc = loop.metrics?.crossover_hz;
    if (fc) { const x = X(Math.log10(fc)); ctx.strokeStyle = "#16A34A"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
    ctx.fillStyle = "#38BDF8"; ctx.font = "10px ui-monospace"; ctx.fillText("gain dB", 4, 11);
    ctx.fillStyle = "#F59E0B"; ctx.fillText("phase", 54, 11);
    ctx.fillStyle = "#64748b"; ctx.fillText("−180°", W - 36, Yp(-180) - 3);
  }, [loop]);

  const installed = tools.filter((t) => t.installed);

  return (
    <div className="flex flex-col gap-3">
      {/* installed design tools */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Cpu className="h-4 w-4 text-accent" /> Design tools on this PC</CardTitle>
          <span className="text-xs text-muted">{installed.length} of {tools.length} installed</span>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {tools.map((t) => (
              <div key={t.id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${t.installed ? "border-line bg-panel" : "border-line bg-panel2/50 opacity-60"}`}>
                <span className="rounded bg-ks/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ks">{KIND_LABEL[t.kind] ?? t.kind}</span>
                <span className="text-sm font-medium text-ink">{t.name}</span>
                <span className="ml-auto">
                  {t.launchable
                    ? <Button variant="secondary" onClick={() => launch(t)}><Play className="h-3.5 w-3.5" /> Launch</Button>
                    : <span className="text-[11px] text-muted">{t.installed ? "installed" : "not found"}</span>}
                </span>
              </div>
            ))}
          </div>
          {note && <div className="mt-2 text-[11px] text-muted">{note}</div>}
        </CardContent>
      </Card>

      {/* CubeMX .ioc pinout / mux / timers */}
      <Card>
        <CardHeader>
          <CardTitle>STM32CubeMX — pinout, mux &amp; timers</CardTitle>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="md" onClick={() => fileRef.current?.click()}><FileUp className="h-4 w-4" /> Open .ioc</Button>
            {ioc && <Button variant="primary" size="md" onClick={saveIoc}><Save className="h-4 w-4" /> Save .ioc</Button>}
            <input ref={fileRef} type="file" accept=".ioc" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) f.text().then(loadIoc); e.target.value = ""; }} />
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {!ioc && <div className="text-xs text-muted">Open a STM32CubeMX <code className="font-mono">.ioc</code> project to view and edit pin assignments (alternate-function mux), GPIO labels and timer settings — then Save a modified .ioc.</div>}
          {ioc && <>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
              <span className="text-muted">MCU <span className="font-mono font-semibold text-ink">{ioc.mcu}</span></span>
              <span className="text-muted">Family <span className="font-mono text-ink">{ioc.family}</span></span>
              <span className="text-muted">Peripherals</span>
              {ioc.peripherals.map((p) => <span key={p} className="rounded bg-panel2 px-1.5 py-0.5 font-mono text-[11px] text-ink">{p}</span>)}
            </div>

            {/* pin / mux table */}
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Pin assignments ({ioc.pins.length})</div>
              <div className="max-h-[280px] overflow-auto rounded-lg border border-line">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-panel2 text-[10px] uppercase tracking-wide text-muted">
                    <tr><th className="px-3 py-2">Pin</th><th className="px-3 py-2">Signal (mux)</th><th className="px-3 py-2">Mode</th><th className="px-3 py-2">GPIO label</th></tr>
                  </thead>
                  <tbody className="font-mono">
                    {ioc.pins.map((p) => (
                      <tr key={p.pin} className="border-t border-line">
                        <td className="px-3 py-1 font-semibold text-ink">{p.pin}</td>
                        <td className="px-3 py-1 text-accent">{p.signal}</td>
                        <td className="px-3 py-1 text-muted">{p.mode || "—"}</td>
                        <td className="px-3 py-1">
                          <input defaultValue={p.label} onChange={(e) => setEdit(`${p.pin}.GPIO_Label`, e.target.value)}
                            className="w-32 rounded border border-line bg-panel px-1.5 py-0.5 text-ink" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* timers */}
            {ioc.timers.length > 0 && (
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Timers</div>
                <div className="flex flex-col gap-2">
                  {ioc.timers.map((t) => (
                    <div key={t.name} className="rounded-lg border border-line bg-panel2/50 p-2">
                      <div className="mb-1 font-mono text-xs font-semibold text-ink">{t.name}</div>
                      <div className="flex flex-wrap gap-2">
                        {["Prescaler", "Period", "Pulse", "ClockDivision"].map((k) => (
                          <label key={k} className="flex flex-col gap-0.5 text-[10px] uppercase text-muted">{k}
                            <input defaultValue={t.params[k] ?? ""} placeholder="—"
                              onChange={(e) => setEdit(`${t.name}.${k}`, e.target.value)}
                              className="w-28 rounded border border-line bg-panel px-1.5 py-0.5 font-mono text-xs text-ink" />
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="text-[11px] text-muted">Edits are written to a copy on Save — open it in CubeMX and regenerate code. Timers show the common fields; other keys are preserved untouched.</div>
          </>}
        </CardContent>
      </Card>

      {/* power supply designer (TI Power Stage Designer function + WEBENCH bridge) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Zap className="h-4 w-4 text-accent" /> Power supply designer</CardTitle>
          <span className="text-xs text-muted">buck / boost stage — TI WEBENCH is online-only, opened pre-filled</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Topology
              <select value={topo} onChange={(e) => setTopo(e.target.value as "buck" | "boost")} className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm text-ink">
                <option value="buck">Buck (step-down)</option><option value="boost">Boost (step-up)</option>
              </select>
            </label>
            {([["vin", "Vin (V)"], ["vout", "Vout (V)"], ["iout", "Iout (A)"], ["fsw_khz", "fsw (kHz)"], ["ripple_pct", "ΔIL (%)"]] as const).map(([k, lbl]) => (
              <label key={k} className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">{lbl}
                <input type="number" value={ps[k]} onChange={(e) => setPs((s) => ({ ...s, [k]: parseFloat(e.target.value) }))}
                  className="w-24 rounded-lg border border-line bg-panel px-2 py-1.5 font-mono text-sm text-ink" />
              </label>
            ))}
            <label className="flex items-center gap-1.5 pb-1.5 text-[11px] font-semibold uppercase text-muted">
              <input type="checkbox" checked={isolated} onChange={(e) => setIsolated(e.target.checked)} className="accent-accent" />
              Isolated
            </label>
            <Button variant="primary" size="md" onClick={autoDesign}><Sparkles className="h-4 w-4" /> Auto-design</Button>
            <Button variant="secondary" size="md" onClick={computePower}>Sizing only</Button>
            <Button variant="secondary" size="md" onClick={openWebench}><ExternalLink className="h-4 w-4" /> Open in WEBENCH</Button>
          </div>

          {design?.ok && design.recommendation && (
            <div className="rounded-lg border border-accent/30 bg-accent/5 p-3">
              <div className="mb-2 text-sm"><span className="font-semibold text-ink capitalize">{design.recommendation.topology}</span>
                <span className="text-muted"> — {design.recommendation.reason}</span></div>
              {(design.parts?.length ?? 0) > 0 && (
                <div className="mb-2">
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Candidate TI parts</div>
                  <div className="flex flex-wrap gap-1.5">
                    {design.parts!.map((p) => (
                      <button key={p.mpn} onClick={() => openExternal(p.datasheet)} title={p.note}
                        className="inline-flex items-center gap-1 rounded-md border border-line bg-panel px-2 py-1 font-mono text-[11px] text-ink hover:border-accent">
                        {p.mpn}{p.integrated_fet ? " ·FET" : ""} <ExternalLink className="h-3 w-3 text-muted" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {design.compensation && (
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-muted">
                  <span>fc <span className="font-mono text-ink">{(design.compensation.crossover_hz / 1000).toFixed(1)} kHz</span></span>
                  <span>Rc <span className="font-mono text-ink">{design.compensation.type2.Rc_ohm} Ω</span></span>
                  <span>Cc1 <span className="font-mono text-ink">{design.compensation.type2.Cc1_nF} nF</span></span>
                  <span>Cc2 <span className="font-mono text-ink">{design.compensation.type2.Cc2_pF} pF</span></span>
                  <span className="text-muted">(type-II starting point)</span>
                </div>
              )}
            </div>
          )}
          {psOut?.ok && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[["Duty", psOut.duty_pct + " %"], ["Inductor", psOut.inductor_uH + " µH"],
                [topo === "boost" ? "Iin" : "Ipk", (topo === "boost" ? psOut.input_current_A : psOut.peak_current_A) + " A"],
                ["Cout (1%)", psOut.output_cap_uF_for_1pct + " µF"]].map(([k, v]) => (
                <div key={k as string} className="rounded-lg border border-line bg-panel2/60 px-3 py-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{k}</div>
                  <div className="mt-0.5 font-mono text-sm text-ink">{v}</div>
                </div>
              ))}
              {psOut.note && <div className="col-span-full text-[11px] text-muted">{psOut.note}</div>}
            </div>
          )}
          {psOut && !psOut.ok && <div className="text-xs text-danger">{psOut.error}</div>}

          {/* SPICE verification — simulate the power stage and PASS/FAIL the sizing */}
          <div className="mt-1 border-t border-line pt-3">
            <div className="mb-2 flex flex-wrap items-end gap-3">
              <div className="mr-1 flex items-center gap-2 text-[13px] font-semibold text-ink"><FlaskConical className="h-4 w-4 text-accent" /> Verify in SPICE</div>
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">L (µH)
                <input type="number" value={sim.L_uH} onChange={(e) => setSim((s) => ({ ...s, L_uH: parseFloat(e.target.value) }))}
                  className="w-24 rounded-lg border border-line bg-panel px-2 py-1.5 font-mono text-sm text-ink" />
              </label>
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Cout (µF)
                <input type="number" value={sim.Cout_uF} onChange={(e) => setSim((s) => ({ ...s, Cout_uF: parseFloat(e.target.value) }))}
                  className="w-24 rounded-lg border border-line bg-panel px-2 py-1.5 font-mono text-sm text-ink" />
              </label>
              <Button variant="primary" size="md" onClick={verifyInSpice} disabled={simBusy || !spiceEngine}>
                <FlaskConical className={`h-4 w-4 ${simBusy ? "animate-pulse" : ""}`} /> {simBusy ? "Simulating…" : `Verify (${spiceEngine || "no engine"})`}
              </Button>
              <span className="text-[11px] text-muted">runs a transient sim and checks ripple / inductor / efficiency</span>
            </div>

            {sv?.ok && (
              <div className={`rounded-lg border p-3 ${sv.verified ? "border-verified/40 bg-verified/5" : "border-unverified/40 bg-unverified/5"}`}>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                  {sv.verified ? <CheckCircle2 className="h-4 w-4 text-verified" /> : <XCircle className="h-4 w-4 text-unverified" />}
                  <span className={sv.verified ? "text-verified" : "text-unverified"}>{sv.verified ? "VERIFIED" : "FAILS TARGETS"}</span>
                  <span className="text-xs font-normal text-muted">· {sv.engine} · {sv.topology}</span>
                </div>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                  {sv.checks?.map((c) => (
                    <div key={c.name} className="flex items-center gap-2 rounded-md border border-line bg-panel px-2.5 py-1.5 text-xs">
                      {c.pass ? <CheckCircle2 className="h-3.5 w-3.5 text-verified" /> : <XCircle className="h-3.5 w-3.5 text-danger" />}
                      <span className="text-muted">{c.name}</span>
                      <span className="ml-auto font-mono text-ink">{c.value} {c.unit}</span>
                      <span className="font-mono text-muted">{c.cmp} {c.limit}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-muted">
                  <span>Vout <span className="font-mono text-ink">{sv.metrics?.vout_mean} V</span></span>
                  <span>Ripple <span className="font-mono text-ink">{sv.metrics?.vout_ripple_mvpp} mVpp</span></span>
                  <span>IL ripple <span className="font-mono text-ink">{sv.metrics?.il_ripple_a} A ({sv.metrics?.il_ripple_pct}%)</span></span>
                  <span>η <span className="font-mono text-ink">{sv.metrics?.efficiency_pct ?? "—"} %</span></span>
                </div>
                <canvas ref={svCanvas} className="mt-2 h-[120px] w-full rounded-lg border border-line bg-screen" />
                {sv.note && <div className="mt-1 text-[11px] text-muted">{sv.note}</div>}
              </div>
            )}
            {sv && !sv.ok && (
              <div className="rounded-lg border border-unverified/40 bg-unverified/5 px-3 py-2 text-xs text-ink">
                {sv.error}{sv.install ? " — install LTspice (adi.com)" : ""}
              </div>
            )}
          </div>

          {/* Closed-loop stability — python-control margins on the designed compensator */}
          <div className="mt-1 border-t border-line pt-3">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <div className="mr-1 flex items-center gap-2 text-[13px] font-semibold text-ink"><FlaskConical className="h-4 w-4 text-accent" /> Loop margin</div>
              <Button variant="primary" size="md" onClick={verifyLoop} disabled={loopBusy || !loopAvail}>
                {loopBusy ? "Analyzing…" : "Verify loop (python-control)"}
              </Button>
              <span className="text-[11px] text-muted">
                {loopAvail ? "phase / gain margin of the type-II comp on a current-mode buck plant" : "install python-control to enable"}
              </span>
            </div>

            {loop?.ok && (
              <div className={`rounded-lg border p-3 ${loop.stable ? "border-verified/40 bg-verified/5" : "border-unverified/40 bg-unverified/5"}`}>
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
                  {loop.stable ? <CheckCircle2 className="h-4 w-4 text-verified" /> : <XCircle className="h-4 w-4 text-unverified" />}
                  <span className={loop.stable ? "text-verified" : "text-unverified"}>{loop.stable ? "STABLE" : "MARGIN LOW"}</span>
                  <span className="text-xs font-normal text-muted">· {loop.engine} · {loop.topology}</span>
                </div>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-3">
                  {loop.checks?.map((c) => (
                    <div key={c.name} className="flex items-center gap-2 rounded-md border border-line bg-panel px-2.5 py-1.5 text-xs">
                      {c.pass ? <CheckCircle2 className="h-3.5 w-3.5 text-verified" /> : <XCircle className="h-3.5 w-3.5 text-danger" />}
                      <span className="text-muted">{c.name}</span>
                      <span className="ml-auto font-mono text-ink">
                        {c.name === "Gain margin" && loop.metrics?.gain_margin_infinite ? "∞" : c.value ?? "—"} {c.unit}
                      </span>
                      <span className="font-mono text-muted">{c.cmp} {c.limit}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-muted">
                  <span>crossover <span className="font-mono text-ink">{loop.metrics?.crossover_hz ? (loop.metrics.crossover_hz / 1000).toFixed(1) : "—"} kHz</span></span>
                  <span>target fc <span className="font-mono text-ink">{loop.metrics?.target_crossover_hz ? (loop.metrics.target_crossover_hz / 1000).toFixed(1) : "—"} kHz</span></span>
                  <span>Ri <span className="font-mono text-ink">{loop.assumptions?.ri_ohm} Ω</span></span>
                  <span>Vref <span className="font-mono text-ink">{loop.assumptions?.vref_v} V</span></span>
                </div>
                <canvas ref={bodeCanvas} className="mt-2 h-[140px] w-full rounded-lg border border-line bg-screen" />
                {loop.note && <div className="mt-1 text-[11px] text-muted">{loop.note}</div>}
              </div>
            )}
            {loop && !loop.ok && (
              <div className="rounded-lg border border-unverified/40 bg-unverified/5 px-3 py-2 text-xs text-ink">
                {loop.error}{loop.install ? ` — ${loop.install}` : ""}
              </div>
            )}
          </div>

          {/* Magnetics — OpenMagnetics/MKF real-catalog core+winding design with computed losses */}
          <div className="mt-1 border-t border-line pt-3">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <div className="mr-1 flex items-center gap-2 text-[13px] font-semibold text-ink"><Zap className="h-4 w-4 text-accent" /> Inductor magnetics</div>
              <Button variant="primary" size="md" onClick={designMagnetics} disabled={magBusy || !magDb?.available}>
                {magBusy ? "Searching cores…" : `Design magnetics (L=${sim.L_uH} µH)`}
              </Button>
              {magDb?.available ? (
                <span className="text-[11px] text-muted">{magDb.core_materials} materials · {magDb.core_shapes} shapes · {magDb.wires} wires · {magDb.core_manufacturers?.length} vendors</span>
              ) : (
                <span className="text-[11px] text-muted">install PyOpenMagnetics to enable</span>
              )}
            </div>

            {mag?.ok && (mag.designs?.length ?? 0) > 0 && (
              <div className="rounded-lg border border-accent/30 bg-accent/5 p-3">
                <div className="mb-2 text-[11px] text-muted">
                  {mag.engine} · {mag.mode} · L {mag.requirement?.inductance_uH} µH, Idc {mag.requirement?.i_dc_a} A, Ipk {mag.requirement?.i_peak_a} A @ {mag.requirement?.fsw_khz} kHz
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-[10px] uppercase tracking-wide text-muted">
                      <tr>
                        <th className="py-1 pr-3">Core</th><th className="pr-3">Material</th><th className="pr-3">Turns</th>
                        <th className="pr-3">Gap</th><th className="pr-3">P<sub>core</sub></th><th className="pr-3">P<sub>cu</sub></th>
                        <th className="pr-3">P<sub>tot</sub></th><th>Score</th>
                      </tr>
                    </thead>
                    <tbody className="font-mono">
                      {mag.designs!.map((d, i) => (
                        <tr key={i} className="border-t border-line/60">
                          <td className="py-1 pr-3 text-ink">{d.core_shape}</td>
                          <td className="pr-3 text-muted">{d.core_material}</td>
                          <td className="pr-3 text-ink">{d.turns.join("+")}</td>
                          <td className="pr-3 text-muted">{d.gap_mm != null ? `${d.gap_mm} mm` : "—"}</td>
                          <td className="pr-3 text-ink">{d.core_loss_w != null ? `${(d.core_loss_w * 1000).toFixed(0)} mW` : "—"}</td>
                          <td className="pr-3 text-ink">{d.winding_loss_w != null ? `${(d.winding_loss_w * 1000).toFixed(0)} mW` : "—"}</td>
                          <td className="pr-3 font-semibold text-ink">{d.total_loss_w != null ? `${(d.total_loss_w * 1000).toFixed(0)} mW` : "—"}</td>
                          <td className="text-muted">{d.score ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {mag.note && <div className="mt-2 text-[11px] text-muted">{mag.note}</div>}
              </div>
            )}
            {mag && !mag.ok && (
              <div className="rounded-lg border border-unverified/40 bg-unverified/5 px-3 py-2 text-xs text-ink">
                {mag.error}{mag.install ? ` — ${mag.install}` : ""}
              </div>
            )}
          </div>

          {/* Capacitor bank — RMS ripple, parallels, ESR loss, derating for input + output caps */}
          <div className="mt-1 border-t border-line pt-3">
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <div className="mr-1 flex items-center gap-2 text-[13px] font-semibold text-ink"><Zap className="h-4 w-4 text-accent" /> Capacitor bank</div>
              <Button variant="primary" size="md" onClick={sizeCaps}>Size caps (22 µF MLCC)</Button>
              <span className="text-[11px] text-muted">RMS ripple · parallels · ESR loss · voltage derating (input + output)</span>
            </div>
            {caps?.ok && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {([["Input cap", caps.input_cap], ["Output cap", caps.output_cap]] as const).map(([label, b]) => b && (
                  <div key={label} className={`rounded-lg border p-3 ${b.ok ? "border-verified/40 bg-verified/5" : "border-unverified/40 bg-unverified/5"}`}>
                    <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold">
                      {b.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-verified" /> : <XCircle className="h-3.5 w-3.5 text-unverified" />}
                      <span className="text-ink">{label}</span>
                      <span className="ml-auto font-mono text-muted">{b.parallel_count}× → {b.total_capacitance_uF} µF</span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[11px] text-muted">
                      <span>Irms <span className="text-ink">{b.rms_current_a} A</span></span>
                      <span>ESR <span className="text-ink">{b.total_esr_mohm} mΩ</span></span>
                      <span>P<sub>ESR</sub> <span className="text-ink">{(b.esr_loss_w * 1000).toFixed(1)} mW</span></span>
                      <span>ΔT <span className="text-ink">{b.temp_rise_c != null ? `${b.temp_rise_c} °C` : "—"}</span></span>
                      <span>V<sub>ripple</sub> <span className="text-ink">{b.ripple_voltage_mvpp} mV</span></span>
                      <span className={b.derating_ok ? "" : "text-danger"}>V<sub>derate</sub> <span className={b.derating_ok ? "text-ink" : "text-danger"}>{b.v_applied}/{b.v_derated_limit} V</span></span>
                    </div>
                  </div>
                ))}
                {caps.note && <div className="col-span-full text-[11px] text-muted">{caps.note}</div>}
              </div>
            )}
            {caps && !caps.ok && <div className="rounded-lg border border-unverified/40 bg-unverified/5 px-3 py-2 text-xs text-ink">{caps.error}</div>}
          </div>
        </CardContent>
      </Card>

      {/* Digi-Key WEBENCH adapter — the only public route to WEBENCH-backed part data */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Zap className="h-4 w-4 text-accent" /> Digi-Key WEBENCH data
            {dk && (
              <span className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                dk.connected ? "bg-verified/15 text-verified" : dk.configured ? "bg-unverified/15 text-unverified" : "bg-panel2 text-muted"}`}>
                {dk.connected ? "connected" : dk.configured ? "keys set" : "not connected"}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-[12px] leading-relaxed text-muted">
            WEBENCH is TI's cloud tool — no offline build, no public API. Digi-Key's developer API is the supported route to
            WEBENCH-backed part data and per-part WEBENCH launch links. Register a free app at{" "}
            <button onClick={() => openExternal("https://developer.digikey.com/")} className="text-accent hover:underline">developer.digikey.com</button>,
            then Connect below. Keys are held in memory for this session only — never written to the project.
          </p>
          {!dk?.connected && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Client ID
                <input value={dkId} onChange={(e) => setDkId(e.target.value)} placeholder="OAuth client id"
                  className="w-56 rounded-lg border border-line bg-panel px-2 py-1.5 font-mono text-xs text-ink" />
              </label>
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Client Secret
                <input type="password" value={dkSecret} onChange={(e) => setDkSecret(e.target.value)} placeholder="OAuth client secret"
                  className="w-56 rounded-lg border border-line bg-panel px-2 py-1.5 font-mono text-xs text-ink" />
              </label>
              <Button variant="primary" size="md" onClick={dkConnect} disabled={!dkId || !dkSecret}>Connect</Button>
            </div>
          )}
          {dk?.connected && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Part search
                <input value={dkQuery} onChange={(e) => setDkQuery(e.target.value)} placeholder="e.g. TPS54560 / buck 3.3V"
                  className="w-64 rounded-lg border border-line bg-panel px-2 py-1.5 font-mono text-sm text-ink" />
              </label>
              <Button variant="primary" size="md" onClick={dkSearch}>Search</Button>
            </div>
          )}
          {dkParts.length > 0 && (
            <div className="divide-y divide-line rounded-lg border border-line">
              {dkParts.map((p) => (
                <div key={p.mpn} className="flex items-center gap-3 px-3 py-2 text-xs">
                  <span className="font-mono text-ink">{p.mpn}</span>
                  <span className="truncate text-muted">{p.description}</span>
                  <div className="ml-auto flex shrink-0 gap-2">
                    {p.datasheet && <button onClick={() => openExternal(p.datasheet!)} className="text-accent hover:underline">datasheet</button>}
                    {p.webench && <button onClick={() => openExternal(p.webench!)} className="inline-flex items-center gap-1 text-accent hover:underline">WEBENCH <ExternalLink className="h-3 w-3" /></button>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
