"""Per-vendor capability profiles: model-derived channel counts + dialect feature sets."""

from fastapi.testclient import TestClient

from ece_suite import main as _main
from ece_suite.instruments.capabilities import dmm_capabilities, scope_capabilities


def test_scope_channels_from_model():
    assert scope_capabilities("tektronix", "TBS1052C")["channels"] == 2
    assert scope_capabilities("keysight", "DSOX1204G")["channels"] == 4
    assert scope_capabilities("keysight", "EDUX1052G")["channels"] == 2
    assert scope_capabilities("rigol", "")["channels"] == 4          # family default
    assert scope_capabilities("rigol", "")["channels_source"] == "family-default"


def test_scope_vendor_feature_differences():
    assert "GND" in scope_capabilities("rigol", "")["couplings"]
    assert "GND" not in scope_capabilities("keysight", "")["couplings"]
    assert "HRES" not in scope_capabilities("tektronix", "")["acq_types"]


def test_dmm_dialect_feature_sets():
    fl = dmm_capabilities("fluke-legacy")
    assert "CAP" not in fl["functions"] and fl["nplc"] is False and fl["math"] == ["OFF"]
    assert dmm_capabilities("fluke-28x")["functions"] == ["READ"]
    assert "TEMP" in dmm_capabilities("keysight")["functions"]
    assert "TEMP" not in dmm_capabilities("rigol")["functions"]


def test_capabilities_endpoint_contract():
    c = TestClient(_main.app)
    s = c.get("/api/instruments/scope/capabilities").json()
    assert {"vendor", "channels", "couplings", "acq_types", "connected"} <= set(s)
    d = c.get("/api/instruments/dmm/capabilities").json()
    assert "functions" in d and d["connected"] is False
