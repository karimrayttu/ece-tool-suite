"""Multi-vendor DMM support (Keysight + Fluke).

The user's DMM may be a Keysight Truevolt (34460/61/65A) or a Fluke. Fluke 8845A/8846A speak
the HP/Agilent 34401 SCPI command set (same as Keysight here), but the Fluke 45 / 8808A use a
simpler legacy dialect (``VDC``/``VAC``/``OHMS`` + ``MEAS?``). ``make_dmm`` reads ``*IDN?`` and
returns the right driver; the detected dialect is cached on the transport.
"""

from __future__ import annotations

from .scpi import parse_idn, safe_float
from .transport import Transport

_UNIT = {"VDC": "V", "VAC": "V", "IDC": "A", "IAC": "A", "RES": "Ω", "FRES": "Ω",
         "FREQ": "Hz", "CAP": "F", "TEMP": "°C", "DIOD": "V", "CONT": "Ω"}


# --- SCPI dialect: Keysight Truevolt + Fluke 8845/8846 (34401-compatible) --
_SCPI_FUNC = {"VDC": "VOLT:DC", "VAC": "VOLT:AC", "IDC": "CURR:DC", "IAC": "CURR:AC",
              "RES": "RES", "FRES": "FRES", "FREQ": "FREQ", "CAP": "CAP",
              "TEMP": "TEMP", "DIOD": "DIOD", "CONT": "CONT"}
_SCPI_NPLC_OK = {"VDC", "IDC", "RES", "FRES", "TEMP"}


class ScpiDmm:
    dialect = "scpi"

    def __init__(self, transport: Transport):
        self.t = transport
        self.function = "VDC"

    def identify(self):
        return parse_idn(self.t.query("*IDN?"))

    def configure(self, function: str, rng: str | float = "AUTO", nplc: float | None = None,
                  math: str | None = None, autozero: bool | None = None) -> dict:
        function = function.upper()
        if function not in _SCPI_FUNC:
            raise ValueError(f"unknown DMM function {function!r}")
        base = _SCPI_FUNC[function]
        cmd = f":CONF:{base}"
        if rng not in (None, "", "AUTO", "auto"):
            cmd += f" {rng}"
        self.t.write(cmd)
        if nplc is not None and function in _SCPI_NPLC_OK:
            self.t.write(f":SENS:{base}:NPLC {nplc}")
        if autozero is not None and function in _SCPI_NPLC_OK:
            self.t.write(f":SENS:{base}:ZERO:AUTO {1 if autozero else 0}")
        if math is not None:
            m = math.upper()
            if m in ("OFF", "NONE", ""):
                self.t.write(":CALC:STAT OFF")
            else:  # NULL (relative), DB, DBM
                self.t.write(f":CALC:FUNC {m}")
                self.t.write(":CALC:STAT ON")
        self.function = function
        return {"function": function, "unit": _UNIT[function]}

    def read(self) -> dict:
        val = safe_float(self.t.query(":READ?"))
        return {"connected": True, "value": val, "unit": _UNIT.get(self.function, ""),
                "function": self.function, "dialect": self.dialect, "provenance": self.t.default_provenance.value}


# --- Fluke legacy dialect: Fluke 45 / 8808A -------------------------------
_FLUKE_FUNC = {"VDC": "VDC", "VAC": "VAC", "IDC": "ADC", "IAC": "AAC",
               "RES": "OHMS", "FRES": "OHMS", "FREQ": "FREQ", "CONT": "CONT", "DIOD": "DIODE"}


class FlukeLegacyDmm:
    dialect = "fluke-legacy"

    def __init__(self, transport: Transport):
        self.t = transport
        self.function = "VDC"

    def identify(self):
        return parse_idn(self.t.query("*IDN?"))

    def configure(self, function: str, rng: str | float = "AUTO", nplc: float | None = None,
                  math: str | None = None, autozero: bool | None = None) -> dict:
        # math/autozero aren't part of the legacy command set — silently ignored here.
        function = function.upper()
        cmd = _FLUKE_FUNC.get(function)
        if cmd is None:
            raise ValueError(f"function {function!r} not supported on this Fluke DMM")
        self.t.write(cmd)  # legacy: the function keyword IS the command (e.g. "VDC")
        self.function = function
        return {"function": function, "unit": _UNIT.get(function, "")}

    def read(self) -> dict:
        val = safe_float(self.t.query("MEAS?"))
        return {"connected": True, "value": val, "unit": _UNIT.get(self.function, ""),
                "function": self.function, "dialect": self.dialect, "provenance": self.t.default_provenance.value}


# --- Fluke 287/289 handheld dialect (serial / IR cable) -------------------
# The 28x handhelds don't answer ``*IDN?``. They use a short binary-ish serial protocol:
# ``ID`` -> ``FLUKE 287,V1.00,...`` and ``QM`` -> ``QM,+1.23456E+0,VDC,NORMAL,NONE`` where
# QM returns the *primary display* value + unit directly (the meter's rotary switch/soft-keys
# choose the function, so there is no remote CONF).
_FLUKE28X_UNIT = {"VDC": "V", "VAC": "V", "ADC": "A", "AAC": "A", "OHM": "Ω", "OHMS": "Ω",
                  "HZ": "Hz", "F": "F", "CEL": "°C", "FAR": "°F", "V": "V", "A": "A"}


class Fluke28xDmm:
    dialect = "fluke-28x"

    def __init__(self, transport: Transport):
        self.t = transport
        self.function = "AUTO"

    def identify(self):
        try:
            resp = self.t.query("ID")  # e.g. "FLUKE 287,V1.00,12345678"
            parts = [p.strip() for p in resp.replace("FLUKE", "FLUKE,").split(",") if p.strip()]
            model = parts[1] if len(parts) > 1 else "28x"
            return parse_idn(f"FLUKE,{model},,{parts[2] if len(parts) > 2 else ''}")
        except Exception:  # noqa: BLE001
            return parse_idn("FLUKE,28x,,")

    def configure(self, function: str, rng: str | float = "AUTO", nplc: float | None = None,
                  math: str | None = None, autozero: bool | None = None) -> dict:
        # The handheld's function is chosen on the meter itself; QM reports whatever it shows.
        self.function = function.upper()
        return {"function": self.function, "unit": _UNIT.get(self.function, "")}

    def read(self) -> dict:
        val, unit = None, ""
        try:
            resp = self.t.query("QM").strip()  # "QM,+1.23456E+0,VDC,NORMAL,NONE"
            fields = [f.strip() for f in resp.split(",")]
            nums = [f for f in fields if safe_float(f) is not None]
            if nums:
                val = safe_float(nums[0])
            for f in fields:
                if f.upper() in _FLUKE28X_UNIT:
                    unit = _FLUKE28X_UNIT[f.upper()]
                    self.function = f.upper()
                    break
        except Exception:  # noqa: BLE001
            pass
        return {"connected": True, "value": val, "unit": unit or _UNIT.get(self.function, ""),
                "function": self.function, "dialect": self.dialect,
                "provenance": self.t.default_provenance.value}


def _is_fluke_legacy(vendor: str, model: str) -> bool:
    v, m = vendor.upper(), model.upper()
    if "FLUKE" not in v:
        return False
    # 8845A/8846A are 34401-compatible (SCPI); 45 and 8808A are legacy.
    if "8845" in m or "8846" in m:
        return False
    return m == "45" or m.startswith("45") or "8808" in m or "8806" in m


_DIALECTS = {"fluke-legacy": FlukeLegacyDmm, "fluke-28x": Fluke28xDmm, "scpi": ScpiDmm}


def make_dmm(transport: Transport):
    """Return the right DMM driver for the connected instrument (dialect cached on transport)."""
    cached = getattr(transport, "_dmm_dialect", None)
    if cached in _DIALECTS:
        return _DIALECTS[cached](transport)

    vendor = model = ""
    idn_ok = False
    try:
        idn = parse_idn(transport.query("*IDN?"))
        vendor, model = idn.vendor, idn.model
        idn_ok = bool(vendor)
    except Exception:  # noqa: BLE001
        pass

    if not idn_ok:
        # No *IDN? — could be a Fluke 28x handheld, which answers "ID".
        try:
            resp = transport.query("ID").upper()
            if "FLUKE" in resp and ("287" in resp or "289" in resp or "28X" in resp):
                dialect = "fluke-28x"
                _cache_dialect(transport, dialect)
                return Fluke28xDmm(transport)
        except Exception:  # noqa: BLE001
            pass

    dialect = "fluke-legacy" if _is_fluke_legacy(vendor, model) else "scpi"
    _cache_dialect(transport, dialect)
    return _DIALECTS[dialect](transport)


def _cache_dialect(transport: Transport, dialect: str) -> None:
    try:
        transport._dmm_dialect = dialect  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
