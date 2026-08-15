"""Parametric value normalizer + parts enrichment (jlcparts-inspired)."""

from __future__ import annotations

import math

from fastapi.testclient import TestClient

from ece_suite import main as _main
from ece_suite import param_parse as PP
from ece_suite import parts

client = TestClient(_main.app)


def test_si_prefix_and_units():
    assert math.isclose(PP.parse_value("4.7µF")["value"], 4.7e-6)
    assert PP.parse_value("4.7µF")["unit"] == "F"
    assert math.isclose(PP.parse_value("10 mΩ")["value"], 0.01)
    assert math.isclose(PP.parse_value("480MHz")["value"], 480e6)
    assert math.isclose(PP.parse_value("100nF")["value"], 100e-9)
    assert PP.parse_value("2.5A")["unit"] == "A"


def test_engineering_r_k_m_notation():
    assert math.isclose(PP.parse_value("4k7", "Ω")["value"], 4700)
    assert math.isclose(PP.parse_value("4R7")["value"], 4.7)
    assert math.isclose(PP.parse_value("1M5", "Ω")["value"], 1.5e6)
    assert math.isclose(PP.parse_value("0R01")["value"], 0.01)
    assert PP.parse_value("4R7")["unit"] == "Ω"


def test_tolerance_and_unparseable():
    assert math.isclose(PP.parse_tolerance("±10%"), 0.10)
    assert math.isclose(PP.parse_tolerance("1%"), 0.01)
    assert PP.parse_tolerance("nope") is None
    assert PP.parse_value("") is None
    assert PP.parse_value("garbage!!") is None


def test_normalize_specs_typed_fields():
    t = PP.normalize_specs({"capacitance": "10uF", "voltage": "6.3V"})
    assert math.isclose(t["capacitance_value"], 10e-6) and t["capacitance_unit"] == "F"
    assert math.isclose(t["voltage_value"], 6.3)
    r = PP.normalize_specs({"resistance": "4k7", "tol": "1%"})
    assert math.isclose(r["resistance_value"], 4700) and math.isclose(r["tol_fraction"], 0.01)


def test_search_results_are_enriched():
    res = parts.search_offline("10uF")
    assert res, "expected the 10uF cap in the catalog"
    hit = next(p for p in res if "10uF" in p["desc"] or "106" in p["mpn"])
    assert math.isclose(hit["specs_typed"].get("capacitance_value"), 10e-6)


def test_numeric_range_filter():
    # capacitors with capacitance >= 1uF: the 10uF passes, the 100nF does not
    res = parts.search_offline(category="capacitor", spec_key="capacitance", vmin=1e-6)
    caps = {p["mpn"] for p in res}
    assert any("106" in m for m in caps)                    # 10uF present
    assert not any("104" in m for m in caps)                # 100nF filtered out


def test_load_external_catalog():
    n0 = parts.status()["external_loaded"]
    added = parts.load_external([{"mpn": "TEST-CAP-1", "mfr": "Acme", "desc": "CAP 47uF 35V",
                                  "category": "capacitor", "specs": {"capacitance": "47uF", "voltage": "35V"}}])
    assert added == 1 and parts.status()["external_loaded"] == n0 + 1
    hit = next(p for p in parts.search_offline("TEST-CAP-1") if p["mpn"] == "TEST-CAP-1")
    assert math.isclose(hit["specs_typed"]["capacitance_value"], 47e-6)


def test_endpoints():
    d = client.get("/api/parts/parse", params={"text": "4k7", "unit": "Ω"}).json()
    assert d["value"] == 4700
    s = client.get("/api/parts/search", params={"category": "capacitor", "spec_key": "capacitance", "vmin": 1e-6}).json()
    assert s["ok"] and all(r["specs_typed"].get("capacitance_value", 0) >= 1e-6 for r in s["results"])
