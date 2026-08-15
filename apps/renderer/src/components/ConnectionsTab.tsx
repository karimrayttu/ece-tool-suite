import { AlertTriangle, Bot, Check, Copy, PlugZap, RefreshCw, Search, Terminal } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  baseUrl, connectInstrument, disconnectInstrument, getHealth, getVisaResources,
  ioAutoconnect, ioDetails, ioScpi, mcpInfo, verifyInstrument,
  type IoDetails, type McpInfo,
} from "../lib/api";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const ROLES = ["scope", "dmm", "sa", "psu", "awg", "eload"];
const IFACES: [string, string][] = [
  ["lan", "LAN (VXI-11)"], ["socket", "LAN socket :5025"], ["hislip", "LAN HiSLIP"],
  ["usb", "USB"], ["serial", "Serial (COM)"], ["gpib", "GPIB"],
];
const QUICK = ["*IDN?", "*RST", "*CLS", ":SYST:ERR?", "*OPC?", "*STB?"];

export function ConnectionsTab() {
  const [base, setBase] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, IoDetails>>({});
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  // add-by-address form
  const [addRole, setAddRole] = useState("scope");
  const [iface, setIface] = useState("lan");
  const [host, setHost] = useState("");

  // interactive IO
  const [ioRole, setIoRole] = useState("scope");
  const [cmd, setCmd] = useState("*IDN?");
  const [log, setLog] = useState<{ dir: "tx" | "rx" | "err"; text: string }[]>([]);
  const logEnd = useRef<HTMLDivElement | null>(null);

  // MCP (drive this bench from Claude Desktop / Code)
  const [mcp, setMcp] = useState<McpInfo | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async (b: string) => {
    const h = await getHealth(b);
    const out: Record<string, IoDetails> = {};
    await Promise.all(ROLES.map(async (r) => {
      out[r] = h?.instruments?.[r]?.connected ? await ioDetails(b, r)
        : { connected: false, role: r };
    }));
    setDetails(out);
  }, []);

  useEffect(() => {
    (async () => { const b = await baseUrl(); setBase(b); await refresh(b); setMcp(await mcpInfo(b)); })();
  }, [refresh]);

  function copyMcp() {
    if (!mcp) return;
    navigator.clipboard?.writeText(mcp.config_json);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  useEffect(() => { logEnd.current?.scrollIntoView({ block: "end" }); }, [log]);

  async function discover() {
    if (!base) return; setBusy("discover");
    const r = await getVisaResources(base);
    const named = r.resources.filter((x) => x.idn).map((x) => x.idn).join(" · ");
    setNote(`${r.resources.length} VISA resource(s)${named ? ": " + named : " (use Auto-connect all to assign)"}`);
    setBusy("");
  }
  async function autoAll() {
    if (!base) return; setBusy("auto");
    const r = await ioAutoconnect(base, true);
    setNote(r.connected.length ? `Connected ${r.connected.length}` : "No new instruments matched a free role");
    await refresh(base); setBusy("");
  }
  async function addByAddress() {
    if (!base || !host) return; setBusy("add");
    const r = await connectInstrument(base, addRole, { host, interface: iface });
    setNote(r.ok ? `Connected ${addRole}: ${r.idn || r.resource}` : `Failed: ${r.error}`);
    await refresh(base); setBusy("");
  }
  async function verify(role: string) {
    if (!base) return; setBusy(role);
    const r = await verifyInstrument(base, role);
    setNote(r.ok ? `${role}: VERIFIED_HW` : `${role}: ${(r.reasons && r.reasons[0]) || r.error || "not verified"}`);
    await refresh(base); setBusy("");
  }
  async function disconnect(role: string) {
    if (!base) return; setBusy(role);
    await disconnectInstrument(base, role);
    await refresh(base); setBusy("");
  }
  async function send(query: boolean) {
    if (!base || !cmd.trim()) return;
    setLog((l) => [...l, { dir: "tx", text: `${ioRole} ‹ ${cmd}` }]);
    const r = await ioScpi(base, ioRole, cmd, query);
    if (!r.ok) setLog((l) => [...l, { dir: "err", text: r.error || "error" }]);
    else if (r.response != null) setLog((l) => [...l, { dir: "rx", text: r.response as string }]);
    else setLog((l) => [...l, { dir: "rx", text: "(written)" }]);
  }

  const connectedRoles = ROLES.filter((r) => details[r]?.connected);

  return (
    <div className="flex flex-col gap-3">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-panel">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-ink"><PlugZap className="h-4 w-4 text-accent" /> Connections</div>
          <div className="text-xs text-muted">Discover, add and talk to instruments — a Connection Expert for your bench.</div>
        </div>
        <div className="ml-auto flex gap-2">
          <Button variant="secondary" size="md" onClick={discover} disabled={!!busy}><Search className={`h-4 w-4 ${busy === "discover" ? "animate-spin" : ""}`} /> Discover</Button>
          <Button variant="primary" size="md" onClick={autoAll} disabled={!!busy}><RefreshCw className={`h-4 w-4 ${busy === "auto" ? "animate-spin" : ""}`} /> Auto-connect all</Button>
        </div>
        {note && <span className="w-full text-[11px] text-muted">{note}</span>}
      </div>

      {/* instrument inventory */}
      <Card>
        <CardHeader><CardTitle>Instruments</CardTitle><span className="text-xs text-muted">{connectedRoles.length} connected</span></CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-lg border border-line">
            <table className="w-full text-left text-xs">
              <thead className="bg-panel2 text-[11px] uppercase tracking-wide text-muted">
                <tr><th className="px-3 py-2">Role</th><th className="px-3 py-2">Instrument</th><th className="px-3 py-2">Address</th><th className="px-3 py-2">State</th><th className="px-3 py-2 text-right">Actions</th></tr>
              </thead>
              <tbody>
                {ROLES.map((r) => {
                  const d = details[r];
                  const idn = d?.idn;
                  return (
                    <tr key={r} className="border-t border-line">
                      <td className="px-3 py-2 font-medium capitalize text-ink">{r}</td>
                      <td className="px-3 py-2 text-muted">
                        {idn ? <span><span className="text-ink">{idn.vendor} {idn.model}</span> · SN {idn.serial || "?"} · fw {idn.firmware || "?"}</span> : "—"}
                      </td>
                      <td className="px-3 py-2 font-mono text-[11px] text-muted">{d?.resource ?? "—"}</td>
                      <td className="px-3 py-2">
                        {d?.connected
                          ? <span className={d.provenance === "VERIFIED_HW" ? "text-verified" : "text-unverified"}>{d.provenance}</span>
                          : <span className="text-muted">disconnected</span>}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex justify-end gap-1.5">
                          <Button variant="ghost" onClick={() => verify(r)} disabled={!d?.connected || busy === r}>Verify</Button>
                          <Button variant="ghost" onClick={() => disconnect(r)} disabled={!d?.connected || busy === r}>Disconnect</Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* add by address */}
          <div className="mt-3 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-panel2/50 p-3">
            <label className="flex flex-col gap-1 text-[11px] font-medium uppercase text-muted">Assign to
              <select value={addRole} onChange={(e) => setAddRole(e.target.value)} className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm capitalize text-ink">
                {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[11px] font-medium uppercase text-muted">Interface
              <select value={iface} onChange={(e) => setIface(e.target.value)} className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm text-ink">
                {IFACES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="flex flex-1 flex-col gap-1 text-[11px] font-medium uppercase text-muted">Address
              <input value={host} onChange={(e) => setHost(e.target.value)}
                placeholder={iface === "serial" ? "COM3" : iface === "gpib" ? "22" : iface === "usb" ? "USB0::0x2A8D::…::INSTR" : "192.168.0.10"}
                className="min-w-[180px] rounded-lg border border-line bg-panel px-2.5 py-1.5 font-mono text-sm text-ink" />
            </label>
            <Button variant="primary" size="md" onClick={addByAddress} disabled={!host || busy === "add"}>Connect</Button>
          </div>
        </CardContent>
      </Card>

      {/* interactive IO */}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Terminal className="h-4 w-4 text-accent" /> Interactive IO</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2">
          <div className="flex items-start gap-2 rounded-lg border border-unverified/40 bg-unverified/5 px-3 py-2 text-[11px] text-ink">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-unverified" />
            Raw SCPI is a direct passthrough — it bypasses the app's safety gates. Output-enable / level
            commands can energize your DUT. Every command is logged.
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={ioRole} onChange={(e) => setIoRole(e.target.value)} className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm capitalize text-ink">
              {(connectedRoles.length ? connectedRoles : ROLES).map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <input value={cmd} onChange={(e) => setCmd(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send(cmd.trim().endsWith("?"))}
              placeholder="SCPI command…"
              className="min-w-[220px] flex-1 rounded-lg border border-line bg-panel px-2.5 py-1.5 font-mono text-sm text-ink" />
            <Button variant="secondary" size="md" onClick={() => send(false)} disabled={!details[ioRole]?.connected}>Write</Button>
            <Button variant="primary" size="md" onClick={() => send(true)} disabled={!details[ioRole]?.connected}>Query</Button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {QUICK.map((q) => (
              <button key={q} onClick={() => setCmd(q)} className="rounded-md border border-line bg-panel px-2 py-0.5 font-mono text-[11px] text-muted hover:bg-panel2 hover:text-ink">{q}</button>
            ))}
            <button onClick={() => setLog([])} className="ml-auto text-[11px] text-muted hover:text-ink">Clear log</button>
          </div>
          <div className="instr-screen h-[180px] overflow-y-auto rounded-lg border border-screenline bg-screen p-2 font-mono text-[11px] leading-relaxed">
            {log.length === 0 && <div className="text-slate-500">Responses appear here. Try *IDN? on a connected instrument.</div>}
            {log.map((l, i) => (
              <div key={i} className={l.dir === "tx" ? "text-sky-300" : l.dir === "err" ? "text-red-400" : "text-emerald-300"}>
                {l.dir === "tx" ? "→ " : l.dir === "err" ? "✗ " : "← "}{l.text}
              </div>
            ))}
            <div ref={logEnd} />
          </div>
        </CardContent>
      </Card>

      {/* MCP server — drive this bench from an external AI client */}
      {mcp && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Bot className="h-4 w-4 text-accent" /> AI control (MCP server)</CardTitle>
            <span className={`text-xs ${mcp.available ? "text-verified" : "text-muted"}`}>{mcp.available ? "● ready" : "unavailable"}</span>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-[13px] text-muted">
              Drive this bench from Claude Desktop or Claude Code — the app runs as a Model Context
              Protocol server exposing your connected instruments as tools. Add this to your MCP
              client config, keep the app running, and ask Claude to measure, auto-connect or send SCPI.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {mcp.tools.map((t) => (
                <span key={t} className="rounded-md border border-line bg-panel2 px-2 py-0.5 font-mono text-[11px] text-ink">{t}</span>
              ))}
            </div>
            <div className="relative">
              <button onClick={copyMcp} className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-md border border-line bg-panel px-2 py-1 text-[11px] text-muted hover:text-ink">
                {copied ? <><Check className="h-3.5 w-3.5 text-verified" /> Copied</> : <><Copy className="h-3.5 w-3.5" /> Copy</>}
              </button>
              <pre className="instr-screen max-h-[240px] overflow-auto rounded-lg border border-screenline bg-screen p-3 font-mono text-[11px] leading-relaxed text-emerald-200">{mcp.config_json}</pre>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
