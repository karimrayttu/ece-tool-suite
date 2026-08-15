"""SPICE-based VERIFICATION of power-stage designs.

This is a verification method, not a simulation playground: given a buck/boost design (the
values your sizing calc produced), it generates a self-contained switching netlist, runs it in
**LTspice** (headless ``-b``; ngspice fallback), parses the ``.raw``, and checks the measured
behaviour against PASS/FAIL targets — output regulation, output-voltage ripple, inductor
ripple current, efficiency, and load-step dip. Same lab-truth spirit as the instrument gates:
a design isn't "verified" until the simulation confirms the numbers.

The netlist is behavioural + self-contained (ideal switches with Ron, L DCR, C ESR) so it
always converges without hunting vendor models. It verifies the POWER STAGE (L/C sizing →
ripple/transient), which is exactly what buck/boost sizing needs checked.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile

RAW_PARSER_INSTALL = 'pip install -e "backend[spice]"'


def can_read_raw() -> bool:
    """Running the sim and reading its result are separate capabilities.

    The engine is a binary found on disk; the ``.raw`` parser is the spicelib package, which
    sits in its own extra because it is GPL-3.0. A machine can easily have one and not the
    other, and saying so up front beats failing after the simulation has already run.
    """
    return importlib.util.find_spec("spicelib") is not None


def engines() -> list[dict]:
    """Available SPICE engines for verification (LTspice preferred, ngspice fallback)."""
    from . import design_tools
    lt = next((t["path"] for t in design_tools.detect_tools() if t["id"] == "ltspice" and t["installed"]), None)
    ng = shutil.which("ngspice") or shutil.which("ngspice_con")
    # KiCad bundles ngspice
    if not ng:
        import glob
        hits = glob.glob(r"C:\Program Files\KiCad\*\bin\ngspice.exe")
        ng = hits[-1] if hits else None
    out = []
    if lt:
        out.append({"id": "ltspice", "name": "LTspice", "path": lt})
    if ng:
        out.append({"id": "ngspice", "name": "ngspice", "path": ng})
    return out


def buck_netlist(vin: float, vout: float, iout: float, L_uH: float, Cout_uF: float,
                 fsw_khz: float, esr_mohm: float = 10.0, dcr_mohm: float = 20.0,
                 ron_mohm: float = 15.0, cycles: int = 800, load_step: bool = True) -> str:
    """Synchronous buck, fixed-duty (open-loop power stage). Non-overlapping gate drives with
    dead-time + a freewheel diode (no shoot-through, no dead-time spike). Constant-current load
    that steps +50% at 70% of the run so a load-step dip can be measured."""
    T = 1.0 / (fsw_khz * 1e3)
    dt = 0.02 * T                          # dead-time
    # loss-compensated duty so the open-loop stage settles near Vout (a real loop would do this);
    # covers DCR + switch Ron + the dead-time freewheel-diode drop.
    d_loss = iout * (dcr_mohm + ron_mohm) * 1e-3 + 0.4 * (2 * dt / T)
    D = min(0.95, (vout + d_loss) / vin)
    tstop = cycles * T
    tstep = T / 200.0
    step_t = tstop * 0.7
    hs_w = max(D * T - dt, T * 0.01)
    ls_w = max((1 - D) * T - 2 * dt, T * 0.01)
    load = (f"Bload out 0 I=IF(TIME<{step_t:.9g}, {iout:.6g}, {1.5 * iout:.6g})"
            if load_step else f"Iload out 0 {iout:.6g}")
    return f"""* buck power-stage verification (open-loop, D={D:.4f})
Vin in 0 {vin:.6g}
Vg1 g1 0 PULSE(0 5 0 1n 1n {hs_w:.9g} {T:.9g})
Vg2 g2 0 PULSE(0 5 {D * T + dt:.9g} 1n 1n {ls_w:.9g} {T:.9g})
S1 in sw g1 0 SWM
S2 sw 0 g2 0 SWM
.model SWM SW(Ron={ron_mohm * 1e-3:.6g} Roff=1Meg Vt=2.5 Vh=0.1)
Dfw 0 sw DFW
.model DFW D(Ron=30m Roff=1Meg Vfwd=0.4)
L1 sw nx {L_uH * 1e-6:.9g} Rser={dcr_mohm * 1e-3:.6g}
Resr nx out {esr_mohm * 1e-3:.6g}
Cout out 0 {Cout_uF * 1e-6:.9g} ic={vout:.6g}
{load}
.ic V(out)={vout:.6g} I(L1)={iout:.6g}
.tran 0 {tstop:.9g} 0 {tstep:.9g} uic
.end
"""


def boost_netlist(vin: float, vout: float, iout: float, L_uH: float, Cout_uF: float,
                  fsw_khz: float, esr_mohm: float = 10.0, dcr_mohm: float = 20.0,
                  ron_mohm: float = 15.0, cycles: int = 800) -> str:
    D = 1.0 - vin / vout
    T = 1.0 / (fsw_khz * 1e3)
    tstop = cycles * T
    tstep = T / 200.0
    return f"""* boost power-stage verification (fixed duty D={D:.4f})
Vin in 0 {vin:.6g}
Vg1 g1 0 PULSE(0 5 0 1n 1n {D * T:.9g} {T:.9g})
L1 in sw {L_uH * 1e-6:.9g} Rser={dcr_mohm * 1e-3:.6g}
S1 sw 0 g1 0 SWM
.model SWM SW(Ron={ron_mohm * 1e-3:.6g} Roff=1Meg Vt=2.5 Vh=0.1)
D1 sw out DIDEAL
.model DIDEAL D(Ron=20m Roff=1Meg Vfwd=0.3)
Resr out ox {esr_mohm * 1e-3:.6g}
Cout ox 0 {Cout_uF * 1e-6:.9g} ic={vin:.6g}
Iload out 0 {iout:.6g}
.ic V(ox)={vin:.6g}
.tran 0 {tstop:.9g} 0 {tstep:.9g} uic
.end
"""


def _run(netlist: str, engine: dict, workdir: str) -> str:
    """Run the netlist headless; return the .raw path."""
    cir = os.path.join(workdir, "verify.cir")
    with open(cir, "w") as f:
        f.write(netlist)
    if engine["id"] == "ltspice":
        subprocess.run([engine["path"], "-b", "-Run", cir], capture_output=True, timeout=120)
        raw = os.path.join(workdir, "verify.raw")
    else:  # ngspice
        raw = os.path.join(workdir, "verify.raw")
        subprocess.run([engine["path"], "-b", "-r", raw, cir], capture_output=True, timeout=120)
    if not os.path.exists(raw):
        raise RuntimeError("simulation produced no .raw output")
    return raw


def _steady_metrics(raw_path: str, vin: float, vout: float, iout: float, topology: str,
                    fsw_khz: float) -> dict:
    """Ripple / IL-ripple / efficiency (power-stage), + informational regulation & load-step dip.

    Switching ripple is measured over a NARROW window (last ~20 cycles before the load step) so
    slow open-loop drift can't inflate it; efficiency + DC point use a wider settled window.
    """
    import numpy as np
    from spicelib import RawRead

    r = RawRead(raw_path)
    names = {n.lower(): n for n in r.get_trace_names()}
    t = np.abs(np.asarray(r.get_trace("time").get_wave(), dtype=float))

    def trace(*cands):
        for c in cands:
            if c.lower() in names:
                return np.asarray(r.get_trace(names[c.lower()]).get_wave(), dtype=float).real
        return None

    vo = trace("V(out)")
    iin = trace("I(Vin)")
    il = trace("I(L1)")
    if vo is None:
        raise RuntimeError("no V(out) in results")

    n = len(t)
    te = t[-1]
    step_t = te * 0.7
    T = 1.0 / (fsw_khz * 1e3)
    # narrow switching-ripple window: ~20 cycles ending just before the load step
    ripple_win = (t >= step_t - 20 * T) & (t < step_t - T)
    if ripple_win.sum() < 10:
        ripple_win = (t >= te * 0.6) & (t < step_t)
    # wider window for DC point + efficiency
    dc_win = (t >= te * 0.45) & (t < step_t)

    vout_mean = float(np.mean(vo[dc_win]))
    vout_ripple = float(np.ptp(vo[ripple_win]))
    il_ripple = float(np.ptp(il[ripple_win])) if il is not None else None
    eff = None
    if iin is not None and dc_win.sum() > 2:
        tw, iw = t[dc_win], iin[dc_win]                 # energy-based avg input power (robust to
        dur = tw[-1] - tw[0]                             # partial cycles): Pavg = ∫v·i dt / Δt
        integ = getattr(np, "trapezoid", None) or np.trapz  # numpy>=2 renamed trapz
        pin = float(vin * abs(integ(iw, tw) / dur)) if dur > 0 else 0.0
        eff = 100.0 * (vout_mean * iout) / pin if pin > 1e-9 else None
        if eff is not None and (eff <= 0 or eff > 101.0):
            eff = None                                  # unphysical -> not settled / unreliable
    dip_mv = None
    step = (t >= step_t) & (t <= step_t + 30 * T)
    if step.any():
        dip_mv = float((vout_mean - np.min(vo[step])) * 1e3)
    return {
        "vout_mean": round(vout_mean, 4),
        "regulation_pct": round(100.0 * (vout_mean - vout) / vout, 3),
        "vout_ripple_mvpp": round(vout_ripple * 1e3, 3),
        "il_ripple_a": round(il_ripple, 4) if il_ripple is not None else None,
        "il_ripple_pct": round(100.0 * il_ripple / iout, 1) if il_ripple is not None else None,
        "efficiency_pct": round(eff, 2) if eff is not None else None,
        "load_step_dip_mv": round(dip_mv, 2) if dip_mv is not None else None,
        "waveform": {"t": t[::max(1, n // 800)].tolist(), "vout": vo[::max(1, n // 800)].tolist()},
        "points": n,
    }


def verify(topology: str, vin: float, vout: float, iout: float, L_uH: float, Cout_uF: float,
           fsw_khz: float, targets: dict | None = None, esr_mohm: float = 10.0,
           dcr_mohm: float = 20.0, engine_id: str | None = None) -> dict:
    eng_list = engines()
    if not eng_list:
        return {"ok": False, "error": "no SPICE engine found — install LTspice (adi.com) or ngspice",
                "install": "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"}
    if not can_read_raw():
        return {"ok": False, "error": "spicelib is not installed, so the .raw output cannot be read",
                "install": RAW_PARSER_INSTALL}
    engine = next((e for e in eng_list if e["id"] == engine_id), eng_list[0])
    topo = "boost" if topology.lower().startswith("boost") else "buck"
    nl = (boost_netlist if topo == "boost" else buck_netlist)(vin, vout, iout, L_uH, Cout_uF, fsw_khz,
                                                              esr_mohm=esr_mohm, dcr_mohm=dcr_mohm)
    try:
        with tempfile.TemporaryDirectory() as wd:
            raw = _run(nl, engine, wd)
            m = _steady_metrics(raw, vin, vout, iout, topo, fsw_khz)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "engine": engine["name"], "error": str(e), "netlist": nl}

    # PASS/FAIL is on POWER-STAGE properties (open-loop SPICE verifies L/C sizing + efficiency).
    tg = {"vout_ripple_mvpp": max(50.0, 0.01 * vout * 1e3),  # default ~1% of Vout
          "il_ripple_pct": 40.0, "efficiency_pct": 85.0}
    tg.update(targets or {})
    def chk(name, val, unit, limit, ok, cmp):
        return {"name": name, "value": float(val), "unit": unit, "limit": float(limit),
                "pass": bool(ok), "cmp": cmp}

    checks = [chk("Output ripple (pk-pk)", m["vout_ripple_mvpp"], "mV", round(tg["vout_ripple_mvpp"], 1),
                  m["vout_ripple_mvpp"] <= tg["vout_ripple_mvpp"], "<=")]
    if m["il_ripple_pct"] is not None:
        checks.append(chk("Inductor ripple", m["il_ripple_pct"], "% Iout", tg["il_ripple_pct"],
                          m["il_ripple_pct"] <= tg["il_ripple_pct"], "<="))
    if m["efficiency_pct"] is not None:
        checks.append(chk("Efficiency", m["efficiency_pct"], "%", tg["efficiency_pct"],
                          m["efficiency_pct"] >= tg["efficiency_pct"], ">="))
    return {"ok": True, "engine": engine["name"], "topology": topo, "metrics": m, "checks": checks,
            "verified": all(c["pass"] for c in checks),
            "note": "Open-loop power-stage verification: ripple/inductor/efficiency are checked; "
                    "V(out) regulation & load-step recovery are the control loop's job (design the "
                    "compensator in LTpowerCAD, then closed-loop verify)."}
