"""Vendor identification — map a ``*IDN?`` response to a canonical bench-instrument vendor
and the SCPI dialect its drivers should speak.

Most modern bench instruments are SCPI-1999 compliant, so a single Keysight-style driver
covers Keysight/Agilent, Rigol, Siglent and Rohde & Schwarz for the operations this app uses
(waveform preamble + IEEE block, ``:CHANx:SCAL``, ``:TIM:SCAL``, ``:TRIG:EDGE``, ``:MEAS:*``).
Tektronix uses a different waveform/measurement command set, so it gets its own driver.
"""

from __future__ import annotations

from .scpi import IdnInfo, parse_idn

# canonical vendor key -> (display name, marker substrings found in *IDN? vendor field)
_VENDORS: list[tuple[str, str, tuple[str, ...]]] = [
    ("keysight", "Keysight", ("KEYSIGHT", "AGILENT", "HEWLETT", "HP ")),
    ("tektronix", "Tektronix", ("TEKTRONIX", "TEK ")),
    ("lecroy", "Teledyne LeCroy", ("LECROY", "TELEDYNE")),
    ("keithley", "Keithley", ("KEITHLEY",)),
    ("rigol", "Rigol", ("RIGOL",)),
    ("siglent", "Siglent", ("SIGLENT", "ATTEN")),
    ("rohde", "Rohde & Schwarz", ("ROHDE", "R&S", "HAMEG", "RS ")),
    ("fluke", "Fluke", ("FLUKE",)),
    ("bk", "B&K Precision", ("B&K", "BK PRECISION", "BK ")),
    ("ni", "National Instruments", ("NATIONAL INSTRUMENTS", "NI ")),
    ("gwinstek", "GW Instek", ("GW INSTEK", "GWINSTEK", "GOOD WILL")),
    ("yokogawa", "Yokogawa", ("YOKOGAWA",)),
    ("owon", "OWON", ("OWON", "FUJIAN LILLIPUT", "LILLIPUT")),
    ("aimtti", "Aim-TTi", ("AIM", "THURLBY", "TTI ")),
    ("chroma", "Chroma", ("CHROMA",)),
    ("kikusui", "Kikusui", ("KIKUSUI",)),
    ("itech", "ITECH", ("ITECH",)),
    ("pico", "Pico Technology", ("PICO TECH", "PICO ")),
    ("hantek", "Hantek", ("HANTEK",)),
]

# Vendors whose scope/AWG/SA speak the InfiniiVision-compatible SCPI our Keysight driver uses.
_SCPI_1999_SCOPE = {"keysight", "rigol", "siglent", "rohde", "gwinstek"}


def canonical_vendor(vendor_field: str) -> str:
    """Return the canonical vendor key for a raw ``*IDN?`` vendor field (``"unknown"`` if none)."""
    v = (vendor_field or "").upper()
    for key, _name, markers in _VENDORS:
        if any(m in v for m in markers):
            return key
    return "unknown"


def vendor_display(key: str) -> str:
    for k, name, _ in _VENDORS:
        if k == key:
            return name
    return "Unknown"


def scope_dialect(vendor_key: str) -> str:
    """Which scope driver to use: ``"tektronix"`` or ``"keysight"`` (the SCPI-1999 default)."""
    if vendor_key == "tektronix":
        return "tektronix"
    return "keysight"


# Per-role vendor menu shown in the UI. `dialect` names the driver path a choice maps to,
# so the picker is honest about what actually changes: the command set spoken, nothing else.
SUPPORTED_BY_ROLE: dict[str, list[dict]] = {
    "scope": [
        {"id": "auto", "name": "Auto-detect (*IDN?)", "dialect": "auto"},
        {"id": "keysight", "name": "Keysight / Agilent InfiniiVision", "dialect": "keysight"},
        {"id": "rigol", "name": "Rigol DS/MSO", "dialect": "keysight"},
        {"id": "siglent", "name": "Siglent SDS", "dialect": "keysight"},
        {"id": "rohde", "name": "Rohde & Schwarz RTB/RTM", "dialect": "keysight"},
        {"id": "gwinstek", "name": "GW Instek GDS", "dialect": "keysight"},
        {"id": "tektronix", "name": "Tektronix TBS/TDS/MSO", "dialect": "tektronix"},
        {"id": "ni", "name": "NI (SCPI via NI-VISA)", "dialect": "keysight"},
    ],
    "dmm": [
        {"id": "auto", "name": "Auto-detect (*IDN? / Fluke ID)", "dialect": "auto"},
        {"id": "keysight", "name": "Keysight Truevolt 34460A-class", "dialect": "scpi"},
        {"id": "fluke", "name": "Fluke 8845A/8846A (SCPI)", "dialect": "scpi"},
        {"id": "fluke-legacy", "name": "Fluke 45 / 8808A (legacy VDC/VAC)", "dialect": "fluke-legacy"},
        {"id": "fluke-28x", "name": "Fluke 287/289 handheld (serial)", "dialect": "fluke-28x"},
        {"id": "keithley", "name": "Keithley DMM6500-class (SCPI)", "dialect": "scpi"},
        {"id": "rigol", "name": "Rigol DM3058-class (SCPI)", "dialect": "scpi"},
        {"id": "ni", "name": "NI 4065-class (SCPI via NI-VISA)", "dialect": "scpi"},
    ],
    "sa": [
        {"id": "auto", "name": "Auto-detect (*IDN?)", "dialect": "auto"},
        {"id": "keysight", "name": "Keysight N9000-class", "dialect": "keysight"},
        {"id": "rigol", "name": "Rigol DSA/RSA", "dialect": "keysight"},
        {"id": "siglent", "name": "Siglent SSA/SVA", "dialect": "keysight"},
        {"id": "rohde", "name": "Rohde & Schwarz FPC/FPH", "dialect": "keysight"},
    ],
    "psu": [
        {"id": "auto", "name": "Auto-detect (*IDN?)", "dialect": "auto"},
        {"id": "keysight", "name": "Keysight E36xxx", "dialect": "scpi"},
        {"id": "rigol", "name": "Rigol DP800/DP900", "dialect": "scpi"},
        {"id": "siglent", "name": "Siglent SPD", "dialect": "scpi"},
        {"id": "bk", "name": "B&K Precision 9100-class", "dialect": "scpi"},
        {"id": "rohde", "name": "R&S NGE/NGL", "dialect": "scpi"},
    ],
    "awg": [
        {"id": "auto", "name": "Auto-detect (*IDN?)", "dialect": "auto"},
        {"id": "keysight", "name": "Keysight 33500-class", "dialect": "scpi"},
        {"id": "rigol", "name": "Rigol DG800/DG1000Z", "dialect": "scpi"},
        {"id": "siglent", "name": "Siglent SDG", "dialect": "scpi"},
    ],
    "eload": [
        {"id": "auto", "name": "Auto-detect (*IDN?)", "dialect": "auto"},
        {"id": "keysight", "name": "Keysight EL30000-class", "dialect": "scpi"},
        {"id": "rigol", "name": "Rigol DL3000", "dialect": "scpi"},
        {"id": "siglent", "name": "Siglent SDL1000X", "dialect": "scpi"},
        {"id": "itech", "name": "ITECH IT8500-class", "dialect": "scpi"},
    ],
}


def identify(transport) -> tuple[IdnInfo, str]:
    """Query ``*IDN?`` and return ``(IdnInfo, canonical_vendor_key)``."""
    try:
        idn = parse_idn(transport.query("*IDN?"))
    except Exception:  # noqa: BLE001
        idn = parse_idn("")
    return idn, canonical_vendor(idn.vendor)


# USB vendor IDs for bench test instruments, so a plugged-in device can be named even when no
# VISA/driver is installed yet (VID read from the Windows PnP tree). Vendor-agnostic USBTMC
# class detection (io_env) is the backstop for any instrument not in this table.
VENDOR_VIDS: dict[int, str] = {
    0x2A8D: "keysight", 0x0957: "keysight",     # Keysight / Agilent
    0x0699: "tektronix",
    0x05E6: "keithley",                          # Keithley (now Tektronix)
    0x1AB1: "rigol",
    0xF4EC: "siglent", 0x1AB2: "siglent",
    0x0AAD: "rohde",                             # Rohde & Schwarz / Hameg
    0x2184: "gwinstek",
    0x3923: "ni", 0x1093: "ni",                 # National Instruments
    0x0F7E: "fluke",
    0x0B21: "yokogawa",
    0x5345: "owon",
    0x103E: "aimtti", 0x20CE: "aimtti",         # Aim-TTi / Thurlby Thandar
    0x1698: "chroma",
    0x0CE9: "pico",                             # Pico Technology
    0x049F: "itech",
}


def vendor_for_vid(vid: int) -> str:
    return VENDOR_VIDS.get(vid, "unknown")


# Map a model string to the bench role it should drive (heuristic, by product-family prefix).
_ROLE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("scope", ("DSO", "MSO", "MXR", "DPO", "TDS", "MDO", "SDS", "HDO", "DHO", "EDUX",
               "DS1", "DS2", "DS4", "DS6", "DS7")),
    ("dmm", ("3446", "3440", "3441", "3447", "3455", "3457", "3458", "8845", "8846", "8808",
             "EDU34", "287", "289", "DM30", "DM31", "DM32", "DM40", "SDM", "TRUEVOLT", "34401")),
    ("sa", ("N90", "N99", "CXA", "EXA", "PXA", "MXA", "UXA", "FIELDFOX", "RSA", "FSV", "FSW",
            "FPC", "SSA", "SVA", "SA815")),
    ("psu", ("E36", "EDU36", "N67", "N57", "N87", "N69", "SPD", "SPS", "DP7", "DP8", "DP9",
             "PWS", "PPS", "72-")),
    ("awg", ("335", "336", "EDU33", "AFG", "DG1", "DG2", "DG4", "DG5", "SDG", "33500", "33600")),
    ("eload", ("N33", "N36", "EL34", "IT85", "IT88", "DL30", "DL31", "SDL", "63")),
]


def classify_role(model: str) -> str | None:
    """Best-effort bench role for an instrument model (scope/dmm/sa/psu/awg/eload)."""
    m = (model or "").upper().replace(" ", "")
    for role, prefixes in _ROLE_PATTERNS:
        if any(p in m for p in prefixes):
            return role
    return None
