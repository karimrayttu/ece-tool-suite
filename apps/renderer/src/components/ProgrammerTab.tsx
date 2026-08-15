import { AlertTriangle, Cpu, Download, HardDriveDownload, RefreshCw, Usb } from "lucide-react";
import { useEffect, useState } from "react";
import {
  baseUrl, mcuDevice, mcuDevices, mcuErase, mcuRead, mcuStatus,
  type McuRead, type McuStatus,
} from "../lib/api";
import { downloadBlob } from "../lib/csv";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

function bytesFromB64(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function download(name: string, data: BlobPart, type = "application/octet-stream") {
  downloadBlob(name, new Blob([data], { type }));
}
const fmtBytes = (n: number) => (n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`);

export function ProgrammerTab() {
  const [base, setBase] = useState<string | null>(null);
  const [status, setStatus] = useState<McuStatus | null>(null);
  const [devices, setDevices] = useState<string[]>([]);
  const [device, setDevice] = useState("atmega4809");
  const [info, setInfo] = useState<Record<string, string | number | boolean>>({});
  const [read, setRead] = useState<McuRead | null>(null);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [confirmErase, setConfirmErase] = useState(false);

  const refreshStatus = async (b: string) => setStatus(await mcuStatus(b));

  useEffect(() => {
    (async () => {
      const b = await baseUrl(); setBase(b);
      await refreshStatus(b);
      setDevices((await mcuDevices(b)).devices);
      setInfo(await mcuDevice(b, "atmega4809"));
    })();
  }, []);

  async function pickDevice(name: string) {
    setDevice(name); setRead(null);
    if (base && devices.includes(name)) setInfo(await mcuDevice(base, name));
  }
  async function readFirmware() {
    if (!base) return;
    setBusy("read"); setNote("Reading flash…"); setRead(null);
    const r = await mcuRead(base, { device, memory: "flash" });
    setRead(r);
    setNote(r.ok ? `Read ${fmtBytes(r.bytes ?? 0)} from ${device}` : `Read failed: ${r.error}`);
    setBusy("");
  }
  async function erase() {
    if (!base) return;
    setBusy("erase");
    const r = await mcuErase(base, { device, confirm: confirmErase });
    setNote(r.ok ? "Chip erased" : `Erase: ${r.error}`);
    setBusy("");
  }
  async function refresh() { if (base) { setBusy("refresh"); await refreshStatus(base); setBusy(""); } }

  const tool = status?.tools?.[0];
  const infoRows: [string, string][] = [
    ["Architecture", String(info.architecture ?? "—")],
    ["Interface", String(info.interface ?? "—")],
    ["Flash", info.flash_size_bytes ? fmtBytes(Number(info.flash_size_bytes)) : "—"],
    ["EEPROM", info.eeprom_size_bytes ? fmtBytes(Number(info.eeprom_size_bytes)) : "—"],
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 shadow-panel">
        <div className="mr-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink"><HardDriveDownload className="h-4 w-4 text-accent" /> MCU Programmer / Firmware</div>
          <div className="text-xs text-muted">Read device ID, dump flash (extract firmware) and program AVR/PIC targets via a UPDI debugger — pymcuprog.</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {status && (
            <span className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs ${tool ? "bg-verified/10 text-verified" : "bg-panel2 text-muted"}`}>
              <Usb className="h-3.5 w-3.5" />
              {tool ? `${tool.product}${tool.serial ? ` · ${tool.serial}` : ""}` : "no debugger connected"}
            </span>
          )}
          <Button variant="secondary" size="md" onClick={refresh} disabled={!!busy}><RefreshCw className={`h-4 w-4 ${busy === "refresh" ? "animate-spin" : ""}`} /> Refresh</Button>
        </div>
        {note && <span className="w-full text-[11px] text-muted">{note}</span>}
      </div>

      {status && !status.available && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-unverified/40 bg-unverified/5 px-3 py-2 text-[12px] text-ink">
          <Download className="h-4 w-4 text-unverified" />
          The pymcuprog toolchain isn't installed. Add it with <code className="rounded bg-panel2 px-1 font-mono">uv pip install pymcuprog</code> in the backend venv.
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Target</CardTitle>
          <span className="text-xs text-muted">{status?.n_devices ?? 0} supported devices</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase text-muted">Device
              <input list="mcu-devices" value={device} onChange={(e) => pickDevice(e.target.value)}
                className="w-52 rounded-lg border border-line bg-panel px-2.5 py-1.5 font-mono text-sm text-ink" />
              <datalist id="mcu-devices">{devices.map((d) => <option key={d} value={d} />)}</datalist>
            </label>
            <Button variant="primary" size="md" onClick={readFirmware} disabled={!!busy}>
              <HardDriveDownload className={`h-4 w-4 ${busy === "read" ? "animate-pulse" : ""}`} /> Read firmware
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {infoRows.map(([k, v]) => (
              <div key={k} className="rounded-lg border border-line bg-panel2/60 px-3 py-2">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{k}</div>
                <div className="mt-0.5 font-mono text-sm text-ink">{v}</div>
              </div>
            ))}
          </div>

          {read?.ok && (
            <div className="rounded-lg border border-verified/30 bg-verified/5 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
                <span className="text-muted">Device ID <span className="font-mono text-ink">{read.device_id || "—"}</span></span>
                <span className="text-muted">Vcc <span className="font-mono text-ink">{read.voltage != null ? `${read.voltage} V` : "—"}</span></span>
                <span className="text-muted">Read <span className="font-mono text-ink">{fmtBytes(read.bytes ?? 0)}</span></span>
                <span className="text-muted">Base <span className="font-mono text-ink">0x{(read.base_address ?? 0).toString(16)}</span></span>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => read.intel_hex && download(`${device}_flash.hex`, read.intel_hex, "text/plain")} disabled={!read.intel_hex}>
                  <Download className="h-3.5 w-3.5" /> Download .hex
                </Button>
                <Button variant="secondary" onClick={() => read.data_b64 && download(`${device}_flash.bin`, bytesFromB64(read.data_b64) as unknown as BlobPart)} disabled={!read.data_b64}>
                  <Download className="h-3.5 w-3.5" /> Download .bin
                </Button>
              </div>
            </div>
          )}
          {read && !read.ok && (
            <div className="rounded-lg border border-line bg-panel2/60 px-3 py-2 text-xs text-muted">{read.error}</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2 text-danger"><AlertTriangle className="h-4 w-4" /> Danger zone</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted">Chip erase wipes all flash + EEPROM on the target. Irreversible.</span>
          <label className="ml-auto flex items-center gap-2 text-xs text-danger">
            <input type="checkbox" checked={confirmErase} onChange={(e) => setConfirmErase(e.target.checked)} /> I understand
          </label>
          <Button variant="danger" size="md" onClick={erase} disabled={!confirmErase || !!busy}>
            <Cpu className="h-4 w-4" /> Chip erase
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
