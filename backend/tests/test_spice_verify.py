"""SPICE power-stage verification: netlist generation + (if an engine is present) real runs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ece_suite import main as _main
from ece_suite import spice_verify as SV

# Verification needs both halves: a binary to run the netlist and spicelib to read
# the .raw it produces. They install separately, so check both.
HAS_ENGINE = bool(SV.engines()) and SV.can_read_raw()


def test_engines_shape():
    for e in SV.engines():
        assert {"id", "name", "path"} <= set(e)


def test_buck_netlist_structure():
    nl = SV.buck_netlist(12, 3.3, 2, 10, 47, 500)
    assert ".tran" in nl and ".end" in nl
    assert "L1 sw nx 1e-05" in nl or "1e-05" in nl        # 10 uH inductor present
    assert "Dfw" in nl and "S1" in nl and "S2" in nl        # freewheel diode + both switches
    assert "PULSE" in nl                                     # gate drive


def test_boost_netlist_structure():
    nl = SV.boost_netlist(5, 12, 1, 15, 220, 500)
    assert ".tran" in nl and "D1 sw out" in nl and "L1 in sw" in nl


def test_status_endpoint():
    r = TestClient(_main.app).get("/api/spice/status").json()
    assert "engines" in r and isinstance(r["engines"], list)


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a SPICE engine and the spice extra")
def test_wellsized_buck_verifies():
    r = SV.verify("buck", vin=12, vout=3.3, iout=2, L_uH=10, Cout_uF=47, fsw_khz=500)
    assert r["ok"], r.get("error")
    m = r["metrics"]
    # physically sane: ~3.3V, IL ripple near the analytic (Vin-Vout)*D/(L*fsw)=~0.48A, good eff
    assert 2.7 < m["vout_mean"] < 3.4
    assert m["il_ripple_pct"] is not None and m["il_ripple_pct"] < 45
    assert m["efficiency_pct"] is None or m["efficiency_pct"] > 85
    assert r["verified"] is True


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a SPICE engine and the spice extra")
def test_undersized_inductor_fails_verification():
    # a 1.5 uH inductor at 12->3.3/2A is badly under-sized -> huge inductor ripple -> must FAIL
    r = SV.verify("buck", vin=12, vout=3.3, iout=2, L_uH=1.5, Cout_uF=47, fsw_khz=500)
    assert r["ok"]
    assert r["metrics"]["il_ripple_pct"] > 60
    assert r["verified"] is False
    assert any(c["name"] == "Inductor ripple" and not c["pass"] for c in r["checks"])


@pytest.mark.skipif(not HAS_ENGINE, reason="needs a SPICE engine and the spice extra")
def test_verify_endpoint_serializes():
    # regression: numpy scalars must be coerced so FastAPI can serialize the response
    r = TestClient(_main.app).post("/api/spice/verify", json={
        "topology": "buck", "vin": 12, "vout": 3.3, "iout": 2, "L_uH": 10, "Cout_uF": 47, "fsw_khz": 500})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and isinstance(d["verified"], bool)
    assert all(isinstance(c["pass"], bool) for c in d["checks"])
    assert len(d["metrics"]["waveform"]["vout"]) > 100
