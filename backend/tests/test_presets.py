"""Transactional preset runner — ordering, confirm, verify, rollback, fault injection."""

from ece_suite.instruments.sim import SimPSU
from ece_suite.presets import PresetRunner, PresetStep
from ece_suite.registry import Capability
from ece_suite.safety import DUTSafetyEnvelope, OpType, RatingModel

ENV = DUTSafetyEnvelope(max_voltage=12.0, max_current=1.0)
RATING = RatingModel(max_output_voltage=30.0, max_output_current=5.0)


def good_steps():
    return [
        PresetStep(OpType.SET_PROTECTION, ":VOLT:PROT 6.0", verify_query=":VOLT:PROT?", expected=6.0, description="OVP=6V"),
        PresetStep(OpType.SET_PROTECTION, ":CURR:PROT 0.8", verify_query=":CURR:PROT?", expected=0.8, description="OCP=0.8A"),
        PresetStep(OpType.SET_LEVEL, ":VOLT 5.0", capability=Capability.SOURCE_CONTROL, params={"voltage": 5.0}, verify_query=":VOLT?", expected=5.0, description="Vset=5V"),
        PresetStep(OpType.SET_LEVEL, ":CURR 0.5", capability=Capability.SOURCE_CONTROL, params={"current": 0.5}, verify_query=":CURR?", expected=0.5, description="Ilim=0.5A"),
        PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL, description="enable output"),
    ]


def test_good_preset_runs_with_confirm():
    psu = SimPSU()
    res = PresetRunner(psu, instrument="PSU").run(good_steps(), envelope=ENV, rating=RATING, confirm=True)
    assert res.ok, res.summary
    assert psu.output is True
    assert res.provenance == "SIMULATED"


def test_enable_without_confirm_aborts_and_leaves_output_off():
    psu = SimPSU()
    res = PresetRunner(psu).run(good_steps(), envelope=ENV, rating=RATING, confirm=False)
    assert not res.ok and res.rolled_back
    assert psu.output is False


def test_enable_not_last_is_blocked_before_execution():
    steps = [
        PresetStep(OpType.SET_PROTECTION, ":VOLT:PROT 6.0"),
        PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL),
        PresetStep(OpType.SET_LEVEL, ":VOLT 5.0", capability=Capability.SOURCE_CONTROL, params={"voltage": 5.0}),
    ]
    psu = SimPSU()
    res = PresetRunner(psu).run(steps, envelope=ENV, rating=RATING, confirm=True)
    assert not res.ok and "last step" in res.summary
    assert psu.output is False


def test_enable_without_protection_blocked():
    steps = [
        PresetStep(OpType.SET_LEVEL, ":VOLT 5.0", capability=Capability.SOURCE_CONTROL, params={"voltage": 5.0}),
        PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL),
    ]
    psu = SimPSU()
    res = PresetRunner(psu).run(steps, envelope=ENV, rating=RATING, confirm=True)
    assert not res.ok and "protective limits" in res.summary


def test_over_envelope_setlevel_aborts_and_output_off():
    steps = [
        PresetStep(OpType.SET_PROTECTION, ":VOLT:PROT 15.0", verify_query=":VOLT:PROT?", expected=15.0),
        PresetStep(OpType.SET_LEVEL, ":VOLT 20.0", capability=Capability.SOURCE_CONTROL, params={"voltage": 20.0}),
        PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL),
    ]
    psu = SimPSU()
    res = PresetRunner(psu).run(steps, envelope=ENV, rating=RATING, confirm=True)
    assert not res.ok and res.rolled_back
    assert psu.output is False


def test_no_envelope_aborts():
    psu = SimPSU()
    res = PresetRunner(psu).run(good_steps(), rating=RATING, confirm=True)  # envelope omitted
    assert not res.ok
    assert psu.output is False


def test_error_queue_post_condition_triggers_rollback():
    psu = SimPSU()
    psu.inject_error('-222,"Data out of range"')  # surfaces on the first post-write drain
    res = PresetRunner(psu).run(good_steps(), envelope=ENV, rating=RATING, confirm=True)
    assert not res.ok and res.rolled_back
    assert psu.output is False
    assert "instrument error" in res.summary
