"""HDL/RTL engine: pure parsing + language logic always; live tool runs when installed;
AI design/optimize loop offline via an injected fake Anthropic client."""

from __future__ import annotations

import asyncio
import types

import pytest
from fastapi.testclient import TestClient

from ece_suite import main as _main
from ece_suite import rtl, rtl_ai

TC = rtl.toolchain()
HAS_VERILOG = TC["capabilities"]["simulate_verilog"]
HAS_LINT_V = TC["capabilities"]["lint_verilog"]
HAS_SYNTH = TC["capabilities"]["synthesize"]


# --- toolchain + language logic ------------------------------------------
def test_toolchain_shape():
    assert {"tools", "capabilities", "languages", "any", "install"} <= set(TC)
    for t in TC["tools"]:
        assert {"id", "name", "installed", "path"} <= set(t)
    assert set(TC["capabilities"]) >= {
        "lint_verilog", "simulate_verilog", "simulate_vhdl", "synthesize", "format"}


def test_norm_lang_sniffing():
    assert rtl._norm_lang("sv") == "systemverilog"
    assert rtl._norm_lang(None, "always_ff @(posedge clk) q <= d;") == "systemverilog"
    assert rtl._norm_lang(None, "entity foo is end entity;") == "vhdl"
    assert rtl._norm_lang(None, "module m; endmodule") == "verilog"


def test_module_and_entity_names():
    assert rtl.module_names("module alu(...);\nendmodule\nmodule tb; endmodule") == ["alu", "tb"]
    assert rtl.entity_names("entity counter is end;\narchitecture a of counter is") == ["counter"]


# --- diagnostic parsing (the core of honest tool feedback) ----------------
def test_parse_verilator_diagnostics():
    blob = ("%Error: dut.sv:7:12: syntax error, unexpected ';'\n"
            "%Warning-WIDTH: dut.sv:10:5: Operator width mismatch\n")
    d = rtl.parse_diagnostics(blob, "verilator")
    assert d[0]["severity"] == "error" and d[0]["line"] == 7 and d[0]["col"] == 12
    assert d[1]["severity"] == "warning" and d[1]["code"] == "WIDTH"


def test_parse_iverilog_and_ghdl_generic():
    iv = rtl.parse_diagnostics("dut.v:5: error: unknown module type: foo\n", "iverilog")
    assert iv[0]["severity"] == "error" and iv[0]["line"] == 5
    gh = rtl.parse_diagnostics("tb.vhd:12:7: no declaration for \"clk\"\n", "ghdl")
    assert gh[0]["line"] == 12 and gh[0]["col"] == 7


def test_parse_ignores_noise():
    assert rtl.parse_diagnostics("just a plain log line with no location\n") == []


# --- VCD summary ----------------------------------------------------------
def test_summarize_vcd(tmp_path):
    vcd = tmp_path / "dump.vcd"
    vcd.write_text(
        "$timescale 1ns $end\n$var wire 1 ! clk $end\n$var wire 8 # q $end\n"
        "$enddefinitions $end\n#0\n0!\n#50\n1!\n#100\n0!\n", encoding="utf-8")
    s = rtl._summarize_vcd(vcd)
    assert s is not None and "clk" in s["signals"] and "q" in s["signals"]
    assert s["time_end"] == 100
    assert rtl._summarize_vcd(tmp_path / "nope.vcd") is None


# --- graceful degradation vs live runs -----------------------------------
_DUT = "module inv(input a, output y); assign y = ~a; endmodule\n"
_TB = ('module tb; reg a; wire y; inv d(.a(a), .y(y));\n'
       'initial begin a=0; #1 if (y!==1) $display("FAIL"); a=1; #1 '
       'if (y!==0) $display("FAIL"); else $display("PASS"); $finish; end\nendmodule\n')


@pytest.mark.skipif(HAS_LINT_V, reason="linter installed — exercised by the live test")
def test_lint_graceful_without_toolchain():
    r = rtl.lint(_DUT, "verilog")
    assert r["ok"] is False and "install" in r


@pytest.mark.skipif(not HAS_LINT_V, reason="no Verilog linter installed")
def test_lint_clean_module_live():
    r = rtl.lint(_DUT, "verilog")
    assert r["ok"] and r["clean"] and r["errors"] == 0


@pytest.mark.skipif(not HAS_LINT_V, reason="no Verilog linter installed")
def test_lint_catches_syntax_error_live():
    r = rtl.lint("module bad(input a output y); assign y=~a; endmodule", "verilog")
    assert r["ok"] and r["errors"] >= 1


@pytest.mark.skipif(not HAS_VERILOG, reason="Icarus Verilog not installed")
def test_simulate_pass_live():
    r = rtl.simulate(_DUT, _TB, "verilog")
    assert r["ok"] and r["compiled"] and r["verdict"] == "pass"


# --- Yosys stat parser + FPGA mapping ------------------------------------
def test_parse_yosys_stat_new_and_old_format():
    new = "\n=== top ===\n\n     5 wires\n     2 cells\n     1   $_AND_\n     1   $_NOR_\n"
    stats, cells = rtl._parse_yosys_stat(new)
    assert stats["wires"] == 5 and stats["cells"] == 2
    assert cells["$_AND_"] == 1 and cells["$_NOR_"] == 1
    old_stats, _ = rtl._parse_yosys_stat("Number of cells: 7\nNumber of wires: 9\n")
    assert old_stats["cells"] == 7 and old_stats["wires"] == 9


def test_fpga_families_shape():
    fams = rtl.fpga_families()
    ids = {f["id"] for f in fams}
    assert {"ice40", "ecp5", "gowin"} <= ids
    for f in fams:
        assert {"id", "name", "synth", "pnr", "available"} <= set(f)


@pytest.mark.skipif(not HAS_SYNTH, reason="Yosys not installed")
def test_synth_reports_real_cells_live():
    r = rtl.synthesize("module aoi(input a,b,c, output y); assign y = ~((a&b)|c); endmodule", "verilog")
    assert r["synthesized"] and r["stats"].get("cells", 0) >= 1
    assert sum(r["cells"].values()) >= 1


@pytest.mark.skipif(not HAS_SYNTH, reason="Yosys not installed")
def test_fpga_synth_utilization_live():
    dut = ("module cnt(input clk, rst, output reg [3:0] q);\n"
           "always @(posedge clk) if (rst) q<=0; else q<=q+1; endmodule")
    r = rtl.fpga_synth(dut, "ice40", "verilog")
    assert r["ok"] and r["synthesized"] and r["device"].startswith("Lattice")
    # a 4-bit counter must map to real iCE40 flip-flops
    assert r["utilization"].get("ffs", 0) >= 4
    assert r["pnr_available"] is True  # nextpnr-ice40 ships in the bundle


def test_fpga_endpoint_contract():
    r = TestClient(_main.app).post("/api/rtl/fpga", json={"source": _DUT, "family": "ice40", "language": "verilog"})
    assert r.status_code == 200 and "ok" in r.json()


HAS_ICE40_PNR = rtl._which("nextpnr-ice40") is not None


@pytest.mark.skipif(not (HAS_SYNTH and HAS_ICE40_PNR), reason="Yosys+nextpnr-ice40 required")
def test_fpga_timing_reports_fmax_live():
    dut = ("module cnt(input clk, rst, output reg [7:0] q);\n"
           "always @(posedge clk) if (rst) q<=0; else q<=q+1; endmodule")
    r = rtl.fpga_timing(dut, "ice40", "hx8k", "verilog")
    assert r["ok"] and r["routed"]
    assert r["clocks"] and r["clocks"][0]["fmax_mhz"] > 1.0     # a real placed Fmax
    assert "ICESTORM_LC" in r["utilization"]


def test_vendor_fpga_tools_shape():
    for v in rtl.vendor_fpga_tools():
        assert {"id", "name", "constraint", "installed", "path"} <= set(v)


# --- register-map generator ----------------------------------------------
_SPEC = {"name": "ctrl", "data_width": 32, "addr_width": 8, "registers": [
    {"name": "CTRL", "offset": 0, "fields": [
        {"name": "EN", "bits": "0", "access": "rw", "reset": 0},
        {"name": "MODE", "bits": "2:1", "access": "rw", "reset": 1}]},
    {"name": "STATUS", "offset": 4, "fields": [{"name": "BUSY", "bits": "0", "access": "ro"}]}]}


def test_regmap_generates_sv_and_markdown():
    from ece_suite import regmap
    r = regmap.generate(_SPEC, lint=False)
    assert r["ok"] and r["n_registers"] == 2
    assert "module ctrl_regs" in r["systemverilog"]
    assert "assign ctrl_en = ctrl_en_q;" in r["systemverilog"]   # HW output actually driven
    assert "`CTRL`" in r["markdown"] and "| Bits | Field |" in r["markdown"]


def test_regmap_rejects_overlapping_fields():
    from ece_suite import regmap
    bad = {"name": "x", "registers": [{"name": "R", "offset": 0, "fields": [
        {"name": "A", "bits": "3:0"}, {"name": "B", "bits": "2:1"}]}]}
    assert regmap.generate(bad, lint=False)["ok"] is False


@pytest.mark.skipif(not HAS_LINT_V, reason="no Verilog linter installed")
def test_regmap_output_is_lint_clean_live():
    from ece_suite import regmap
    r = regmap.generate(_SPEC, lint=True)
    assert r["lint"]["ok"] and r["lint"]["clean"], r["lint"].get("diagnostics")


def test_constraint_templates():
    ports = [{"port": "clk", "pin": "35", "is_clock": True, "period_ns": 20},
             {"port": "led", "pin": "A5", "iostd": "LVCMOS33"}]
    xdc = rtl.constraint_template("xdc", ports)
    assert xdc["ok"] and "PACKAGE_PIN A5" in xdc["text"] and "create_clock" in xdc["text"]
    pcf = rtl.constraint_template("pcf", ports)
    assert "set_io clk 35" in pcf["text"]
    lpf = rtl.constraint_template("lpf", ports)
    assert 'LOCATE COMP "led" SITE "A5";' in lpf["text"]
    assert rtl.constraint_template("bogus", ports)["ok"] is False


def test_devenv_snippets_and_logic_sources_endpoints():
    c = TestClient(_main.app)
    d = c.get("/api/rtl/devenv").json()
    assert {i["id"] for i in d["items"]} >= {"vscode", "git", "python", "gtkwave", "cocotb"}
    assert all("purpose" in i and "installed" in i for i in d["items"])
    s = c.get("/api/rtl/snippets").json()["snippets"]
    ids = {x["id"] for x in s}
    assert {"cdc-2ff", "reset-sync", "tb-selfcheck", "xdc-timing", "ila-tcl", "cocotb-test"} <= ids
    assert all(x["code"].strip() and x["note"] for x in s)
    ls = c.get("/api/logic/sources").json()["sources"]
    assert {x["id"] for x in ls} == {"sigrok", "pulseview", "saleae"}


def test_export_project_writes_files(tmp_path):
    r = rtl.export_project({"a.tcl": "puts hi\n", "b.xdc": "# pins\n"}, str(tmp_path / "proj"))
    assert r["ok"] and sorted(r["written"]) == ["a.tcl", "b.xdc"]
    assert (tmp_path / "proj" / "a.tcl").read_text() == "puts hi\n"
    assert rtl.export_project({"x": "y"}, "relative/path")["ok"] is False


def test_regmap_and_constraint_endpoints():
    c = TestClient(_main.app)
    r = c.post("/api/rtl/regmap", json={"spec": _SPEC, "lint": False}).json()
    assert r["ok"] and "systemverilog" in r
    r2 = c.post("/api/rtl/constraints", json={"fmt": "pcf", "ports": [{"port": "clk", "pin": "35"}]}).json()
    assert r2["ok"] and "set_io" in r2["text"]


# --- AI design/optimize loop (offline, injected client) -------------------
class _FakeMessages:
    def __init__(self, replies):
        self._replies = list(replies)

    async def create(self, **_kw):
        text = self._replies.pop(0) if self._replies else self._last
        self._last = text
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)])


class _FakeClient:
    def __init__(self, *replies):
        self.messages = _FakeMessages(replies)


def _run(coro):
    return asyncio.run(coro)


def test_extract_code_and_notes():
    txt = "Here you go:\n```systemverilog\nmodule m; endmodule\n```\nUses always_ff."
    assert rtl_ai._extract_code(txt).strip() == "module m; endmodule"
    assert "always_ff" in rtl_ai._notes(txt)
    assert rtl_ai._extract_code("no code here") is None


def test_strip_tb_modules_removes_echoed_testbench():
    # models sometimes echo the provided testbench in their code block; compiling it alongside
    # the real tb then dies on duplicate definitions — the strip removes exactly those modules
    tb = "module tb; mux2 d(); endmodule"
    code = "module mux2(input a, output y); assign y=a; endmodule\nmodule tb; mux2 d(); endmodule"
    out = rtl_ai._strip_tb_modules(code, tb)
    assert "module mux2" in out and "module tb" not in out
    assert rtl_ai._strip_tb_modules(code, None) == code  # no tb -> untouched


def test_generate_requires_key_without_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = _run(rtl_ai.generate("a 2:1 mux", "systemverilog"))
    assert r["ok"] is False and "ANTHROPIC_API_KEY" in r["error"]


def test_generate_offline_returns_code_and_rounds():
    reply = "```systemverilog\nmodule inv(input a, output y); assign y=~a; endmodule\n```\nSimple."
    r = _run(rtl_ai.generate("an inverter", "systemverilog", max_rounds=1,
                             client=_FakeClient(reply)))
    assert r["ok"] and "module inv" in r["code"]
    assert r["n_rounds"] == 1 and isinstance(r["rounds"], list)
    # validated only if a linter graded it clean; without tools it stays False
    assert r["validated"] == (HAS_LINT_V and r["rounds"][-1]["lint"].get("errors") == 0)


def test_optimize_keeps_original_when_not_validated():
    # candidate differs, but with no testbench+no toolchain it can't be proven → keep original
    cand = "```verilog\nmodule inv(input a, output y); assign y = ~a; // tuned\nendmodule\n```"
    r = _run(rtl_ai.optimize(_DUT, "area", "verilog", client=_FakeClient(cand)))
    assert r["ok"] and "candidate" in r
    if not r["accepted"]:
        assert r["code"] == _DUT


# --- endpoint contracts ---------------------------------------------------
def test_status_endpoint():
    r = TestClient(_main.app).get("/api/rtl/status").json()
    assert "capabilities" in r and "languages" in r and "ai" in r


def test_lint_endpoint_contract():
    r = TestClient(_main.app).post("/api/rtl/lint", json={"source": _DUT, "language": "verilog"})
    assert r.status_code == 200
    d = r.json()
    assert "ok" in d
    if d["ok"]:
        assert "diagnostics" in d and isinstance(d["diagnostics"], list)


def test_registry_exposes_rtl_tools_on_both_surfaces():
    from ece_suite.registry import Surface
    chat = _main.registry.names_for(Surface.CHATBOX)
    auto = _main.registry.names_for(Surface.AUTONOMOUS)
    assert {"rtl_lint", "rtl_simulate", "rtl_fpga_synth"} <= chat
    assert {"rtl_lint", "rtl_simulate", "rtl_fpga_synth"} <= auto  # ANALYZE tools are safe autonomously
