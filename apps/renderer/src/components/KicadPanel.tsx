import { useState } from "react";
import { analyzeKicad, baseUrl } from "../lib/api";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const SAMPLE = `(kicad_sch (version 20240130)
  (symbol (lib_id "Regulator_Linear:AMS1117-3.3") (at 100 100 0)
    (property "Reference" "U1") (property "Value" "AMS1117-3.3"))
  (symbol (lib_id "Device:R") (at 50 50 0)
    (property "Reference" "R1") (property "Value" "10k"))
  (symbol (lib_id "Device:C") (at 60 60 0)
    (property "Reference" "C1") (property "Value" "100nF"))
  (label "SDA" (at 10 10 0))
  (global_label "VCC" (at 20 20 0)))`;

interface Analysis {
  ok?: boolean;
  error?: string;
  component_count?: number;
  components?: { ref: string; value: string; lib_id: string }[];
  nets?: string[];
  detectors?: { regulators?: string[]; decoupling_caps?: number; resistors?: number; capacitors?: number; ics?: number };
}

export function KicadPanel() {
  const [text, setText] = useState(SAMPLE);
  const [res, setRes] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);

  async function analyze() {
    setBusy(true);
    const b = await baseUrl();
    setRes((await analyzeKicad(b, text)) as Analysis);
    setBusy(false);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>KiCad schematic analyze</CardTitle>
        <span className="text-xs text-muted">paste a .kicad_sch — pure parser, no KiCad needed</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={8}
          className="w-full rounded-lg border border-line bg-panel2 p-2 font-mono text-xs text-ink"
        />
        <button onClick={analyze} className="self-start rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90">
          {busy ? "Analyzing…" : "Analyze"}
        </button>

        {res && res.ok === false && (
          <div className="rounded-md border border-danger/40 px-3 py-2 text-xs text-danger">{res.error}</div>
        )}
        {res && res.ok !== false && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge tone="accent">{res.component_count} components</Badge>
              {res.detectors?.regulators?.length ? <Badge tone="verified">reg: {res.detectors.regulators.join(", ")}</Badge> : null}
              <Badge tone="muted">decoupling caps: {res.detectors?.decoupling_caps ?? 0}</Badge>
              <Badge tone="muted">R:{res.detectors?.resistors ?? 0} C:{res.detectors?.capacitors ?? 0} U:{res.detectors?.ics ?? 0}</Badge>
            </div>
            <table className="w-full text-left text-xs">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3">Ref</th>
                  <th className="py-1 pr-3">Value</th>
                  <th className="py-1 pr-3">Library</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {(res.components ?? []).map((c) => (
                  <tr key={c.ref} className="border-t border-line">
                    <td className="py-1 pr-3 text-ink">{c.ref}</td>
                    <td className="py-1 pr-3 text-muted">{c.value}</td>
                    <td className="py-1 pr-3 text-muted">{c.lib_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {res.nets?.length ? <div className="text-[11px] text-muted">nets: {res.nets.join(", ")}</div> : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
