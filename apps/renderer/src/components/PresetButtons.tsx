import { Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { applyPreset, baseUrl, listPresets, type PresetInfo } from "../lib/api";
import { Button } from "./ui/button";

// Auto-setup buttons for a given instrument role. Applies the preset to the CONNECTED
// instrument (measurement presets are ALLOW; source presets live in the Sources tab).
export function PresetButtons({ role }: { role: string }) {
  const [base, setBase] = useState<string | null>(null);
  const [presets, setPresets] = useState<PresetInfo[]>([]);
  const [note, setNote] = useState("");

  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      const all = await listPresets(b);
      setBase(b);
      setPresets(all.filter((p) => p.instrument === role));
    })();
  }, [role]);

  async function apply(p: PresetInfo) {
    if (!base) return;
    const r = await applyPreset(base, p.id, {});
    setNote(r.connected === false ? `${role} not connected` : r.ok ? `applied: ${p.name}` : `blocked: ${r.summary}`);
  }

  if (!presets.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
        <Wand2 className="h-3.5 w-3.5" /> Auto-setup
      </span>
      {presets.map((p) => (
        <Button key={p.id} variant="subtle" onClick={() => apply(p)} title={p.testing_for}>
          {p.name}
        </Button>
      ))}
      {note && <span className="text-[11px] text-muted">{note}</span>}
    </div>
  );
}
