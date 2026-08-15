"""End-to-end spine: sim transport -> SCPI path -> decode, plus registry safety contracts."""

import numpy as np
import pytest

from ece_suite.audit import AuditLog
from ece_suite.instruments.preamble import decode_waveform, parse_preamble
from ece_suite.instruments.scpi import drain_error_queue, parse_idn
from ece_suite.instruments.sim import SimScope
from ece_suite.provenance import Provenance
from ece_suite.registry import Capability, Surface, ToolRegistry, ToolSpec


def _sim_tool():
    return {"value": 1.0, "provenance": "SIMULATED"}


def test_sim_idn_and_provenance():
    s = SimScope()
    info = parse_idn(s.query("*IDN?"))
    assert info.vendor == "SIM"
    assert s.default_provenance is Provenance.SIMULATED


def test_sim_capture_via_scpi_recovers_default_sine():
    s = SimScope(points=2000, timebase_s_per_div=200e-6, ch_scale_v_per_div=0.2)
    pre = parse_preamble(s.query(":WAV:PRE?"))
    raw = s.query_raw(":WAV:DATA?")
    t, v = decode_waveform(raw, pre, byteorder="LSB")
    assert v.shape == (2000,)
    assert t[0] < 0 < t[-1]                 # screen centered on t=0
    assert 0.9 < float(np.ptp(v)) < 1.1     # 1 Vpp default sine within quantization


def test_error_queue_drain():
    s = SimScope()
    assert drain_error_queue(s) == []
    s.inject_error('-222,"Data out of range"')
    errs = drain_error_queue(s)
    assert errs and "Data out of range" in errs[0]
    assert drain_error_queue(s) == []       # queue emptied


def test_autonomous_surface_is_subset_of_chatbox():
    reg = ToolRegistry()
    reg.register(ToolSpec("read_x", "", _sim_tool, Capability.READ_INSTRUMENT))
    reg.register(ToolSpec("src_x", "", _sim_tool, Capability.SOURCE_CONTROL))
    reg.register(ToolSpec("cfg_x", "", _sim_tool, Capability.CONFIGURE_INSTRUMENT, confirm_required=True))
    chat = reg.names_for(Surface.CHATBOX)
    auto = reg.names_for(Surface.AUTONOMOUS)
    assert auto <= chat                      # the load-bearing contract
    assert "src_x" not in auto               # source control never autonomous
    assert "cfg_x" not in auto               # confirm-required never autonomous
    assert "src_x" in chat


def test_source_control_blocked_on_autonomous():
    reg = ToolRegistry()
    reg.register(ToolSpec("src_x", "", _sim_tool, Capability.SOURCE_CONTROL))
    with pytest.raises(PermissionError):
        reg.call("src_x", {}, surface=Surface.AUTONOMOUS)


def test_registry_tags_results_for_the_model():
    reg = ToolRegistry()
    reg.register(ToolSpec("read_x", "", _sim_tool, Capability.READ_INSTRUMENT))
    out = reg.call("read_x", {}, surface=Surface.CHATBOX)
    assert out["_provenance"] == "SIMULATED"
    assert "NOT a real measurement" in out["_provenance_note"]


def test_provenance_bearing_tool_without_tag_raises():
    reg = ToolRegistry()
    reg.register(ToolSpec("bad", "", lambda: {"value": 1}, Capability.READ_INSTRUMENT))
    with pytest.raises(RuntimeError):
        reg.call("bad", {}, surface=Surface.CHATBOX)


def test_audit_log_writes(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    rec = log.record("test_event", foo="bar")
    assert rec["seq"] == 1
    content = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    assert "test_event" in content and "bar" in content
