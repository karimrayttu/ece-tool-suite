"""Simulated Fluke 45 / 8808A (legacy dialect) — TEST DOUBLE for multi-vendor routing.

Speaks the legacy Fluke command set: bare function keywords (VDC/VAC/OHMS/…) and MEAS?.
"""

from __future__ import annotations

from .base import SimInstrument

_LEGACY_FUNCS = {"VDC", "VAC", "ADC", "AAC", "OHMS", "FREQ", "CONT", "DIODE"}


class SimFlukeDMM(SimInstrument):
    idn = "FLUKE,45,SN-0007,1.0"

    def __init__(self, nominal: float = 3.300):
        super().__init__()
        self.function = "VDC"
        self.nominal = nominal

    def _handle_write(self, c: str, u: str) -> None:
        if u in _LEGACY_FUNCS:
            self.function = u
        # RATE S/M/F and other legacy config are accepted silently

    def _handle_query(self, c: str, u: str) -> str | None:
        if u in ("MEAS?", "VAL?", "MEAS1?"):
            return f"{self.nominal:.6E}"
        return None
