"""Simulated spectrum analyzer (Keysight X-series-style SCPI).

Returns an ASCII trace (dBm vs frequency): a flat noise floor plus a deterministic tone
at the center frequency, so peak-search and trace rendering have something real to chew on.
"""

from __future__ import annotations

import numpy as np

from .base import SimInstrument


class SimSpectrumAnalyzer(SimInstrument):
    idn = "SIM,ECE-SUITE-SA,SN-0003,0.0.0"

    def __init__(
        self,
        *,
        center_hz: float = 100e6,
        span_hz: float = 10e6,
        points: int = 1001,
        ref_level_dbm: float = 0.0,
        noise_floor_dbm: float = -90.0,
        peak_dbm: float = -20.0,
    ):
        super().__init__()
        self.center = center_hz
        self.span = span_hz
        self.points = points
        self.ref_level = ref_level_dbm
        self.noise_floor = noise_floor_dbm
        self.peak_dbm = peak_dbm

    def freqs(self) -> np.ndarray:
        start = self.center - self.span / 2.0
        stop = self.center + self.span / 2.0
        return np.linspace(start, stop, self.points)

    def trace(self) -> np.ndarray:
        f = self.freqs()
        # Gaussian tone at center over a flat noise floor (deterministic).
        sigma = max(self.span / 200.0, 1.0)
        bump = (self.peak_dbm - self.noise_floor) * np.exp(-0.5 * ((f - self.center) / sigma) ** 2)
        return self.noise_floor + bump

    def _handle_write(self, cmd: str, u: str) -> None:
        if u.startswith(":FREQ:CENT") or u.startswith(":FREQUENCY:CENTER"):
            self.center = float(cmd.split()[-1])
        elif u.startswith(":FREQ:SPAN") or u.startswith(":FREQUENCY:SPAN"):
            self.span = float(cmd.split()[-1])
        elif u.startswith(":DISP:WIND:TRAC:Y:RLEV") or u.startswith(":DISPLAY"):
            try:
                self.ref_level = float(cmd.split()[-1])
            except ValueError:
                pass

    def _handle_query(self, cmd: str, u: str) -> str | None:
        if u.startswith(":FREQ:CENT") or u.startswith(":FREQUENCY:CENTER"):
            return repr(self.center)
        if u.startswith(":FREQ:SPAN") or u.startswith(":FREQUENCY:SPAN"):
            return repr(self.span)
        # The driver asks ":TRAC? TRACE1"; X-series also accepts ":TRAC:DATA? TRACE1". Match on
        # the command head so the argument and the optional :DATA node both work.
        if u.split("?")[0].split()[0] in (":TRAC", ":TRACE", ":TRAC:DATA", ":TRACE:DATA"):
            return ",".join(f"{x:.4f}" for x in self.trace())
        if u.startswith(":CALC:MARK:X") or u.startswith(":CALCULATE:MARKER:X"):
            return repr(self.center)  # peak is at center in this model
        if u.startswith(":CALC:MARK:Y") or u.startswith(":CALCULATE:MARKER:Y"):
            return f"{self.peak_dbm:.4f}"
        return None

    def _handle_query_raw(self, cmd: str, u: str) -> bytes | None:
        if u.startswith(":DISP:DATA") or u.startswith(":DISPLAY:DATA"):
            from ..pngutil import ieee_block, render_trace_png
            return ieee_block(render_trace_png(self.trace().tolist(), color=(34, 197, 94)))
        return None
