"""Instrument screenshot endpoint returns a valid PNG (sim renders the current trace)."""

from fastapi.testclient import TestClient

from ece_suite.instruments.sim import SimScope, SimSpectrumAnalyzer
from ece_suite.main import app, manager

client = TestClient(app)
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def test_scope_screenshot_is_png():
    manager.set("scope", SimScope())
    try:
        r = client.get("/api/scope/screenshot")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == PNG_SIG
        assert len(r.content) > 100
    finally:
        manager.disconnect("scope")


def test_sa_screenshot_is_png():
    manager.set("sa", SimSpectrumAnalyzer())
    try:
        r = client.get("/api/sa/screenshot")
        assert r.status_code == 200 and r.content[:8] == PNG_SIG
    finally:
        manager.disconnect("sa")


def test_screenshot_disconnected_409():
    manager.disconnect("scope")
    assert client.get("/api/scope/screenshot").status_code == 409


def test_screenshot_unsupported_role_404():
    assert client.get("/api/dmm/screenshot").status_code == 404
