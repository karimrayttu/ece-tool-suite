import { Power, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { baseUrl, openWs, psuApply, psuOff, psuPreview, type PsuFrame, type Verdict } from "../lib/api";
import { fmtEng } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { NumField } from "./ui/field";
import { Knob, Led, SegMeter, VuMeter } from "./ui/instrument";
import { ConnectionBar } from "./ConnectionBar";

const VTONE: Record<Verdict, "verified" | "unverified" | "danger"> = { ALLOW: "verified", REQUIRE_CONFIRM: "unverified", BLOCK: "danger" };

export function PsuPanel() {
  const [base, setBase] = useState<string | null>(null);
  const [frame, setFrame] = useState<PsuFrame | null>(null);
  const [vset, setVset] = useState(3.3);
  const [iset, setIset] = useState(0.5);
  const [ovp, setOvp] = useState(3.6);
  const [ocp, setOcp] = useState(0.6);
  const [dutV, setDutV] = useState(3.6);
  const [dutI, setDutI] = useState(0.6);
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
      ws = openWs<PsuFrame>(b, "/ws/psu", (f) => !stop && setFrame(f), () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);

  const bodyVals = { vset, iset, ovp, ocp, dut_max_v: dutV, dut_max_i: dutI };

  useEffect(() => {
    if (!base) return;
    (async () => setVerdict(await psuPreview(base, bodyVals)))();
  }, [base, vset, iset, ovp, ocp, dutV, dutI]); // eslint-disable-line react-hooks/exhaustive-deps

  async function enable() {
    if (!base) return;
    const r = await psuApply(base, { ...bodyVals, confirm });
    setNote(r.connected === false ? "PSU not connected" : r.ok ? "output ENABLED" : `aborted: ${r.summary}`);
  }
  async function off() { if (base) { await psuOff(base); setNote("output OFF (manual)"); } }

  const connected = Boolean(frame?.connected);
  const on = Boolean(frame?.output_on);

  return (
    <div className="flex flex-col gap-3">
      <ConnectionBar role="psu" />
      <Card>
        <CardHeader>
          <CardTitle>Power Supply</CardTitle>
          {connected && <Badge tone={on ? "verified" : "muted"}>{on ? "OUTPUT ON" : "output off"}</Badge>}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {/* analog power-hardware face: VU needle for volts, LED bar for amps */}
          <div className="flex flex-wrap items-center justify-center gap-8 rounded-xl2 border border-line bg-panel2/60 px-4 py-4">
            <VuMeter value={connected && frame?.vout != null && ovp > 0 ? frame.vout / ovp : 0}
              label="V" legend={connected && frame?.vout != null ? `measured ${fmtEng(frame.vout, "V")} / OVP ${fmtEng(ovp, "V")}` : "measured voltage"} width={210} />
            <div className="flex flex-col items-center gap-2">
              <div className="seg-readout--amber seg-readout text-3xl">
                {connected && frame?.iout != null ? fmtEng(frame.iout, "A") : "— A"}
              </div>
              <SegMeter value={connected && frame?.iout != null && ocp > 0 ? frame.iout / ocp : 0} segments={28} />
              <span className="module-label !text-[9px]">current · OCP {fmtEng(ocp, "A")}</span>
              <span className="mt-1 inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted">
                <Led color={on ? "green" : "red"} on={connected} /> {on ? "output on" : "output off"}
              </span>
            </div>
          </div>

          {/* set knobs (drag ↑↓ · shift fine · dbl-click reset) + protection entry */}
          <div className="flex flex-wrap items-center gap-6">
            <Knob label="Vset" value={vset} min={0} max={30} step={0.05} defaultValue={3.3}
              size="lg" color="#e7ecf3" unit="V" showScale onChange={setVset} />
            <Knob label="I limit" value={iset} min={0} max={5} step={0.01} defaultValue={0.5}
              size="lg" color="#fbbf24" unit="A" showScale onChange={setIset} />
            <div className="mx-1 h-14 w-px bg-line" />
            <div className="flex flex-wrap items-end gap-3">
              <NumField label="Vset (V)" value={vset} set={setVset} />
              <NumField label="Ilim (A)" value={iset} set={setIset} step={0.01} />
              <NumField label="OVP (V)" value={ovp} set={setOvp} />
              <NumField label="OCP (A)" value={ocp} set={setOcp} step={0.01} />
              <NumField label="DUT max V" value={dutV} set={setDutV} />
              <NumField label="DUT max I" value={dutI} set={setDutI} step={0.01} />
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
          {!connected && <div className="text-xs text-muted">Connect a Keysight power supply above. OVP/OCP are set + verified before the output is ever enabled.</div>}
        </CardContent>
      </Card>
    </div>
  );
}
