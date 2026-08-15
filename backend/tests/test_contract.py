"""Load-bearing contract: the autonomous bridge's surface is a strict subset of the
chatbox surface, and it never exposes a SOURCE_CONTROL tool. Asserted over the REAL app
registry so the two surfaces cannot silently drift apart as tools are added."""

from ece_suite.main import registry
from ece_suite.registry import Capability, Surface


def test_autonomous_is_subset_of_chatbox():
    chat = registry.names_for(Surface.CHATBOX)
    auto = registry.names_for(Surface.AUTONOMOUS)
    assert auto <= chat


def test_source_control_preset_hidden_from_autonomous():
    auto = registry.names_for(Surface.AUTONOMOUS)
    chat = registry.names_for(Surface.CHATBOX)
    assert "psu_apply_preset" in chat
    assert "psu_apply_preset" not in auto


def test_no_source_control_tool_visible_to_autonomous():
    for spec in registry.list_for(Surface.AUTONOMOUS):
        assert spec.capability is not Capability.SOURCE_CONTROL


def test_read_tools_available_to_both_surfaces():
    auto = registry.names_for(Surface.AUTONOMOUS)
    for name in ("scope_capture", "dmm_measure_vdc", "sa_peak"):
        assert name in auto
