"""Multi-vendor oscilloscope wiring.

``make_scope`` reads ``*IDN?`` and returns the right driver:

* Keysight / Rigol / Siglent / R&S / GW-Instek -> :class:`KeysightScope` (they share the
  InfiniiVision-style SCPI this app uses: ``:WAV:PRE?`` + IEEE block, ``:CHANx:SCAL``,
  ``:TIM:SCAL``, ``:TRIG:EDGE``, ``:MEAS:*``).
* Tektronix -> :class:`TektronixScope`, which speaks Tek's ``WFMOutpre``/``CURVe``/
  ``MEASUrement:IMMed`` command set instead.

The Tektronix driver is written from the MSO/DPO/TDS programmer manuals; it goes live the
moment a Tek scope is attached (no simulator stands in for it).
"""

from __future__ import annotations

import numpy as np

from ..provenance import Waveform
from ..safety import SafetyInvariantEngine, ScopeFrontEnd
from .keysight import KeysightScope
from .scpi import safe_float
from .transport import Transport
from .vendors import identify, scope_dialect


def _parse_ieee_block(raw: bytes) -> bytes:
    """Strip a IEEE-488.2 definite-length block header ``#<n><len><payload>``."""
    if not raw or raw[:1] != b"#":
        return raw
    ndigits = int(chr(raw[1]))
    start = 2 + ndigits
    length = int(raw[2:start] or b"0")
    return raw[start:start + length]


# Tek MEASUrement:IMMed:TYPe keyword per our measurement key.
_TEK_MEAS = {
    "vpp": "PK2pk", "vamp": "AMPlitude", "vmax": "MAXimum", "vmin": "MINimum",
    "vtop": "HIGH", "vbase": "LOW", "vavg": "MEAN", "vrms": "RMS",
    "freq": "FREQuency", "period": "PERIod", "duty": "PDUty", "pwidth": "PWIdth",
    "nwidth": "NWIdth", "rise": "RISe", "fall": "FALL", "over": "POVershoot",
}
_TEK_UNIT = {"vpp": "V", "vamp": "V", "vmax": "V", "vmin": "V", "vtop": "V", "vbase": "V",
             "vavg": "V", "vrms": "V", "freq": "Hz", "period": "s", "duty": "%",
             "pwidth": "s", "nwidth": "s", "rise": "s", "fall": "s", "over": "%"}
_TEK_ACQ = {"NORM": "SAMple", "AVER": "AVErage", "HRES": "HIRes", "PEAK": "PEAKdetect"}


class TektronixScope(KeysightScope):
    """Tektronix scope driver (MSO/DPO/TDS). Overrides the vendor-specific commands; reuses
    the shared snapshot/bounded-autoset logic from :class:`KeysightScope`."""

    def reset(self) -> None:
        self.t.write("*RST")
        self.t.write("*CLS")
        self.t.write("HEADer OFF")  # values come back bare, not "CMD value"

    def set_channel(self, ch, *, enabled=None, scale=None, offset=None, coupling=None,
                    probe=None, bwlimit=None, invert=None, label=None, unit=None) -> None:
        if enabled is not None:
            self.t.write(f"SELect:CH{ch} {'ON' if enabled else 'OFF'}")
            (self.enabled.add if enabled else self.enabled.discard)(ch)
        if probe is not None and probe:
            self.t.write(f"CH{ch}:PRObe:GAIN {1.0 / float(probe)}")  # Tek uses gain = 1/atten
        if coupling is not None:
            self.t.write(f"CH{ch}:COUPling {coupling}")
        if scale is not None:
            self.t.write(f"CH{ch}:SCAle {scale}")
        if offset is not None:
            self.t.write(f"CH{ch}:OFFSet {offset}")
        if bwlimit is not None:
            self.t.write(f"CH{ch}:BANdwidth {'TWEnty' if bwlimit else 'FULl'}")
        if invert is not None:
            self.t.write(f"CH{ch}:INVert {'ON' if invert else 'OFF'}")
        if label is not None:
            self.t.write(f'CH{ch}:LABel "{label}"')

    def set_timebase(self, *, scale=None, position=None, reference=None) -> None:
        if scale is not None:
            self.t.write(f"HORizontal:SCAle {scale}")
        if position is not None:
            self.t.write(f"HORizontal:DELay:TIMe {position}")

    def set_trigger(self, *, mode=None, source=None, level=None, slope=None,
                    coupling=None, holdoff=None, sweep=None) -> None:
        if source is not None:
            self.t.write(f"TRIGger:A:EDGE:SOUrce {source.replace('CHAN', 'CH')}")
        if slope is not None:
            self.t.write(f"TRIGger:A:EDGE:SLOpe {'RISe' if slope.upper().startswith('POS') else 'FALL'}")
        if coupling is not None:
            self.t.write(f"TRIGger:A:EDGE:COUPling {coupling}")
        if level is not None:
            self.t.write(f"TRIGger:A:LEVel {level}")
        if holdoff is not None:
            self.t.write(f"TRIGger:A:HOLDoff:TIMe {holdoff}")
        if sweep is not None:
            self.t.write(f"TRIGger:A:MODe {'AUTO' if sweep.upper().startswith('AUTO') else 'NORMal'}")

    def set_acquisition(self, *, atype=None, count=None, points=None) -> None:
        if atype is not None:
            self.t.write(f"ACQuire:MODe {_TEK_ACQ.get(atype.upper(), 'SAMple')}")
        if count is not None:
            self.t.write(f"ACQuire:NUMAVg {count}")
        if points is not None:
            self.t.write(f"HORizontal:RECOrdlength {points}")

    def run(self) -> None:
        self.t.write("ACQuire:STOPAfter RUNSTop")
        self.t.write("ACQuire:STATE RUN")

    def stop(self) -> None:
        self.t.write("ACQuire:STATE STOP")

    def single(self) -> None:
        self.t.write("ACQuire:STOPAfter SEQuence")
        self.t.write("ACQuire:STATE RUN")

    def _front_end(self, ch: int = 1) -> ScopeFrontEnd:
        def q(cmd, default):
            try:
                return self.t.query(cmd).strip()
            except Exception:  # noqa: BLE001
                return default
        gain = safe_float(q(f"CH{ch}:PRObe:GAIN?", "1")) or 1.0
        atten = 1.0 / gain if gain else 1.0
        coup = q(f"CH{ch}:COUPling?", "DC")
        term = safe_float(q(f"CH{ch}:TERmination?", "1e6")) or 1e6
        return ScopeFrontEnd(attenuation=atten, coupling=coup, input_impedance=term)

    def displayed_channels(self) -> list[int]:
        out = []
        for ch in (1, 2, 3, 4):
            try:
                if self.t.query(f"SELect:CH{ch}?").strip() in ("1", "ON", "on"):
                    out.append(ch)
            except Exception:  # noqa: BLE001
                pass
        return out or [1]

    def capture(self, ch: int = 1) -> Waveform:
        self.t.write(f"DATa:SOUrce CH{ch}")
        self.t.write("DATa:ENCdg RIBinary")  # signed integer, MSB first
        self.t.write("DATa:WIDth 2")
        self.t.write("DATa:STARt 1")
        # DATa:STOP is a persistent setting that does NOT track the record length; without
        # setting it the CURVe? transfer is silently truncated to a stale value. Pull the full
        # acquired record.
        rec = int(safe_float(self.t.query("HORizontal:RECOrdlength?")) or 0)
        if rec <= 0:
            rec = int(safe_float(self.t.query("WFMOutpre:NR_Pt?")) or 0)
        if rec > 0:
            self.t.write(f"DATa:STOP {rec}")
        xincr = safe_float(self.t.query("WFMOutpre:XINCR?")) or 1.0
        xzero = safe_float(self.t.query("WFMOutpre:XZEro?")) or 0.0
        ymult = safe_float(self.t.query("WFMOutpre:YMUlt?")) or 1.0
        yoff = safe_float(self.t.query("WFMOutpre:YOFf?")) or 0.0
        yzero = safe_float(self.t.query("WFMOutpre:YZEro?")) or 0.0
        payload = _parse_ieee_block(self.t.query_raw("CURVe?"))
        codes = np.frombuffer(payload, dtype=">i2").astype(np.float64)
        v = (codes - yoff) * ymult + yzero
        t = xzero + np.arange(len(v), dtype=np.float64) * xincr
        return Waveform(
            t=t.tolist(), v=v.tolist(), unit_t="s", unit_v="V",
            provenance=self.t.default_provenance, source=f"tek:CH{ch}",
            meta={"points": int(len(v)), "vpp": float(np.ptp(v)) if len(v) else 0.0},
        )

    def _tek_meas(self, ch: int, typ: str) -> float | None:
        self.t.write(f"MEASUrement:IMMed:SOUrce CH{ch}")
        self.t.write(f"MEASUrement:IMMed:TYPe {typ}")
        return safe_float(self.t.query("MEASUrement:IMMed:VALue?"))

    def measure(self, ch: int = 1) -> dict:
        return {
            "vpp": self._tek_meas(ch, "PK2pk"), "vrms": self._tek_meas(ch, "RMS"),
            "vmax": self._tek_meas(ch, "MAXimum"), "vmin": self._tek_meas(ch, "MINimum"),
            "freq": self._tek_meas(ch, "FREQuency"), "period": self._tek_meas(ch, "PERIod"),
        }

    def measure_all(self, ch: int = 1) -> dict:
        return {key: {"value": self._tek_meas(ch, typ), "unit": _TEK_UNIT[key]}
                for key, typ in _TEK_MEAS.items()}

    def measure_vpp(self, ch: int = 1) -> float:
        return float(self._tek_meas(ch, "PK2pk") or 0.0)


def make_scope(transport: Transport, engine: SafetyInvariantEngine | None = None):
    """Return the oscilloscope driver matching the connected instrument's vendor.

    The dialect is cached on the transport so the per-frame WS loop doesn't re-``*IDN?``.
    """
    dialect = getattr(transport, "_scope_dialect", None)
    if dialect is None:
        _idn, vendor = identify(transport)
        dialect = scope_dialect(vendor)
        # Only cache a CONFIDENT detection. If *IDN? failed/timed out (vendor == "unknown"),
        # use the SCPI-1999 default for this call but leave the cache unset so a later call
        # can re-detect — otherwise a momentarily-unreachable Tek scope is locked to Keysight.
        if vendor != "unknown":
            try:
                transport._scope_vendor = vendor        # type: ignore[attr-defined]
                transport._scope_dialect = dialect      # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
    if dialect == "tektronix":
        return TektronixScope(transport, engine)
    return KeysightScope(transport, engine)
