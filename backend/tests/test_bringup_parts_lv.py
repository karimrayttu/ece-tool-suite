"""Parts-from-URL, FPGA bring-up chain, and LabVIEW COM/template surfaces."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ece_suite import labview as LV
from ece_suite import main as _main
from ece_suite import parts_url as PU
from ece_suite import rtl

HAS_FLOW = rtl.toolchain()["capabilities"]["synthesize"] and rtl._which("nextpnr-ice40")
HAS_OFL = rtl._ofl() is not None


# --- parts from URL (offline URL-structure parsing) ------------------------
def test_url_parsers_extract_mpn():
    cases = {
        "https://www.digikey.com/en/products/detail/texas-instruments/INA240A1PWR/6109679":
            ("Digi-Key", "INA240A1PWR"),
        "https://www.mouser.com/ProductDetail/Texas-Instruments/TPS62840DLCR?qs=x":
            ("Mouser", None),  # single-seg Mfr-MPN form: partition at first dash
        "https://www.lcsc.com/product-detail/Voltage-Regulators_AMS-AMS1117-3-3_C6186.html":
            ("LCSC", "C6186"),
        "https://www.ti.com/product/DRV8301": ("Texas Instruments", "DRV8301"),
    }
    for url, (vendor, mpn) in cases.items():
        r = PU.parse_url(url)
        assert r["vendor"] == vendor, url
        if mpn:
            assert r["mpn"] == mpn, url


def test_mouser_single_segment_form():
    r = PU.parse_url("https://www.mouser.com/ProductDetail/511-STM32H743ZIT6")
    assert r["vendor"] == "Mouser" and r["mpn"] == "STM32H743ZIT6"


def test_part_from_url_rejects_non_url():
    assert PU.part_from_url("not a url")["ok"] is False


def test_part_from_url_offline_no_fetch():
    r = PU.part_from_url("https://www.ti.com/product/INA240", fetch=False)
    assert r["ok"] and r["mpn"] == "INA240" and r["fetched"] is False
    assert r["name"]  # falls back to mpn


def test_jsonld_product_extraction():
    html = ('<script type="application/ld+json">{"@type":"Product","name":"Best Chip",'
            '"mpn":"XYZ-1","brand":{"name":"Acme"},"offers":{"price":"1.23"}}</script>')
    prods = PU._jsonld_products(html)
    assert prods and prods[0]["mpn"] == "XYZ-1"


def test_parts_list_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(PU, "DATA_DIR", tmp_path)
    monkeypatch.setattr(PU, "LIST_PATH", tmp_path / "parts_list.json")
    a = PU.add_part({"mpn": "ABC123", "vendor": "Digi-Key", "source_url": "https://x/1"})
    assert a["ok"] and not a["duplicate"] and a["count"] == 1
    d = PU.add_part({"mpn": "ABC123", "vendor": "Digi-Key", "source_url": "https://x/1"})
    assert d["duplicate"]
    assert len(PU.list_parts()) == 1
    rid = PU.list_parts()[0]["id"]
    assert PU.remove_part(rid)["removed"] == 1
    assert PU.list_parts() == []


def test_parts_endpoints_contract():
    c = TestClient(_main.app)
    r = c.post("/api/parts/from-url", json={"url": "nope", "add": False}).json()
    assert r["ok"] is False
    assert "parts" in c.get("/api/parts/list").json()
    assert c.get("/api/parts/list/export").status_code == 200


# --- FPGA bring-up ---------------------------------------------------------
_BLINKY = ("module blink(input clk, output reg led);\n"
           "reg [22:0] c; always @(posedge clk) begin c<=c+1; led<=c[22]; end endmodule\n")


@pytest.mark.skipif(not HAS_OFL, reason="openFPGALoader not installed")
def test_fpga_boards_list_live():
    r = rtl.fpga_boards()
    assert r["ok"] and r["count"] > 50           # real board DB, not a stub


@pytest.mark.skipif(not HAS_OFL, reason="openFPGALoader not installed")
def test_fpga_detect_honest_without_cable():
    r = rtl.fpga_detect()
    assert r["ok"]                # tool ran
    assert isinstance(r["found"], bool)          # honest boolean, log included
    assert "log" in r


@pytest.mark.skipif(not HAS_FLOW, reason="yosys+nextpnr-ice40 required")
def test_bitstream_end_to_end_live(tmp_path, monkeypatch):
    monkeypatch.setattr(rtl, "_BUILD_ROOT", tmp_path)
    r = rtl.fpga_bitstream(_BLINKY, "ice40")
    assert r["ok"] and r["built"], r.get("steps")
    assert r["bitstream"] and r["size_bytes"] > 1000     # a real iCE40 bitstream
    assert r["fmax_mhz"] and r["fmax_mhz"] > 1
    assert [s["ok"] for s in r["steps"]] == [True, True, True]


def test_program_rejects_missing_bitstream():
    r = rtl.fpga_program(r"C:\nope\missing.bin")
    assert r["ok"] is False


def test_vendor_export_writes_files(tmp_path, monkeypatch):
    monkeypatch.setattr(rtl, "_VENDOR_ROOT", tmp_path)
    r = rtl.vendor_export(_BLINKY, "xilinx", "artix7")
    assert r["ok"] and "build.tcl" in r["files_written"]
    from pathlib import Path
    assert (Path(r["dir"]) / "run.bat").exists()


def test_vendor_launch_rejects_bad_dir():
    assert rtl.vendor_launch(r"C:\definitely\not\here")["ok"] is False


# --- LabVIEW COM / templates ----------------------------------------------
def test_lv_vi_run_validates_path():
    assert LV.vi_run_com("missing.vi")["ok"] is False


def test_lv_templates_shape():
    t = LV.list_templates()
    assert t["ok"] and isinstance(t["templates"], list)
    if LV.status()["installed"]:
        assert t["count"] > 0                      # LabVIEW ships templates


def test_lv_builder_status_honest():
    b = LV.builder_status()
    assert "available" in b and "builder_vi" in b


def test_lv_dashboard_gated_without_builder(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(LV, "BUILDER_VI", Path(r"C:\nope\VIBuilder.vi"))
    r = LV.generate_dashboard({"title": "x"}, r"C:\nope\out.vi")
    assert r["ok"] is False and "guide" in r


def test_lv_endpoints_contract():
    c = TestClient(_main.app)
    assert "templates" in c.get("/api/labview/templates").json()
    assert "available" in c.get("/api/labview/builder-status").json()
    r = c.post("/api/labview/vi-run", json={"vi_path": "missing.vi"}).json()
    assert r["ok"] is False
