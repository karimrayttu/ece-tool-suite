import { useCallback, useEffect, useRef, useState } from "react";
import {
  baseUrl, setupCatalog, setupInstall, setupStatus,
  type SetupTool, type SetupInstallStatus,
} from "../lib/api";
import { openExternal } from "../lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const ACTIVE_STATES = new Set(["starting", "downloading", "extracting", "verifying"]);

export function SetupTab() {
  const [tools, setTools] = useState<SetupTool[]>([]);
  const [installs, setInstalls] = useState<Record<string, SetupInstallStatus>>({});
  const timer = useRef<number>();

  const refresh = useCallback(async () => {
    const b = await baseUrl();
    setTools((await setupCatalog(b)).tools);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // poll install progress while anything is active; refresh the catalog when one finishes
  useEffect(() => {
    const tick = async () => {
      const b = await baseUrl();
      const st = (await setupStatus(b)).installs;
      setInstalls((prev) => {
        const justFinished = Object.entries(st).some(
          ([id, s]) => s.finished && !prev[id]?.finished);
        if (justFinished) refresh();
        return st;
      });
    };
    timer.current = window.setInterval(tick, 1200);
    return () => clearInterval(timer.current);
  }, [refresh]);

  async function install(t: SetupTool) {
    const b = await baseUrl();
    const r = await setupInstall(b, t.id);
    if (!r.ok && r.url) openExternal(r.url);
  }

  const groups = [...new Set(tools.map((t) => t.group))];
  const anyActive = Object.values(installs).some((s) => ACTIVE_STATES.has(s.state));

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Software setup — third-party tools, one click each</CardTitle>
          <div className="flex items-center gap-3">
            <span className="hidden text-xs text-muted lg:inline">
              Freely-redistributed tools install from their official source with live progress.
              Login-gated vendors open their official download page — no login is ever bypassed.
            </span>
            <button onClick={refresh}
              className="shrink-0 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90">
              ⟳ Re-scan installed
            </button>
          </div>
        </CardHeader>
      </Card>

      {groups.map((g) => (
        <Card key={g}>
          <CardHeader><CardTitle>{g}</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {tools.filter((t) => t.group === g).map((t) => {
              const st = installs[t.id];
              const active = st && ACTIVE_STATES.has(st.state);
              return (
                <div key={t.id} className="relative flex flex-col gap-1 overflow-hidden rounded-lg border border-line bg-panel2/50 px-3.5 py-2 transition-all hover:border-[#39424f] hover:bg-panel2">
                  {t.installed && <span className="absolute left-0 top-0 h-full w-[3px] bg-verified/80 shadow-glow-green" aria-hidden />}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${t.installed ? "bg-verified shadow-glow-green" : "bg-slate-500"}`} />
                    <span className="text-[13px] font-semibold text-ink">{t.name}</span>
                    {t.installed && <span className="rounded-md border border-emerald-500/40 px-1.5 py-0.5 text-[10px] text-emerald-500">installed</span>}
                    {t.approx_mb ? <span className="text-[11px] text-muted">~{t.approx_mb >= 1000 ? `${(t.approx_mb / 1000).toFixed(1)} GB` : `${t.approx_mb} MB`}</span> : null}
                    <span className="ml-auto flex gap-2">
                      {t.one_click && !t.installed && !active && (
                        <button onClick={() => install(t)} disabled={t.needs_winget}
                          className="rounded-md bg-accent px-3 py-1 text-xs font-semibold text-bg hover:opacity-90 disabled:opacity-40">
                          Install
                        </button>
                      )}
                      {t.one_click && t.installed && !active && (
                        <button onClick={() => install(t)}
                          className="rounded-md bg-panel2 px-3 py-1 text-xs font-semibold text-muted hover:text-ink">
                          Reinstall / update
                        </button>
                      )}
                      <button onClick={() => openExternal(t.url)}
                        className="rounded-md border border-line px-3 py-1 text-xs text-muted hover:text-ink">
                        Official page
                      </button>
                    </span>
                  </div>
                  <div className="text-[11px] text-muted">{t.purpose}</div>
                  <div className="text-[11px] text-muted/70">source: {t.source}{t.path ? ` · found: ${t.path}` : ""}</div>
                  {t.note && <div className="text-[11px] text-muted/90">{t.note}</div>}
                  {t.needs_winget && !t.installed && (
                    <div className="text-[11px] text-amber-500">winget (App Installer) not found — use the official page instead.</div>
                  )}
                  {st && (active || st.state === "error" || st.state === "done") && (
                    <div className="mt-1 flex flex-col gap-1">
                      {active && (
                        <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel2">
                          <div className="h-full bg-accent transition-all"
                            style={{ width: `${st.state === "downloading" ? st.progress : 100}%`,
                                     opacity: st.state === "downloading" ? 1 : 0.6 }} />
                        </div>
                      )}
                      <div className={`text-[11px] ${st.state === "error" ? "text-danger" : st.state === "done" ? "text-emerald-500" : "text-muted"}`}>
                        {st.state === "error" ? `failed: ${st.error}` : `${st.state}${st.detail ? ` — ${st.detail}` : ""}`}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>
      ))}
      {anyActive && <div className="text-center text-[11px] text-muted">installing… you can keep using the app; progress updates live</div>}
    </div>
  );
}
