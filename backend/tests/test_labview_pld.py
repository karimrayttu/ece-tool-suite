"""LabVIEW integration + Xilinx/Intel/Lattice PLD target map and vendor project export."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ece_suite import labview as LV
from ece_suite import main as _main
from ece_suite import rtl

HAS_LV = LV.status()["installed"]

_DUT = ("module blink(input clk, output reg led);\n"
        "reg [23:0] c; always @(posedge clk) begin c<=c+1; led<=c[23]; end endmodule\n")
_PORTS = [{"port": "clk", "pin": "W5", "is_clock": True, "period_ns": 10},
          {"port": "led", "pin": "U16", "iostd": "LVCMOS33"}]


# --- LabVIEW ---------------------------------------------------------------
def test_labview_status_shape():
    st = LV.status()
    assert {"installed", "installs", "default", "cli", "cli_available", "download"} <= set(st)
    for i in st["installs"]:
        assert {"version", "path", "bitness"} <= set(i)


def test_labview_input_validation_is_honest():
    assert LV.run_vi("not-a-vi.txt")["ok"] is False
    assert LV.mass_compile(r"C:\definitely\not\a\dir")["ok"] is False
    assert LV.execute_build_spec("nope.lvproj")["ok"] is False


@pytest.mark.skipif(not HAS_LV, reason="LabVIEW not installed")
def test_labview_detects_real_install():
    st = LV.status()
    assert st["cli_available"], "LabVIEW present but LabVIEWCLI missing"
    assert any(i["version"] == "2025" for i in st["installs"])
    assert LV.list_projects() is not None  # scans real folders without raising


def test_labview_endpoints_contract():
    c = TestClient(_main.app)
    assert "installed" in c.get("/api/labview/status").json()
    assert "projects" in c.get("/api/labview/projects").json()
    r = c.post("/api/labview/run-vi", json={"vi_path": "missing.vi"}).json()
    assert r["ok"] is False


# --- PLD target map --------------------------------------------------------
def test_pld_targets_cover_vendors_and_cplds():
    t = rtl.pld_targets()
    assert {"xilinx", "intel", "lattice"} <= set(t)
    cplds = [f for v in t.values() for f in v["families"].values() if f.get("cpld")]
    assert len(cplds) >= 4  # CoolRunner-II, MAX II, MAX V, MachXO2/3
    for v in t.values():
        assert "tool_installed" in v
        for f in v["families"].values():
            assert f["part"]


# --- vendor project export -------------------------------------------------
def test_vivado_project_files():
    r = rtl.vendor_project(_DUT, "xilinx", "artix7", ports=_PORTS)
    assert r["ok"] and r["part"] == "xc7a35tcpg236-1" and r["top"] == "blink"
    f = r["files"]
    assert "build.tcl" in f and "synth_design -top blink -part xc7a35tcpg236-1" in f["build.tcl"]
    assert "write_bitstream" in f["build.tcl"]
    assert "PACKAGE_PIN W5" in f["constraints.xdc"] and "create_clock" in f["constraints.xdc"]
    assert "vivado -mode batch" in f["run.bat"]


def test_quartus_project_cpld():
    r = rtl.vendor_project(_DUT, "intel", "max2")
    assert r["ok"] and r["is_cpld"] and r["part"] == "EPM240T100C5"
    qsf = r["files"]["blink.qsf"]
    assert "DEVICE EPM240T100C5" in qsf and "TOP_LEVEL_ENTITY blink" in qsf
    assert "quartus_sh --flow compile" in r["files"]["run.bat"]


def test_lattice_open_flow_needs_no_vendor_tool():
    r = rtl.vendor_project(_DUT, "lattice", "ice40", ports=_PORTS)
    assert r["ok"]
    b = r["files"]["build_open.bat"]
    assert "synth_ice40" in b and "nextpnr-ice40" in b and "icepack" in b
    assert "pins.pcf" in r["files"]
    assert any("no vendor tool" in n for n in r["notes"])


def test_xilinx_cpld_refuses_honestly():
    r = rtl.vendor_project(_DUT, "xilinx", "coolrunner2")
    assert r["ok"] is False and "ISE" in r["error"]


def test_vendor_project_unknowns():
    assert rtl.vendor_project(_DUT, "nope", "x")["ok"] is False
    assert rtl.vendor_project(_DUT, "xilinx", "nope")["ok"] is False


def test_vendor_project_endpoint():
    c = TestClient(_main.app)
    r = c.post("/api/rtl/vendor-project", json={
        "source": _DUT, "vendor": "lattice", "family": "ecp5"}).json()
    assert r["ok"] and "build_radiant.tcl" in r["files"]
    t = c.get("/api/rtl/pld-targets").json()
    assert "xilinx" in t["vendors"]
