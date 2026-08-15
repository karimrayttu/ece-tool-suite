import { Power, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { baseUrl, eloadApply, eloadOff, eloadPreview, openWs, type EloadFrame, type Verdict } from "../lib/api";
import { fmtEng } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { NumField } from "./ui/field";
import { ConnectionBar } from "./ConnectionBar";

const VTONE: Record<Verdict, "verified" | "unverified" | "danger"> = { ALLOW: "verified", REQUIRE_CONFIRM: "unverified", BLOCK: "danger" };
const MODES = [["CURR", "CC"], ["VOLT", "CV"], ["RES", "CR"], ["POW", "CP"]];
const LEVEL_UNIT: Record<string, string> = { CURR: "A", VOLT: "V", RES: "Ω", POW: "W" };

export function EloadPanel() {
  const [base, setBase] = useState<string | null>(null);
  const [frame, setFrame] = useState<EloadFrame | null>(null);
  const [mode, setMode] = useState("CURR");
  const [level, setLevel] = useState(0.5);
  const [ocp, setOcp] = useState(2.0);
  const [dutV, setDutV] = useState(30);
  const [dutI, setDutI] = useState(2.0);
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
      ws = openWs<EloadFrame>(b, "/ws/eload", (f) => !stop && setFrame(f), () => {});
    })();
    return () => { stop = true; ws?.close(); };
  }, []);

  const bodyVals = { mode, level, ocp, dut_max_v: dutV, dut_max_i: dutI };

  useEffect(() => {
    if (!base) return;
    (async () => setVerdict(await eloadPreview(base, bodyVals)))();
  }, [base, mode, level, ocp, dutV, dutI]); // eslint-disable-line react-hooks/exhaustive-deps

  async function enable() {
    if (!base) return;
    const r = await eloadApply(base, { ...bodyVals, confirm });
    setNote(r.connected === false ? "e-load not connected" : r.ok ? "input ENABLED" : `aborted: ${r.summary}`);
  }
  async function off() { if (base) { await eloadOff(base); setNote("input OFF (manual)"); } }

  const connected = Boolean(frame?.connected);
  const on = Boolean(frame?.input_on);

  return (
    <div className="flex flex-col gap-3">
      <ConnectionBar role="eload" />
      <Card>
        <CardHeader>
          <CardTitle>Electronic Load</CardTitle>
          {connected && <Badge tone={on ? "verified" : "muted"}>{on ? "INPUT ON" : "input off"}</Badge>}
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-xl2 border border-line bg-panel2 px-4 py-5 text-center">
              <div className="text-[11px] text-muted">DUT voltage</div>
              <div className="font-mono text-4xl text-ink">{connected && frame?.vout != null ? fmtEng(frame.vout, "V") : "—"}</div>
            </div>
            <div className="rounded-xl2 border border-line bg-panel2 px-4 py-5 text-center">
              <div className="text-[11px] text-muted">sink current</div>
              <div className="font-mono text-4xl text-ink">{connected && frame?.iout != null ? fmtEng(frame.iout, "A") : "—"}</div>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-muted">Mode
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink">
                {MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <NumField label={`Level (${LEVEL_UNIT[mode] ?? "A"})`} value={level} set={setLevel} step={0.01} />
            <NumField label="OCP (A)" value={ocp} set={setOcp} step={0.01} />
            <div className="mx-1 h-8 w-px bg-line" />
            <NumField label="DUT max V" value={dutV} set={setDutV} />
            <NumField label="DUT max I" value={dutI} set={setDutI} step={0.01} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {verdict && <Badge tone={VTONE[verdict.overall]}>{verdict.overall}</Badge>}
            <label className="flex items-center gap-2 text-xs text-sim">
              <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              <ShieldAlert className="h-3.5 w-3.5" /> Confirm sink
            </label>
            <button onClick={enable} disabled={!confirm || (verdict ? !verdict.ok_to_run : true)}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90 disabled:cursor-not-allowed disabled:bg-line disabled:text-muted">
              <Power className="h-3.5 w-3.5" /> Enable input
            </button>
            <button onClick={off} className="rounded-md bg-danger/20 px-3 py-1.5 text-xs font-semibold text-danger hover:bg-danger/30">Input OFF</button>
            {note && <span className="text-[11px] text-muted">{note}</span>}
          </div>
          {!connected && <div className="text-xs text-muted">Connect a Keysight electronic load above. OCP is set + verified before the input is enabled.</div>}
        </CardContent>
      </Card>
    </div>
  );
}
