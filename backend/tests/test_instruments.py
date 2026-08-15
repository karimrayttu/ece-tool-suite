"""Sim DMM + spectrum analyzer behavior."""

import numpy as np

from ece_suite.instruments.sim import SimDMM, SimSpectrumAnalyzer
from ece_suite.provenance import Provenance


def test_dmm_measures_vdc_deterministically():
    d = SimDMM(nominal_vdc=3.300)
    assert abs(float(d.query(":MEAS:VOLT:DC?")) - 3.3) < 1e-6
    assert d.default_provenance is Provenance.SIMULATED
    assert d.query("*IDN?").startswith("SIM,")


def test_dmm_function_switch_changes_reading():
    d = SimDMM(nominal_idc=0.012)
    d.write(':FUNC "CURR:DC"')
    assert "CURR" in d.query(":FUNC?")
    assert abs(float(d.query(":READ?")) - 0.012) < 1e-9


def test_sa_trace_has_peak_near_center():
    sa = SimSpectrumAnalyzer(center_hz=100e6, span_hz=10e6, points=1001, peak_dbm=-20, noise_floor_dbm=-90)
    trace = np.array([float(x) for x in sa.query(":TRAC:DATA? TRACE1").split(",")])
    assert trace.size == 1001
    peak_freq = sa.freqs()[int(np.argmax(trace))]
    assert abs(peak_freq - 100e6) < (10e6 / 1001) * 3
    assert abs(float(trace.max()) - (-20.0)) < 1.0
    assert float(trace.min()) <= -89.0  # noise floor


def test_sa_answers_the_trace_query_the_driver_actually_sends():
    """KeysightSpectrumAnalyzer.trace() sends ":TRAC? TRACE1", not ":TRAC:DATA?".

    The sim used to answer only the :DATA form, so the driver got an empty trace and the UI
    drew a bare graticule while still reporting a peak marker.
    """
    sa = SimSpectrumAnalyzer(points=1001)
    for form in (":TRAC? TRACE1", ":TRAC:DATA? TRACE1", ":TRACE? TRACE1"):
        assert len(sa.query(form).split(",")) == 1001, form


def test_sa_marker_reports_peak():
    sa = SimSpectrumAnalyzer(center_hz=100e6, peak_dbm=-25)
    assert abs(float(sa.query(":CALC:MARK:X?")) - 100e6) < 1.0
    assert abs(float(sa.query(":CALC:MARK:Y?")) - (-25.0)) < 1.0
