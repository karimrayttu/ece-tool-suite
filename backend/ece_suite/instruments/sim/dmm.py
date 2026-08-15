"""Simulated bench DMM (Keysight 34461A-style SCPI).

Deterministic readings (no RNG) so tests are stable: the model returns a configurable
nominal for each function. A small load model lets it respond to PSU output later.
"""

from __future__ import annotations

from .base import SimInstrument


class SimDMM(SimInstrument):
    idn = "SIM,ECE-SUITE-DMM,SN-0002,0.0.0"

    def __init__(self, *, nominal_vdc: float = 3.300, nominal_idc: float = 0.0):
        super().__init__()
        self.function = "VOLT:DC"
        self.nplc = 1.0
        self.range = "AUTO"
        self.nominal_vdc = nominal_vdc
        self.nominal_idc = nominal_idc

    def _on_reset(self) -> None:
        self.function = "VOLT:DC"
        self.nplc = 1.0
        self.range = "AUTO"

    def _value_for_function(self) -> float:
        f = self.function.upper()
        if f.startswith("VOLT"):
            return self.nominal_vdc
        if f.startswith("CURR"):
            return self.nominal_idc
        if f.startswith("RES"):
            return 1.0e3
        return self.nominal_vdc

    def _handle_write(self, cmd: str, u: str) -> None:
        if u.startswith(":CONF:VOLT:DC") or u.startswith(":CONFIGURE:VOLTAGE:DC"):
            self.function = "VOLT:DC"
        elif u.startswith(":CONF:CURR") or u.startswith(":CONFIGURE:CURRENT"):
            self.function = "CURR:DC"
        elif u.startswith(":CONF:RES") or u.startswith(":CONFIGURE:RESISTANCE"):
            self.function = "RES"
        elif u.startswith(":FUNC") or u.startswith(":FUNCTION"):
            # :FUNC "VOLT:DC"
            self.function = cmd.split(maxsplit=1)[-1].strip().strip('"')
        elif u.startswith(":VOLT:DC:NPLC") or u.startswith(":VOLTAGE:DC:NPLC"):
            self.nplc = float(cmd.split()[-1])

    def _handle_query(self, cmd: str, u: str) -> str | None:
        if u in (":READ?", ":FETC?", ":FETCH?"):
            return f"{self._value_for_function():.6E}"
        if u.startswith(":MEAS:VOLT:DC") or u.startswith(":MEASURE:VOLTAGE:DC"):
            return f"{self.nominal_vdc:.6E}"
        if u.startswith(":MEAS:CURR") or u.startswith(":MEASURE:CURRENT"):
            return f"{self.nominal_idc:.6E}"
        if u.startswith(":MEAS:RES") or u.startswith(":MEASURE:RESISTANCE"):
            return f"{1.0e3:.6E}"
        if u.startswith(":FUNC") or u.startswith(":FUNCTION"):
            return f'"{self.function}"'
        return None
