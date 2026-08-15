"""WebSocket telemetry streams — the live path the UI depends on.

Covers the audit gap: all 7 /ws/* endpoints had zero automated coverage. Verifies the
hardware-first not-connected frame, that each stream actually LOOPS (>1 frame), the
/ws/dmm -> datalog recorder side-effect that feeds CSV export, and /ws/chat's honest
no-API-key error event.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ece_suite import main as _main

client = TestClient(_main.app)

TELEMETRY_WS = ["/ws/scope", "/ws/dmm", "/ws/sa", "/ws/psu", "/ws/awg", "/ws/eload"]


def test_all_telemetry_streams_send_honest_not_connected_and_loop():
    for path in TELEMETRY_WS:
        with client.websocket_connect(path) as ws:
            first = ws.receive_json()
            second = ws.receive_json()      # proves the streaming loop, not a one-shot
        assert first == {"connected": False}, f"{path} first frame: {first}"
        assert second == {"connected": False}, f"{path} second frame: {second}"


class _FakeDmm:
    """Stands in for a connected DMM driver (read() shape matches KeysightDmm.read)."""

    def read(self) -> dict:
        return {"connected": True, "provenance": "VERIFIED_HW", "value": 1.234,
                "unit": "V DC", "function": "VOLT"}


def test_ws_dmm_streams_reading_and_records_to_datalog(monkeypatch):
    monkeypatch.setattr(_main, "dmm_driver", lambda: _FakeDmm())
    _main.recorder.clear("dmm")
    assert client.post("/api/log/dmm/start").json()["active"] is True
    try:
        with client.websocket_connect("/ws/dmm") as ws:
            frame = ws.receive_json()
        assert frame["connected"] is True and frame["value"] == 1.234
        # side-effect: the reading was recorded while streaming
        status = client.get("/api/log/dmm/status").json()
        assert status["count"] >= 1
        # and the live CSV export path serves it
        r = client.get("/api/log/dmm/export")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "1.234" in r.text
    finally:
        client.post("/api/log/dmm/stop")
        _main.recorder.clear("dmm")


def test_ws_dmm_error_frame_keeps_connection_alive(monkeypatch):
    class _Broken:
        def read(self) -> dict:
            raise RuntimeError("VISA timeout")

    monkeypatch.setattr(_main, "dmm_driver", lambda: _Broken())
    with client.websocket_connect("/ws/dmm") as ws:
        first = ws.receive_json()
        second = ws.receive_json()          # loop survives the driver error
    assert first == {"connected": True, "error": "VISA timeout"}
    assert second["error"] == "VISA timeout"


def test_ws_chat_honest_error_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "hello"})
        ev = ws.receive_json()
    assert ev["type"] == "error"
    assert "ANTHROPIC_API_KEY" in ev["message"]


def test_ws_chat_ignores_empty_message(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "   "})    # ignored — loop continues
        ws.send_json({"message": "real"})
        ev = ws.receive_json()
    assert ev["type"] == "error"            # the honest no-key event for the real message
