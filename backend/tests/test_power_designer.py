"""Native WEBENCH-class power designer + Digi-Key adapter (no-key states)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ece_suite import digikey as DK
from ece_suite import main as _main
from ece_suite import power_designer as P


def test_topology_selection():
    assert P.recommend_topology(12, 3.3, 2)["topology"] == "buck"
    assert P.recommend_topology(5, 12, 1)["topology"] == "boost"
    assert P.recommend_topology(5, 5, 1)["topology"] == "buck-boost"
    assert P.recommend_topology(5, 3.3, 0.3)["topology"] == "ldo"       # small drop, low current


def test_candidate_parts_are_real_ti():
    parts = P.candidate_parts("buck", 12, 3.3, 2)
    mpns = {p["mpn"] for p in parts}
    assert mpns and mpns <= {p["mpn"] for p in P.TI_PARTS}
    assert all(p["datasheet"].startswith("https://www.ti.com/product/") for p in parts)


def test_sizing_and_compensation():
    d = P.design(12, 3.3, 2)
    assert d["recommendation"]["topology"] == "buck"
    assert d["sizing"]["inductor_uH"] > 0 and d["sizing"]["output_cap_uF"] > 0
    c = d["compensation"]
    assert c["crossover_hz"] == 50000.0 and c["power_pole_hz"] > 0
    assert c["type2"]["Rc_ohm"] > 0 and c["type2"]["Cc1_nF"] > 0


def test_isolated_selects_flyback_and_surfaces_flyback_parts():
    # isolation is an explicit input (not inferable from Vin/Vout/Iout)
    rec = P.recommend_topology(48, 12, 0.1, isolated=True)
    assert rec["topology"] == "flyback"
    d = P.design(48, 12, 0.1, isolated=True)
    assert d["recommendation"]["topology"] == "flyback"
    assert {p["mpn"] for p in d["parts"]} >= {"LM5180"}      # flyback catalog parts now reachable
    assert d["sizing"]["turns_ratio_np_ns"] > 0
    # non-isolated stays buck (defensible for a non-isolated 48->12 step-down)
    assert P.design(48, 12, 0.1)["recommendation"]["topology"] == "buck"


def test_flyback_and_ldo_sizing():
    fb = P.size_stage("flyback", 48, 12, 0.1)
    assert fb["turns_ratio_np_ns"] > 0 and fb["primary_inductance_uH"] > 0
    ldo = P.size_stage("ldo", 5, 3.3, 0.3)
    assert abs(ldo["power_dissipation_w"] - (5 - 3.3) * 0.3) < 1e-6 and ldo["dropout_ok"]


def test_digikey_honest_without_keys():
    assert DK.configured() is False
    assert DK.status()["configured"] is False
    r = DK.search_parts("TPS")
    assert r["ok"] is False and "credentials" in r["error"].lower()
    assert DK.webench_launch("TPS54560").startswith("https://webench.ti.com/")


def test_endpoints():
    c = TestClient(_main.app)
    d = c.get("/api/power/design", params={"vin": 12, "vout": 3.3, "iout": 2}).json()
    assert d["ok"] and d["recommendation"]["topology"] == "buck" and len(d["parts"]) > 0
    s = c.get("/api/digikey/status").json()
    assert s["configured"] is False and "developer.digikey.com" in s["register_url"]
