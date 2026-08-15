"""Function generator + electronic load — safety-gated through the preset runner."""

import pytest
from fastapi.testclient import TestClient

from ece_suite.instruments.sim import SimEload, SimFuncGen
from ece_suite.main import app, manager

client = TestClient(app)

AWG = {"func": "SIN", "freq": 1000, "vpp": 2.0, "offset": 0.0, "dut_max_v": 3.0, "dut_max_i": 1.0}
ELOAD = {"mode": "CURR", "level": 1.0, "ocp": 2.0, "dut_max_v": 30.0, "dut_max_i": 2.0}


@pytest.fixture(autouse=True)
def _src():
    manager.set("awg", SimFuncGen())
    manager.set("eload", SimEload(source_v=5.0))
    yield
    manager.disconnect("awg")
    manager.disconnect("eload")


def test_awg_preview_requires_confirm_within_envelope():
    pv = client.post("/api/awg/preview", json=AWG).json()
    assert pv["overall"] == "REQUIRE_CONFIRM" and pv["ok_to_run"]  # peak 1.0 V <= 3.0


def test_awg_over_envelope_blocked():
    pv = client.post("/api/awg/preview", json={**AWG, "vpp": 8.0}).json()  # peak 4.0 > 3.0
    assert pv["overall"] == "BLOCK"


def test_awg_apply_confirm_enables_then_off():
    a = client.post("/api/awg/apply", json={**AWG, "confirm": True}).json()
    assert a["ok"], a["summary"]
    assert manager.get("awg").output is True
    assert client.post("/api/awg/off").json()["ok"]
    assert manager.get("awg").output is False


def test_awg_apply_without_confirm_aborts():
    a = client.post("/api/awg/apply", json={**AWG, "confirm": False}).json()
    assert not a["ok"]
    assert manager.get("awg").output is False


def test_eload_preview_requires_confirm():
    pv = client.post("/api/eload/preview", json=ELOAD).json()
    assert pv["overall"] == "REQUIRE_CONFIRM" and pv["ok_to_run"]


def test_eload_over_envelope_blocked():
    pv = client.post("/api/eload/preview", json={**ELOAD, "level": 5.0}).json()  # 5 A > 2 A
    assert pv["overall"] == "BLOCK"


def test_eload_apply_confirm_enables_then_off():
    a = client.post("/api/eload/apply", json={**ELOAD, "confirm": True}).json()
    assert a["ok"], a["summary"]
    assert manager.get("eload").input is True
    assert client.post("/api/eload/off").json()["ok"]
    assert manager.get("eload").input is False
