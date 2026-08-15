import { useEffect, useState } from "react";
import {
  baseUrl,
  connectInstrument,
  disconnectInstrument,
  getHealth,
  getVisaResources,
  instrumentsSupported,
  PROVENANCE_TONE,
  verifyInstrument,
  type Provenance,
  type SupportedVendor,
  type VisaResource,
} from "../lib/api";
import { Badge } from "./ui/badge";

export function ConnectionBar({ role, onChange }: { role: string; onChange?: (connected: boolean) => void }) {
  const [base, setBase] = useState<string | null>(null);
  const [resources, setResources] = useState<VisaResource[]>([]);
  const [resource, setResource] = useState("");
  const [status, setStatus] = useState<{ connected: boolean; provenance?: Provenance | null; resource?: string | null; vendor?: string | null }>({ connected: false });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [host, setHost] = useState("");
  const [iface, setIface] = useState("lan");
  const [vendors, setVendors] = useState<SupportedVendor[]>([]);
  const [vendor, setVendor] = useState("auto");

  async function refresh(b: string) {
    const h = await getHealth(b);
    const s = h?.instruments?.[role];
    if (s) {
      setStatus({ connected: s.connected, provenance: s.provenance, resource: s.resource, vendor: s.vendor });
      onChange?.(s.connected);
    }
  }

  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      setBase(b);
      await refresh(b);
      const s = await instrumentsSupported(b);
      setVendors(s.roles[role] ?? []);
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function discover() {
    if (!base) return;
    setBusy(true);
    const r = await getVisaResources(base);
    setResources(r.resources);
    if (r.resources[0] && !resource) setResource(r.resources[0].resource);
    setNote(r.resources.length ? `${r.resources.length} resource(s) found` : "no VISA resources found");
    setBusy(false);
  }
  async function connect() {
    if (!base || !resource) return;
    setBusy(true);
    const r = await connectInstrument(base, role, { resource, vendor_hint: vendor });
    setNote(r.ok ? `connected${r.vendor && r.vendor !== "unknown" ? ` (${r.vendor})` : ""}: ${r.idn || resource}` : `connect failed: ${r.error}`);
    await refresh(base);
    setBusy(false);
  }
  async function connectByAddress() {
    if (!base || !host) return;
    setBusy(true);
    const r = await connectInstrument(base, role, { host, interface: iface, vendor_hint: vendor });
    setNote(r.ok ? `connected${r.vendor && r.vendor !== "unknown" ? ` (${r.vendor})` : ""}: ${r.idn || r.resource}` : `connect failed: ${r.error}`);
    await refresh(base);
    setBusy(false);
  }
  async function verify() {
    if (!base) return;
    const r = await verifyInstrument(base, role);
    setNote(r.ok ? "VERIFIED_HW — *IDN? + read-back OK" : `not verified: ${(r.reasons && r.reasons[0]) || r.error || ""}`);
    await refresh(base);
  }
  async function disconnect() {
    if (!base) return;
    await disconnectInstrument(base, role);
    setNote("disconnected");
    await refresh(base);
  }

  const prov = status.provenance ?? undefined;
  const btn = "rounded-md bg-line px-2.5 py-1 text-xs text-ink hover:bg-line/70 disabled:opacity-40";

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel2 px-3 py-2">
      {status.connected ? (
        <Badge tone={prov ? PROVENANCE_TONE[prov] : "unverified"}>{prov ?? "connected"}</Badge>
      ) : (
        <Badge tone="muted">disconnected</Badge>
      )}
      {status.connected && status.vendor && status.vendor !== "unknown" && (
        <span className="rounded bg-ks/20 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-ks">{status.vendor}</span>
      )}
      <input
        list={`res-${role}`}
        value={resource}
        onChange={(e) => setResource(e.target.value)}
        placeholder="TCPIP0::192.168.0.10::INSTR  or  USB0::0x2A8D::…::INSTR"
        className="min-w-[260px] flex-1 rounded-md border border-line bg-panel px-2 py-1 font-mono text-xs text-ink placeholder:text-muted/50"
      />
      <datalist id={`res-${role}`}>
        {resources.map((r) => (
          <option key={r.resource} value={r.resource}>
            {r.keysight ? "★ Keysight " : ""}
            {r.idn ?? ""}
          </option>
        ))}
      </datalist>
      {vendors.length > 0 && (
        <select value={vendor} onChange={(e) => setVendor(e.target.value)}
          title="Instrument brand — Auto uses *IDN?; pick explicitly if your unit answers with an OEM string"
          className="rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink">
          {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
        </select>
      )}
      <button className={btn} onClick={discover} disabled={busy}>Discover</button>
      <button className={btn} onClick={connect} disabled={busy || !resource}>Connect</button>
      <button className={btn} onClick={verify} disabled={busy || !status.connected}>Verify</button>
      <button className={btn} onClick={disconnect} disabled={busy || !status.connected}>Disconnect</button>

      {/* connect by friendly address (LAN / raw socket / USB / serial / GPIB) */}
      <div className="flex w-full flex-wrap items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-muted">or by address:</span>
        <input value={host} onChange={(e) => setHost(e.target.value)}
          placeholder={iface === "serial" ? "COM3" : iface === "gpib" ? "22" : "192.168.0.10"}
          className="w-40 rounded-md border border-line bg-panel px-2 py-1 font-mono text-xs text-ink placeholder:text-muted/50" />
        <select value={iface} onChange={(e) => setIface(e.target.value)} className="rounded-md border border-line bg-panel px-2 py-1 text-xs text-ink">
          <option value="lan">LAN (VXI-11)</option>
          <option value="socket">LAN socket :5025</option>
          <option value="hislip">LAN HiSLIP</option>
          <option value="usb">USB</option>
          <option value="serial">Serial (COM)</option>
          <option value="gpib">GPIB</option>
        </select>
        <button className={btn} onClick={connectByAddress} disabled={busy || !host}>Connect address</button>
      </div>

      {note && (
        <span className="w-full font-mono text-[11px] text-muted">
          {note}
          {status.resource ? ` · ${status.resource}` : ""}
        </span>
      )}
    </div>
  );
}
