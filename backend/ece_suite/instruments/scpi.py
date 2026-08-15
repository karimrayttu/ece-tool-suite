"""SCPI / IEEE-488.2 helpers shared by every instrument driver.

Kept transport-agnostic: each function takes a ``Transport`` and speaks plain SCPI, so the
same helpers work against the SimTransport and the real VisaTransport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .transport import Transport


@dataclass(frozen=True)
class IdnInfo:
    vendor: str
    model: str
    serial: str
    firmware: str
    raw: str

    @property
    def is_keysight(self) -> bool:
        v = self.vendor.upper()
        return "KEYSIGHT" in v or "AGILENT" in v


def parse_idn(raw: str) -> IdnInfo:
    """Parse a ``*IDN?`` response: ``vendor,model,serial,firmware``."""
    parts = [p.strip() for p in raw.strip().split(",")]
    while len(parts) < 4:
        parts.append("")
    return IdnInfo(parts[0], parts[1], parts[2], parts[3], raw.strip())


def safe_float(s: str) -> float | None:
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return None if abs(v) > 1e30 else v  # Keysight returns ~9.9E37 for invalid


def drain_error_queue(transport: Transport, *, limit: int = 64) -> list[str]:
    """Read ``:SYSTem:ERRor?`` until the queue reports no error (code 0) or ``limit`` hit.

    A non-empty return is a hard signal that a preceding write was rejected — callers must
    treat that as BLOCKED/UNVERIFIED, per the safety discipline.
    """
    errors: list[str] = []
    for _ in range(limit):
        resp = transport.query(":SYSTem:ERRor?").strip()
        if not resp:
            break
        code = resp.split(",", 1)[0].strip()
        try:
            if int(float(code)) == 0:
                break
        except ValueError:
            # non-numeric -> record and stop to avoid an infinite loop
            errors.append(resp)
            break
        errors.append(resp)
    return errors


def query_bool(transport: Transport, cmd: str) -> bool:
    return transport.query(cmd).strip() in ("1", "ON", "on", "TRUE", "true")


def query_float(transport: Transport, cmd: str) -> float:
    return float(transport.query(cmd).strip())
