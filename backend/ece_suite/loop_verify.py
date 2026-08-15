"""Closed-loop stability verification of the compensator, using python-control.

The native designer (`power_designer.compensation`) produces a type-II network as an *open-loop
starting point* — it targets a phase margin but never computes the achieved one. This module
closes that gap: it builds the small-signal loop gain T(s) = plant(s) x compensator(s) x divider
for a **peak current-mode buck** (the topology the type-II network is designed for) and asks
python-control for the ACHIEVED crossover, phase margin and gain margin, then PASS/FAILs them.

Honesty boundaries (per the EE guardrails — this is a starting-point check, not a bench result):
  * The plant is the standard low-frequency current-mode model (single dominant load pole, ESR
    zero, one high-frequency sampling pole at fsw/2). It is NOT the full Ridley sampled-data model
    and does not include slope-compensation or subharmonic (Q-peaking) effects.
  * The current-mode DC gain needs the controller's current-sense transresistance Ri and the
    feedback reference Vref — both IC-specific. Sensible defaults are used and RETURNED so they
    can be refined against the datasheet. Treat the margins as a design-review sanity check, then
    confirm on the bench (or a full closed-loop AC sim) before trusting a loop.
"""

from __future__ import annotations

import math


def _available() -> bool:
    try:
        import control  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def verify(vin: float, vout: float, iout: float, L_uH: float, Cout_uF: float,
           fsw_khz: float = 500.0, esr_mohm: float = 10.0, ri_ohm: float = 0.1,
           vref_v: float = 0.8, gm_ea_uA_V: float = 1000.0,
           pm_min_deg: float = 45.0, gm_min_db: float = 6.0) -> dict:
    """Build the current-mode buck loop with the designed type-II comp and return real margins."""
    if not _available():
        return {"ok": False, "error": "python-control not installed", "install": "pip install control"}
    import control

    from . import power_designer

    if iout <= 0 or vout <= 0 or Cout_uF <= 0 or L_uH <= 0:
        return {"ok": False, "error": "vout, iout, L and Cout must be > 0"}

    comp = power_designer.compensation(vin, vout, iout, L_uH, Cout_uF, fsw_khz,
                                       esr_mohm=esr_mohm, gm_ea_uA_V=gm_ea_uA_V)
    rc = float(comp["type2"]["Rc_ohm"])
    cc1 = float(comp["type2"]["Cc1_nF"]) * 1e-9
    cc2 = max(float(comp["type2"]["Cc2_pF"]) * 1e-12, 1e-15)

    rload = vout / iout
    cout = Cout_uF * 1e-6
    esr = esr_mohm * 1e-3
    fsw = fsw_khz * 1e3
    gm = gm_ea_uA_V * 1e-6
    hdiv = vref_v / vout                       # feedback divider ratio Vfb/Vout

    s = control.tf("s")

    # --- power stage: peak current-mode control-to-output ---
    wp1 = 1.0 / (rload * cout)                 # dominant load pole
    wp2 = 2 * math.pi * (fsw / 2.0)            # sampling / high-frequency pole
    gcm0 = rload / ri_ohm                       # current-mode DC gain (V/V)
    plant = gcm0 / ((1 + s / wp1) * (1 + s / wp2))
    if esr > 0:
        wz_esr = 1.0 / (esr * cout)
        plant = plant * (1 + s / wz_esr)

    # --- type-II transconductance compensator: vc/vsense = gm * Zc(s) ---
    cpar = cc1 * cc2 / (cc1 + cc2)
    zc = (1 + s * rc * cc1) / (s * (cc1 + cc2) * (1 + s * rc * cpar))
    comp_tf = gm * zc

    loop = plant * comp_tf * hdiv              # open-loop gain T(s)

    gain_margin, phase_margin, _wcg, wcp = (float(x) for x in control.margin(loop))
    fc = (wcp / (2 * math.pi)) if math.isfinite(wcp) and wcp > 0 else None
    pm = phase_margin if math.isfinite(phase_margin) else None
    # No -180 deg crossing -> control returns inf: gain margin is (effectively) infinite = healthy.
    if math.isinf(gain_margin):
        gm_db, gm_infinite = None, True
    elif gain_margin > 0:
        gm_db, gm_infinite = 20 * math.log10(gain_margin), False
    else:
        gm_db, gm_infinite = None, False

    # --- Bode data for the UI (downsampled) ---
    omega = [10 ** (i / 6.0) for i in range(6, 6 * 7)]     # ~10 rad/s .. 1e6 rad/s
    mag, phase, _ = control.frequency_response(loop, omega)
    try:                                                    # control returns arrays
        mag = list(mag); phase = list(phase)
    except TypeError:
        mag = [mag]; phase = [phase]
    bode = [{"f_hz": round(w / (2 * math.pi), 2),
             "mag_db": round(float(20 * math.log10(abs(m))) if abs(m) > 0 else -200.0, 2),
             "phase_deg": round(float(p) * 180.0 / math.pi, 2)}
            for w, m, p in zip(omega, mag, phase)]

    def chk(name: str, val: float | None, limit: float, unit: str, *, force_pass: bool = False) -> dict:
        ok = force_pass or (val is not None and val >= limit)
        return {"name": name, "value": None if val is None else round(float(val), 2),
                "cmp": ">=", "limit": limit, "unit": unit, "pass": bool(ok)}

    checks = [
        chk("Phase margin", pm, pm_min_deg, "deg"),
        chk("Gain margin", gm_db, gm_min_db, "dB", force_pass=gm_infinite),
    ]
    stable = all(c["pass"] for c in checks) and fc is not None

    return {
        "ok": True, "engine": "python-control", "topology": "buck (current-mode)",
        "stable": bool(stable),
        "metrics": {"crossover_hz": round(float(fc), 1) if fc else None,
                    "phase_margin_deg": None if pm is None else round(float(pm), 1),
                    "gain_margin_db": None if gm_db is None else round(float(gm_db), 1),
                    "gain_margin_infinite": gm_infinite,
                    "target_crossover_hz": comp["crossover_hz"]},
        "checks": checks,
        "compensation": comp,
        "assumptions": {"ri_ohm": ri_ohm, "vref_v": vref_v, "gm_ea_uA_V": gm_ea_uA_V,
                        "esr_mohm": esr_mohm, "hf_pole_hz": round(fsw / 2.0, 1)},
        "bode": bode,
        "note": "Current-mode buck loop with the designed type-II comp. Ri and Vref are IC-specific "
                "modeling assumptions (shown above) — refine from the datasheet, then confirm on the "
                "bench or a full closed-loop AC sim. Not a substitute for measured margin.",
    }
