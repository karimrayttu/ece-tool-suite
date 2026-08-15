"""Multi-vendor DMM: auto-detect Keysight (SCPI) vs Fluke legacy from *IDN?."""

from ece_suite.instruments.dmm import FlukeLegacyDmm, ScpiDmm, _is_fluke_legacy, make_dmm
from ece_suite.instruments.sim import SimDMM, SimFlukeDMM


def test_routes_keysight_to_scpi():
    d = make_dmm(SimDMM())
    assert isinstance(d, ScpiDmm) and d.dialect == "scpi"


def test_routes_fluke_legacy():
    d = make_dmm(SimFlukeDMM())
    assert isinstance(d, FlukeLegacyDmm) and d.dialect == "fluke-legacy"


def test_scpi_reads_value():
    d = make_dmm(SimDMM(nominal_vdc=3.3))
    d.configure("VDC")
    assert abs(d.read()["value"] - 3.3) < 1e-6


def test_fluke_reads_value():
    d = make_dmm(SimFlukeDMM(nominal=1.234))
    d.configure("VDC")
    r = d.read()
    assert abs(r["value"] - 1.234) < 1e-6 and r["dialect"] == "fluke-legacy"


def test_detection_matrix():
    assert _is_fluke_legacy("Fluke", "45")
    assert _is_fluke_legacy("FLUKE", "8808A")
    assert not _is_fluke_legacy("Fluke", "8846A")   # 34401-compatible -> SCPI
    assert not _is_fluke_legacy("Keysight", "34461A")
    assert not _is_fluke_legacy("Agilent", "34401A")


def test_dialect_cached_on_transport():
    t = SimFlukeDMM()
    make_dmm(t)
    assert getattr(t, "_dmm_dialect", None) == "fluke-legacy"
