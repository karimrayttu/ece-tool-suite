"""Capacitor-bank sizing + loss for buck/boost input and output caps.

Standard switching-converter capacitor math (Erickson & Maksimovic; app-note practice) — the
value pecst offers, reimplemented from first principles so it is fully under our control and
verifiable, and fed from a candidate part rather than a fixed dielectric database:

  * RMS ripple current the cap must carry (topology- and location-dependent)
  * parallel-count needed to meet the ripple-current rating AND a target capacitance
  * ESR power loss (P = Irms^2 * ESR_bank) and per-cap temperature rise (P * Rth)
  * resulting output/input voltage ripple (ESR term + capacitive term)
  * voltage derating check per dielectric (MLCC/X7R 80%, tantalum 50%, ...)

Honesty boundary: a design starting point on the part you specify. RMS uses the standard
first-order model (input cap uses the dominant Iout*sqrt(D(1-D)) term; MLCC DC-bias capacitance
loss is NOT modelled — derate C from the part's bias curve). Confirm against the cap datasheet's
ripple-current-vs-frequency and bias curves, and a bench thermal check.
"""

from __future__ import annotations

import math

# fraction of rated voltage you should not exceed, by dielectric family
_DERATE = {"mlcc": 0.80, "x7r": 0.80, "x5r": 0.80, "ceramic": 0.80, "polymer": 0.90,
           "electrolytic": 0.80, "aluminum": 0.80, "tantalum": 0.50, "film": 0.60}


def _bank(irms_req: float, v_applied: float, ripple_pp: float, is_output: bool,
          fsw: float, c_each_uF: float, esr_each_mohm: float, irms_each_a: float,
          vrated: float, dielectric: str, rth_c_w: float | None,
          target_uF: float | None) -> dict:
    esr_each = esr_each_mohm * 1e-3
    n_ripple = math.ceil(irms_req / irms_each_a) if irms_each_a > 0 else 1
    n_cap = math.ceil(target_uF / c_each_uF) if target_uF and c_each_uF > 0 else 1
    n = max(1, n_ripple, n_cap)
    c_tot = c_each_uF * n
    esr_tot = esr_each / n
    p_loss = irms_req ** 2 * esr_tot
    dt = (p_loss / n) * rth_c_w if rth_c_w else None            # per-capacitor rise
    # ripple voltage: ESR (resistive) term + capacitive (charge) term
    if is_output:
        v_ripple = ripple_pp * esr_tot + ripple_pp / (8.0 * fsw * c_tot * 1e-6)
    else:                                                       # capacitive term dominates the input cap
        v_ripple = ripple_pp * esr_tot + irms_req / (fsw * c_tot * 1e-6) * 0.5
    derate = _DERATE.get(dielectric.lower(), 0.80)
    v_ok = v_applied <= vrated * derate
    ir_ok = irms_each_a > 0 and irms_req <= irms_each_a * n
    return {
        "rms_current_a": round(irms_req, 3),
        "parallel_count": n, "count_for_ripple": n_ripple, "count_for_capacitance": n_cap,
        "total_capacitance_uF": round(c_tot, 2), "total_esr_mohm": round(esr_tot * 1e3, 2),
        "esr_loss_w": round(p_loss, 4),
        "temp_rise_c": round(dt, 1) if dt is not None else None,
        "ripple_voltage_mvpp": round(v_ripple * 1e3, 2),
        "v_applied": round(v_applied, 2), "v_derated_limit": round(vrated * derate, 2),
        "derating_ok": bool(v_ok), "ripple_current_ok": bool(ir_ok),
        "ok": bool(v_ok and ir_ok),
    }


def size(topology: str, vin: float, vout: float, iout: float, fsw_khz: float = 500.0,
         il_ripple_pp_a: float | None = None,
         c_each_uF: float = 22.0, esr_each_mohm: float = 5.0, irms_each_a: float = 2.0,
         vrated: float = 25.0, dielectric: str = "mlcc", rth_c_w: float | None = 40.0,
         target_out_uF: float | None = None, target_in_uF: float | None = None) -> dict:
    """Size the input and output capacitor banks for a buck or boost stage, on a candidate cap."""
    t = "boost" if topology.lower().startswith("boost") else "buck"
    if vin <= 0 or vout <= 0 or iout <= 0 or fsw_khz <= 0:
        return {"ok": False, "error": "vin, vout, iout, fsw must be > 0"}
    fsw = fsw_khz * 1e3
    ripple = il_ripple_pp_a if il_ripple_pp_a and il_ripple_pp_a > 0 else 0.3 * iout

    if t == "buck":
        d = min(0.98, max(0.02, vout / vin))
        in_irms = iout * math.sqrt(d * (1 - d))                # classic buck input-cap RMS
        out_irms = ripple / math.sqrt(12.0)                    # triangular inductor ripple
        v_in, v_out_applied = vin, vout
    else:                                                       # boost
        d = min(0.98, max(0.02, 1.0 - vin / vout))
        in_irms = ripple / math.sqrt(12.0)                     # boost input = inductor current
        out_irms = iout * math.sqrt(d / (1 - d))               # pulsed diode current
        v_in, v_out_applied = vin, vout

    cap = dict(c_each_uF=c_each_uF, esr_each_mohm=esr_each_mohm, irms_each_a=irms_each_a,
               vrated=vrated, dielectric=dielectric, rth_c_w=rth_c_w)
    inp = _bank(in_irms, v_in, ripple, False, fsw, target_uF=target_in_uF, **cap)
    out = _bank(out_irms, v_out_applied, ripple, True, fsw, target_uF=target_out_uF, **cap)

    return {
        "ok": True, "topology": t, "duty_pct": round(d * 100, 2),
        "candidate": {"c_uF": c_each_uF, "esr_mohm": esr_each_mohm, "irms_a": irms_each_a,
                      "vrated": vrated, "dielectric": dielectric},
        "input_cap": inp, "output_cap": out,
        "note": "First-order sizing on the candidate cap. MLCC DC-bias capacitance loss not modelled "
                "— derate C from the part's bias curve; verify ripple-current rating vs frequency and "
                "check temperature on the bench.",
    }
