import { useEffect, useState } from "react";
import { baseUrl, getHealth, instrumentCaps } from "../lib/api";

const NAMES: Record<string, string> = {
  keysight: "KEYSIGHT", tektronix: "TEKTRONIX", lecroy: "TELEDYNE LECROY",
  keithley: "KEITHLEY", rigol: "RIGOL", siglent: "SIGLENT", rohde: "ROHDE & SCHWARZ",
  fluke: "FLUKE", "fluke-legacy": "FLUKE", "fluke-28x": "FLUKE", gwinstek: "GW INSTEK",
  bk: "B&K PRECISION", ni: "NI", itech: "ITECH", yokogawa: "YOKOGAWA",
};

/** Live brand nameplate: the CONNECTED instrument's vendor + model, never hardcoded. */
export function VendorBadge({ role, showModel = true }: { role: string; showModel?: boolean }) {
  const [vendor, setVendor] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  useEffect(() => {
    let stop = false;
    let id: number | undefined;
    (async () => {
      const b = await baseUrl();
      const tick = async () => {
        const h = await getHealth(b);
        const s = h?.instruments?.[role];
        if (stop) return;
        setVendor(s?.vendor ?? null);
        if (s?.connected) {
          const c = await instrumentCaps(b, role);
          if (!stop) setModel(c.model ?? null);
        } else setModel(null);
      };
      await tick();
      id = window.setInterval(tick, 5000);
    })();
    return () => { stop = true; if (id) clearInterval(id); };
  }, [role]);
  const label = vendor && NAMES[vendor] ? NAMES[vendor] : vendor ? vendor.toUpperCase() : "MULTI-VENDOR";
  return (
    <span className="text-sm font-semibold tracking-wide text-ks">
      {label}{showModel && model ? <span className="ml-1.5 font-mono text-xs text-muted">{model}</span> : null}
    </span>
  );
}
