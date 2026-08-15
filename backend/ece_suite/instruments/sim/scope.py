"""Simulated Keysight-style oscilloscope (CHAN1)."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from ..preamble import FORMAT_BYTE, FORMAT_WORD, Preamble, encode_waveform_block
from .base import SimInstrument

SignalFn = Callable[[np.ndarray], np.ndarray]


def _default_signal(t: np.ndarray) -> np.ndarray:
    """1 kHz, 1 Vpp sine — a recognizable default."""
    return 0.5 * np.sin(2 * math.pi * 1_000.0 * t)


class SimScope(SimInstrument):
    idn = "SIM,ECE-SUITE-SCOPE,SN-0001,0.0.0"

    def __init__(
        self,
        *,
        signal: SignalFn = _default_signal,
        points: int = 1000,
        timebase_s_per_div: float = 200e-6,
        ch_scale_v_per_div: float = 0.2,
        ch_offset_v: float = 0.0,
        fmt: int = FORMAT_WORD,
    ):
        super().__init__()
        self._signal = signal
        self.points = points
        self.timebase = timebase_s_per_div
        self.ch_scale = ch_scale_v_per_div
        self.ch_offset = ch_offset_v
        self.fmt = fmt
        self.byteorder = "LSB"
        # front-end state queried by the safety engine before near-limit ops
        self.probe_attenuation = 10.0   # 10x probe
        self.coupling = "DC"
        self.input_impedance = 1e6      # 1 MΩ
        # multi-channel display state + the channel a :WAV:DATA? read targets
        self.ch_enabled = {1: True, 2: False, 3: False, 4: False}
        self.wav_source = 1

    def _preamble(self) -> Preamble:
        n = self.points
        xinc = (self.timebase * 10.0) / n
        xorigin = -(self.timebase * 10.0) / 2.0
        full_scale_v = self.ch_scale * 8.0
        if self.fmt == FORMAT_WORD:
            yref, yinc = 32768.0, full_scale_v / 65536.0
        elif self.fmt == FORMAT_BYTE:
            yref, yinc = 128.0, full_scale_v / 256.0
        else:
            raise ValueError(f"sim supports BYTE/WORD only, not {self.fmt}")
        return Preamble(
            fmt=self.fmt, wtype=0, points=n, count=1,
            xincrement=xinc, xorigin=xorigin, xreference=0.0,
            yincrement=yinc, yorigin=self.ch_offset, yreference=yref,
        )

    def _channel_signal(self, t: np.ndarray, ch: int) -> np.ndarray:
        """A distinct recognizable waveform per channel so the multi-trace UI is live."""
        if ch == 1:
            return np.asarray(self._signal(t), dtype=np.float64)
        if ch == 2:  # 2 kHz sine, smaller
            return 0.3 * np.sin(2 * math.pi * 2_000.0 * t + 1.0)
        if ch == 3:  # 500 Hz square
            return 0.4 * np.sign(np.sin(2 * math.pi * 500.0 * t))
        # ch 4: 1 kHz triangle
        ph = (1_000.0 * t) % 1.0
        return 0.25 * (2.0 * np.abs(2.0 * ph - 1.0) - 1.0)

    def _volts(self, pre: Preamble, ch: int | None = None) -> np.ndarray:
        n = np.arange(pre.points, dtype=np.float64)
        t = pre.xorigin + (n - pre.xreference) * pre.xincrement
        return self._channel_signal(t, ch if ch is not None else self.wav_source) + self.ch_offset

    def _handle_write(self, cmd: str, u: str) -> None:
        if u.startswith(":WAV:SOUR") or u.startswith(":WAVEFORM:SOURCE"):
            arg = cmd.split()[-1].upper().replace("CHANNEL", "CHAN")
            if arg.startswith("CHAN"):
                self.wav_source = int(arg[4:] or "1")
        elif u.startswith(":WAV:FORM") or u.startswith(":WAVEFORM:FORMAT"):
            self.fmt = FORMAT_WORD if cmd.split()[-1].upper().startswith("WORD") else FORMAT_BYTE
        elif u.startswith(":WAV:POIN") or u.startswith(":WAVEFORM:POINTS"):
            self.points = int(float(cmd.split()[-1]))
        elif (u.startswith(":CHAN") or u.startswith(":CHANNEL")) and (":DISP" in u or ":DISPLAY" in u):
            try:
                ch = int(u.split(":")[1].replace("CHANNEL", "").replace("CHAN", ""))
                self.ch_enabled[ch] = cmd.split()[-1].upper() in ("1", "ON")
            except (ValueError, IndexError):
                pass
        elif u.startswith(":TIM:SCAL") or u.startswith(":TIMEBASE:SCALE"):
            self.timebase = float(cmd.split()[-1])
        elif u.startswith(":CHAN1:SCAL") or u.startswith(":CHANNEL1:SCALE"):
            self.ch_scale = float(cmd.split()[-1])
        elif u.startswith(":CHAN1:OFFS") or u.startswith(":CHANNEL1:OFFSET"):
            self.ch_offset = float(cmd.split()[-1])
        elif u.startswith(":CHAN1:PROB") or u.startswith(":CHANNEL1:PROBE"):
            self.probe_attenuation = float(cmd.split()[-1])
        elif u.startswith(":CHAN1:COUP") or u.startswith(":CHANNEL1:COUPLING"):
            self.coupling = cmd.split()[-1].upper()
        elif u.startswith(":CHAN1:IMP") or u.startswith(":CHANNEL1:IMPEDANCE"):
            arg = cmd.split()[-1].upper()
            self.input_impedance = 50.0 if arg in ("FIFT", "FIFTY", "50") else 1e6

    def _handle_query(self, cmd: str, u: str) -> str | None:
        if u.startswith(":WAV:PRE") or u.startswith(":WAVEFORM:PRE"):
            p = self._preamble()
            return ",".join(str(x) for x in (
                p.fmt, p.wtype, p.points, p.count,
                p.xincrement, p.xorigin, int(p.xreference),
                p.yincrement, p.yorigin, int(p.yreference),
            ))
        if u.startswith(":WAV:FORM") or u.startswith(":WAVEFORM:FORMAT"):
            return "WORD" if self.fmt == FORMAT_WORD else "BYTE"
        if u.startswith(":CHAN1:PROB") or u.startswith(":CHANNEL1:PROBE"):
            return repr(self.probe_attenuation)
        if u.startswith(":CHAN1:COUP") or u.startswith(":CHANNEL1:COUPLING"):
            return self.coupling
        if u.startswith(":CHAN1:IMP") or u.startswith(":CHANNEL1:IMPEDANCE"):
            return "FIFT" if abs(self.input_impedance - 50.0) < 1 else "ONEM"
        if u.startswith(":TIM:SCAL") or u.startswith(":TIMEBASE:SCALE"):
            return repr(self.timebase)
        if (u.startswith(":CHAN") or u.startswith(":CHANNEL")) and (":DISP" in u or ":DISPLAY" in u):
            try:
                ch = int(u.split(":")[1].replace("CHANNEL", "").replace("CHAN", ""))
                return "1" if self.ch_enabled.get(ch) else "0"
            except (ValueError, IndexError):
                return "0"
        if u.startswith(":MEAS:") or u.startswith(":MEASURE:"):
            # target the channel named in the query (e.g. ":MEAS:VPP? CHAN2"), else CH1
            ch = self.wav_source
            tail = u.replace("CHANNEL", "CHAN")
            if "CHAN" in tail:
                try:
                    ch = int(tail.split("CHAN")[-1].strip() or self.wav_source)
                except ValueError:
                    pass
            v = self._volts(self._preamble(), ch)
            freq = {1: 1000.0, 2: 2000.0, 3: 500.0, 4: 1000.0}.get(ch, 1000.0)
            if "VPP" in u or "VAMP" in u:
                return repr(float(np.ptp(v)))
            if "VRMS" in u:
                return repr(float(np.sqrt(np.mean(np.square(v)))))
            if "VMAX" in u or "VTOP" in u:
                return repr(float(v.max()))
            if "VMIN" in u or "VBAS" in u:
                return repr(float(v.min()))
            if "VAV" in u:
                return repr(float(v.mean()))
            if "FREQ" in u:
                return repr(freq)
            if "PER" in u:
                return repr(1.0 / freq)
            if "DUTY" in u:
                return "50.0"
            return None  # pwidth/nwidth/rise/fall/overshoot not simulated -> null
        return None

    def _handle_query_raw(self, cmd: str, u: str) -> bytes | None:
        if u.startswith(":WAV:DATA") or u.startswith(":WAVEFORM:DATA"):
            pre = self._preamble()
            return encode_waveform_block(self._volts(pre), pre, byteorder=self.byteorder)
        if u.startswith(":DISP:DATA") or u.startswith(":DISPLAY:DATA"):
            from ..pngutil import ieee_block, render_trace_png
            return ieee_block(render_trace_png(self._volts(self._preamble()).tolist()))
        return None
