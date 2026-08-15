"""Safety-gated PSU/source endpoints (sim PSU connected for the test)."""

import pytest
from fastapi.testclient import TestClient

from ece_suite.instruments.sim import SimPSU
from ece_suite.main import app, manager

client = TestClient(app)

BASE = {"vset": 3.3, "iset": 0.5, "ovp": 3.6, "ocp": 0.6, "dut_max_v": 3.6, "dut_max_i": 0.6}


@pytest.fixture(autouse=True)
def _psu():
    manager.set("psu", SimPSU())
    yield
    manager.disconnect("psu")


def test_preview_requires_confirm_within_envelope():
    pv = client.post("/api/psu/preview", json=BASE).json()
    assert pv["overall"] == "REQUIRE_CONFIRM" and pv["ok_to_run"]


def test_preview_over_envelope_blocked():
    pv = client.post("/api/psu/preview", json={**BASE, "vset": 5.0}).json()
    assert pv["overall"] == "BLOCK" and not pv["ok_to_run"]


def test_apply_without_confirm_aborts_output_off():
    a = client.post("/api/psu/apply", json={**BASE, "confirm": False}).json()
    assert not a["ok"] and a["rolled_back"]
    assert manager.get("psu").output is False


def test_apply_with_confirm_energizes_then_off():
    a = client.post("/api/psu/apply", json={**BASE, "confirm": True}).json()
    assert a["ok"], a["summary"]
    assert manager.get("psu").output is True
    off = client.post("/api/psu/off").json()
    assert off["ok"]
    assert manager.get("psu").output is False


def test_not_connected():
    manager.disconnect("psu")
    a = client.post("/api/psu/apply", json={**BASE, "confirm": True}).json()
    assert a.get("connected") is False
