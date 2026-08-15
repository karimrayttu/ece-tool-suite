"""Magnetics design + loss analysis via OpenMagnetics (PyOpenMagnetics / MKF).

Fills the hole the native power designer leaves: given an inductance and its current waveform,
the MKF engine searches a real multi-vendor core/material/wire database, picks a core + gap +
winding, and computes physics-grade core and copper losses (Steinmetz/iGSE, skin/proximity) —
things textbook L/C formulas cannot give.

Version note: the high-level converter->magnetics pipeline (`design_magnetics_from_converter` /
`process_converter`) is broken in the pinned wheel (1.6.1) — it raises "key 'designRequirements'
not found". We deliberately bypass it and drive the adviser directly with a hand-built MAS
`Inputs` (validated working), so this module does not depend on that path.

Honesty boundary: results are datasheet-grade magnetics math on real catalog parts, but they are
a *design starting point* — confirm the chosen core's saturation/thermal margin against its
datasheet and, ideally, a bench thermal measurement before committing.
"""

from __future__ import annotations

import math

_DEFAULT_MODE = "standard cores"   # datasheet-fit catalog (per the ignore-stock rule); faster than "available cores"


def _om():
    """Return the PyOpenMagnetics module, or None if it is not importable."""
    try:
        import PyOpenMagnetics as om  # noqa: N813
        return om
    except Exception:  # noqa: BLE001
        return None


def available() -> bool:
    return _om() is not None


def db_summary() -> dict:
    """Sizes of the bundled multi-vendor database — proves what the engine can pick from."""
    om = _om()
    if om is None:
        return {"available": False, "install": "pip install PyOpenMagnetics"}
    try:
        materials = om.get_core_material_names()
        shapes = om.get_core_shape_names(True)
        manufacturers = om.get_available_core_manufacturers()
        wires = om.get_available_wires()
        return {
            "available": True, "engine": "OpenMagnetics / MKF",
            "core_materials": len(materials), "core_shapes": len(shapes),
            "core_manufacturers": manufacturers if isinstance(manufacturers, list) else [],
            "wires": len(wires) if isinstance(wires, list) else None,
            "mode": _DEFAULT_MODE,
        }
    except Exception as e:  # noqa: BLE001
        return {"available": True, "error": str(e)}


def _num(v):
    """Pull a scalar out of a MKF value that may be a bare number or a {nominal|maximum|...} dict."""
    if isinstance(v, dict):
        for k in ("nominal", "maximum", "value", "minimum"):
            if v.get(k) is not None:
                return v[k]
        return None
    return v


def _name(v):
    return v.get("name") if isinstance(v, dict) else v


def _one(design: dict) -> dict:
    """Flatten one MKF design entry {mas, scoring, ...} into a clean summary dict."""
    mas = design["mas"]
    core = mas["magnetic"]["core"]["functionalDescription"]
    coil = mas["magnetic"]["coil"]["functionalDescription"]
    outs = mas.get("outputs") or []
    o0 = outs[0] if outs else {}

    gaps_mm = [round(float(g["length"]) * 1e3, 3) for g in core.get("gapping", []) if g.get("length")]
    core_loss = _num((o0.get("coreLosses") or {}).get("coreLosses"))
    wdg_loss = _num((o0.get("windingLosses") or {}).get("windingLosses"))
    ind = _num((o0.get("inductance") or {}).get("magnetizingInductance")) if isinstance(o0.get("inductance"), dict) else None
    temp = _num(o0.get("temperature"))

    def _w(x):
        return round(float(x), 4) if isinstance(x, (int, float)) else None

    total = None
    if isinstance(core_loss, (int, float)) and isinstance(wdg_loss, (int, float)):
        total = round(float(core_loss) + float(wdg_loss), 4)

    return {
        "core_shape": _name(core.get("shape")),
        "core_material": _name(core.get("material")),
        "gap_mm": gaps_mm[0] if gaps_mm else None,
        "turns": [w.get("numberTurns") for w in coil],
        "core_loss_w": _w(core_loss),
        "winding_loss_w": _w(wdg_loss),
        "total_loss_w": total,
        "inductance_uH": round(float(ind) * 1e6, 2) if isinstance(ind, (int, float)) else None,
        "temperature_rise_c": round(float(temp), 1) if isinstance(temp, (int, float)) else None,
        "score": round(float(design["scoring"]), 3) if isinstance(design.get("scoring"), (int, float)) else None,
    }


def advise_inductor(inductance_uH: float, i_dc: float, i_ripple_pp: float, fsw_khz: float = 500.0,
                    ambient_c: float = 25.0, duty: float = 0.5, n_results: int = 3,
                    mode: str = _DEFAULT_MODE) -> dict:
    """Search the real core/wire DB for an inductor of `inductance_uH` carrying a DC-biased
    triangular current (offset i_dc, peak-peak ripple i_ripple_pp) at fsw, and return the top-N
    core+winding designs with computed core/copper losses.
    """
    om = _om()
    if om is None:
        return {"ok": False, "error": "PyOpenMagnetics not installed", "install": "pip install PyOpenMagnetics"}
    if inductance_uH <= 0 or i_dc < 0 or fsw_khz <= 0:
        return {"ok": False, "error": "inductance, current and fsw must be positive"}

    i_peak = i_dc + i_ripple_pp / 2.0
    i_rms = math.sqrt(i_dc ** 2 + (i_ripple_pp ** 2) / 12.0)     # DC + triangular ripple
    inputs = {
        "designRequirements": {"magnetizingInductance": {"nominal": inductance_uH * 1e-6},
                               "name": "L", "turnsRatios": []},
        "operatingPoints": [{
            "name": "op", "conditions": {"ambientTemperature": ambient_c},
            "excitationsPerWinding": [{
                "frequency": fsw_khz * 1e3,
                "current": {"processed": {"label": "Triangular", "offset": i_dc, "peak": i_peak,
                                          "peakToPeak": i_ripple_pp, "rms": i_rms,
                                          "dutyCycle": max(0.01, min(0.99, duty))}}}]}],
    }
    try:
        res = om.calculate_advised_magnetics(inputs, max(1, min(n_results, 8)), mode)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"MKF adviser failed: {e}"}
    if isinstance(res, dict) and "data" in res:
        data = res["data"]
        if isinstance(data, str):                                # MKF wraps some errors as {"data": "Exception: ..."}
            return {"ok": False, "error": data}
    else:
        data = res if isinstance(res, list) else []
    if not data:
        return {"ok": False, "error": "no core in the catalog satisfied the requirement (try mode='available cores')"}

    designs = []
    for d in data:
        try:
            designs.append(_one(d))
        except Exception:  # noqa: BLE001 — skip a malformed entry rather than failing the whole call
            continue
    return {
        "ok": True, "engine": "OpenMagnetics / MKF", "mode": mode,
        "requirement": {"inductance_uH": inductance_uH, "i_dc_a": round(i_dc, 3),
                        "i_peak_a": round(i_peak, 3), "i_rms_a": round(i_rms, 3),
                        "ripple_pp_a": round(i_ripple_pp, 3), "fsw_khz": fsw_khz},
        "designs": designs,
        "note": "Real catalog cores (multi-vendor) with MKF-computed core + copper losses. Starting "
                "point — verify the chosen core's saturation & thermal margin against its datasheet.",
    }
