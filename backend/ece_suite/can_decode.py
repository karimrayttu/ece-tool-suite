"""Minimal offline CAN decoder (DBC + frames -> physical signals).

Ports the offline path of the CSS-Electronics CAN reverse-engineering workflow: parse a DBC,
decode logged frames into engineering values. Supports Intel (little-endian) fully and
Motorola (big-endian) via the standard sawtooth. No hardware or python-can needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Signal:
    name: str
    start: int
    length: int
    little: bool
    signed: bool
    scale: float
    offset: float
    unit: str


@dataclass
class Message:
    id: int
    name: str
    length: int
    signals: list[Signal] = field(default_factory=list)


_BO = re.compile(r"\s*BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)")
_SG = re.compile(
    r'\s*SG_\s+(\w+)\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([^,]+),([^)]+)\)\s*\[[^\]]*\]\s*"([^"]*)"'
)


def parse_dbc(text: str) -> dict[int, Message]:
    msgs: dict[int, Message] = {}
    cur: Message | None = None
    for line in text.splitlines():
        mbo = _BO.match(line)
        if mbo:
            cur = Message(int(mbo.group(1)), mbo.group(2), int(mbo.group(3)))
            msgs[cur.id] = cur
            continue
        msg = _SG.match(line)
        if msg and cur is not None:
            cur.signals.append(Signal(
                msg.group(1), int(msg.group(2)), int(msg.group(3)),
                msg.group(4) == "1", msg.group(5) == "-",
                float(msg.group(6)), float(msg.group(7)), msg.group(8)))
    return msgs


def _extract_intel(data: bytes, start: int, length: int) -> int:
    val = int.from_bytes(data.ljust(8, b"\x00")[:8], "little")
    return (val >> start) & ((1 << length) - 1)


def _extract_motorola(data: bytes, start: int, length: int) -> int:
    result = 0
    bit = start
    for _ in range(length):
        byte_index, bit_index = bit // 8, bit % 8
        b = data[byte_index] if byte_index < len(data) else 0
        result = (result << 1) | ((b >> (7 - bit_index)) & 1)
        bit += 15 if bit_index == 0 else -1
    return result


def _decode_signal(data: bytes, s: Signal) -> float:
    raw = _extract_intel(data, s.start, s.length) if s.little else _extract_motorola(data, s.start, s.length)
    if s.signed and raw >= (1 << (s.length - 1)):
        raw -= 1 << s.length
    return round(raw * s.scale + s.offset, 6)


def parse_log(text: str) -> list[dict]:
    """Each non-empty line: '<id> <hex bytes>' where id is decimal or 0xHEX and the rest is hex
    (spaces optional). e.g. '256 00 00 00 40 1F 00 00 00' or '0x100,DEADBEEF'."""
    frames: list[dict] = []
    for line in text.splitlines():
        line = line.strip().replace(",", " ")
        if not line or line.startswith(("#", "//")):
            continue
        parts = line.split()
        try:
            cid = int(parts[0], 16) if parts[0].lower().startswith("0x") else int(parts[0])
        except ValueError:
            continue
        hexstr = "".join(parts[1:]).replace("0x", "")
        try:
            data = bytes.fromhex(hexstr)
        except ValueError:
            continue
        frames.append({"id": cid, "data": data})
    return frames


def decode_frames(msgs: dict[int, Message], frames: list[dict]) -> list[dict]:
    out: list[dict] = []
    for fr in frames:
        msg = msgs.get(fr["id"])
        data = fr["data"] if isinstance(fr["data"], (bytes, bytearray)) else bytes.fromhex(str(fr["data"]).replace(" ", ""))
        if msg is None:
            out.append({"id": fr["id"], "name": None, "signals": {}})
            continue
        sigs = {s.name: {"value": _decode_signal(data, s), "unit": s.unit} for s in msg.signals}
        out.append({"id": fr["id"], "name": msg.name, "signals": sigs})
    return out
