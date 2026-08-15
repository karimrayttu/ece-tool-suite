from ece_suite.instruments.keysight import KeysightScope, run_bringup
from ece_suite.instruments.sim import SimScope
from ece_suite.safety import SafetyInvariantEngine
from tests.test_verification import MockHwScope


def test_driver_configure_capture_measure():
    drv = KeysightScope(SimScope())
    drv.configure_channel(0.5, probe=10)
    drv.configure_timebase(1e-4)
    wf = drv.capture()
    assert len(wf.v) > 0 and wf.provenance.value == "SIMULATED"
    assert drv.measure_vpp() > 0


def test_bounded_autoset_sets_ranges():
    drv = KeysightScope(SimScope(), SafetyInvariantEngine())
    cfg = drv.bounded_autoset(expected_vpp=1.0, expected_freq=1000.0)
    assert cfg["vdiv"] > 0 and cfg["tdiv"] > 0


def test_bringup_on_sim_runs_but_not_verified():
    r = run_bringup(SimScope(), SafetyInvariantEngine())
    assert r["ok"] is True               # every step executed
    assert r["hardware_verified"] is False  # a simulator cannot be hardware-verified
    assert r["provenance"] == "SIMULATED"
    steps = {s["step"] for s in r["steps"]}
    assert {"identify", "reset", "verify", "bounded_autoset", "capture"} <= steps


def test_bringup_promotes_mock_hardware():
    hw = MockHwScope()
    r = run_bringup(hw, SafetyInvariantEngine())
    assert r["hardware_verified"] is True
    assert r["provenance"] == "VERIFIED_HW"
