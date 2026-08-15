import { useEffect, useState } from "react";
import {
  baseUrl, lvStatus, lvProjects, lvRunVi, lvMassCompile, lvBuild, lvLaunch, lvClose,
  lvComStatus, lvViRun, lvTemplates, lvCreateVi, lvBuilderStatus,
  type LvStatus, type LvProject, type LvOpResult, type LvComStatus, type LvViRunResult,
  type LvTemplate,
} from "../lib/api";
import { openExternal } from "../lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Led } from "./ui/instrument";

export function LabviewTab() {
  const [st, setSt] = useState<LvStatus | null>(null);
  const [projects, setProjects] = useState<LvProject[]>([]);
  const [viPath, setViPath] = useState("");
  const [dir, setDir] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ op: string; r: LvOpResult } | null>(null);
  const [com, setCom] = useState<LvComStatus | null>(null);
  const [viPath2, setViPath2] = useState("");
  const [viInputs, setViInputs] = useState("{}");
  const [viOutputs, setViOutputs] = useState("");
  const [viResult, setViResult] = useState<LvViRunResult | null>(null);
  const [templates, setTemplates] = useState<LvTemplate[]>([]);
  const [tpl, setTpl] = useState("");
  const [tplPath, setTplPath] = useState("");
  const [tplNote, setTplNote] = useState("");
  const [builder, setBuilder] = useState<{ available: boolean; guide?: string | null } | null>(null);

  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      setSt(await lvStatus(b));
      setProjects((await lvProjects(b)).projects);
      const t = await lvTemplates(b);
      setTemplates(t.templates);
      if (t.templates.length && !tpl) setTpl(t.templates[0].name);
      setBuilder(await lvBuilderStatus(b));
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function runVi2() {
    setBusy("vi2");
    try {
      const b = await baseUrl();
      let inputs: Record<string, unknown> = {};
      try { inputs = JSON.parse(viInputs || "{}"); } catch { setViResult({ ok: false, error: "inputs is not valid JSON" }); return; }
      const outs = viOutputs.split(",").map((s) => s.trim()).filter(Boolean);
      setViResult(await lvViRun(b, { vi_path: viPath2, inputs, outputs: outs }));
    } finally { setBusy(null); }
  }

  async function createFromTpl() {
    setBusy("tpl");
    setTplNote("");
    try {
      const b = await baseUrl();
      const r = await lvCreateVi(b, { save_path: tplPath, template: tpl, open_in_labview: true });
      setTplNote(r.ok ? `created ${r.created}${r.opened ? " — opened in LabVIEW" : ""}` : (r.error ?? "failed"));
    } finally { setBusy(null); }
  }

  async function op(name: string, fn: (b: string) => Promise<LvOpResult>) {
    setBusy(name);
    try {
      const b = await baseUrl();
      setResult({ op: name, r: await fn(b) });
    } finally { setBusy(null); }
  }

  const btn = "rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40";

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>LabVIEW — projects, headless VI runs, builds (official NI CLI)</CardTitle>
          <span className="text-xs text-muted">Operations shell out to NI's LabVIEWCLI (RunVI / MassCompile / ExecuteBuildSpec) — nothing simulated.</span>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2 text-xs">
          {st === null ? <span className="text-muted">detecting…</span> : st.installed ? (
            <>
              {st.installs.map((i) => (
                <span key={i.path} className="rounded-md border border-emerald-500/40 px-2 py-1 text-emerald-500">● LabVIEW {i.version} ({i.bitness})</span>
              ))}
              <span className={`rounded-md border px-2 py-1 ${st.cli_available ? "border-emerald-500/40 text-emerald-500" : "border-amber-500/40 text-amber-500"}`}>
                {st.cli_available ? "● LabVIEW CLI" : "○ LabVIEW CLI missing (install via NI Package Manager)"}
              </span>
              <button onClick={() => op("launch", (b) => lvLaunch(b))} disabled={!!busy} className={`${btn} bg-accent text-bg hover:opacity-90`}>Open LabVIEW</button>
              <button onClick={() => op("close", (b) => lvClose(b))} disabled={!!busy || !st.cli_available} className={`${btn} bg-panel2 text-ink`}>{busy === "close" ? "Closing…" : "Close LabVIEW"}</button>
            </>
          ) : (
            <>
              <span className="text-amber-500">LabVIEW not installed.</span>
              <button onClick={() => openExternal(st.download)} className={`${btn} bg-accent text-bg`}>Get LabVIEW (ni.com)</button>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Projects (.lvproj found in Documents / Desktop)</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-1">
          {projects.length === 0 && <span className="text-xs text-muted">No .lvproj files found.</span>}
          {projects.slice(0, 12).map((p) => (
            <div key={p.path} className="flex items-center gap-2 rounded-lg border border-line bg-panel2/50 px-3 py-1.5 text-xs">
              <span className="font-semibold text-ink">{p.name}</span>
              <span className="truncate text-muted">{p.path}</span>
              <span className="ml-auto flex gap-2">
                <button onClick={() => op("open", (b) => lvLaunch(b, p.path))} disabled={!st?.installed || !!busy} className={`${btn} bg-accent text-bg hover:opacity-90`}>Open</button>
                <button onClick={() => op("build", (b) => lvBuild(b, p.path))} disabled={!st?.cli_available || !!busy} className={`${btn} bg-panel2 text-ink`}>{busy === "build" ? "Building…" : "Build"}</button>
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Headless operations</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <input value={viPath} onChange={(e) => setViPath(e.target.value)} placeholder="C:\path\to\some.vi"
              className="w-80 rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-xs text-ink" />
            <button onClick={() => op("run-vi", (b) => lvRunVi(b, viPath))} disabled={!st?.cli_available || !viPath || !!busy}
              className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "run-vi" ? "Running…" : "Run VI"}</button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input value={dir} onChange={(e) => setDir(e.target.value)} placeholder="C:\folder\of\VIs (mass compile)"
              className="w-80 rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-xs text-ink" />
            <button onClick={() => op("mass-compile", (b) => lvMassCompile(b, dir))} disabled={!st?.cli_available || !dir || !!busy}
              className={`${btn} bg-panel2 text-ink`}>{busy === "mass-compile" ? "Compiling…" : "Mass compile"}</button>
          </div>
          {result && (
            <div className="flex flex-col gap-1">
              <div className={`font-semibold ${result.r.ok ? "text-emerald-500" : "text-danger"}`}>
                {result.op}: {result.r.ok ? "OK" : (result.r.error ?? `exit ${result.r.returncode}`)}
              </div>
              {result.r.log && <pre className="max-h-48 overflow-auto rounded-md border border-line bg-panel2 p-2 font-mono text-[11px] text-ink">{result.r.log}</pre>}
            </div>
          )}
        </CardContent>
      </Card>

      {/* VI automation (ActiveX VI Server): set controls → run → read indicators */}
      <Card>
        <CardHeader>
          <CardTitle>VI automation — set inputs · run · read outputs</CardTitle>
          <button onClick={async () => { setBusy("com"); try { setCom(await lvComStatus(await baseUrl())); } finally { setBusy(null); } }}
            disabled={!!busy}
            className="rounded-md bg-panel2 px-3 py-1.5 text-xs font-semibold text-ink hover:opacity-90 disabled:opacity-40">
            {busy === "com" ? "Connecting…" : "Test VI Server"}
          </button>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-xs">
          {com && (
            <span className="inline-flex items-center gap-1.5">
              <Led color={com.connected ? "green" : "red"} on />
              {com.connected ? `VI Server connected — LabVIEW ${com.version}` : `${com.error}${com.hint ? ` · ${com.hint}` : ""}`}
            </span>
          )}
          <div className="grid gap-2 lg:grid-cols-[1fr_1fr_220px_auto]">
            <input value={viPath2} onChange={(e) => setViPath2(e.target.value)} placeholder="C:\path\to\dashboard.vi"
              className="rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-xs text-ink" />
            <input value={viInputs} onChange={(e) => setViInputs(e.target.value)} placeholder='inputs JSON, e.g. {"Setpoint": 3.3}'
              className="rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-xs text-ink" />
            <input value={viOutputs} onChange={(e) => setViOutputs(e.target.value)} placeholder="outputs: Reading, Status"
              className="rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-xs text-ink" />
            <button onClick={runVi2} disabled={!!busy || !viPath2}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90 disabled:opacity-40">
              {busy === "vi2" ? "Running…" : "Set → Run → Read"}
            </button>
          </div>
          {viResult && (
            <div className={viResult.ok ? "text-emerald-500" : "text-danger"}>
              {viResult.ok
                ? <>ran <b>{viResult.vi}</b>{Object.keys(viResult.outputs ?? {}).length > 0 && <> · outputs: <span className="font-mono text-ink">{JSON.stringify(viResult.outputs)}</span></>}</>
                : viResult.error}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dashboard builder: scaffold from LabVIEW templates + spec-driven codegen status */}
      <Card>
        <CardHeader>
          <CardTitle>Dashboard builder</CardTitle>
          <span className="text-xs text-muted">scaffold a new VI from LabVIEW's design-pattern templates, then wire graphs/charts in LabVIEW</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <select value={tpl} onChange={(e) => setTpl(e.target.value)}
              className="max-w-[300px] rounded-md border border-line bg-panel2 px-2 py-1.5 text-xs text-ink">
              {templates.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
              {templates.length === 0 && <option value="">no templates found</option>}
            </select>
            <input value={tplPath} onChange={(e) => setTplPath(e.target.value)}
              placeholder="where to save the new VI, e.g. C:\Projects\dashboard.vi"
              className="min-w-[280px] flex-1 rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-xs text-ink" />
            <button onClick={createFromTpl} disabled={!!busy || !tpl || !st?.installed}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-bg hover:opacity-90 disabled:opacity-40">
              {busy === "tpl" ? "Creating…" : "Create VI + open"}
            </button>
          </div>
          {tplNote && <div className="text-accent">{tplNote}</div>}
          <div className="flex items-start gap-2 border-t border-line pt-2">
            <Led color={builder?.available ? "green" : "amber"} on className="mt-0.5" />
            <span className="text-muted">
              Spec-driven VI codegen (build graphs/controls from a JSON spec):{" "}
              {builder?.available
                ? <span className="text-verified">VIBuilder.vi present — /api/labview/dashboard is live</span>
                : <>needs a one-time VIBuilder.vi build in LabVIEW (G scripting is already enabled). Guide: <span className="font-mono text-ink">{builder?.guide ?? "~/.ece-suite/labview/BUILDER_GUIDE.md"}</span></>}
            </span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
