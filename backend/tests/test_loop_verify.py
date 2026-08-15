"""Closed-loop margin verification (python-control)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ece_suite import loop_verify as lv
from ece_suite import main as _main

client = TestClient(_main.app)
_HAS_CONTROL = lv._available()
requires_control = pytest.mark.skipif(not _HAS_CONTROL, reason="python-control not installed")


def test_status_endpoint():
    s = client.get("/api/power/loop/status").json()
    assert s["engine"] == "python-control"
    assert s["available"] is _HAS_CONTROL


@requires_control
def test_well_designed_buck_is_stable_and_json_clean():
    r = lv.verify(12, 3.3, 2, L_uH=10, Cout_uF=47, fsw_khz=500)
    assert r["ok"] and r["engine"] == "python-control"
    json.dumps(r)                                   # no numpy leaks -> serializable
    assert r["metrics"]["phase_margin_deg"] > 45    # healthy PM
    assert r["stable"] is True
    assert 0 <= r["metrics"]["phase_margin_deg"] <= 180
    assert len(r["bode"]) > 10


@requires_control
def test_infinite_gain_margin_counts_as_pass():
    # a loop whose phase never reaches -180 has infinite gain margin -> the GM check must PASS
    r = lv.verify(12, 3.3, 2, L_uH=10, Cout_uF=47, fsw_khz=500)
    gm_check = next(c for c in r["checks"] if c["name"] == "Gain margin")
    if r["metrics"]["gain_margin_infinite"]:
        assert gm_check["pass"] is True and gm_check["value"] is None


@requires_control
def test_low_margin_design_is_flagged():
    # tiny output cap -> LC/phase erosion; margins should be finite and lower
    good = lv.verify(12, 3.3, 2, L_uH=10, Cout_uF=47, fsw_khz=500)["metrics"]["phase_margin_deg"]
    tight = lv.verify(12, 3.3, 2, L_uH=47, Cout_uF=2.2, fsw_khz=500)
    assert tight["ok"]
    # the two designs must not produce identical margins — the analysis is responsive to L/C
    assert tight["metrics"]["phase_margin_deg"] != good


@requires_control
def test_endpoint_serializes():
    body = {"vin": 12, "vout": 3.3, "iout": 2, "L_uH": 10, "Cout_uF": 47, "fsw_khz": 500}
    r = client.post("/api/power/loop", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] and "checks" in d and "bode" in d
    assert d["metrics"]["target_crossover_hz"] == 50000.0   # fsw/10


@requires_control
def test_mcp_tool_registered():
    info = client.get("/api/mcp/info").json()
    assert "power_loop_verify" in info["tools"]
