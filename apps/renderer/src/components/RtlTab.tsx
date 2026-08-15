import { useEffect, useState } from "react";
import {
  baseUrl, rtlStatus, rtlLint, rtlSimulate, rtlSynth, rtlFpga, rtlTiming, rtlRegmap, rtlFormat,
  rtlGenerate, rtlOptimize, pldTargets, vendorProject,
  rtlDevEnv, rtlSnippets, rtlGtkwave, rtlExportProject,
  type DevEnvItem, type RtlSnippet,
  rtlJtag, rtlBitstream, rtlProgram, rtlVendorExport, rtlVendorLaunch,
  type HdlLang, type RtlToolchain, type RtlDiagnostic, type RtlLintResult, type RtlSimResult,
  type RtlSynthResult, type RtlFpgaResult, type RtlTimingResult, type RtlRegmapResult,
  type RtlGenerateResult, type RtlOptimizeResult, type PldVendor, type VendorProjectResult,
  type JtagResult, type BitstreamResult, type ProgramResult, type VendorExportResult,
} from "../lib/api";
import { Led } from "./ui/instrument";

const SAMPLE_REGMAP = JSON.stringify({
  name: "ctrl", data_width: 32, addr_width: 8,
  registers: [
    { name: "CTRL", offset: 0, description: "Control register", fields: [
      { name: "EN", bits: "0", access: "rw", reset: 0, description: "Core enable" },
      { name: "MODE", bits: "2:1", access: "rw", reset: 1, description: "Operating mode" }] },
    { name: "STATUS", offset: 4, description: "Status register", fields: [
      { name: "BUSY", bits: "0", access: "ro", description: "Busy flag" },
      { name: "CODE", bits: "7:4", access: "ro", description: "Result code" }] },
    { name: "DATA", offset: 8, access: "rw", reset: 0, description: "Data word" }],
}, null, 2);
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const SAMPLE: Record<HdlLang, { dut: string; tb: string }> = {
  systemverilog: {
    dut: `module counter #(parameter W = 8) (
  input  logic         clk,
  input  logic         rst_n,
  input  logic         en,
  output logic [W-1:0] q
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)      q <= '0;
    else if (en)     q <= q + 1'b1;
  end
endmodule`,
    tb: `module tb;
  logic clk = 0, rst_n = 0, en = 1;
  logic [7:0] q, q0;
  counter dut(.clk(clk), .rst_n(rst_n), .en(en), .q(q));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("dump.vcd"); $dumpvars(0, tb);
    @(negedge clk); rst_n = 1;   // release reset on a falling edge (no race with counting edge)
    @(negedge clk); q0 = q;      // reference count after reset
    repeat (16) @(posedge clk);  // exactly 16 enabled rising edges
    #1;
    if (q == q0 + 8'd16) $display("PASS q=%0d (counted 16)", q);
    else                 $display("FAIL q=%0d (expected %0d)", q, q0 + 8'd16);
    $finish;
  end
endmodule`,
  },
  verilog: {
    dut: `module adder(
  input  [3:0] a,
  input  [3:0] b,
  output [4:0] sum
);
  assign sum = a + b;
endmodule`,
    tb: `module tb;
  reg  [3:0] a, b;
  wire [4:0] sum;
  adder dut(.a(a), .b(b), .sum(sum));
  initial begin
    a = 4'd7; b = 4'd9; #1;
    if (sum == 5'd16) $display("PASS");
    else              $display("FAIL sum=%0d", sum);
    $finish;
  end
endmodule`,
  },
  vhdl: {
    dut: `library ieee; use ieee.std_logic_1164.all; use ieee.numeric_std.all;
entity inv is port(a : in std_logic; y : out std_logic); end entity;
architecture rtl of inv is begin y <= not a; end architecture;`,
    tb: `library ieee; use ieee.std_logic_1164.all;
entity tb is end entity;
architecture sim of tb is
  signal a, y : std_logic := '0';
begin
  dut: entity work.inv port map(a => a, y => y);
  process begin
    a <= '0'; wait for 1 ns; assert y = '1' report "FAIL" severity error;
    a <= '1'; wait for 1 ns; assert y = '0' report "FAIL" severity error;
    report "PASS"; wait;
  end process;
end architecture;`,
  },
};

const SEV_TONE: Record<string, string> = {
  error: "text-danger", warning: "text-amber-400", note: "text-muted", info: "text-muted",
};

function Diagnostics({ diags }: { diags: RtlDiagnostic[] }) {
  if (!diags.length) return null;
  return (
    <div className="flex flex-col gap-1 font-mono text-xs">
      {diags.map((d, i) => (
        <div key={i} className="flex gap-2">
          <span className={`shrink-0 font-semibold uppercase ${SEV_TONE[d.severity] ?? "text-muted"}`}>{d.severity}</span>
          <span className="shrink-0 text-muted">{d.line != null ? `L${d.line}${d.col != null ? ":" + d.col : ""}` : "—"}</span>
          <span className="text-ink">{d.message}{d.code ? ` [${d.code}]` : ""}</span>
        </div>
      ))}
    </div>
  );
}

function verdictTone(v?: string) {
  if (v === "pass") return "bg-emerald-500/15 text-emerald-400 border-emerald-500/40";
  if (v === "fail" || v === "compile_error") return "bg-danger/15 text-danger border-danger/40";
  return "bg-panel2 text-muted border-line";
}

export function RtlTab() {
  const [lang, setLang] = useState<HdlLang>("systemverilog");
  const [source, setSource] = useState(SAMPLE.systemverilog.dut);
  const [tb, setTb] = useState(SAMPLE.systemverilog.tb);
  const [tc, setTc] = useState<RtlToolchain | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [lint, setLintRes] = useState<RtlLintResult | null>(null);
  const [sim, setSim] = useState<RtlSimResult | null>(null);
  const [synth, setSynth] = useState<RtlSynthResult | null>(null);
  const [fpga, setFpga] = useState<RtlFpgaResult | null>(null);
  const [timing, setTiming] = useState<RtlTimingResult | null>(null);
  const [family, setFamily] = useState("ice40");
  const [targetMhz, setTargetMhz] = useState("");
  const [regmapSpec, setRegmapSpec] = useState(SAMPLE_REGMAP);
  const [regmap, setRegmap] = useState<RtlRegmapResult | null>(null);
  const [devenv, setDevenv] = useState<DevEnvItem[]>([]);
  const [snips, setSnips] = useState<RtlSnippet[]>([]);
  const [snipId, setSnipId] = useState("");
  const [wavNote, setWavNote] = useState("");
  const [exportDir, setExportDir] = useState("");
  const [exportNote, setExportNote] = useState("");
  const [plds, setPlds] = useState<Record<string, PldVendor>>({});
  const [pldVendor, setPldVendor] = useState("xilinx");
  const [pldFamily, setPldFamily] = useState("artix7");
  const [vp, setVp] = useState<VendorProjectResult | null>(null);
  const [vpFile, setVpFile] = useState<string>("");
  const [jtag, setJtag] = useState<JtagResult | null>(null);
  const [bit, setBit] = useState<BitstreamResult | null>(null);
  const [prog, setProg] = useState<ProgramResult | null>(null);
  const [vexp, setVexp] = useState<VendorExportResult | null>(null);
  const [board, setBoard] = useState("");
  const [gen, setGen] = useState<RtlGenerateResult | null>(null);
  const [opt, setOpt] = useState<RtlOptimizeResult | null>(null);
  const [spec, setSpec] = useState("A synchronous 8-bit up/down counter with load and enable.");
  const [goal, setGoal] = useState("area");

  useEffect(() => {
    (async () => {
      const b = await baseUrl();
      setTc(await rtlStatus(b));
      setPlds((await pldTargets(b)).vendors);
      setDevenv((await rtlDevEnv(b)).items);
      const s = await rtlSnippets(b);
      setSnips(s.snippets);
      if (s.snippets.length) setSnipId(s.snippets[0].id);
    })();
  }, []);

  function insertSnippet() {
    const s = snips.find((x) => x.id === snipId);
    if (!s) return;
    if (s.language === "systemverilog") { setLang("systemverilog"); setSource(s.code); }
    else navigator.clipboard.writeText(s.code);
  }

  async function openWave() {
    const vcdText = sim?.vcd?.text;
    if (!vcdText) { setWavNote("run a simulation with $dumpfile/$dumpvars first"); return; }
    const r = await rtlGtkwave(await baseUrl(), vcdText, "sim");
    setWavNote(r.ok ? `opened in GTKWave (${r.file})` : (r.error ?? "failed"));
  }

  async function exportVendor() {
    if (!vp?.ok || !vp.files) { setExportNote("generate a vendor project first"); return; }
    const r = await rtlExportProject(await baseUrl(), { files: vp.files, dest: exportDir, open_in: "vscode" });
    setExportNote(r.ok ? `written to ${r.dir} (${r.written?.length} files) — opened in VS Code` : (r.error ?? "failed"));
  }

  function loadSample(l: HdlLang) {
    setLang(l); setSource(SAMPLE[l].dut); setTb(SAMPLE[l].tb);
    setLintRes(null); setSim(null); setSynth(null); setFpga(null); setTiming(null); setGen(null); setOpt(null);
  }

  async function run(kind: string, fn: () => Promise<void>) {
    setBusy(kind);
    try { await fn(); } finally { setBusy(null); }
  }

  const cap = tc?.capabilities ?? {};
  const doLint = () => run("lint", async () => setLintRes(await rtlLint(await baseUrl(), { source, language: lang })));
  const doSim = () => run("sim", async () => setSim(await rtlSimulate(await baseUrl(), { source, testbench: tb, language: lang })));
  const doSynth = () => run("synth", async () => setSynth(await rtlSynth(await baseUrl(), { source, language: lang })));
  const doFpga = () => run("fpga", async () => setFpga(await rtlFpga(await baseUrl(), { source, family, language: lang })));
  const doTiming = () => run("timing", async () => setTiming(await rtlTiming(await baseUrl(), {
    source, family, language: lang, target_mhz: targetMhz ? Number(targetMhz) : undefined })));
  const doRegmap = () => run("regmap", async () => {
    let spec: Record<string, unknown>;
    try { spec = JSON.parse(regmapSpec); } catch (e) { setRegmap({ ok: false, error: `Invalid JSON: ${(e as Error).message}` }); return; }
    const r = await rtlRegmap(await baseUrl(), { spec, lint: true });
    setRegmap(r);
    if (r.ok && r.systemverilog) { setLang("systemverilog"); setSource(r.systemverilog); }
  });
  const doFormat = () => run("format", async () => {
    const r = await rtlFormat(await baseUrl(), { source, language: lang });
    if (r.ok && r.formatted) setSource(r.formatted);
  });
  const doGenerate = () => run("gen", async () => {
    const r = await rtlGenerate(await baseUrl(), { spec, language: lang, testbench: tb || undefined });
    setGen(r);
    if (r.ok && r.code) setSource(r.code);
  });
  const doJtag = () => run("jtag", async () => setJtag(await rtlJtag(await baseUrl())));
  const doBitstream = () => run("bit", async () => {
    const fam = family === "ecp5" ? "ecp5" : "ice40"; // open flow families
    setBit(await rtlBitstream(await baseUrl(), { source, family: fam, language: lang }));
  });
  const doProgram = () => run("prog", async () => {
    if (!bit?.bitstream) return;
    setProg(await rtlProgram(await baseUrl(), { bitstream: bit.bitstream, board: board || undefined }));
  });
  const doVendorExport = () => run("vexp", async () => {
    const r = await rtlVendorExport(await baseUrl(), { source, vendor: pldVendor, family: pldFamily, language: lang });
    setVexp(r);
  });
  const doVendorLaunch = () => run("vlaunch", async () => {
    if (!vexp?.dir) return;
    await rtlVendorLaunch(await baseUrl(), vexp.dir, pldVendor);
  });
  const doVendorProject = () => run("vp", async () => {
    const r = await vendorProject(await baseUrl(), { source, vendor: pldVendor, family: pldFamily, language: lang });
    setVp(r);
    setVpFile(r.ok && r.files ? Object.keys(r.files)[0] : "");
  });
  const doOptimize = () => run("opt", async () => {
    const r = await rtlOptimize(await baseUrl(), { source, goal, language: lang, testbench: tb || undefined });
    setOpt(r);
    if (r.ok && r.accepted && r.code) setSource(r.code);
  });

  const btn = "rounded-md px-3 py-1.5 text-xs font-semibold disabled:opacity-40";
  const langBtn = (l: HdlLang, label: string) => (
    <button key={l} onClick={() => loadSample(l)}
      className={`${btn} ${lang === l ? "bg-accent text-bg" : "bg-panel2 text-muted hover:text-ink"}`}>{label}</button>
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Toolchain status */}
      <Card>
        <CardHeader>
          <CardTitle>RTL / HDL Workbench</CardTitle>
          <span className="text-xs text-muted">Design, verify, and bring up programmable logic — Verilog · SystemVerilog · VHDL. Every verdict comes from the real toolchain: Verilator, Icarus, GHDL, Yosys, nextpnr.</span>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2 text-xs">
          {tc?.tools.map((t) => (
            <span key={t.id} className={`rounded-md border px-2 py-1 ${t.installed ? "border-emerald-500/40 text-emerald-400" : "border-line text-muted/60"}`}>
              {t.installed ? "●" : "○"} {t.name}
            </span>
          ))}
          <span className={`rounded-md border px-2 py-1 ${tc?.ai ? "border-accent/50 text-accent" : "border-line text-muted/60"}`}>
            {tc?.ai ? "●" : "○"} AI RTL
          </span>
          {tc && !tc.any && (
            <span className="text-amber-400">No HDL toolchain found — install OSS CAD Suite to enable lint/sim/synth.</span>
          )}
          {tc?.vendors && tc.vendors.some((v) => v.installed) && (
            <div className="flex w-full flex-wrap items-center gap-2 border-t border-line pt-2">
              <span className="text-[11px] text-muted">Vendor tools:</span>
              {tc.vendors.filter((v) => v.installed).map((v) => (
                <span key={v.id} className="rounded-md border border-emerald-500/40 px-2 py-1 text-emerald-400">● {v.name}</span>
              ))}
            </div>
          )}
          {devenv.length > 0 && (
            <div className="flex w-full flex-wrap items-center gap-2 border-t border-line pt-2">
              <span className="text-[11px] text-muted">Workflow stack:</span>
              {devenv.map((d) => (
                <span key={d.id} title={d.purpose}
                  className={`rounded-md border px-2 py-1 ${d.installed ? "border-emerald-500/40 text-emerald-400" : "border-line text-muted/60"}`}>
                  {d.installed ? "●" : "○"} {d.name}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* engineering patterns: CDC · reset · self-checking TB · XDC · ILA · cocotb */}
      <Card>
        <CardHeader>
          <CardTitle>Engineering patterns</CardTitle>
          <span className="text-xs text-muted">Reference implementations of the skills that matter: clock-domain crossing, reset synchronization, self-checking testbenches, XDC timing, ILA debug, cocotb.</span>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2 text-xs">
          <select value={snipId} onChange={(e) => setSnipId(e.target.value)}
            className="min-w-[280px] rounded-md border border-line bg-panel2 px-2 py-1.5 text-xs text-ink">
            {snips.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button onClick={insertSnippet} className={`${btn} bg-accent text-bg hover:opacity-90`}>
            {snips.find((s) => s.id === snipId)?.language === "systemverilog" ? "Load into editor" : "Copy to clipboard"}
          </button>
          <span className="w-full text-[11px] text-muted">{snips.find((s) => s.id === snipId)?.note}</span>
        </CardContent>
      </Card>

      {/* Editors */}
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div className="flex items-center gap-2">{(["verilog", "systemverilog", "vhdl"] as HdlLang[]).map((l) => langBtn(l, l === "systemverilog" ? "SystemVerilog" : l === "verilog" ? "Verilog" : "VHDL"))}</div>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-muted">Design (DUT)
              <textarea value={source} onChange={(e) => setSource(e.target.value)} rows={18} spellCheck={false}
                className="rounded-lg border border-line bg-panel2 p-2 font-mono text-xs text-ink" />
            </label>
            <label className="flex flex-col gap-1 text-[11px] text-muted">Testbench
              <textarea value={tb} onChange={(e) => setTb(e.target.value)} rows={18} spellCheck={false}
                className="rounded-lg border border-line bg-panel2 p-2 font-mono text-xs text-ink" />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={doLint} disabled={!!busy} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "lint" ? "Linting…" : "Lint"}</button>
            <button onClick={doSim} disabled={!!busy || !cap.simulate_verilog && lang !== "vhdl"} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "sim" ? "Simulating…" : "Simulate"}</button>
            <button onClick={doSynth} disabled={!!busy || lang === "vhdl"} className={`${btn} bg-panel2 text-ink hover:opacity-90`}>{busy === "synth" ? "Synthesizing…" : "Synthesize (generic)"}</button>
            <button onClick={doFormat} disabled={!!busy || lang === "vhdl" || !cap.format} className={`${btn} bg-panel2 text-ink hover:opacity-90`}>{busy === "format" ? "Formatting…" : "Format"}</button>
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <span className="text-[11px] text-muted">FPGA target</span>
            <select value={family} onChange={(e) => setFamily(e.target.value)} className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs text-ink">
              {(tc?.fpga?.families ?? []).map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            <button onClick={doFpga} disabled={!!busy || lang === "vhdl" || !tc?.fpga?.available} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "fpga" ? "Mapping…" : "Synthesize to FPGA"}</button>
            <button onClick={doTiming} disabled={!!busy || lang === "vhdl" || !tc?.fpga?.families.find((f) => f.id === family)?.pnr || (family !== "ice40" && family !== "ecp5")} className={`${btn} bg-panel2 text-ink hover:opacity-90`}>{busy === "timing" ? "Routing…" : "Place & Route + Timing"}</button>
            <input value={targetMhz} onChange={(e) => setTargetMhz(e.target.value)} placeholder="target MHz" className="w-24 rounded-md border border-line bg-panel2 px-2 py-1 text-xs text-ink" />
          </div>
        </CardContent>
      </Card>

      {/* AI design / optimize */}
      <Card>
        <CardHeader>
          <CardTitle>GenAI RTL — design & optimize, validated by the toolchain</CardTitle>
          <span className="text-xs text-muted">The model proposes RTL; it is only "validated" if lint (and, with a testbench, simulation) actually pass.</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[11px] text-muted">Spec (natural language → RTL)
            <textarea value={spec} onChange={(e) => setSpec(e.target.value)} rows={2}
              className="rounded-lg border border-line bg-panel2 p-2 text-xs text-ink" />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={doGenerate} disabled={!!busy || !tc?.ai} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "gen" ? "Designing…" : "Generate RTL"}</button>
            <span className="mx-1 text-muted">·</span>
            <span className="text-[11px] text-muted">Optimize current DUT for</span>
            <select value={goal} onChange={(e) => setGoal(e.target.value)} className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs text-ink">
              <option value="area">area</option><option value="timing">timing</option>
              <option value="power">power</option><option value="readability">readability</option>
            </select>
            <button onClick={doOptimize} disabled={!!busy || !tc?.ai} className={`${btn} bg-panel2 text-ink hover:opacity-90`}>{busy === "opt" ? "Optimizing…" : "Optimize"}</button>
            {!tc?.ai && <span className="text-[11px] text-amber-400">Set ANTHROPIC_API_KEY to enable AI RTL.</span>}
          </div>
        </CardContent>
      </Card>

      {/* Register-map generator */}
      <Card>
        <CardHeader>
          <CardTitle>Register map → SystemVerilog + documentation</CardTitle>
          <span className="text-xs text-muted">One spec drives both a synthesizable register block and its datasheet — generated RTL is lint-checked so it can't drift from the docs.</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-[11px] text-muted">Spec (JSON: registers · offsets · fields · access)
              <textarea value={regmapSpec} onChange={(e) => setRegmapSpec(e.target.value)} rows={12} spellCheck={false}
                className="rounded-lg border border-line bg-panel2 p-2 font-mono text-[11px] text-ink" />
            </label>
            <div className="flex flex-col gap-1 text-[11px] text-muted">Documentation (Markdown)
              <pre className="h-[268px] overflow-auto rounded-lg border border-line bg-panel2 p-2 font-mono text-[11px] text-ink">{regmap?.ok ? regmap.markdown : regmap?.error ?? "Generate to preview the register datasheet."}</pre>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={doRegmap} disabled={!!busy} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "regmap" ? "Generating…" : "Generate register block"}</button>
            {regmap?.ok && <span className="text-[11px] text-muted">{regmap.n_registers} registers · SystemVerilog loaded into the DUT editor
              {regmap.lint && <span className={regmap.lint.clean ? " text-emerald-400" : " text-danger"}> · lint {regmap.lint.clean ? "clean" : `${regmap.lint.errors} err`}</span>}
            </span>}
            {regmap && !regmap.ok && <span className="text-[11px] text-danger">{regmap.error}</span>}
          </div>
        </CardContent>
      </Card>

      {/* Xilinx / Intel / Lattice vendor project export */}
      <Card>
        <CardHeader>
          <CardTitle>Vendor FPGA / CPLD project — Xilinx · Intel · Lattice</CardTitle>
          <span className="text-xs text-muted">Generates a ready-to-run vendor batch flow (Vivado tcl / Quartus qsf / Radiant tcl) for the DUT above — Lattice parts also get an open yosys+nextpnr script that needs no vendor tool.</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select value={pldVendor} onChange={(e) => { const v = e.target.value; setPldVendor(v); setPldFamily(Object.keys(plds[v]?.families ?? {})[0] ?? ""); }}
              className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs text-ink">
              {Object.entries(plds).map(([id, v]) => <option key={id} value={id}>{v.vendor}</option>)}
            </select>
            <select value={pldFamily} onChange={(e) => setPldFamily(e.target.value)}
              className="rounded-md border border-line bg-panel2 px-2 py-1 text-xs text-ink">
              {Object.entries(plds[pldVendor]?.families ?? {}).map(([id, f]) => (
                <option key={id} value={id}>{f.name}{f.board ? ` — ${f.board}` : ""}</option>
              ))}
            </select>
            <button onClick={doVendorProject} disabled={!!busy} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "vp" ? "Generating…" : "Generate project"}</button>
            {plds[pldVendor] && (
              <span className={plds[pldVendor].tool_installed ? "text-emerald-400" : "text-muted"}>
                {plds[pldVendor].tool}: {plds[pldVendor].tool_installed ? "installed — run.bat works now" : "not installed (scripts still generated; see Setup tab)"}
              </span>
            )}
          </div>
          {vp && !vp.ok && <div className="rounded-md border border-danger/40 px-3 py-2 text-xs text-danger">{vp.error}</div>}
          {vp?.ok && vp.files && (
            <div className="flex flex-col gap-2">
              <div className="text-xs text-muted">
                <b className="text-ink">{vp.part}</b>{vp.is_cpld ? " (CPLD)" : ""} · top <b className="text-ink">{vp.top}</b>
                {(vp.notes ?? []).map((n, i) => <div key={i}>{n}</div>)}
              </div>
              <div className="flex flex-wrap gap-1">
                {Object.keys(vp.files).map((f) => (
                  <button key={f} onClick={() => setVpFile(f)}
                    className={`rounded-md px-2 py-1 font-mono text-[11px] ${vpFile === f ? "bg-accent text-bg" : "bg-panel2 text-muted hover:text-ink"}`}>{f}</button>
                ))}
                <button onClick={() => navigator.clipboard.writeText(vp.files![vpFile] ?? "")}
                  className="rounded-md border border-line px-2 py-1 text-[11px] text-muted hover:text-ink">Copy file</button>
              </div>
              <pre className="max-h-56 overflow-auto rounded-md border border-line bg-panel2 p-2 font-mono text-[11px] text-ink">{vp.files[vpFile]}</pre>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <input value={exportDir} onChange={(e) => setExportDir(e.target.value)}
                  placeholder="destination folder for the vendor project"
                  className="w-80 rounded-md border border-line bg-panel2 px-2 py-1.5 font-mono text-xs text-ink" />
                <button onClick={exportVendor} className={`${btn} bg-accent text-bg hover:opacity-90`}>Export to folder + open in VS Code</button>
                {exportNote && <span className="text-[11px] text-muted">{exportNote}</span>}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Bring-up: detect → bitstream → program (real hardware path) */}
      <Card>
        <CardHeader>
          <CardTitle>Bring-up — JTAG detect · bitstream · program</CardTitle>
          <span className="text-xs text-muted">The complete path onto real silicon: probe USB/JTAG, build an actual bitstream (yosys → nextpnr → pack), flash it with openFPGALoader.</span>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={doJtag} disabled={!!busy} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "jtag" ? "Probing…" : "1 · Detect hardware"}</button>
            <button onClick={doBitstream} disabled={!!busy} className={`${btn} bg-accent text-bg hover:opacity-90`}>{busy === "bit" ? "Building…" : "2 · Build bitstream"}</button>
            <input value={board} onChange={(e) => setBoard(e.target.value)} placeholder="board (optional, e.g. ice40_generic)"
              className="w-56 rounded-md border border-line bg-panel2 px-2 py-1 font-mono text-xs text-ink" />
            <button onClick={doProgram} disabled={!!busy || !bit?.bitstream} className={`${btn} bg-panel2 text-ink hover:opacity-90`}>{busy === "prog" ? "Flashing…" : "3 · Program board"}</button>
          </div>
          <div className="flex flex-col gap-2 text-xs">
            {jtag && (
              <div className="flex items-start gap-2">
                <Led color={jtag.found ? "green" : "amber"} on className="mt-1" />
                <div>
                  <span className={jtag.found ? "font-semibold text-verified" : "text-muted"}>
                    {jtag.ok ? (jtag.found ? `FPGA detected: ${jtag.devices?.map((d) => d.model ?? d.idcode).join(", ")}` : "no JTAG cable/board answered — connect the board's USB and re-probe") : jtag.error}
                  </span>
                  {jtag.log && !jtag.found && <pre className="mt-1 max-h-24 overflow-auto rounded border border-line bg-panel2 p-1.5 font-mono text-[10px] text-muted">{jtag.log}</pre>}
                </div>
              </div>
            )}
            {bit && (
              <div className="flex flex-col gap-1">
                <span className={bit.built ? "font-semibold text-verified" : "text-danger"}>
                  {bit.built
                    ? `bitstream built: ${bit.bitstream} (${((bit.size_bytes ?? 0) / 1024).toFixed(1)} KB · Fmax ${bit.fmax_mhz?.toFixed(1)} MHz · ${bit.device})`
                    : `build failed at ${bit.stage ?? "?"}${bit.error ? ` — ${bit.error}` : ""}`}
                </span>
                {(bit.steps ?? []).map((s) => (
                  <span key={s.step} className={s.ok ? "text-muted" : "text-danger"}>
                    {s.ok ? "✓" : "✗"} {s.step}{!s.ok && <pre className="mt-0.5 max-h-24 overflow-auto rounded border border-line bg-panel2 p-1.5 font-mono text-[10px]">{s.log_tail}</pre>}
                  </span>
                ))}
              </div>
            )}
            {prog && (
              <div>
                <span className={prog.programmed ? "font-semibold text-verified" : "text-danger"}>
                  {prog.programmed ? "board programmed ✓" : `programming failed${prog.hint ? ` — ${prog.hint}` : ""}`}
                </span>
                {prog.log && <pre className="mt-1 max-h-28 overflow-auto rounded border border-line bg-panel2 p-1.5 font-mono text-[10px] text-muted">{prog.log}</pre>}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2">
              <span className="text-muted">Vendor hand-off:</span>
              <button onClick={doVendorExport} disabled={!!busy} className={`${btn} bg-panel2 text-ink hover:opacity-90`}>{busy === "vexp" ? "Exporting…" : `Export ${plds[pldVendor]?.tool ?? "vendor"} project to disk`}</button>
              <button onClick={doVendorLaunch} disabled={!!busy || !vexp?.dir} className={`${btn} bg-panel2 text-ink hover:opacity-90`}>Open folder{plds[pldVendor]?.tool_installed ? " + launch tool" : ""}</button>
              {vexp?.dir && <span className="font-mono text-[10.5px] text-muted">{vexp.dir}</span>}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {(lint || sim || synth || fpga || timing || gen || opt) && (
        <Card>
          <CardHeader><CardTitle>Results</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4 text-xs">
            {lint && (
              <div className="flex flex-col gap-1">
                <div className="font-semibold text-ink">Lint {lint.tool ? `(${lint.tool})` : ""}
                  {lint.ok ? <span className={lint.clean ? "ml-2 text-emerald-400" : "ml-2 text-danger"}>{lint.clean ? "clean" : `${lint.errors} error(s), ${lint.warnings} warning(s)`}</span>
                    : <span className="ml-2 text-amber-400">{lint.error}</span>}
                </div>
                <Diagnostics diags={lint.diagnostics ?? []} />
              </div>
            )}
            {sim && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2 font-semibold text-ink">Simulate {sim.tool ? `(${sim.tool})` : ""}
                  {sim.ok ? <span className={`rounded-md border px-2 py-0.5 text-[11px] uppercase ${verdictTone(sim.verdict)}`}>{sim.verdict}</span>
                    : <span className="text-amber-400">{sim.error}</span>}
                </div>
                {sim.stdout && <pre className="max-h-48 overflow-auto rounded-md border border-line bg-panel2 p-2 font-mono text-[11px] text-ink">{sim.stdout}</pre>}
                {sim.vcd && sim.vcd.signals.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 text-muted">
                    <span>VCD: <span className="text-ink">{sim.vcd.signals.join(", ")}</span> · t_end={sim.vcd.time_end}</span>
                    <button onClick={openWave} className="rounded-md border border-line px-2 py-0.5 text-[11px] text-muted hover:text-ink">Open in GTKWave</button>
                    {wavNote && <span className="text-[11px]">{wavNote}</span>}
                  </div>
                )}
                <Diagnostics diags={sim.diagnostics ?? []} />
              </div>
            )}
            {synth && (
              <div className="flex flex-col gap-1">
                <div className="font-semibold text-ink">Synthesize (Yosys){synth.top ? ` — top ${synth.top}` : ""}
                  {!synth.ok && <span className="ml-2 text-amber-400">{synth.error}</span>}
                </div>
                {synth.stats && (
                  <div className="flex flex-wrap gap-3 font-mono text-[11px] text-ink">
                    {Object.entries(synth.stats).map(([k, v]) => <span key={k}>{k}: <b>{v}</b></span>)}
                  </div>
                )}
                {synth.cells && Object.keys(synth.cells).length > 0 && (
                  <div className="text-muted">cells: <span className="font-mono text-ink">{Object.entries(synth.cells).map(([k, v]) => `${k}×${v}`).join("  ")}</span></div>
                )}
              </div>
            )}
            {fpga && (
              <div className="flex flex-col gap-1">
                <div className="font-semibold text-ink">FPGA synthesis — {fpga.device ?? fpga.family}
                  {!fpga.ok && <span className="ml-2 text-amber-400">{fpga.error}</span>}
                  {fpga.ok && fpga.synthesized === false && <span className="ml-2 text-danger">synthesis failed</span>}
                </div>
                {fpga.utilization && Object.keys(fpga.utilization).length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(fpga.utilization).map(([k, v]) => (
                      <span key={k} className="rounded-md border border-accent/40 bg-accent/10 px-2 py-1 font-mono text-[11px] text-ink">{k.toUpperCase()}: <b>{v}</b></span>
                    ))}
                    <span className="rounded-md border border-line px-2 py-1 font-mono text-[11px] text-muted">total cells: {fpga.total_cells}</span>
                  </div>
                )}
                {fpga.cells && Object.keys(fpga.cells).length > 0 && (
                  <div className="text-muted">primitives: <span className="font-mono text-ink">{Object.entries(fpga.cells).map(([k, v]) => `${k}×${v}`).join("  ")}</span></div>
                )}
                {fpga.note && <div className="text-[11px] text-muted">{fpga.note}{fpga.boards ? ` · boards: ${fpga.boards}` : ""}</div>}
                <Diagnostics diags={fpga.diagnostics ?? []} />
              </div>
            )}
            {timing && (
              <div className="flex flex-col gap-1">
                <div className="font-semibold text-ink">Timing (nextpnr place & route){timing.device ? ` — ${timing.family} ${timing.device}` : ""}
                  {!timing.ok && <span className="ml-2 text-amber-400">{timing.error}</span>}
                  {timing.ok && timing.routed === false && <span className="ml-2 text-danger">did not route ({timing.stage})</span>}
                  {timing.ok && timing.met_timing != null && <span className={`ml-2 ${timing.met_timing ? "text-emerald-400" : "text-danger"}`}>{timing.met_timing ? "meets timing" : "FAILS timing"}</span>}
                </div>
                {(timing.clocks ?? []).map((c) => (
                  <div key={c.clock} className="font-mono text-[11px] text-ink">
                    <span className="text-accent font-semibold">Fmax {c.fmax_mhz.toFixed(1)} MHz</span> · clock <span className="text-muted">{c.clock}</span>
                    {c.verdict ? <span className={c.verdict === "PASS" ? "ml-1 text-emerald-400" : "ml-1 text-danger"}>({c.verdict}{c.target_mhz ? ` at ${c.target_mhz} MHz` : ""})</span> : null}
                  </div>
                ))}
                {timing.utilization && Object.keys(timing.utilization).length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(timing.utilization).map(([k, v]) => (
                      <span key={k} className="rounded-md border border-line px-2 py-1 font-mono text-[11px] text-muted">{k}: <b className="text-ink">{v.used}</b>/{v.total} ({v.pct}%)</span>
                    ))}
                  </div>
                )}
                <Diagnostics diags={timing.diagnostics ?? []} />
              </div>
            )}
            {gen && (
              <div className="flex flex-col gap-1">
                <div className="font-semibold text-ink">AI design
                  {gen.ok ? <span className={gen.validated ? "ml-2 text-emerald-400" : "ml-2 text-amber-400"}>{gen.validated ? "validated by toolchain" : `not validated (${gen.n_rounds} round${gen.n_rounds === 1 ? "" : "s"})`}</span>
                    : <span className="ml-2 text-danger">{gen.error}</span>}
                </div>
                {gen.notes && <div className="text-muted">{gen.notes}</div>}
                {gen.rounds && gen.rounds.length > 1 && <div className="text-muted">Iterated {gen.rounds.length}× against lint/sim feedback.</div>}
                <div className="text-[11px] text-muted">Code loaded into the DUT editor above.</div>
              </div>
            )}
            {opt && (
              <div className="flex flex-col gap-1">
                <div className="font-semibold text-ink">AI optimize ({opt.goal})
                  {opt.ok ? <span className={opt.accepted ? "ml-2 text-emerald-400" : "ml-2 text-amber-400"}>{opt.accepted ? "accepted (still validates)" : "rejected — kept original"}</span>
                    : <span className="ml-2 text-danger">{opt.error}</span>}
                </div>
                {opt.note && <div className="text-amber-400">{opt.note}</div>}
                {opt.notes && <div className="text-muted">{opt.notes}</div>}
                {opt.before?.synth?.stats && opt.after?.synth?.stats && (
                  <div className="font-mono text-[11px] text-ink">cells: {opt.before.synth.stats.cells ?? "?"} → {opt.after.synth.stats.cells ?? "?"}</div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
