"""Assistant loop tested with a fake Anthropic client (no API call, no key needed)."""

from types import SimpleNamespace

import pytest

from ece_suite.assistant import SYSTEM_PROMPT, Assistant, build_tool_defs
from ece_suite.instruments.sim import SimPSU, SimScope
from ece_suite.main import manager, registry
from ece_suite.registry import Surface


@pytest.fixture(autouse=True)
def _connect_sims():
    manager.set("scope", SimScope())
    manager.set("psu", SimPSU())
    yield
    manager.disconnect("scope")
    manager.disconnect("psu")


# --- fake streaming client ------------------------------------------------
class FakeStream:
    def __init__(self, chunks, final):
        self._chunks = chunks
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for t in self._chunks:
                yield SimpleNamespace(type="content_block_delta",
                                      delta=SimpleNamespace(type="text_delta", text=t))
        return gen()

    async def get_final_message(self):
        return self._final


class FakeMessages:
    def __init__(self, turns):
        self.turns = turns
        self.i = 0

    def stream(self, **kw):
        turn = self.turns[self.i]
        self.i += 1
        return FakeStream(turn["chunks"], turn["final"])


class FakeClient:
    def __init__(self, turns):
        self.messages = FakeMessages(turns)


def _tool_use(name, inp, tid="t1"):
    return SimpleNamespace(stop_reason="tool_use",
                           content=[SimpleNamespace(type="tool_use", name=name, input=inp, id=tid)])


def _text(t):
    return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=t)])


# --- tests ----------------------------------------------------------------
def test_build_tool_defs_and_system_prompt():
    defs = build_tool_defs(registry, Surface.CHATBOX)
    names = {d["name"] for d in defs}
    assert "scope_capture" in names and "psu_apply_preset" in names
    assert all("input_schema" in d for d in defs)
    assert "provenance" in SYSTEM_PROMPT.lower()


async def test_no_key_yields_error():
    a = Assistant(registry, client=None, api_key="")
    events = [ev async for ev in a.run("hello")]
    assert events and events[0]["type"] == "error"


async def test_tool_loop_surfaces_provenance():
    turns = [
        {"chunks": ["Checking CH1… "], "final": _tool_use("scope_measure_vpp", {})},
        {"chunks": ["Vpp is ~1 V (SIMULATED)."], "final": _text("Vpp is ~1 V (SIMULATED).")},
    ]
    a = Assistant(registry, client=FakeClient(turns))
    events = [ev async for ev in a.run("what's the Vpp?")]
    types = [e["type"] for e in events]
    assert "text" in types and "tool_use" in types and "tool_result" in types
    assert types[-1] == "done"
    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr["provenance"] == "SIMULATED"  # provenance reached the model path


async def test_assistant_cannot_self_confirm_source():
    psu = manager.get("psu")
    psu.write(":OUTP OFF")  # ensure baseline
    inp = {"voltage": 3.3, "current": 0.5, "ovp": 3.6, "ocp": 0.6,
           "dut_max_v": 3.6, "dut_max_i": 0.6, "confirm": True}
    turns = [
        {"chunks": [], "final": _tool_use("psu_apply_preset", inp)},
        {"chunks": ["I can't energize that myself."], "final": _text("Use the preset's confirm control.")},
    ]
    a = Assistant(registry, client=FakeClient(turns))
    events = [ev async for ev in a.run("turn on the 3.3V rail")]
    tr = next(e for e in events if e["type"] == "tool_result")
    assert tr.get("error") and "confirm" in tr["error"].lower()
    assert psu.output is False  # the model could NOT energize the DUT
