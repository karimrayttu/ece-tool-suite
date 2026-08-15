"""Server-side session logging endpoints."""

from fastapi.testclient import TestClient

from ece_suite.main import app, recorder

client = TestClient(app)


def test_log_lifecycle_and_export():
    recorder.stop("dmm")
    recorder.clear("dmm")
    assert client.get("/api/log/dmm/status").json()["active"] is False

    client.post("/api/log/dmm/start")
    assert client.get("/api/log/dmm/status").json()["active"] is True

    recorder.record("dmm", {"value": 3.3, "unit": "V", "function": "VDC"})
    recorder.record("dmm", {"value": 3.31, "unit": "V", "function": "VDC"})
    assert client.get("/api/log/dmm/status").json()["count"] >= 2

    exp = client.get("/api/log/dmm/export")
    assert exp.status_code == 200
    assert "value" in exp.text and "3.3" in exp.text

    client.post("/api/log/dmm/stop")
    client.post("/api/log/dmm/clear")
    assert client.get("/api/log/dmm/status").json()["count"] == 0


def test_record_only_when_active():
    recorder.stop("dmm")
    recorder.clear("dmm")
    recorder.record("dmm", {"value": 1.0})  # not active -> dropped
    assert recorder.count("dmm") == 0
