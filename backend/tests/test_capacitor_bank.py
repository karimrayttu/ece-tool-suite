"""Capacitor-bank sizing + loss."""

from __future__ import annotations

import json
import math

from fastapi.testclient import TestClient

from ece_suite import capacitor_bank as CB
from ece_suite import main as _main

client = TestClient(_main.app)


def test_buck_input_rms_matches_closed_form():
    # buck input-cap RMS = Iout * sqrt(D(1-D)); D = Vout/Vin
    r = CB.size("buck", 12, 3.3, 2.0, fsw_khz=500, il_ripple_pp_a=0.6)
    d = 3.3 / 12
    assert abs(r["input_cap"]["rms_current_a"] - 2.0 * math.sqrt(d * (1 - d))) < 1e-3
    # output-cap RMS = triangular inductor ripple / sqrt(12)
    assert abs(r["output_cap"]["rms_current_a"] - 0.6 / math.sqrt(12)) < 1e-3
    json.dumps(r)                                     # serializable


def test_boost_output_sees_high_pulsed_rms():
    r = CB.size("boost", 5, 12, 1.0, fsw_khz=500)
    d = 1 - 5 / 12
    assert abs(r["output_cap"]["rms_current_a"] - 1.0 * math.sqrt(d / (1 - d))) < 1e-2
    # boost output RMS >> its input RMS
    assert r["output_cap"]["rms_current_a"] > r["input_cap"]["rms_current_a"]


def test_voltage_derating_flags_overvoltage():
    # 24 V rail on a 25 V MLCC -> exceeds 80% (20 V) -> derating fails
    r = CB.size("buck", 48, 24, 1.0, vrated=25, dielectric="mlcc")
    assert r["output_cap"]["derating_ok"] is False
    assert r["output_cap"]["v_derated_limit"] == 20.0
    # tantalum derates harder (50%)
    rt = CB.size("buck", 48, 24, 1.0, vrated=25, dielectric="tantalum")
    assert rt["output_cap"]["v_derated_limit"] == 12.5


def test_parallel_count_scales_with_ripple_current():
    # a cap rated for only 0.2 A must be paralleled to carry a big ripple
    r = CB.size("boost", 5, 12, 3.0, fsw_khz=300, irms_each_a=0.2)
    assert r["output_cap"]["parallel_count"] >= 2
    assert r["output_cap"]["total_esr_mohm"] < r["candidate"]["esr_mohm"]   # ESR drops with parallels


def test_bad_input_handled():
    assert CB.size("buck", 0, 3.3, 2)["ok"] is False


def test_endpoint_and_mcp():
    resp = client.post("/api/power/capacitors", json={"topology": "buck", "vin": 12, "vout": 3.3, "iout": 2, "fsw_khz": 500})
    assert resp.status_code == 200 and resp.json()["ok"]
    assert "capacitor_bank" in client.get("/api/mcp/info").json()["tools"]
