"""pymcuprog integration: device catalog + metadata work offline; hardware paths error honestly."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ece_suite import main as _main
from ece_suite import programmer as P

# The device catalog and its metadata come out of pymcuprog itself, so those tests need the
# `mcu` extra. The gating and honest-error tests below run either way.
requires_pymcuprog = pytest.mark.skipif(not P.available(), reason="needs the mcu extra")


@requires_pymcuprog
def test_available_and_catalog():
    assert P.available() is True
    devs = P.supported_devices()
    assert len(devs) > 50 and "atmega4809" in devs


@requires_pymcuprog
def test_device_info_metadata():
    info = P.device_info("atmega4809")
    assert info["flash_size_bytes"] == 49152        # 48 KB
    assert info["architecture"] == "avr8x" and info["interface"] == "UPDI"


def test_read_without_tool_is_honest():
    r = P.read_target("atmega4809")
    assert r["ok"] is False and "debugger" in r["error"].lower()


def test_destructive_ops_gated():
    assert P.chip_erase("atmega4809", None, confirm=False)["ok"] is False
    assert P.write_hex("atmega4809", None, ":00000001FF", confirm=False)["ok"] is False


@requires_pymcuprog
def test_endpoints():
    c = TestClient(_main.app)
    assert c.get("/api/mcu/status").json()["available"] is True
    assert len(c.get("/api/mcu/devices").json()["devices"]) > 50
    assert c.get("/api/mcu/device/atmega4809").json()["flash_size_bytes"] == 49152
    r = c.post("/api/mcu/read", json={"device": "atmega4809"}).json()
    assert r["ok"] is False and "debugger" in r["error"].lower()
    assert c.post("/api/mcu/erase", json={"device": "atmega4809", "confirm": False}).json()["ok"] is False
