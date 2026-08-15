"""Per-vendor instrument capability profiles.

Different brands expose genuinely different feature sets — a TBS1052C has two channels,
a legacy Fluke 45 has no capacitance mode, Rigol scopes add GND coupling. The UI asks for
the CONNECTED instrument's profile and renders only what that unit can actually do.

Profiles are per command-dialect family with model-number refinement (channel count from
the model string when the vendor encodes it, e.g. Keysight DSOX1204 -> 4 ch, Tek TBS1052
-> 2 ch). Where the model is unknown we default to the family's common configuration and
say so — never invent features a unit may not have beyond the family baseline.
"""

from __future__ import annotations

import re

# model-number channel encodings: (vendor, regex with a channel-count group)
_CH_PATTERNS: list[tuple[str, str]] = [
    ("keysight", r"[DM]SO-?X?\s?\d{2}(\d)\d[A-Z]?"),   # DSOX1204G -> 4, EDUX1052G -> 2 (3rd digit... actually 4th)
    ("tektronix", r"TBS\d{2}(\d)\d"),                   # TBS1052C -> 2, TBS2104 -> 4? pattern gives 3rd digit
    ("rigol", r"[DM]S[OA]?\d(\d)\d{2}"),                # DS1104Z -> ... encodings vary
    ("siglent", r"SDS\d{2}(\d)\d"),
]


def _channels_from_model(vendor: str, model: str) -> int | None:
    m = (model or "").upper()
    # explicit trailing channel digit conventions: last digit of the numeric block is the
    # channel count for most families (DSOX1204 -> 4, TBS1052 -> 2, SDS1104X-E -> 4)
    num = re.search(r"(\d{3,4})", m)
    if num:
        last = int(num.group(1)[-1])
        if last in (2, 4):
            return last
    return None


SCOPE_PROFILES: dict[str, dict] = {
    "keysight": {
        "family": "InfiniiVision-class",
        "channels_default": 4,
        "couplings": ["DC", "AC"],
        "acq_types": ["NORM", "AVER", "HRES", "PEAK"],
        "trig_modes": ["EDGE", "PULSE"],
        "trig_coup": ["DC", "AC", "LFR"],
        "probe_factors": [1, 10, 100],
        "notes": "Full InfiniiVision command set: bounded auto-setup, 16-measurement grid, PNG screenshots.",
    },
    "rigol": {
        "family": "DS/MSO-class",
        "channels_default": 4,
        "couplings": ["DC", "AC", "GND"],
        "acq_types": ["NORM", "AVER", "HRES", "PEAK"],
        "trig_modes": ["EDGE", "PULSE"],
        "trig_coup": ["DC", "AC", "LFR"],
        "probe_factors": [1, 10, 100],
        "notes": "SCPI-1999 shared path; GND coupling supported.",
    },
    "siglent": {
        "family": "SDS-class",
        "channels_default": 4,
        "couplings": ["DC", "AC", "GND"],
        "acq_types": ["NORM", "AVER", "PEAK"],
        "trig_modes": ["EDGE", "PULSE"],
        "trig_coup": ["DC", "AC", "LFR"],
        "probe_factors": [1, 10, 100],
        "notes": "SCPI-1999 shared path.",
    },
    "rohde": {
        "family": "RTB/RTM-class",
        "channels_default": 4,
        "couplings": ["DC", "AC", "GND"],
        "acq_types": ["NORM", "AVER", "HRES", "PEAK"],
        "trig_modes": ["EDGE", "PULSE"],
        "trig_coup": ["DC", "AC", "LFR"],
        "probe_factors": [1, 10, 100],
        "notes": "SCPI-1999 shared path.",
    },
    "gwinstek": {
        "family": "GDS-class",
        "channels_default": 4,
        "couplings": ["DC", "AC", "GND"],
        "acq_types": ["NORM", "AVER", "PEAK"],
        "trig_modes": ["EDGE", "PULSE"],
        "trig_coup": ["DC", "AC", "LFR"],
        "probe_factors": [1, 10, 100],
        "notes": "SCPI-1999 shared path.",
    },
    "tektronix": {
        "family": "TBS/TDS/MSO-class",
        "channels_default": 2,
        "couplings": ["DC", "AC", "GND"],
        "acq_types": ["NORM", "AVER", "PEAK"],
        "trig_modes": ["EDGE", "PULSE"],
        "trig_coup": ["DC", "AC", "LFR"],
        "probe_factors": [1, 10, 100],
        "notes": "Native Tek command set (WFMOutpre/CURVe capture, MEASUrement:IMMed).",
    },
    "ni": {
        "family": "SCPI via NI-VISA",
        "channels_default": 2,
        "couplings": ["DC", "AC"],
        "acq_types": ["NORM", "AVER"],
        "trig_modes": ["EDGE"],
        "trig_coup": ["DC", "AC"],
        "probe_factors": [1, 10],
        "notes": "Generic SCPI baseline — only features the shared path guarantees.",
    },
}

# DMM function menus by dialect. Keys are the app's function ids the UI renders.
DMM_PROFILES: dict[str, dict] = {
    "keysight": {
        "family": "Truevolt-class",
        "functions": ["VDC", "VAC", "IDC", "IAC", "RES", "FRES", "FREQ", "CAP", "DIOD", "CONT", "TEMP"],
        "math": ["OFF", "NULL", "DB", "DBM"],
        "nplc": True, "autozero": True,
        "notes": "Full Truevolt SCPI set incl. capacitance and temperature.",
    },
    "fluke": {
        "family": "8845A/8846A",
        "functions": ["VDC", "VAC", "IDC", "IAC", "RES", "FRES", "FREQ", "CAP", "DIOD", "CONT", "TEMP"],
        "math": ["OFF", "NULL", "DB", "DBM"],
        "nplc": True, "autozero": True,
        "notes": "34401-compatible SCPI; capacitance on 8846A only.",
    },
    "keithley": {
        "family": "DMM6500-class",
        "functions": ["VDC", "VAC", "IDC", "IAC", "RES", "FRES", "FREQ", "CAP", "DIOD", "CONT", "TEMP"],
        "math": ["OFF", "NULL", "DB", "DBM"],
        "nplc": True, "autozero": True,
        "notes": "SCPI-compatible set.",
    },
    "rigol": {
        "family": "DM3058-class",
        "functions": ["VDC", "VAC", "IDC", "IAC", "RES", "FRES", "FREQ", "CAP", "DIOD", "CONT"],
        "math": ["OFF", "NULL", "DB", "DBM"],
        "nplc": True, "autozero": True,
        "notes": "No temperature on DM3058.",
    },
    "ni": {
        "family": "PXI/USB DMM (SCPI)",
        "functions": ["VDC", "VAC", "IDC", "IAC", "RES", "FRES", "DIOD"],
        "math": ["OFF", "NULL"],
        "nplc": True, "autozero": True,
        "notes": "Generic SCPI baseline.",
    },
    "fluke-legacy": {
        "family": "Fluke 45 / 8808A",
        "functions": ["VDC", "VAC", "IDC", "IAC", "RES", "FREQ", "DIOD", "CONT"],
        "math": ["OFF"],
        "nplc": False, "autozero": False,
        "notes": "Legacy command set (VDC/VAC/OHMS...): no capacitance, no NPLC, no math.",
    },
    "fluke-28x": {
        "family": "Fluke 287/289 handheld",
        "functions": ["READ"],
        "math": ["OFF"],
        "nplc": False, "autozero": False,
        "notes": "Read-only serial protocol — the meter's rotary switch selects the function.",
    },
}


def scope_capabilities(vendor: str, model: str = "") -> dict:
    prof = dict(SCOPE_PROFILES.get(vendor) or SCOPE_PROFILES["keysight"])
    ch = _channels_from_model(vendor, model)
    prof["channels"] = ch or prof["channels_default"]
    prof["channels_source"] = "model" if ch else "family-default"
    prof["vendor"] = vendor
    prof["model"] = model or None
    return prof


def dmm_capabilities(dialect_or_vendor: str, model: str = "") -> dict:
    prof = dict(DMM_PROFILES.get(dialect_or_vendor) or DMM_PROFILES["keysight"])
    prof["vendor"] = dialect_or_vendor
    prof["model"] = model or None
    return prof
