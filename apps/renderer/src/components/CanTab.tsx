import { useState } from "react";
import { baseUrl, canDecode, type CanDecoded } from "../lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const SAMPLE_DBC = `BO_ 256 EngineData: 8 ECU
 SG_ RPM : 24|16@1+ (0.25,0) [0|16383.75] "rpm" ECU
 SG_ Temp : 40|8@1+ (1,-40) [-40|215] "degC" ECU`;

const SAMPLE_LOG = `256 00 00 00 40 1F 5A 00 00
256 00 00 00 00 3E 6E 00 00`;

export function CanTab() {
  const [dbc, setDbc] = useState(SAMPLE_DBC);
  const [log, setLog] = useState(SAMPLE_LOG);
  const [res, setRes] = useState<{ ok: boolean; decoded?: CanDecoded[]; error?: string } | null>(null);

  async function decode() {
    const b = await baseUrl();
    setRes(await canDecode(b, dbc, log));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>CAN bus — offline DBC decode</CardTitle>
        <span className="text-xs text-muted">paste a DBC + a CAN log (id + hex bytes)</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            DBC
            <textarea value={dbc} onChange={(e) => setDbc(e.target.value)} rows={8}
              className="rounded-lg border border-line bg-panel2 p-2 font-mono text-xs text-ink" />
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-muted">
            CAN log
            <textarea value={log} onChange={(e) => setLog(e.target.value)} rows={8}
              className="rounded-lg border border-line bg-panel2 p-2 font-mono text-xs text-ink" />
          </label>
        </div>
        <button onClick={decode} className="self-start rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90">Decode</button>

        {res && res.ok === false && <div className="rounded-md border border-danger/40 px-3 py-2 text-xs text-danger">{res.error}</div>}
        {res && res.ok && (
          <table className="w-full text-left text-xs">
            <thead className="text-muted">
              <tr><th className="py-1 pr-3">ID</th><th className="py-1 pr-3">Message</th><th className="py-1 pr-3">Signals</th></tr>
            </thead>
            <tbody className="font-mono">
              {(res.decoded ?? []).map((d, i) => (
                <tr key={i} className="border-t border-line align-top">
                  <td className="py-1 pr-3 text-ink">{d.id}</td>
                  <td className="py-1 pr-3 text-muted">{d.name ?? "(unknown id)"}</td>
                  <td className="py-1 pr-3 text-ink">
                    {Object.entries(d.signals).map(([k, v]) => `${k}=${v.value}${v.unit ? " " + v.unit : ""}`).join("   ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
