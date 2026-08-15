import { Check, Cpu, X } from "lucide-react";
import { useEffect, useState } from "react";
import { agentRun, agentStatus, baseUrl, type AgentStatus } from "../lib/api";
import { cn } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

function Chip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs", ok ? "text-verified" : "text-muted")}>
      {ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
      {label}
    </span>
  );
}

export function AgentPanel() {
  const [base, setBase] = useState<string | null>(null);
  const [st, setSt] = useState<AgentStatus | null>(null);
  const [prompt, setPrompt] = useState("Measure CH1 Vpp and report it with its provenance.");
  const [out, setOut] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      setBase(b);
      setSt(await agentStatus(b));
    })();
  }, []);

  async function run() {
    if (!base) return;
    setBusy(true);
    const r = await agentRun(base, prompt);
    setOut(r.ok ? (r.events ?? []).join("\n") : r.error ?? "error");
    setBusy(false);
  }

  const ready = Boolean(st?.ready);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-accent" /> Claude Code + MCP bridge (Layer B)
        </CardTitle>
        <Badge tone={ready ? "verified" : "muted"}>{ready ? "ready" : "not ready"}</Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <Chip ok={Boolean(st?.sdk_installed)} label="Agent SDK" />
          <Chip ok={Boolean(st?.claude_cli)} label="claude CLI" />
          <Chip ok={Boolean(st?.api_key)} label="API key" />
        </div>
        <div className="text-[11px] text-muted">
          Exposed (read-only) tools: <span className="font-mono text-ink">{(st?.exposed_tools ?? []).join(", ") || "…"}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input value={prompt} onChange={(e) => setPrompt(e.target.value)} disabled={!ready}
            className="min-w-[220px] flex-1 rounded-md border border-line bg-panel px-3 py-1.5 text-sm text-ink disabled:cursor-not-allowed" />
          <button onClick={run} disabled={!ready || busy}
            className={cn("rounded-md px-3 py-1.5 text-xs font-semibold", !ready || busy ? "cursor-not-allowed bg-line text-muted" : "bg-accent text-bg hover:opacity-90")}>
            {busy ? "Running…" : "Run agent"}
          </button>
        </div>
        {!ready && (
          <div className="rounded-md border border-sim/40 bg-panel px-3 py-2 text-[11px] text-sim">
            Layer B needs the <code className="font-mono">claude</code> CLI
            (<code className="font-mono">npm i -g @anthropic-ai/claude-code</code>) and an API key. The agent only ever sees
            the read-only surface — it cannot energize or run a safety-gated preset.
          </div>
        )}
        {out && <pre className="overflow-x-auto rounded-lg border border-line bg-panel2 p-3 font-mono text-[11px] text-ink">{out}</pre>}
      </CardContent>
    </Card>
  );
}
