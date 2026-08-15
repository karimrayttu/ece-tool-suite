"""The honesty contract is enforced structurally — these tests prove it."""

import pytest

from ece_suite.provenance import (
    Provenance,
    Reading,
    Waveform,
    tag_tool_result,
    to_wire,
)


def test_cannot_construct_reading_without_provenance():
    with pytest.raises(TypeError):
        Reading(value=3.3, unit="V")  # type: ignore[call-arg]


def test_reading_rejects_non_provenance_tag():
    with pytest.raises(TypeError):
        Reading(3.3, "V", "SIMULATED")  # a bare string is not allowed  # type: ignore[arg-type]


def test_to_wire_includes_provenance():
    r = Reading(3.3, "V", Provenance.SIMULATED, source="sim:DMM")
    wire = to_wire(r)
    assert wire["provenance"] == "SIMULATED"
    assert wire["value"] == 3.3
    assert wire["kind"] == "reading"


def test_to_wire_rejects_untagged_object():
    class Bare:
        provenance = None

    with pytest.raises(TypeError):
        to_wire(Bare())


def test_trust_can_lower_but_not_raise():
    r = Reading(1.0, "V", Provenance.UNVERIFIED_HW)
    lowered = r.downgraded_to(Provenance.SIMULATED)
    assert lowered.provenance is Provenance.SIMULATED
    with pytest.raises(ValueError):
        r.downgraded_to(Provenance.VERIFIED_HW)  # raising trust is forbidden


def test_waveform_length_mismatch_rejected():
    with pytest.raises(ValueError):
        Waveform(t=[0.0, 1.0], v=[0.0], unit_t="s", unit_v="V", provenance=Provenance.SIMULATED)


def test_tool_result_is_tagged_for_the_model():
    payload = tag_tool_result({"reading": 5.0}, Provenance.SIMULATED)
    assert payload["_provenance"] == "SIMULATED"
    assert "NOT a real measurement" in payload["_provenance_note"]


def test_provenance_ranks_are_ordered():
    assert Provenance.SIMULATED.rank < Provenance.UNVERIFIED_HW.rank < Provenance.VERIFIED_HW.rank
    assert Provenance.VERIFIED_HW.is_hardware_truth
    assert not Provenance.SIMULATED.is_hardware_truth
