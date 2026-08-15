"""Simulated bench power supply — the SOURCE_CONTROL exemplar.

This is the dangerous instrument: it can energize a DUT. The model faithfully implements
*hardware* protections (OVP/OCP trip, output defaults OFF, OVP clamps output) because the
safety discipline says hardware limits — not software gating — are the real safety
mechanism. The SafetyInvariantEngine + PresetRunner sit in front of writes to it.
"""

from __future__ import annotations

from .base import SimInstrument


class SimPSU(SimInstrument):
    idn = "SIM,ECE-SUITE-PSU,SN-0004,0.0.0"

    def __init__(self, *, max_voltage: float = 30.0, max_current: float = 5.0):
        super().__init__()
        self.max_voltage = max_voltage      # instrument rating (RatingModel mirror)
        self.max_current = max_current
        self.vset = 0.0
        self.iset = 0.0                     # current limit
        self.ovp = max_voltage             # over-voltage protection trip
        self.ocp = max_current             # over-current protection trip
        self.output = False
        self.load_resistance: float | None = None  # None -> open circuit (iout=0)
        self.tripped: str | None = None

    def _on_reset(self) -> None:
        self.vset = self.iset = 0.0
        self.ovp, self.ocp = self.max_voltage, self.max_current
        self.output = False
        self.tripped = None

    # measured outputs reflect the hardware model
    def _vout(self) -> float:
        if not self.output or self.tripped:
            return 0.0
        return min(self.vset, self.ovp)

    def _iout(self) -> float:
        if not self.output or self.tripped:
            return 0.0
        if self.load_resistance is None or self.load_resistance <= 0:
            return 0.0
        i = self._vout() / self.load_resistance
        return min(i, self.iset)            # CC clamp at current limit

    def _enable_output(self) -> None:
        # hardware OVP/OCP check at enable
        if self.vset > self.ovp:
            self.output = False
            self.tripped = "OVP"
            self._errq.append('-200,"OVP trip: vset exceeds OVP"')
            return
        self.output = True
        self.tripped = None

    def _handle_write(self, cmd: str, u: str) -> None:
        if u.startswith(":VOLT:PROT") or u.startswith(":VOLTAGE:PROTECTION"):
            self.ovp = float(cmd.split()[-1])
        elif u.startswith(":CURR:PROT") or u.startswith(":CURRENT:PROTECTION"):
            self.ocp = float(cmd.split()[-1])
        elif u.startswith(":VOLT") or u.startswith(":VOLTAGE"):
            v = float(cmd.split()[-1])
            if v > self.max_voltage:
                self._errq.append('-222,"Data out of range: voltage exceeds rating"')
            else:
                self.vset = v
        elif u.startswith(":CURR") or u.startswith(":CURRENT"):
            i = float(cmd.split()[-1])
            if i > self.max_current:
                self._errq.append('-222,"Data out of range: current exceeds rating"')
            else:
                self.iset = i
        elif u.startswith(":OUTP") or u.startswith(":OUTPUT"):
            arg = cmd.split()[-1].upper()
            if arg in ("ON", "1"):
                self._enable_output()
            else:
                self.output = False

    def _handle_query(self, cmd: str, u: str) -> str | None:
        if u.startswith(":VOLT:PROT") or u.startswith(":VOLTAGE:PROTECTION"):
            return repr(self.ovp)
        if u.startswith(":CURR:PROT") or u.startswith(":CURRENT:PROTECTION"):
            return repr(self.ocp)
        if u.startswith(":VOLT") or u.startswith(":VOLTAGE"):
            return repr(self.vset)
        if u.startswith(":CURR") or u.startswith(":CURRENT"):
            return repr(self.iset)
        if u.startswith(":OUTP") or u.startswith(":OUTPUT"):
            return "1" if self.output else "0"
        if u.startswith(":MEAS:VOLT") or u.startswith(":MEASURE:VOLTAGE"):
            return repr(self._vout())
        if u.startswith(":MEAS:CURR") or u.startswith(":MEASURE:CURRENT"):
            return repr(self._iout())
        return None
