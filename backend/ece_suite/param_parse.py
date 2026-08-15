"""Unit-aware component-value normalizer (jlcparts `attributes.py` pattern, reimplemented).

Turns the free-text parametric strings vendors ship ("4.7µF", "10 mΩ", "2.5 A", "6.3V", "±10%",
and the engineering "4k7" / "4R7" / "1M5" forms) into typed {value, unit} in SI base units, so
parts become numerically filterable and comparable. This is the portable, high-value slice of
jlcparts — the parametric normalization — with NO stock/price/availability (per the ignore-stock
rule) and no dependency on the multi-hundred-MB LCSC catalog.

Use `load_external()` to fold a large normalized catalog you built yourself (e.g. exported from a
jlcparts SQLite) into the parts search; the format is deliberately generic so it is not tied to
any one vendor schema.
"""

from __future__ import annotations

import re

# SI prefix -> multiplier (µ/μ normalized to 'u'; 'K' folded to 'k')
_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "": 1.0,
           "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}
# canonical unit spellings
_UNIT = {"ohm": "Ω", "ohms": "Ω", "r": "Ω", "Ω": "Ω", "f": "F", "h": "H", "v": "V",
         "a": "A", "w": "W", "hz": "Hz", "s": "s", "%": "%"}
# engineering R/k/M "decimal-as-prefix" notation, mainly for resistors: 4k7, 4R7, 1M5, 0R01, 10R
_ENG = re.compile(r"^(\d+)([RrKkMmGup])(\d*)$")
_ENG_MULT = {"R": 1.0, "r": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
             "m": 1e-3, "u": 1e-6, "p": 1e-12}
_NUM = re.compile(r"^([+-]?\d*\.?\d+)\s*([pnuµμmkKMGT]?)\s*([A-Za-zΩ%]*)$")


def parse_value(text: str, default_unit: str | None = None) -> dict | None:
    """Parse one value string to {raw, value (SI base), unit, display}. None if unparseable."""
    if text is None:
        return None
    s = str(text).strip().replace("µ", "u").replace("μ", "u").replace("Ω", "ohm")
    if not s:
        return None

    m = _ENG.match(s)
    if m and (default_unit in (None, "Ω", "ohm") or m.group(2) in "Rr"):
        whole, letter, frac = m.group(1), m.group(2), m.group(3)
        val = float(f"{whole}.{frac}" if frac else whole) * _ENG_MULT.get(letter, 1.0)
        unit = "Ω" if letter in "Rr" or default_unit in ("Ω", "ohm") else (default_unit or "")
        return {"raw": text, "value": val, "unit": unit, "display": _fmt(val, unit)}

    m = _NUM.match(s)
    if not m:
        return None
    num, prefix, unit_raw = m.group(1), m.group(2), m.group(3).lower()
    prefix = "k" if prefix in ("k", "K") else prefix
    if prefix not in _PREFIX:
        return None
    value = float(num) * _PREFIX[prefix]
    unit = _UNIT.get(unit_raw, unit_raw) if unit_raw else (default_unit or "")
    if unit == "ohm":
        unit = "Ω"
    return {"raw": text, "value": value, "unit": unit, "display": _fmt(value, unit)}


def parse_tolerance(text: str) -> float | None:
    """'±10%' / '10%' / '1%' -> 0.10 / 0.10 / 0.01. None if no percent."""
    m = re.search(r"([\d.]+)\s*%", str(text))
    return round(float(m.group(1)) / 100.0, 6) if m else None


_ENG_PREFIXES = [(1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""),
                 (1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")]


def _fmt(value: float, unit: str) -> str:
    if value == 0:
        return f"0 {unit}".strip()
    av = abs(value)
    for mult, pre in _ENG_PREFIXES:
        if av >= mult:
            v = value / mult
            txt = f"{v:.3f}".rstrip("0").rstrip(".")
            return f"{txt} {pre}{unit}".strip()
    return f"{value:g} {unit}".strip()


# spec-key -> the unit those values should be read in (helps R/k/M notation + bare numbers)
_SPEC_UNIT = {"resistance": "Ω", "capacitance": "F", "inductance": "H", "voltage": "V",
              "vout": "V", "vin": "V", "vds": "V", "vr": "V", "iout": "A", "id": "A",
              "current": "A", "power": "W", "frequency": "Hz", "fmax": "Hz", "gbw": "Hz",
              "esr": "Ω", "tol": None}


def normalize_specs(specs: dict) -> dict:
    """Enrich a {key: 'string'} spec dict with typed values under the same keys + '<key>_value'."""
    out: dict = {}
    for k, v in (specs or {}).items():
        parsed = parse_value(v, default_unit=_SPEC_UNIT.get(k))
        if k == "tol":
            tol = parse_tolerance(v)
            if tol is not None:
                out["tol_fraction"] = tol
            continue
        if parsed:
            out[f"{k}_value"] = parsed["value"]
            out[f"{k}_unit"] = parsed["unit"]
            out[f"{k}_display"] = parsed["display"]
    return out
