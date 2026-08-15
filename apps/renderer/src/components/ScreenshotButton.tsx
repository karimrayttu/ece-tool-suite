import { Camera } from "lucide-react";
import { useState } from "react";
import { baseUrl, fetchScreenshot } from "../lib/api";
import { stamp } from "../lib/csv";

export function ScreenshotButton({ role }: { role: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function capture() {
    setBusy(true);
    setErr("");
    const b = await baseUrl();
    const blob = await fetchScreenshot(b, role);
    if (blob) {
      if (url) URL.revokeObjectURL(url);
      setUrl(URL.createObjectURL(blob));
    } else {
      setErr("no image (connect the instrument first)");
    }
    setBusy(false);
  }

  function save() {
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${role}_screen_${stamp()}.png`;
    a.click();
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button onClick={capture} disabled={busy}
          className="inline-flex items-center gap-1 rounded-md bg-line px-2.5 py-1 text-xs text-ink hover:bg-line/70 disabled:opacity-40">
          <Camera className="h-3.5 w-3.5" /> {busy ? "Capturing…" : "Instrument screenshot"}
        </button>
        {url && <button onClick={save} className="rounded-md bg-line px-2.5 py-1 text-xs text-ink hover:bg-line/70">Save PNG</button>}
        {err && <span className="text-[11px] text-muted">{err}</span>}
      </div>
      {url && <img src={url} alt="instrument screen" className="max-w-full rounded-lg border border-line" />}
    </div>
  );
}
