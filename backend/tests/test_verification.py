"""Lab-truth gate + instrument manager.

A SimInstrument cannot be promoted to VERIFIED_HW. A hardware transport (default provenance
UNVERIFIED_HW) is promoted only after *IDN? + a clean read-back. We use a mock-hardware
double (a sim model tagged UNVERIFIED_HW) since no real gear is present — real promotion
against a live Keysight scope is the M7 gate.
"""

from ece_suite.instruments.manager import InstrumentManager
from ece_suite.instruments.sim import SimScope
from ece_suite.provenance import Provenance
from ece_suite.verification import VerificationGate


class MockHwScope(SimScope):
    """A simulator model deliberately tagged as hardware — TEST DOUBLE ONLY."""

    def __init__(self):
        super().__init__()
        self.default_provenance = Provenance.UNVERIFIED_HW


class MockBadIdn(MockHwScope):
    idn = ""  # empty *IDN? response


GATE = VerificationGate()


def test_gate_promotes_hardware_after_idn_and_readback():
    hw = MockHwScope()
    r = GATE.verify(hw, role="scope")
    assert r.ok and r.provenance == "VERIFIED_HW"
    assert hw.default_provenance is Provenance.VERIFIED_HW
    assert r.idn and r.idn.vendor == "SIM"


def test_simulator_is_never_promotable():
    s = SimScope()
    r = GATE.verify(s)
    assert not r.ok and r.provenance == "SIMULATED"
    assert s.default_provenance is Provenance.SIMULATED
    assert any("simulat" in reason.lower() for reason in r.reasons)


def test_gate_fails_when_error_queue_not_empty():
    hw = MockHwScope()
    hw.inject_error('-100,"Command error"')
    r = GATE.verify(hw)
    assert not r.ok and r.provenance == "UNVERIFIED_HW"
    assert hw.default_provenance is Provenance.UNVERIFIED_HW


def test_gate_fails_on_incomplete_idn():
    hw = MockBadIdn()
    r = GATE.verify(hw)
    assert not r.ok and r.provenance == "UNVERIFIED_HW"


def test_manager_swap_verify_disconnect():
    mgr = InstrumentManager({"scope": SimScope()})
    mgr.register_sim_factory("scope", SimScope)
    assert mgr.get("scope").default_provenance is Provenance.SIMULATED
    assert mgr.has_exclusive("scope")

    mgr.set("scope", MockHwScope())
    r = mgr.verify("scope")
    assert r.ok and mgr.get("scope").default_provenance is Provenance.VERIFIED_HW
    assert mgr.any_hardware_verified()

    mgr.disconnect("scope")
    assert mgr.get("scope").default_provenance is Provenance.SIMULATED  # reverted to sim
    assert not mgr.any_hardware_verified()
