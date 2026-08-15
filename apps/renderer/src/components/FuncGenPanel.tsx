import { Power, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { awgApply, awgOff, awgPreview, baseUrl, openWs, type AwgFrame, type Verdict } from "../lib/api";
import { fmtEng } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { NumField } from "./ui/field";
import { Knob } from "./ui/instrument";
import { ConnectionBar } from "./ConnectionBar";

const VTONE: Record<Verdict, "verified" | "unverified" | "danger"> = { ALLOW: "verified", REQUIRE_CONFIRM: "unverified", BLOCK: "danger" };
const SHAPES = ["SIN", "SQU", "RAMP", "PULS", "NOIS", "DC"];

export function FuncGenPanel() {
  const [base, setBase] = useState<string | null>(null);
  const [frame, setFrame] = useState<AwgFrame | null>(null);
  const [func, setFunc] = useState("SIN");
  const [freq, setFreq] = useState(1000);
  const [vpp, setVpp] = useState(1.0);
  const [offset, setOffset] = useState(0.0);
  const [dutV, setDutV] = useState(3.6);
  const [dutI, setDutI] = useState(1.0);
  const [confirm, setConfirm] = useState(false);
  const [verdict, setVerdict] = useState<{ overall: Verdict; ok_to_run: boolean } | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    let ws: WebSocket | null = null;
    let stop = false;
    (async () => {
      const b = await baseUrl();
      if (stop) return;
      setBase(b);
      ws = openWs<AwgFrame>(b, "/ws/awg", (f) => !stop && setFrame(f), () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);

  const bodyVals = { func, freq, vpp, offset, dut_max_v: dutV, dut_max_i: dutI };

  useEffect(() => {
    if (!base) return;
    (async () => setVerdict(await awgPreview(base, bodyVals)))();
  }, [base, func, freq, vpp, offset, dutV, dutI]); // eslint-disable-line react-hooks/exhaustive-deps

  async function enable() {
    if (!base) return;
    const r = await awgApply(base, { ...bodyVals, confirm });
    setNote(r.connected === false ? "AWG not connected" : r.ok ? "output ENABLED" : `aborted: ${r.summary}`);
  }
  async function off() { if (base) { await awgOff(base); setNote("output OFF (manual)"); } }

  const connected = Boolean(frame?.connected);
  const on = Boolean(frame?.output_on);

  return (
    <div className="flex flex-col gap-3">
      <ConnectionBar role="awg" />
      <Card>
        <CardHeader>
          <CardTitle>Function Generator</CardTitle>
          {connected && <Badge tone={on ? "verified" : "muted"}>{on ? "OUTPUT ON" : "output off"}</Badge>}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="screen-frame">
            <div className="crt-screen px-4 py-4 text-center">
              <span className="seg-readout--cyan seg-readout text-lg">
                {connected ? `${frame?.func ?? func} · ${frame?.freq != null ? fmtEng(frame.freq, "Hz") : "—"} · ${frame?.vpp != null ? fmtEng(frame.vpp, "Vpp") : "—"} · offset ${frame?.offset != null ? fmtEng(frame.offset, "V") : "—"}` : "no generator"}
              </span>
            </div>
          </div>

          {/* hardware row: shape keycaps + rotary knobs (drag ↑↓, shift = fine, dbl-click = reset) */}
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex flex-col gap-1.5">
              <span className="module-label !text-[9px]">Shape</span>
              <div className="grid grid-cols-3 gap-1.5">
                {SHAPES.map((s) => (
                  <button key={s} onClick={() => setFunc(s)}
                    className={`rounded-md border px-2.5 py-1.5 font-mono text-[10.5px] font-semibold transition-all ${
                      func === s
                        ? "border-accent/60 bg-accent/15 text-accent shadow-glow-cyan"
                        : "border-line bg-panel2 text-muted hover:text-ink"}`}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
            <Knob label="Frequency" value={Math.log10(Math.max(1, freq))} min={0} max={7}
              defaultValue={3} size="lg" color="#2dd4ea"
              format={(v) => fmtEng(Math.pow(10, v), "Hz")}
              onChange={(v) => setFreq(Number(Math.pow(10, v).toPrecision(3)))} />
            <Knob label="Amplitude" value={vpp} min={0} max={10} step={0.05} defaultValue={1}
              size="lg" color="#fbbf24" unit="Vpp" onChange={setVpp} />
            <Knob label="Offset" value={offset} min={-5} max={5} step={0.05} defaultValue={0}
              size="lg" color="#a78bfa" unit="V" onChange={setOffset} />
            <div className="mx-1 h-14 w-px bg-line" />
            <div className="flex items-end gap-3">
              <NumField label="Freq (Hz)" value={freq} set={setFreq} step={100} width="w-28" />
              <NumField label="DUT max V" value={dutV} set={setDutV} width="w-28" />
              <NumField label="DUT max I" value={dutI} set={setDutI} step={0.01} width="w-28" />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {verdict && <Badge tone={VTONE[verdict.overall]}>{verdict.overall}</Badge>}
            <label className="flex items-center gap-2 text-xs text-sim">
              <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              <ShieldAlert className="h-3.5 w-3.5" /> Confirm energize
            </label>
            <button onClick={enable} disabled={!confirm || (verdict ? !verdict.ok_to_run : true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90 disabled:cursor-not-allowed disabled:bg-line disabled:text-muted">
              <Power className="h-3.5 w-3.5" /> Enable output
            </button>
            <button onClick={off} className="rounded-md bg-danger/20 px-3 py-1.5 text-xs font-semibold text-danger hover:bg-danger/30">Output OFF</button>
            {note && <span className="text-[11px] text-muted">{note}</span>}
          </div>
          {!connected && <div className="text-xs text-muted">Connect a Keysight function generator above. Output voltage limits are set + verified before enabling.</div>}
        </CardContent>
      </Card>
    </div>
  );
}
