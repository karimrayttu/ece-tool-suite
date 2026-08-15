"""Native WEBENCH-class power designer.

Given Vin/Vout/Iout, it recommends a topology, filters a curated database of real TI power ICs
that fit the envelope, sizes the passives for buck/boost/buck-boost/flyback/LDO, and gives a
loop-compensation starting point (power-stage poles/zeros + a type-II network). It feeds the
LTspice PASS/FAIL verifier (spice_verify) for buck/boost.

This reproduces WEBENCH's *design math* offline — it is not TI's exact optimizer or full part
database, and the compensation is a datasheet-refinable starting point, not a final value.
"""

from __future__ import annotations

import math

# --- curated real TI power ICs (approximate spec envelopes; verify against the datasheet) -----
TI_PARTS: list[dict] = [
    {"mpn": "TPS62840", "topo": "buck", "vin": (1.8, 6.5), "vout": (0.4, 6.5), "iout_max": 0.75, "fet": True, "note": "60 nA Iq buck"},
    {"mpn": "TPS62912", "topo": "buck", "vin": (3.0, 17.0), "vout": (0.6, 15.0), "iout_max": 2.0, "fet": True, "note": "low-noise buck"},
    {"mpn": "TPS62143", "topo": "buck", "vin": (3.0, 17.0), "vout": (0.9, 6.0), "iout_max": 2.0, "fet": True},
    {"mpn": "TPS54560", "topo": "buck", "vin": (4.5, 60.0), "vout": (0.8, 58.0), "iout_max": 5.0, "fet": True, "note": "60 V 5 A buck"},
    {"mpn": "TPS54360", "topo": "buck", "vin": (4.5, 60.0), "vout": (0.8, 58.0), "iout_max": 3.5, "fet": True, "note": "60 V 3.5 A buck"},
    {"mpn": "LM5116", "topo": "buck", "vin": (6.0, 100.0), "vout": (1.2, 80.0), "iout_max": 10.0, "fet": False, "note": "wide-Vin sync buck controller"},
    {"mpn": "TPS61088", "topo": "boost", "vin": (2.7, 12.0), "vout": (4.5, 12.6), "iout_max": 5.0, "fet": True, "note": "10 A switch boost"},
    {"mpn": "TPS61230", "topo": "boost", "vin": (2.3, 5.5), "vout": (5.0, 5.5), "iout_max": 2.0, "fet": True},
    {"mpn": "LM5155", "topo": "boost", "vin": (3.5, 45.0), "vout": (5.0, 60.0), "iout_max": 4.0, "fet": False, "note": "boost/flyback/SEPIC controller"},
    {"mpn": "TPS63070", "topo": "buck-boost", "vin": (2.0, 16.0), "vout": (2.5, 9.0), "iout_max": 2.0, "fet": True, "note": "buck-boost"},
    {"mpn": "TPS55288", "topo": "buck-boost", "vin": (2.7, 36.0), "vout": (0.8, 22.0), "iout_max": 8.0, "fet": True, "note": "wide buck-boost"},
    {"mpn": "LM5180", "topo": "flyback", "vin": (4.5, 65.0), "vout": (3.3, 24.0), "iout_max": 0.15, "fet": True, "note": "primary-side-reg flyback"},
    {"mpn": "UCC28742", "topo": "flyback", "vin": (10.0, 100.0), "vout": (3.3, 24.0), "iout_max": 2.0, "fet": False, "note": "flyback controller"},
    {"mpn": "TPS7A4700", "topo": "ldo", "vin": (3.0, 36.0), "vout": (1.4, 20.5), "iout_max": 1.0, "fet": True, "note": "36 V ultra-low-noise LDO"},
    {"mpn": "TLV75701", "topo": "ldo", "vin": (1.45, 5.5), "vout": (0.6, 5.0), "iout_max": 1.0, "fet": True, "note": "1 A LDO"},
    {"mpn": "LP5907", "topo": "ldo", "vin": (2.2, 5.5), "vout": (1.2, 4.5), "iout_max": 0.25, "fet": True, "note": "low-noise LDO"},
]


def recommend_topology(vin: float, vout: float, iout: float, isolated: bool = False) -> dict:
    """Pick a topology from the voltage relationship + a linear-vs-switcher heuristic.

    Isolation cannot be inferred from the electrical envelope, so it is an explicit input:
    isolated=True selects a transformer topology (flyback for the power levels this DB covers).
    """
    if isolated:
        pout = vout * iout
        return {"topology": "flyback", "reason": f"Galvanic isolation requested: flyback suits "
                f"{pout:.1f} W (transformer sets Vout via turns ratio; primary-side or opto feedback)."}
    if vout < vin * 0.9:
        dropout_w = (vin - vout) * iout
        if (vin - vout) <= 3.0 and iout <= 1.0 and dropout_w <= 1.5:
            return {"topology": "ldo", "reason": f"Small drop ({vin - vout:.1f} V) at low current — an LDO is simpler; {dropout_w:.2f} W dissipated."}
        return {"topology": "buck", "reason": f"Vout ({vout} V) < Vin ({vin} V): step down with a buck."}
    if vout > vin * 1.1:
        return {"topology": "boost", "reason": f"Vout ({vout} V) > Vin ({vin} V): step up with a boost."}
    return {"topology": "buck-boost", "reason": f"Vin ({vin} V) straddles Vout ({vout} V): use a buck-boost."}


def candidate_parts(topology: str, vin: float, vout: float, iout: float) -> list[dict]:
    out = []
    for p in TI_PARTS:
        if p["topo"] != topology:
            continue
        vlo, vhi = p["vin"]
        volo, vohi = p["vout"]
        if not (vlo <= vin <= vhi):
            continue
        if not (volo <= vout <= vohi):
            continue
        if p.get("iout_max") and iout > p["iout_max"]:
            continue
        out.append({"mpn": p["mpn"], "integrated_fet": p["fet"], "iout_max": p.get("iout_max"),
                    "note": p.get("note", ""), "datasheet": f"https://www.ti.com/product/{p['mpn']}"})
    return out


# --- passive sizing per topology -----------------------------------------
def size_stage(topology: str, vin: float, vout: float, iout: float, fsw_khz: float = 500.0,
               ripple_pct: float = 30.0, theta_ja: float = 40.0, ambient_c: float = 25.0) -> dict:
    fsw = fsw_khz * 1e3
    if topology == "ldo":
        pd = (vin - vout) * iout
        return {"topology": "ldo", "dropout_ok": (vin - vout) >= 0.3,
                "power_dissipation_w": round(pd, 3), "tj_c": round(ambient_c + pd * theta_ja, 1),
                "note": "no inductor; check dropout + thermal (Tj = Ta + Pd·θJA)."}
    if topology == "boost":
        from . import design_tools
        s = design_tools.boost_stage(vin, vout, iout, fsw_khz, ripple_pct)
        s["output_cap_uF"] = s.pop("output_cap_uF_for_1pct", None)
        return s
    if topology == "buck-boost":
        d = vout / (vin + vout)
        iin = iout / (1 - d)
        il_avg = iin + iout               # inductor carries both
        di = ripple_pct / 100.0 * il_avg
        L = (vin * d) / (fsw * di) if di > 0 else float("inf")
        cout = (iout * d) / (fsw * 0.01 * vout) if vout > 0 else 0.0
        return {"topology": "buck-boost", "duty_pct": round(d * 100, 2),
                "inductor_uH": round(L * 1e6, 3), "avg_inductor_current_A": round(il_avg, 3),
                "output_cap_uF": round(cout * 1e6, 2)}
    if topology == "flyback":
        dmax = 0.45
        vd = 0.5
        n = (vin * dmax) / ((vout + vd) * (1 - dmax))    # Np:Ns turns ratio
        pout = vout * iout
        pin = pout / 0.85
        lp = (vin * dmax) ** 2 / (2 * pin * fsw)          # DCM primary inductance
        ipk = 2 * pin / (vin * dmax)
        return {"topology": "flyback", "turns_ratio_np_ns": round(n, 3), "duty_max_pct": dmax * 100,
                "primary_inductance_uH": round(lp * 1e6, 2), "peak_primary_current_A": round(ipk, 3),
                "note": "DCM estimate; add a snubber + secondary output cap for ripple."}
    # buck (default)
    from . import design_tools
    s = design_tools.buck_stage(vin, vout, iout, fsw_khz, ripple_pct)
    s["output_cap_uF"] = s.pop("output_cap_uF_for_1pct", None)
    return s


# --- loop compensation (type-II starting point) --------------------------
def compensation(vin: float, vout: float, iout: float, L_uH: float, Cout_uF: float,
                 fsw_khz: float = 500.0, esr_mohm: float = 10.0, pm_target: float = 60.0,
                 gm_ea_uA_V: float = 1000.0) -> dict:
    """Power-stage poles/zeros + a type-II compensator starting point (current-mode buck).

    Crossover fc = fsw/10; place the comp zero at the output pole and the comp HF pole at the
    ESR zero. Component values assume a transconductance error amp (gm) and are a STARTING POINT
    to refine against the controller datasheet / LTpowerCAD.
    """
    Cout = Cout_uF * 1e-6
    esr = esr_mohm * 1e-3
    rload = vout / iout
    fsw = fsw_khz * 1e3
    fc = fsw / 10.0
    fp_load = 1.0 / (2 * math.pi * rload * Cout)          # output pole (current-mode dominant)
    fz_esr = 1.0 / (2 * math.pi * esr * Cout) if esr > 0 else float("inf")
    # type-II: comp zero at fp_load, comp pole at fz_esr (or fsw/2), integrator for fc
    gm = gm_ea_uA_V * 1e-6
    # target mid-band gain to set crossover (approximate current-mode: gain ~ gm*Rc*(Vout/Vramp))
    rc = 1.0 / (gm) * (fc / max(fp_load, 1.0)) * 0.5      # scaled starting value
    rc = max(1e3, min(rc, 200e3))
    cc1 = 1.0 / (2 * math.pi * fp_load * rc)              # zero at load pole
    fp_hi = min(fz_esr, fsw / 2.0)
    cc2 = 1.0 / (2 * math.pi * fp_hi * rc) if fp_hi > 0 else 0.0
    return {
        "crossover_hz": round(fc, 1),
        "power_pole_hz": round(fp_load, 1),
        "esr_zero_hz": round(fz_esr, 1) if math.isfinite(fz_esr) else None,
        "phase_margin_target_deg": pm_target,
        "type2": {"Rc_ohm": round(rc, 0), "Cc1_nF": round(cc1 * 1e9, 2), "Cc2_pF": round(cc2 * 1e12, 1)},
        "note": "Starting point (current-mode type-II). Refine Rc/Cc against the IC datasheet or "
                "LTpowerCAD; verify phase margin with a closed-loop AC sim.",
    }


def design(vin: float, vout: float, iout: float, fsw_khz: float = 500.0, ripple_pct: float = 30.0,
           isolated: bool = False) -> dict:
    topo = recommend_topology(vin, vout, iout, isolated)
    t = topo["topology"]
    sizing = size_stage(t, vin, vout, iout, fsw_khz, ripple_pct)
    result = {"input": {"vin": vin, "vout": vout, "iout": iout, "fsw_khz": fsw_khz},
              "recommendation": topo, "parts": candidate_parts(t, vin, vout, iout), "sizing": sizing}
    if t in ("buck", "boost", "buck-boost") and sizing.get("inductor_uH") and sizing.get("output_cap_uF"):
        result["compensation"] = compensation(vin, vout, iout, sizing["inductor_uH"],
                                               sizing["output_cap_uF"], fsw_khz)
    return result
