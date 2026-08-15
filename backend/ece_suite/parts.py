"""Parts search — a provider abstraction.

Two providers: a built-in OFFLINE sample catalog (works with no keys, deterministic), and a
Nexar/Octopart adapter that is key-gated (returns a clear "configure keys" error when the
NEXAR_CLIENT_ID/SECRET env vars are absent or there is no network). This consolidates the
intent of nexar-mcp / pcbparts-mcp without bundling their heavy deps or API keys.
"""

from __future__ import annotations

import os

from . import param_parse

# A small, deterministic offline catalog (mpn, mfr, desc, category, package, price@1k, specs).
_CATALOG: list[dict] = [
    {"mpn": "RC0805FR-0710KL", "mfr": "Yageo", "desc": "RES 10k 1% 0805", "category": "resistor", "package": "0805", "price_1k": 0.002, "specs": {"resistance": "10k", "tol": "1%"}},
    {"mpn": "RC0603FR-074K7L", "mfr": "Yageo", "desc": "RES 4.7k 1% 0603", "category": "resistor", "package": "0603", "price_1k": 0.002, "specs": {"resistance": "4.7k", "tol": "1%"}},
    {"mpn": "CL10A106MQ8NNNC", "mfr": "Samsung", "desc": "CAP 10uF 6.3V X5R 0603", "category": "capacitor", "package": "0603", "price_1k": 0.01, "specs": {"capacitance": "10uF", "voltage": "6.3V"}},
    {"mpn": "CL10B104KB8NNNC", "mfr": "Samsung", "desc": "CAP 100nF 50V X7R 0603", "category": "capacitor", "package": "0603", "price_1k": 0.003, "specs": {"capacitance": "100nF", "voltage": "50V"}},
    {"mpn": "AMS1117-3.3", "mfr": "AMS", "desc": "LDO 3.3V 1A SOT-223", "category": "regulator", "package": "SOT-223", "price_1k": 0.08, "specs": {"vout": "3.3V", "iout": "1A"}},
    {"mpn": "TPS62840DLCR", "mfr": "TI", "desc": "Buck 1.8-6.5Vin 750mA SOT-563", "category": "regulator", "package": "SOT-563", "price_1k": 0.65, "specs": {"type": "buck", "iout": "750mA"}},
    {"mpn": "STM32H743ZIT6", "mfr": "ST", "desc": "MCU ARM Cortex-M7 480MHz LQFP-144", "category": "mcu", "package": "LQFP-144", "price_1k": 9.5, "specs": {"core": "M7", "fmax": "480MHz"}},
    {"mpn": "ESP32-WROOM-32E", "mfr": "Espressif", "desc": "WiFi+BT module", "category": "module", "package": "SMD-38", "price_1k": 2.2, "specs": {"wifi": "yes", "bt": "yes"}},
    {"mpn": "INA240A1PWR", "mfr": "TI", "desc": "Current-sense amp bidir TSSOP-8", "category": "amplifier", "package": "TSSOP-8", "price_1k": 1.1, "specs": {"type": "current-sense"}},
    {"mpn": "DRV8301", "mfr": "TI", "desc": "3-phase gate driver", "category": "gate-driver", "package": "HTSSOP-56", "price_1k": 3.4, "specs": {"phases": 3}},
    {"mpn": "IRLML6344TRPBF", "mfr": "Infineon", "desc": "N-MOSFET 30V 5A SOT-23", "category": "mosfet", "package": "SOT-23", "price_1k": 0.12, "specs": {"vds": "30V", "id": "5A"}},
    {"mpn": "1N4148WS", "mfr": "onsemi", "desc": "Diode 75V 150mA SOD-323", "category": "diode", "package": "SOD-323", "price_1k": 0.01, "specs": {"vr": "75V"}},
    {"mpn": "LMV321", "mfr": "TI", "desc": "Op-amp 1MHz SOT-23-5", "category": "amplifier", "package": "SOT-23-5", "price_1k": 0.09, "specs": {"gbw": "1MHz"}},
    {"mpn": "BME280", "mfr": "Bosch", "desc": "Temp/humidity/pressure sensor", "category": "sensor", "package": "LGA-8", "price_1k": 3.0, "specs": {"i2c": "yes"}},
    {"mpn": "TXB0104", "mfr": "TI", "desc": "4-bit level shifter", "category": "logic", "package": "TSSOP-14", "price_1k": 0.4, "specs": {"channels": 4}},
]


# optional big catalog folded in at runtime via load_external() — e.g. a normalized jlcparts export.
_EXTERNAL: list[dict] = []


def _enrich(p: dict) -> dict:
    """Attach typed parametric fields (SI base units) so specs are numerically filterable."""
    typed = param_parse.normalize_specs(p.get("specs", {}))
    return {**p, "specs_typed": typed} if typed else {**p, "specs_typed": {}}


def load_external(records: list[dict]) -> int:
    """Fold a large normalized catalog (list of {mpn, mfr, desc, category, specs}) into the search.

    Deliberately schema-generic (NOT tied to jlcparts' internal tables) so any exported catalog
    works; stock/price/availability are ignored per the ignore-stock rule. Returns count added.
    """
    added = 0
    for r in records or []:
        if not r.get("mpn"):
            continue
        _EXTERNAL.append({"mpn": r["mpn"], "mfr": r.get("mfr", ""), "desc": r.get("desc", ""),
                          "category": r.get("category", "other"), "package": r.get("package", ""),
                          "specs": r.get("specs", {}), "source": r.get("source", "external")})
        added += 1
    return added


def _match_range(p: dict, spec_key: str, vmin: float | None, vmax: float | None) -> bool:
    if vmin is None and vmax is None:
        return True
    val = p.get("specs_typed", {}).get(f"{spec_key}_value")
    if val is None:
        return False
    if vmin is not None and val < vmin:
        return False
    if vmax is not None and val > vmax:
        return False
    return True


def search_offline(query: str = "", category: str | None = None, limit: int = 20,
                   spec_key: str | None = None, vmin: float | None = None,
                   vmax: float | None = None) -> list[dict]:
    q = (query or "").lower()
    res = []
    for p in [_enrich(x) for x in (_CATALOG + _EXTERNAL)]:
        if category and p["category"] != category:
            continue
        if q and q not in p["mpn"].lower() and q not in p["desc"].lower() and q not in p["category"]:
            continue
        if spec_key and not _match_range(p, spec_key, vmin, vmax):
            continue
        res.append(p)
    return res[:limit]


class NexarProvider:
    def __init__(self) -> None:
        self.client_id = os.environ.get("NEXAR_CLIENT_ID")
        self.secret = os.environ.get("NEXAR_CLIENT_SECRET")

    def available(self) -> bool:
        return bool(self.client_id and self.secret)

    def search(self, query: str, limit: int = 20) -> list[dict]:
        if not self.available():
            raise RuntimeError(
                "Nexar live search requires NEXAR_CLIENT_ID and NEXAR_CLIENT_SECRET "
                "(free at nexar.com) plus network access."
            )
        # Live GraphQL call would go here; kept out of the offline build by design.
        raise RuntimeError("Nexar provider configured but live calls are disabled in this build.")


def status() -> dict:
    return {
        "offline_catalog": len(_CATALOG), "external_loaded": len(_EXTERNAL),
        "providers": {"offline": True, "nexar": NexarProvider().available()},
        "categories": sorted({p["category"] for p in (_CATALOG + _EXTERNAL)}),
    }


def parse_value(text: str, unit: str | None = None) -> dict:
    """Expose the normalizer: turn a value string into typed {value, unit, display}."""
    r = param_parse.parse_value(text, default_unit=unit)
    return r or {"raw": text, "value": None, "unit": unit or "", "display": None}


def search(query: str = "", category: str | None = None, limit: int = 20, provider: str = "offline",
           spec_key: str | None = None, vmin: float | None = None, vmax: float | None = None) -> dict:
    if provider == "nexar":
        return {"provider": "nexar", "results": NexarProvider().search(query, limit)}
    return {"provider": "offline",
            "results": search_offline(query, category, limit, spec_key, vmin, vmax)}
