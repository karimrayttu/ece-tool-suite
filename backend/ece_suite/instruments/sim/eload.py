"""Simulated electronic load (Keysight EL34xxx-style).

Enabling the input sinks current from the DUT, so it is SOURCE_CONTROL. The model supports
the current-protection (OCP) the preset sets and verifies before the input is enabled.
Modes: CURR (CC), VOLT (CV), RES (CR).
"""

from __future__ import annotations

from .base import SimInstrument


class SimEload(SimInstrument):
    idn = "SIM,ECE-SUITE-ELOAD,SN-0006,0.0.0"

    def __init__(self, *, source_v: float = 0.0):
        super().__init__()
        self.mode = "CURR"
        self.level = 0.0
        self.ocp = 5.0
        self.input = False
        self.source_v = source_v  # DUT voltage seen at the input (0 if nothing hooked up)

    def _on_reset(self) -> None:
        self.input = False
        self.level = 0.0
        self.mode = "CURR"

    def _handle_write(self, c: str, u: str) -> None:
        if u.startswith(":INP") or u.startswith(":INPUT"):
            self.input = c.split()[-1].upper() in ("ON", "1")
        elif u.startswith(":CURR:PROT"):
            self.ocp = float(c.split()[-1])
        elif u.startswith(":FUNC") or u.startswith(":MODE"):
            self.mode = c.split()[-1].upper()
        elif u.startswith(":CURR"):
            self.level = float(c.split()[-1])
        elif u.startswith(":VOLT"):
            self.level = float(c.split()[-1])
        elif u.startswith(":RES"):
            self.level = float(c.split()[-1])

    def _handle_query(self, c: str, u: str) -> str | None:
        if u.startswith(":INP"):
            return "1" if self.input else "0"
        if u.startswith(":CURR:PROT"):
            return repr(self.ocp)
        if u.startswith(":FUNC") or u.startswith(":MODE"):
            return self.mode
        if u.startswith(":MEAS:VOLT") or u.startswith(":MEASURE:VOLTAGE"):
            return repr(self.source_v if self.input else 0.0)
        if u.startswith(":MEAS:CURR") or u.startswith(":MEASURE:CURRENT"):
            return repr(self.level if self.input else 0.0)
        if u.startswith(":CURR"):
            return repr(self.level)
        return None
