"""VISA control endpoints — hardware-first (no instruments connected by default)."""

from fastapi.testclient import TestClient

from ece_suite.instruments.sim import SimScope
from ece_suite.main import app, manager

client = TestClient(app)


def test_visa_resources_returns_list():
    r = client.get("/api/visa/resources")
    assert r.status_code == 200
    assert isinstance(r.json().get("resources"), list)


def test_starts_disconnected():
    manager.disconnect("scope")
    h = client.get("/health").json()
    assert h["mode"] == "hardware"
    assert h["instruments"]["scope"]["connected"] is False
    assert h["any_connected"] in (True, False)


def test_connect_bad_resource_returns_error():
    manager.disconnect("scope")
    j = client.post("/api/instruments/scope/connect", json={"resource": "BOGUS::1::INSTR"}).json()
    assert j["ok"] is False and "error" in j
    assert client.get("/health").json()["instruments"]["scope"]["connected"] is False


def test_verify_disconnected_reports_not_connected():
    manager.disconnect("scope")
    r = client.post("/api/instruments/scope/verify").json()
    assert r["ok"] is False and r.get("connected") is False


def test_verify_connected_sim_not_promotable():
    manager.set("scope", SimScope())
    try:
        r = client.post("/api/instruments/scope/verify").json()
        assert r["ok"] is False and r["provenance"] == "SIMULATED"
    finally:
        manager.disconnect("scope")


def test_unknown_role_404():
    assert client.post("/api/instruments/nope/verify").status_code == 404


def test_health_no_hardware_verified():
    assert client.get("/health").json()["hardware_connected"] is False
