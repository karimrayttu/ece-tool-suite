import { useEffect, useState } from "react";
import { baseUrl, listCalcs, runCalc, type CalcMeta } from "../lib/api";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { NumberField } from "./ui/field";

export function CalculatorsPanel() {
  const [base, setBase] = useState<string | null>(null);
  const [calcs, setCalcs] = useState<CalcMeta[]>([]);
  const [sel, setSel] = useState<string>("");
  const [vals, setVals] = useState<Record<string, number>>({});
  const [result, setResult] = useState<unknown>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      const c = await listCalcs(b);
      setBase(b);
      setCalcs(c);
      if (c[0]) {
        setSel(c[0].id);
        setVals(Object.fromEntries(c[0].fields.map((f) => [f.k, f.default])));
      }
    })();
  }, []);

  const cur = calcs.find((c) => c.id === sel);

  function pick(id: string) {
    const c = calcs.find((x) => x.id === id);
    setSel(id);
    setResult(null);
    setErr(null);
    if (c) setVals(Object.fromEntries(c.fields.map((f) => [f.k, f.default])));
  }

  async function run() {
    if (!base || !cur) return;
    const r = await runCalc(base, sel, vals);
    if (r.ok) {
      setResult(r.result);
      setErr(null);
    } else {
      setErr(r.error ?? "error");
      setResult(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Design calculators</CardTitle>
        <span className="text-xs text-muted">pure — no keys, no hardware</span>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-1.5">
          {calcs.map((c) => (
            <button
              key={c.id}
              onClick={() => pick(c.id)}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                c.id === sel ? "bg-accent text-white shadow-sm" : "border border-line bg-panel text-muted hover:bg-panel2 hover:text-ink",
              )}
            >
              {c.name}
            </button>
          ))}
        </div>

        {cur && (
          <div className="flex flex-wrap items-end gap-3 rounded-lg border border-line bg-panel2/50 p-3">
            {cur.fields.map((f) => (
              <NumberField key={f.k} label={f.label} value={vals[f.k] ?? 0} step="any" wrapClassName="w-36"
                onValue={(n) => setVals((v) => ({ ...v, [f.k]: n }))} />
            ))}
            <Button variant="primary" size="md" onClick={run}>Compute</Button>
          </div>
        )}

        {err && <div className="rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger">{err}</div>}
        {result != null && (
          <div className="rounded-lg border border-line bg-panel2/50 p-3">
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Result</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
              {typeof result === "object" && result !== null
                ? Object.entries(result as Record<string, unknown>).map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1">
                      <span className="text-xs text-muted">{k}</span>
                      <span className="font-mono text-sm font-medium text-ink">{typeof v === "number" ? (Number.isInteger(v) ? v : v.toPrecision(5)) : String(v)}</span>
                    </div>
                  ))
                : <span className="font-mono text-sm text-ink">{String(result)}</span>}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
