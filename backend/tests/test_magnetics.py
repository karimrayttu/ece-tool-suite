"""OpenMagnetics/MKF magnetics adapter."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ece_suite import magnetics as M
from ece_suite import main as _main

client = TestClient(_main.app)
_HAS = M.available()
requires_om = pytest.mark.skipif(not _HAS, reason="PyOpenMagnetics not installed")


def test_status_endpoint_shape():
    s = client.get("/api/power/magnetics/status").json()
    assert "available" in s
    if _HAS:
        assert s["core_materials"] > 100 and s["core_shapes"] > 100
        assert s["wires"] and s["wires"] > 100
        assert any("Ferroxcube" in m or "TDK" in m for m in s["core_manufacturers"])


@requires_om
def test_advise_inductor_returns_real_designs_with_losses():
    r = M.advise_inductor(10, i_dc=2.0, i_ripple_pp=0.6, fsw_khz=500, n_results=3)
    assert r["ok"], r.get("error")
    json.dumps(r)                                       # JSON-clean (no numpy / nan leak)
    assert r["designs"], "expected at least one core design"
    d = r["designs"][0]
    assert d["core_shape"] and d["core_material"]       # a real catalog core was chosen
    assert d["turns"] and d["turns"][0] > 0
    assert d["core_loss_w"] is not None and d["core_loss_w"] >= 0
    assert d["winding_loss_w"] is not None and d["winding_loss_w"] >= 0
    # derived current envelope is physically ordered
    assert r["requirement"]["i_peak_a"] >= r["requirement"]["i_dc_a"]


@requires_om
def test_endpoint_serializes():
    body = {"inductance_uH": 22, "i_dc": 1.0, "i_ripple_pp": 0.3, "fsw_khz": 400, "n_results": 2}
    resp = client.post("/api/power/magnetics", json=body)
    assert resp.status_code == 200
    d = resp.json()
    assert d["ok"] and d["engine"].startswith("OpenMagnetics")
    assert len(d["designs"]) >= 1


def test_mcp_tool_registered():
    info = client.get("/api/mcp/info").json()
    assert "magnetics_advise" in info["tools"]


@requires_om
def test_bad_input_is_handled():
    r = M.advise_inductor(0, i_dc=1, i_ripple_pp=0.2)
    assert r["ok"] is False and "positive" in r["error"]
