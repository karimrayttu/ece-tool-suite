"""Preset library + REST endpoints. The app is hardware-first, so tests connect sims."""

import pytest
from fastapi.testclient import TestClient

from ece_suite.instruments.sim import SimDMM, SimPSU, SimScope, SimSpectrumAnalyzer
from ece_suite.main import app, manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def _connect_sims():
    manager.set("scope", SimScope())
    manager.set("dmm", SimDMM())
    manager.set("sa", SimSpectrumAnalyzer())
    manager.set("psu", SimPSU())
    yield
    for r in ("scope", "dmm", "sa", "psu"):
        manager.disconnect(r)


def test_presets_listed():
    ids = {p["id"] for p in client.get("/api/presets").json()}
    assert {"scope_i2c", "scope_ripple", "dmm_dc_rail", "sa_spur", "psu_3v3_rail"} <= ids


def test_measurement_preset_preview_allows_and_applies():
    pv = client.post("/api/presets/scope_i2c/preview").json()
    assert pv["overall"] == "ALLOW" and pv["ok_to_run"]
    a = client.post("/api/presets/scope_i2c/apply").json()
    assert a["ok"] and a["provenance"] == "SIMULATED"


def test_psu_preset_blocked_without_envelope():
    pv = client.post("/api/presets/psu_3v3_rail/preview").json()
    assert pv["overall"] == "BLOCK" and not pv["ok_to_run"]


def test_psu_preset_with_envelope_requires_confirm():
    body = {"envelope": {"max_voltage": 3.6, "max_current": 0.6}}
    pv = client.post("/api/presets/psu_3v3_rail/preview", json=body).json()
    assert pv["overall"] == "REQUIRE_CONFIRM" and pv["ok_to_run"]


def test_psu_apply_without_confirm_aborts_output_off():
    body = {"envelope": {"max_voltage": 3.6, "max_current": 0.6}, "confirm": False}
    a = client.post("/api/presets/psu_3v3_rail/apply", json=body).json()
    assert not a["ok"] and a["rolled_back"]
    assert manager.get("psu").output is False


def test_psu_apply_with_confirm_energizes():
    body = {"envelope": {"max_voltage": 3.6, "max_current": 0.6}, "confirm": True}
    a = client.post("/api/presets/psu_3v3_rail/apply", json=body).json()
    assert a["ok"], a["summary"]
    assert manager.get("psu").output is True


def test_preset_not_connected_reports_so():
    manager.disconnect("psu")  # simulate no PSU
    pv = client.post("/api/presets/psu_3v3_rail/preview", json={"envelope": {"max_voltage": 3.6, "max_current": 0.6}}).json()
    assert pv.get("connected") is False


def test_unknown_preset_404():
    assert client.post("/api/presets/nope/preview").status_code == 404
