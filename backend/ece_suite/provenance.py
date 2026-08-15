"""Truth / provenance core.

The load-bearing honesty primitive of the whole app. Every value that represents a
measurement MUST carry a :class:`Provenance` tag, and the tag travels with the value all
the way to the UI, the WebSocket stream, the audit log, and any assistant tool result.

The defense against ever presenting a simulated or unconfirmed reading as real is
*structural*: you cannot construct a :class:`Reading` or :class:`Waveform` without a
provenance tag, and :func:`to_wire` refuses to serialize anything that lacks one.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Provenance(str, Enum):
    """How much we are allowed to claim about a value's truth.

    Ordering (low → high trust) is meaningful: a pipeline may only *lower* trust as data
    flows, never raise it without passing the corresponding gate.
    """

    SIMULATED = "SIMULATED"          # produced by the SimTransport; no hardware involved
    UNVERIFIED_HW = "UNVERIFIED_HW"  # came off real hardware but not yet *IDN?+readback verified
    VERIFIED_HW = "VERIFIED_HW"      # confirmed: live instrument acked + verify-read passed

    @property
    def rank(self) -> int:
        return {"SIMULATED": 0, "UNVERIFIED_HW": 1, "VERIFIED_HW": 2}[self.value]

    @property
    def is_hardware_truth(self) -> bool:
        return self is Provenance.VERIFIED_HW


def _require_provenance(p: Any) -> Provenance:
    if not isinstance(p, Provenance):
        raise TypeError(
            "provenance must be a Provenance enum member, got "
            f"{type(p).__name__!r}; refusing to create an untagged value"
        )
    return p


@dataclass(frozen=True)
class Reading:
    """A single scalar measurement (e.g. a DMM read).

    ``provenance`` is a required positional field with no default — constructing a Reading
    without it is a TypeError, by design.
    """

    value: float
    unit: str
    provenance: Provenance
    source: str = "unknown"          # e.g. "sim:DMM" or "TCPIP::10.0.0.5::INSTR"
    timestamp: float = field(default_factory=time.time)
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_provenance(self.provenance)

    def downgraded_to(self, p: Provenance) -> Reading:
        """Return a copy with trust lowered. Raising trust this way is forbidden."""
        p = _require_provenance(p)
        if p.rank > self.provenance.rank:
            raise ValueError(
                f"cannot raise provenance {self.provenance.value} -> {p.value} "
                "without passing the corresponding verification gate"
            )
        return Reading(self.value, self.unit, p, self.source, self.timestamp, dict(self.meta))


@dataclass(frozen=True)
class Waveform:
    """A time-series capture (e.g. a scope channel). Arrays kept as plain lists at this
    boundary so the type stays import-light; numpy lives in the instrument layer."""

    t: list[float]
    v: list[float]
    unit_t: str
    unit_v: str
    provenance: Provenance
    source: str = "unknown"
    timestamp: float = field(default_factory=time.time)
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_provenance(self.provenance)
        if len(self.t) != len(self.v):
            raise ValueError(f"t/v length mismatch: {len(self.t)} vs {len(self.v)}")


def to_wire(obj: Any) -> dict:
    """Serialize a Reading/Waveform for the API/WS boundary, guaranteeing the provenance
    tag is present. Anything provenance-bearing is accepted; anything else is rejected."""
    prov = getattr(obj, "provenance", None)
    _require_provenance(prov)
    if isinstance(obj, Reading):
        return {
            "kind": "reading",
            "value": obj.value,
            "unit": obj.unit,
            "provenance": obj.provenance.value,
            "source": obj.source,
            "timestamp": obj.timestamp,
            "meta": dict(obj.meta),
        }
    if isinstance(obj, Waveform):
        return {
            "kind": "waveform",
            "t": obj.t,
            "v": obj.v,
            "unit_t": obj.unit_t,
            "unit_v": obj.unit_v,
            "provenance": obj.provenance.value,
            "source": obj.source,
            "timestamp": obj.timestamp,
            "meta": dict(obj.meta),
        }
    raise TypeError(f"don't know how to serialize {type(obj).__name__}")


def tag_tool_result(payload: dict, provenance: Provenance) -> dict:
    """Wrap an assistant tool result so the model literally cannot receive a value without
    seeing its provenance. Used by the shared tool registry."""
    _require_provenance(provenance)
    out = dict(payload)
    out["_provenance"] = provenance.value
    out["_provenance_note"] = {
        "SIMULATED": "This value came from the simulator. It is NOT a real measurement.",
        "UNVERIFIED_HW": "This value came from hardware but has not passed verify-readback.",
        "VERIFIED_HW": "This value was confirmed against a live, identified instrument.",
    }[provenance.value]
    return out
