"""SafetyInvariantEngine — forbidden-state coverage."""

from ece_suite.registry import Capability
from ece_suite.safety import (
    Action,
    DUTSafetyEnvelope,
    OpType,
    RatingModel,
    SafetyInvariantEngine,
    ScopeFrontEnd,
    Verdict,
    effective_abs_max_v,
)

ENG = SafetyInvariantEngine()
ENV = DUTSafetyEnvelope(max_voltage=12.0, max_current=1.0)
RATING = RatingModel(max_output_voltage=30.0, max_output_current=5.0)


def test_source_setlevel_without_envelope_is_default_denied():
    a = Action(Capability.SOURCE_CONTROL, OpType.SET_LEVEL, "PSU", {"voltage": 5.0})
    assert ENG.evaluate(a).blocked


def test_source_setlevel_within_envelope_and_rating_allowed():
    a = Action(Capability.SOURCE_CONTROL, OpType.SET_LEVEL, "PSU", {"voltage": 5.0, "current": 0.5})
    assert ENG.evaluate(a, envelope=ENV, rating=RATING).allowed


def test_setlevel_exceeds_envelope_blocked():
    a = Action(Capability.SOURCE_CONTROL, OpType.SET_LEVEL, "PSU", {"voltage": 20.0})
    d = ENG.evaluate(a, envelope=ENV, rating=RATING)
    assert d.blocked and any("envelope" in r for r in d.reasons)


def test_setlevel_exceeds_instrument_rating_blocked():
    big = DUTSafetyEnvelope(max_voltage=100.0, max_current=10.0)
    a = Action(Capability.SOURCE_CONTROL, OpType.SET_LEVEL, "PSU", {"voltage": 40.0})
    d = ENG.evaluate(a, envelope=big, rating=RATING)
    assert d.blocked and any("rating" in r for r in d.reasons)


def test_negative_voltage_violates_positive_polarity():
    a = Action(Capability.SOURCE_CONTROL, OpType.SET_LEVEL, "PSU", {"voltage": -5.0})
    assert ENG.evaluate(a, envelope=ENV, rating=RATING).blocked


def test_enable_output_requires_confirm():
    a = Action(Capability.SOURCE_CONTROL, OpType.ENABLE_OUTPUT, "PSU", {})
    assert ENG.evaluate(a, envelope=ENV, rating=RATING).needs_confirm


def test_block_beats_require_confirm():
    # enable with NO envelope -> block(no envelope) must dominate confirm(enable)
    a = Action(Capability.SOURCE_CONTROL, OpType.ENABLE_OUTPUT, "PSU", {})
    assert ENG.evaluate(a).verdict is Verdict.BLOCK


def test_native_autoscale_forbidden():
    a = Action(Capability.CONFIGURE_INSTRUMENT, OpType.AUTOSCALE, "SCOPE", {}, ":AUTOSCALE")
    assert ENG.evaluate(a).blocked
    b = Action(Capability.CONFIGURE_INSTRUMENT, OpType.CONFIGURE, "SCOPE", {}, ":AUToscale")
    assert ENG.evaluate(b).blocked


def test_scope_near_limit_uses_effective_abs_max():
    fe_50 = ScopeFrontEnd(attenuation=1.0, coupling="DC", input_impedance=50.0)
    a = Action(Capability.CONFIGURE_INSTRUMENT, OpType.CONFIGURE, "SCOPE", {"expected_input_v": 48.0})
    assert ENG.evaluate(a, scope_front_end=fe_50).blocked          # 50Ω, 1x -> 5 V abs-max
    fe_probe = ScopeFrontEnd(attenuation=10.0, coupling="DC", input_impedance=1e6)
    assert ENG.evaluate(a, scope_front_end=fe_probe).allowed        # 1MΩ, 10x -> 3000 V


def test_effective_abs_max_helper():
    assert effective_abs_max_v(ScopeFrontEnd(1.0, "DC", 50.0)) == 5.0
    assert effective_abs_max_v(ScopeFrontEnd(10.0, "DC", 1e6)) == 3000.0
