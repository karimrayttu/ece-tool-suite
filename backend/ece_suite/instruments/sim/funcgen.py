"""Simulated function/arbitrary-waveform generator (Keysight 33xxx-style).

Enabling the output energizes the DUT with a signal, so it is SOURCE_CONTROL. The model
supports the output-voltage limits (:VOLT:LIMIT) that the preset sets and verifies before
the output is ever enabled.
"""

from __future__ import annotations

from .base import SimInstrument


class SimFuncGen(SimInstrument):
    idn = "SIM,ECE-SUITE-AWG,SN-0005,0.0.0"

    def __init__(self):
        super().__init__()
        self.func = "SIN"
        self.freq = 1000.0
        self.vpp = 1.0
        self.offset = 0.0
        self.vlim_high = 5.0
        self.vlim_low = -5.0
        self.vlim_state = False
        self.output = False

    def _on_reset(self) -> None:
        self.output = False
        self.vpp = 1.0
        self.freq = 1000.0
        self.func = "SIN"
        self.offset = 0.0
        self.vlim_state = False

    def _handle_write(self, c: str, u: str) -> None:
        if u.startswith(":OUTP") or u.startswith(":OUTPUT"):
            self.output = c.split()[-1].upper() in ("ON", "1")
        elif u.startswith(":VOLT:LIMIT:HIGH"):
            self.vlim_high = float(c.split()[-1])
        elif u.startswith(":VOLT:LIMIT:LOW"):
            self.vlim_low = float(c.split()[-1])
        elif u.startswith(":VOLT:LIMIT:STAT"):
            self.vlim_state = c.split()[-1].upper() in ("ON", "1")
        elif u.startswith(":VOLT:OFFS"):
            self.offset = float(c.split()[-1])
        elif u.startswith(":VOLT"):
            self.vpp = float(c.split()[-1])
        elif u.startswith(":FUNC"):
            self.func = c.split()[-1].upper()
        elif u.startswith(":FREQ"):
            self.freq = float(c.split()[-1])

    def _handle_query(self, c: str, u: str) -> str | None:
        if u.startswith(":OUTP"):
            return "1" if self.output else "0"
        if u.startswith(":VOLT:LIMIT:HIGH"):
            return repr(self.vlim_high)
        if u.startswith(":VOLT:LIMIT:LOW"):
            return repr(self.vlim_low)
        if u.startswith(":VOLT:LIMIT:STAT"):
            return "1" if self.vlim_state else "0"
        if u.startswith(":VOLT:OFFS"):
            return repr(self.offset)
        if u.startswith(":VOLT"):
            return repr(self.vpp)
        if u.startswith(":FUNC"):
            return self.func
        if u.startswith(":FREQ"):
            return repr(self.freq)
        return None
