"""Shared tool registry — one source of truth, three projections.

Both Claude layers consume the SAME registry, but through different *surfaces*:

* ``CHATBOX``     — the in-app assistant: may read/configure, but source/load control and
                    any ``confirm_required`` tool still needs an explicit human confirm.
* ``AUTONOMOUS``  — the Claude Code / MCP bridge: a strictly NARROWER surface. It never
                    sees SOURCE_CONTROL tools and never sees ``confirm_required`` tools.
* ``UI``          — buttons/panels in the renderer.

A contract test (added with M1) asserts AUTONOMOUS ⊆ CHATBOX so the surfaces can't drift.
Every instrument-touching result is wrapped with its provenance tag before it leaves here,
so a model literally cannot receive a value without seeing whether it is real.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from .provenance import Provenance, tag_tool_result


class Capability(str, Enum):
    READ_INSTRUMENT = "READ_INSTRUMENT"
    CONFIGURE_INSTRUMENT = "CONFIGURE_INSTRUMENT"
    SOURCE_CONTROL = "SOURCE_CONTROL"   # energizes a DUT — most dangerous
    PARTS_QUERY = "PARTS_QUERY"
    ANALYZE = "ANALYZE"
    FILE_IO = "FILE_IO"


class Surface(str, Enum):
    CHATBOX = "CHATBOX"
    AUTONOMOUS = "AUTONOMOUS"
    UI = "UI"


# Capabilities the autonomous bridge is NEVER allowed to invoke.
_AUTONOMOUS_FORBIDDEN = {Capability.SOURCE_CONTROL}


@dataclass
class ToolSpec:
    name: str
    description: str
    fn: Callable[..., dict]
    capability: Capability
    input_schema: dict = field(default_factory=dict)
    confirm_required: bool = False
    #: whether results carry instrument provenance (vs pure software results)
    provenance_bearing: bool = True

    def visible_to(self, surface: Surface) -> bool:
        if surface is Surface.AUTONOMOUS:
            if self.capability in _AUTONOMOUS_FORBIDDEN:
                return False
            if self.confirm_required:
                return False
        return True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def list_for(self, surface: Surface) -> list[ToolSpec]:
        return [t for t in self._tools.values() if t.visible_to(surface)]

    def names_for(self, surface: Surface) -> set[str]:
        return {t.name for t in self.list_for(surface)}

    def call(self, name: str, args: dict, *, surface: Surface, human_confirmed: bool = False) -> dict:
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"no such tool: {name}")
        if not spec.visible_to(surface):
            raise PermissionError(
                f"tool {name!r} ({spec.capability.value}) is not available on the "
                f"{surface.value} surface"
            )
        if spec.confirm_required and not human_confirmed:
            # The assistant can SEE a confirm-required tool (so it can guide the user) but
            # may never self-confirm it. Only a human action sets human_confirmed=True.
            raise PermissionError(
                f"tool {name!r} requires explicit human confirmation; the assistant "
                "cannot self-confirm an energize/source operation"
            )
        result = spec.fn(**args)
        if spec.provenance_bearing:
            prov = result.get("provenance")
            if prov is None:
                raise RuntimeError(
                    f"tool {name!r} is provenance-bearing but returned no provenance tag"
                )
            return tag_tool_result(result, Provenance(prov))
        return result
