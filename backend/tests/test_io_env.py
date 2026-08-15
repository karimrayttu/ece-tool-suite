"""Plug-and-play: role classification, USB VID mapping, and environment assessment."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ece_suite import io_env
from ece_suite import main as _main
from ece_suite.instruments.transport import Transport
from ece_suite.instruments.vendors import classify_role, vendor_for_vid
from ece_suite.provenance import Provenance


@pytest.mark.parametrize("model,role", [
    ("DSOX1204G", "scope"), ("MSO54", "scope"), ("EDUX1052A", "scope"), ("SDS1104X-E", "scope"),
    ("TDS2024C", "scope"), ("DHO924S", "scope"),
    ("34461A", "dmm"), ("8846A", "dmm"), ("287", "dmm"), ("DM3068", "dmm"), ("SDM3055", "dmm"),
    ("N9010B", "sa"), ("CXA N9000B", "sa"), ("FieldFox N9918A", "sa"),
    ("E36313A", "psu"), ("EDU36311A", "psu"), ("SPD3303X", "psu"),
    ("33500B", "awg"), ("EDU33212A", "awg"), ("SDG2042X", "awg"),
    ("N3300A", "eload"), ("SDL1020X", "eload"),
    ("SOMETHINGWEIRD", None),
])
def test_classify_role(model, role):
    assert classify_role(model) == role


def test_vendor_for_vid():
    assert vendor_for_vid(0x2A8D) == "keysight"
    assert vendor_for_vid(0x0957) == "keysight"
    assert vendor_for_vid(0x1AB1) == "rigol"
    assert vendor_for_vid(0x0699) == "tektronix"
    assert vendor_for_vid(0xF4EC) == "siglent"
    assert vendor_for_vid(0x1234) == "unknown"


def test_assess_shape():
    a = io_env.assess()
    assert set(a) >= {"backends", "system_visa", "usb_drivable", "lan_drivable",
                      "usb_instruments", "recommendations", "ready"}
    assert isinstance(a["backends"], list) and a["backends"]
    assert isinstance(a["usb_instruments"], list)
    assert isinstance(a["recommendations"], list)
    # pyvisa-py is always importable -> LAN drivable -> ready
    assert a["lan_drivable"] is True and a["ready"] is True


class _FakeProc:
    def __init__(self, stdout): self.stdout = stdout


def test_detect_known_vendor_vid(monkeypatch):
    import json
    dev = {"Name": "Keysight DSOX1204G", "PNPDeviceID": r"USB\VID_2A8D&PID_0396\ABC",
           "CompatibleID": [r"USB\Class_FE&SubClass_03&Prot_01"], "Status": "OK"}
    monkeypatch.setattr(io_env.subprocess, "run", lambda *a, **k: _FakeProc(json.dumps(dev)))
    out = io_env.detect_usb_instruments()
    assert len(out) == 1
    assert out[0]["vendor"] == "keysight" and out[0]["usbtmc"] is True
    assert out[0]["vid"] == "0x2A8D"


def test_detect_unknown_vid_but_usbtmc(monkeypatch):
    """A totally unlisted vendor still gets flagged if it advertises the USBTMC class."""
    import json
    dev = {"Name": "ACME SuperScope", "PNPDeviceID": r"USB\VID_ABCD&PID_1111\X",
           "CompatibleID": [r"USB\Class_FE&SubClass_03", r"USB\Class_FE"], "Status": "OK"}
    monkeypatch.setattr(io_env.subprocess, "run", lambda *a, **k: _FakeProc(json.dumps(dev)))
    out = io_env.detect_usb_instruments()
    assert len(out) == 1
    assert out[0]["vendor"] == "unknown" and out[0]["usbtmc"] is True


def test_detect_ignores_plain_usb(monkeypatch):
    import json
    dev = {"Name": "USB Mass Storage", "PNPDeviceID": r"USB\VID_0781&PID_5583\X",
           "CompatibleID": [r"USB\Class_08&SubClass_06"], "Status": "OK"}
    monkeypatch.setattr(io_env.subprocess, "run", lambda *a, **k: _FakeProc(json.dumps(dev)))
    assert io_env.detect_usb_instruments() == []


def test_discover_lan_returns_list():
    # no LXI instruments on the test host -> empty list, but must not raise
    assert isinstance(io_env.discover_lan(0.2), list)


def test_recommendation_has_link_when_usb_undrivable(monkeypatch):
    monkeypatch.setattr(io_env, "detect_usb_instruments",
                        lambda: [{"vendor": "keysight", "vendor_name": "Keysight", "vid": "0x2A8D",
                                  "pid": "0x0396", "name": "Keysight DSOX", "status": "OK"}])
    monkeypatch.setattr(io_env, "visa_backends",
                        lambda: [{"backend": "system", "label": "sys", "available": False},
                                 {"backend": "@py", "label": "py", "available": True}])
    monkeypatch.setattr(io_env, "usb_backend_ok", lambda: False)
    a = io_env.assess()
    assert a["usb_drivable"] is False
    assert a["recommendations"], "should recommend software"
    rec = a["recommendations"][0]
    assert rec["url"].startswith("http") and rec["software"]


# --- interactive IO (SCPI passthrough) + build_visa_resource ------------------
class _FakeInst(Transport):
    default_provenance = Provenance.UNVERIFIED_HW
    def __init__(self): self.writes = []
    def write(self, c): self.writes.append(c)
    def query(self, c): return "KEYSIGHT,DSOX1204G,SN1,1.0" if c.strip() == "*IDN?" else "0"
    def query_raw(self, c): return b""


def test_hislip_resource():
    assert _main.build_visa_resource("192.168.0.5", "hislip") == "TCPIP0::192.168.0.5::hislip0::INSTR"


def test_interactive_io_query_and_write():
    client = TestClient(_main.app)
    _main.manager.set("scope", _FakeInst())
    try:
        r = client.post("/api/io/scpi", json={"role": "scope", "command": "*IDN?"}).json()
        assert r["ok"] and r["query"] and "DSOX1204G" in r["response"]
        w = client.post("/api/io/scpi", json={"role": "scope", "command": ":RUN", "query": False}).json()
        assert w["ok"] and w["query"] is False
        d = client.get("/api/io/details/scope").json()
        assert d["connected"] and d["idn"]["model"] == "DSOX1204G" and d["vendor"] == "keysight"
    finally:
        _main.manager.disconnect("scope")


def test_interactive_io_not_connected():
    client = TestClient(_main.app)
    _main.manager.disconnect("awg")
    r = client.post("/api/io/scpi", json={"role": "awg", "command": "*IDN?"}).json()
    assert r["ok"] is False and "not connected" in r["error"]
