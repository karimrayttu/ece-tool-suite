"""Keysight instrument drivers — oscilloscope, DMM, spectrum analyzer.

Each driver wraps a Transport (a real VisaTransport in the running app) and speaks the
Keysight SCPI dialect: InfiniiVision/InfiniiVision-X scopes, Truevolt (34460/61/65) DMMs,
and X-series signal analyzers. Provenance flows from the transport, so a reading is
UNVERIFIED_HW until the lab-truth gate promotes the connection to VERIFIED_HW.

The bounded auto-setup deliberately never issues the instrument-native :AUToScale.
"""

from __future__ import annotations

import math

import numpy as np

from ..provenance import Waveform
from ..safety import Action, Capability, OpType, SafetyInvariantEngine, ScopeFrontEnd
from ..verification import VerificationGate
from .preamble import decode_waveform, parse_preamble
from .scpi import parse_idn, safe_float
from .transport import Transport


def _snap_125(v: float) -> float:
    if v <= 0:
        return v
    d = 10 ** math.floor(math.log10(v))
    n = v / d
    for s in (1, 2, 5):
        if n <= s:
            return float(s * d)
    return float(10 * d)


class KeysightScope:
    def __init__(self, transport: Transport, engine: SafetyInvariantEngine | None = None):
        self.t = transport
        self.engine = engine or SafetyInvariantEngine()
        self.enabled: set[int] = {1}

    def identify(self):
        return parse_idn(self.t.query("*IDN?"))

    def reset(self) -> None:
        self.t.write("*RST")
        self.t.write("*CLS")

    def set_channel(self, ch: int, *, enabled: bool | None = None, scale: float | None = None,
                    offset: float | None = None, coupling: str | None = None, probe: float | None = None,
                    bwlimit: bool | None = None, invert: bool | None = None,
                    label: str | None = None, unit: str | None = None) -> None:
        if enabled is not None:
            self.t.write(f":CHAN{ch}:DISP {1 if enabled else 0}")
            (self.enabled.add if enabled else self.enabled.discard)(ch)
        if probe is not None:
            self.t.write(f":CHAN{ch}:PROB {probe}")
        if coupling is not None:
            self.t.write(f":CHAN{ch}:COUP {coupling}")
        if scale is not None:
            self.t.write(f":CHAN{ch}:SCAL {scale}")
        if offset is not None:
            self.t.write(f":CHAN{ch}:OFFS {offset}")
        if bwlimit is not None:
            self.t.write(f":CHAN{ch}:BWL {1 if bwlimit else 0}")
        if invert is not None:
            self.t.write(f":CHAN{ch}:INV {1 if invert else 0}")
        if unit is not None:
            self.t.write(f":CHAN{ch}:UNIT {unit}")
        if label is not None:
            self.t.write(f':CHAN{ch}:LAB "{label}"')

    def set_timebase(self, *, scale: float | None = None, position: float | None = None,
                     reference: str | None = None) -> None:
        if scale is not None:
            self.t.write(f":TIM:SCAL {scale}")
        if position is not None:
            self.t.write(f":TIM:POS {position}")
        if reference is not None:
            self.t.write(f":TIM:REF {reference}")

    def set_trigger(self, *, mode: str | None = None, source: str | None = None,
                    level: float | None = None, slope: str | None = None,
                    coupling: str | None = None, holdoff: float | None = None,
                    sweep: str | None = None) -> None:
        if mode is not None:
            self.t.write(f":TRIG:MODE {mode}")
        if sweep is not None:
            self.t.write(f":TRIG:SWE {sweep}")
        if source is not None:
            self.t.write(f":TRIG:EDGE:SOUR {source}")
        if slope is not None:
            self.t.write(f":TRIG:EDGE:SLOP {slope}")
        if coupling is not None:
            self.t.write(f":TRIG:EDGE:COUP {coupling}")
        if level is not None:
            self.t.write(f":TRIG:EDGE:LEV {level}")
        if holdoff is not None:
            self.t.write(f":TRIG:HOLD {holdoff}")

    def set_acquisition(self, *, atype: str | None = None, count: int | None = None,
                        points: int | None = None) -> None:
        if atype is not None:
            self.t.write(f":ACQ:TYPE {atype}")
        if count is not None:
            self.t.write(f":ACQ:COUN {count}")
        if points is not None:
            self.t.write(f":WAV:POIN {points}")

    def run(self) -> None:
        self.t.write(":RUN")

    def stop(self) -> None:
        self.t.write(":STOP")

    def single(self) -> None:
        self.t.write(":SINGle")

    def configure_channel(self, scale: float, offset: float = 0.0, coupling: str = "DC", probe: float = 10.0) -> None:
        self.set_channel(1, scale=scale, offset=offset, coupling=coupling, probe=probe)

    def configure_timebase(self, scale: float) -> None:
        self.set_timebase(scale=scale)

    def _front_end(self, ch: int = 1) -> ScopeFrontEnd:
        def q(cmd, default):
            try:
                return self.t.query(cmd).strip()
            except Exception:  # noqa: BLE001
                return default
        atten = float(q(f":CHAN{ch}:PROB?", "1") or 1)
        coup = q(f":CHAN{ch}:COUP?", "DC")
        imp = q(f":CHAN{ch}:IMP?", "ONEM")
        z = 50.0 if "FIFT" in imp.upper() else 1e6
        return ScopeFrontEnd(attenuation=atten, coupling=coup, input_impedance=z)

    def bounded_autoset(self, expected_vpp: float, expected_freq: float, ch: int = 1) -> dict:
        decision = self.engine.evaluate(
            Action(Capability.CONFIGURE_INSTRUMENT, OpType.CONFIGURE, "scope",
                   {"expected_input_v": expected_vpp / 2.0}),
            scope_front_end=self._front_end(ch),
        )
        if decision.blocked:
            raise ValueError("bounded_autoset blocked: " + "; ".join(decision.reasons))
        vdiv = _snap_125(expected_vpp / 6.0)
        tdiv = _snap_125((3.0 / expected_freq) / 10.0)
        self.set_channel(ch, scale=vdiv)
        self.set_timebase(scale=tdiv)
        return {"vdiv": vdiv, "tdiv": tdiv}

    def capture(self, ch: int = 1) -> Waveform:
        self.t.write(f":WAV:SOUR CHAN{ch}")
        self.t.write(":WAV:FORM WORD")
        self.t.write(":WAV:BYT LSBF")
        pre = parse_preamble(self.t.query(":WAV:PRE?"))
        t, v = decode_waveform(self.t.query_raw(":WAV:DATA?"), pre, byteorder="LSB")
        return Waveform(
            t=t.tolist(), v=v.tolist(), unit_t="s", unit_v="V",
            provenance=self.t.default_provenance, source=f"keysight:CHAN{ch}",
            meta={"points": int(pre.points), "vpp": float(np.ptp(v))},
        )

    def measure(self, ch: int = 1) -> dict:
        return {
            "vpp": safe_float(self.t.query(f":MEAS:VPP? CHAN{ch}")),
            "vrms": safe_float(self.t.query(f":MEAS:VRMS? CHAN{ch}")),
            "vmax": safe_float(self.t.query(f":MEAS:VMAX? CHAN{ch}")),
            "vmin": safe_float(self.t.query(f":MEAS:VMIN? CHAN{ch}")),
            "freq": safe_float(self.t.query(f":MEAS:FREQ? CHAN{ch}")),
            "period": safe_float(self.t.query(f":MEAS:PER? CHAN{ch}")),
        }

    # The full InfiniiVision measurement set, queried on demand (kept out of the WS
    # frame so live streaming stays light on real hardware).
    _MEAS_ALL = [
        ("vpp", ":MEAS:VPP?", "V"), ("vamp", ":MEAS:VAMP?", "V"),
        ("vmax", ":MEAS:VMAX?", "V"), ("vmin", ":MEAS:VMIN?", "V"),
        ("vtop", ":MEAS:VTOP?", "V"), ("vbase", ":MEAS:VBAS?", "V"),
        ("vavg", ":MEAS:VAV?", "V"), ("vrms", ":MEAS:VRMS?", "V"),
        ("freq", ":MEAS:FREQ?", "Hz"), ("period", ":MEAS:PER?", "s"),
        ("duty", ":MEAS:DUTY?", "%"), ("pwidth", ":MEAS:PWID?", "s"),
        ("nwidth", ":MEAS:NWID?", "s"), ("rise", ":MEAS:RIS?", "s"),
        ("fall", ":MEAS:FALL?", "s"), ("over", ":MEAS:OVER?", "%"),
    ]

    def measure_all(self, ch: int = 1) -> dict:
        out: dict[str, dict] = {}
        for key, cmd, unit in self._MEAS_ALL:
            out[key] = {"value": safe_float(self.t.query(f"{cmd} CHAN{ch}")), "unit": unit}
        return out

    def measure_vpp(self, ch: int = 1) -> float:
        return float(self.t.query(f":MEAS:VPP? CHAN{ch}"))

    def displayed_channels(self) -> list[int]:
        out = []
        for ch in (1, 2, 3, 4):
            try:
                if self.t.query(f":CHAN{ch}:DISP?").strip() in ("1", "ON", "on"):
                    out.append(ch)
            except Exception:  # noqa: BLE001
                pass
        return out or [1]

    def snapshot(self) -> dict:
        """One frame for the live scope view: each displayed channel + its measurements."""
        chans = []
        for ch in self.displayed_channels():
            wf = self.capture(ch)
            chans.append({"ch": ch, "t": wf.t, "v": wf.v, "meta": dict(wf.meta),
                          "measure": self.measure(ch)})
        return {"connected": True, "provenance": self.t.default_provenance.value, "channels": chans}


# =========================================================================
# Digital multimeter (Keysight Truevolt 34460/61/65A)
# =========================================================================
_DMM_FUNC = {
    "VDC": "VOLT:DC", "VAC": "VOLT:AC", "IDC": "CURR:DC", "IAC": "CURR:AC",
    "RES": "RES", "FRES": "FRES", "FREQ": "FREQ", "CAP": "CAP",
    "TEMP": "TEMP", "DIOD": "DIOD", "CONT": "CONT",
}
_DMM_UNIT = {
    "VDC": "V", "VAC": "V", "IDC": "A", "IAC": "A", "RES": "Ω", "FRES": "Ω",
    "FREQ": "Hz", "CAP": "F", "TEMP": "°C", "DIOD": "V", "CONT": "Ω",
}
_DMM_NPLC_OK = {"VDC", "IDC", "RES", "FRES", "TEMP"}


class KeysightDMM:
    def __init__(self, transport: Transport):
        self.t = transport
        self.function = "VDC"

    def identify(self):
        return parse_idn(self.t.query("*IDN?"))

    def configure(self, function: str, rng: str | float = "AUTO", nplc: float | None = None) -> dict:
        function = function.upper()
        if function not in _DMM_FUNC:
            raise ValueError(f"unknown DMM function {function!r}")
        base = _DMM_FUNC[function]
        cmd = f":CONF:{base}"
        if rng not in (None, "", "AUTO", "auto"):
            cmd += f" {rng}"
        self.t.write(cmd)
        if nplc is not None and function in _DMM_NPLC_OK:
            self.t.write(f":SENS:{base}:NPLC {nplc}")
        self.function = function
        return {"function": function, "unit": _DMM_UNIT[function]}

    def read(self) -> dict:
        val = safe_float(self.t.query(":READ?"))
        return {
            "connected": True, "value": val, "unit": _DMM_UNIT.get(self.function, ""),
            "function": self.function, "provenance": self.t.default_provenance.value,
        }


# =========================================================================
# Spectrum / signal analyzer (Keysight X-series, SA mode)
# =========================================================================
class KeysightSpectrumAnalyzer:
    def __init__(self, transport: Transport):
        self.t = transport

    def identify(self):
        return parse_idn(self.t.query("*IDN?"))

    _TRACE_MODE = {"WRITE": "WRIT", "MAXHOLD": "MAXH", "MINHOLD": "MINH", "AVERAGE": "AVER", "VIEW": "VIEW"}

    def configure(self, *, center: float | None = None, span: float | None = None,
                  start: float | None = None, stop: float | None = None,
                  rbw: float | None = None, vbw: float | None = None,
                  rbw_auto: bool | None = None, vbw_auto: bool | None = None,
                  ref_level: float | None = None, atten: float | None = None,
                  preamp: bool | None = None, sweep_points: int | None = None,
                  trace_mode: str | None = None, detector: str | None = None,
                  averages: int | None = None) -> dict:
        if center is not None:
            self.t.write(f":FREQ:CENT {center}")
        if span is not None:
            self.t.write(f":FREQ:SPAN {span}")
        if start is not None:
            self.t.write(f":FREQ:STAR {start}")
        if stop is not None:
            self.t.write(f":FREQ:STOP {stop}")
        if rbw_auto is not None:
            self.t.write(f":BAND:AUTO {1 if rbw_auto else 0}")
        if rbw is not None:
            self.t.write(f":BAND {rbw}")
        if vbw_auto is not None:
            self.t.write(f":BAND:VID:AUTO {1 if vbw_auto else 0}")
        if vbw is not None:
            self.t.write(f":BAND:VID {vbw}")
        if ref_level is not None:
            self.t.write(f":DISP:WIND:TRAC:Y:RLEV {ref_level}")
        if atten is not None:
            self.t.write(f":POW:ATT {atten}")
        if preamp is not None:
            self.t.write(f":POW:GAIN {1 if preamp else 0}")
        if sweep_points is not None:
            self.t.write(f":SWE:POIN {sweep_points}")
        if trace_mode is not None:
            self.t.write(f":TRAC1:TYPE {self._TRACE_MODE.get(trace_mode.upper(), 'WRIT')}")
        if detector is not None:
            self.t.write(f":DET {detector}")
        if averages is not None:
            self.t.write(f":AVER:COUN {averages}")
        return {"ok": True}

    def trace(self) -> dict:
        self.t.write(":FORM:DATA ASC")
        center = float(self.t.query(":FREQ:CENT?"))
        span = float(self.t.query(":FREQ:SPAN?"))
        raw = self.t.query(":TRAC? TRACE1")
        amps = [float(x) for x in raw.strip().split(",") if x.strip()]
        freqs = np.linspace(center - span / 2, center + span / 2, len(amps)).tolist() if amps else []
        return {
            "connected": True, "freqs": freqs, "amps": amps,
            "center": center, "span": span,
            "provenance": self.t.default_provenance.value,
        }

    def marker_peak(self) -> dict:
        self.t.write(":CALC:MARK:MAX")
        return {
            "freq": safe_float(self.t.query(":CALC:MARK:X?")),
            "amp": safe_float(self.t.query(":CALC:MARK:Y?")),
        }


# =========================================================================
# Guided bring-up (scope)
# =========================================================================
def run_bringup(scope_transport: Transport, engine: SafetyInvariantEngine, audit=None) -> dict:
    from .scope_drivers import make_scope  # lazy import to avoid an import cycle

    drv = make_scope(scope_transport, engine)
    steps: list[dict] = []

    idn = drv.identify()
    steps.append({"step": "identify", "ok": bool(idn.vendor), "note": idn.raw})

    drv.reset()
    steps.append({"step": "reset", "ok": True, "note": "*RST + *CLS (safe defaults)"})

    vr = VerificationGate(audit).verify(scope_transport, role="scope")
    steps.append({"step": "verify", "ok": True, "verified": vr.ok,
                  "provenance": vr.provenance, "note": vr.reasons[0] if vr.reasons else ""})

    try:
        cfg = drv.bounded_autoset(expected_vpp=1.0, expected_freq=1000.0)
        steps.append({"step": "bounded_autoset", "ok": True,
                      "note": f"V/div={cfg['vdiv']} timebase={cfg['tdiv']} (no native AUToScale)"})
    except Exception as e:  # noqa: BLE001
        steps.append({"step": "bounded_autoset", "ok": False, "note": str(e)})

    try:
        wf = drv.capture()
        steps.append({"step": "capture", "ok": len(wf.v) > 0, "provenance": wf.provenance.value,
                      "note": f"{len(wf.v)} points, Vpp={wf.meta['vpp']:.3f} V"})
    except Exception as e:  # noqa: BLE001
        steps.append({"step": "capture", "ok": False, "note": str(e)})

    return {
        "ok": all(s["ok"] for s in steps),
        "hardware_verified": vr.ok,
        "provenance": scope_transport.default_provenance.value,
        "steps": steps,
    }
