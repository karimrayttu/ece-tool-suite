"""Design calculators (ported from oh-my-embedded, re-implemented in Python).

Pure functions — no I/O, no keys, no hardware. Each returns a plain dict so the same code
serves the REST endpoints and the tests.
"""

from __future__ import annotations

import math

E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
       3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]


def e24_nearest(value: float) -> float:
    if value <= 0:
        return value
    decade = 10 ** math.floor(math.log10(value))
    norm = value / decade
    best = min(E24, key=lambda x: abs(x - norm))
    return round(best * decade, 12)


def _e24_series(min_v: float, max_v: float) -> list[float]:
    out: list[float] = []
    dec = 10 ** math.floor(math.log10(min_v))
    while dec <= max_v:
        for b in E24:
            v = b * dec
            if min_v <= v <= max_v:
                out.append(round(v, 12))
        dec *= 10
    return out


def voltage_divider(vin: float, r1: float, r2: float) -> float:
    """Vout across r2 (low-side)."""
    return vin * r2 / (r1 + r2)


def design_divider(vin: float, vout: float, r_low_hint: float = 10_000.0) -> dict:
    """Pick an E24 R1/R2 pair so Vout = Vin·R2/(R1+R2) is closest to target."""
    if not (0 < vout < vin):
        raise ValueError("require 0 < vout < vin")
    candidates = _e24_series(r_low_hint / 10, r_low_hint * 10)
    best = None
    for r2 in candidates:
        r1 = e24_nearest(r2 * (vin - vout) / vout)
        vact = voltage_divider(vin, r1, r2)
        err = abs(vact - vout) / vout
        if best is None or err < best["error_pct"]:
            best = {"r1": r1, "r2": r2, "vout_actual": round(vact, 6),
                    "error_pct": err, "current_ua": round(vin / (r1 + r2) * 1e6, 3)}
    best["error_pct"] = round(best["error_pct"] * 100, 4)
    return best


def power_budget(loads: list[dict], vbat: float, capacity_mah: float, derate: float = 0.8) -> dict:
    """loads: [{name, current_ma, duty?}]. Returns avg current, runtime, breakdown."""
    breakdown = []
    avg_ma = 0.0
    for l in loads:
        duty = float(l.get("duty", 1.0))
        contrib = float(l["current_ma"]) * duty
        avg_ma += contrib
        breakdown.append({"name": l.get("name", "?"), "avg_ma": round(contrib, 4)})
    runtime_h = (capacity_mah * derate) / avg_ma if avg_ma > 0 else float("inf")
    return {
        "avg_current_ma": round(avg_ma, 4),
        "avg_power_w": round(avg_ma / 1000.0 * vbat, 4),
        "runtime_hours": round(runtime_h, 3) if math.isfinite(runtime_h) else None,
        "runtime_days": round(runtime_h / 24.0, 3) if math.isfinite(runtime_h) else None,
        "derate": derate,
        "breakdown": breakdown,
    }


def lc_lowpass(fc: float, z0: float) -> dict:
    """L and C for an LC low-pass with cutoff fc into impedance z0."""
    w = 2 * math.pi * fc
    L = z0 / w
    C = 1.0 / (w * z0)
    return {"L_H": L, "C_F": C, "L_uH": round(L * 1e6, 6), "C_nF": round(C * 1e9, 6), "fc_hz": fc, "z0_ohm": z0}


def l_match(rs: float, rl: float, f: float) -> dict:
    """Narrowband L-network match between rs and rl at frequency f."""
    if rs <= 0 or rl <= 0 or rs == rl:
        raise ValueError("require rs>0, rl>0, rs!=rl")
    rhi, rlo = max(rs, rl), min(rs, rl)
    Q = math.sqrt(rhi / rlo - 1.0)
    w = 2 * math.pi * f
    Xs = Q * rlo       # series reactance (low-R side)
    Xp = rhi / Q       # shunt reactance (high-R side)
    return {
        "Q": round(Q, 4),
        "lowpass": {"series_L_uH": round(Xs / w * 1e6, 6), "shunt_C_pF": round(1.0 / (w * Xp) * 1e12, 4)},
        "highpass": {"series_C_pF": round(1.0 / (w * Xs) * 1e12, 4), "shunt_L_uH": round(Xp / w * 1e6, 6)},
        "note": "series element on the low-impedance side, shunt on the high-impedance side",
    }


def microstrip_z0(w: float, h: float, er: float) -> dict:
    """Characteristic impedance of a microstrip (Hammerstad/Wheeler)."""
    u = w / h
    if u <= 1:
        eeff = (er + 1) / 2 + (er - 1) / 2 * ((1 + 12 / u) ** -0.5 + 0.04 * (1 - u) ** 2)
        z0 = 60 / math.sqrt(eeff) * math.log(8 / u + u / 4)
    else:
        eeff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / u) ** -0.5
        z0 = 120 * math.pi / (math.sqrt(eeff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))
    return {"z0_ohm": round(z0, 3), "eeff": round(eeff, 4), "w_over_h": round(u, 4)}


def decoupling_advisor(n_power_pins: int, supply_v: float, ic_class: str = "digital") -> dict:
    caps = [{"value": "100nF", "qty": n_power_pins, "role": "per-pin HF decoupling (X7R, close to each pin)"}]
    if ic_class == "digital":
        caps.append({"value": "1nF", "qty": max(1, n_power_pins // 2), "role": "high-frequency edge decoupling"})
        caps.append({"value": "10uF", "qty": 1, "role": "bulk / local energy reservoir"})
    else:
        caps.append({"value": "1uF", "qty": 1, "role": "bulk"})
    return {"supply_v": supply_v, "ic_class": ic_class, "caps": caps,
            "notes": "Place 100nF caps within a few mm of each power pin with short vias to plane."}


# ESP32 (classic) pin hazards
_FLASH = {6, 7, 8, 9, 10, 11}
_INPUT_ONLY = {34, 35, 36, 37, 38, 39}
_STRAPPING = {0, 2, 5, 12, 15}
_ADC2 = {0, 2, 4, 12, 13, 14, 15, 25, 26, 27}


def check_esp32_pins(assignments: list[dict]) -> dict:
    """assignments: [{gpio:int, function:str}] where function in input/output/pwm/adc/i2c/spi/..."""
    issues: list[str] = []
    seen: dict[int, str] = {}
    for a in assignments:
        gpio = int(a["gpio"])
        fn = str(a.get("function", "")).lower()
        if gpio in seen:
            issues.append(f"GPIO{gpio} assigned twice ({seen[gpio]} and {fn})")
        seen[gpio] = fn
        if gpio in _FLASH:
            issues.append(f"GPIO{gpio} connects to the SPI flash — do NOT use")
        if gpio in _INPUT_ONLY and fn in ("output", "pwm", "dac"):
            issues.append(f"GPIO{gpio} is input-only — cannot be {fn}")
        if gpio in _STRAPPING:
            issues.append(f"GPIO{gpio} is a strapping pin — boot-sensitive, avoid strong pulls")
        if gpio in _ADC2 and fn == "adc":
            issues.append(f"GPIO{gpio} uses ADC2 — unavailable while Wi-Fi is active")
    return {"ok": len(issues) == 0, "issues": issues, "n_assigned": len(assignments)}


C_LIGHT = 299_792_458.0  # m/s


def led_resistor(vsupply: float, vf: float, if_ma: float) -> dict:
    """Series resistor for an LED: R = (Vsupply − Vf) / If."""
    if vsupply <= vf:
        raise ValueError("Vsupply must exceed the LED forward voltage Vf")
    i = if_ma / 1000.0
    r = (vsupply - vf) / i
    p = (vsupply - vf) * i
    return {"r_ideal_ohm": round(r, 3), "r_e24_ohm": e24_nearest(r),
            "resistor_power_w": round(p, 4), "recommend_rating_w": _std_power(p * 2)}


def rc_cutoff(r_ohm: float, c_uf: float) -> dict:
    """First-order RC corner frequency and time constant."""
    c = c_uf * 1e-6
    tau = r_ohm * c
    fc = 1.0 / (2 * math.pi * tau) if tau > 0 else float("inf")
    return {"fc_hz": round(fc, 4), "tau_s": tau, "tau_ms": round(tau * 1e3, 6),
            "settle_5tau_ms": round(tau * 5e3, 6)}


def rl_cutoff(r_ohm: float, l_mh: float) -> dict:
    """First-order RL corner frequency and time constant (τ = L/R)."""
    l = l_mh * 1e-3
    tau = l / r_ohm if r_ohm > 0 else float("inf")
    fc = r_ohm / (2 * math.pi * l) if l > 0 else float("inf")
    return {"fc_hz": round(fc, 4), "tau_s": tau, "tau_us": round(tau * 1e6, 6)}


def lc_resonant(l_uh: float, c_nf: float, r_ohm: float = 0.0) -> dict:
    """Resonant frequency f0 = 1/(2π√(LC)); Q and bandwidth for a *series* RLC if R>0."""
    l = l_uh * 1e-6
    c = c_nf * 1e-9
    f0 = 1.0 / (2 * math.pi * math.sqrt(l * c))
    out = {"f0_hz": round(f0, 4), "f0_mhz": round(f0 / 1e6, 6),
           "x_at_f0_ohm": round(math.sqrt(l / c), 4)}
    if r_ohm > 0:
        q = (1.0 / r_ohm) * math.sqrt(l / c)   # series RLC
        out.update({"Q_series": round(q, 3), "bandwidth_hz": round(f0 / q, 4)})
    return out


def opamp_noninverting(rf: float, rg: float) -> dict:
    """Non-inverting op-amp gain: G = 1 + Rf/Rg."""
    g = 1.0 + rf / rg
    return {"gain_v_v": round(g, 4), "gain_db": round(20 * math.log10(g), 3)}


def opamp_inverting(rf: float, rin: float) -> dict:
    """Inverting op-amp gain: G = −Rf/Rin."""
    g = rf / rin
    return {"gain_v_v": round(-g, 4), "magnitude": round(g, 4), "gain_db": round(20 * math.log10(g), 3)}


def trace_width(current_a: float, temp_rise_c: float, copper_oz: float = 1.0) -> dict:
    """PCB trace width for a current, per IPC-2221:
    A[mil²] = (I / (k·ΔT^0.44))^(1/0.725); width = A / thickness."""
    if temp_rise_c <= 0 or current_a <= 0:
        raise ValueError("current and temperature rise must be > 0")
    th_mil = copper_oz * 1.378  # 1 oz ≈ 1.378 mil
    def width(k: float) -> dict:
        area = (current_a / (k * temp_rise_c ** 0.44)) ** (1 / 0.725)
        w_mil = area / th_mil
        return {"width_mil": round(w_mil, 2), "width_mm": round(w_mil * 0.0254, 4)}
    return {"external": width(0.048), "internal": width(0.024),
            "copper_oz": copper_oz, "thickness_mil": round(th_mil, 4), "standard": "IPC-2221"}


def thermal_junction(power_w: float, theta_ja_c_w: float, ambient_c: float = 25.0) -> dict:
    """Junction temperature Tj = Ta + P·θJA."""
    tj = ambient_c + power_w * theta_ja_c_w
    return {"tj_c": round(tj, 2), "rise_c": round(power_w * theta_ja_c_w, 2), "ambient_c": ambient_c}


def timer_555_astable(r1_ohm: float, r2_ohm: float, c_uf: float) -> dict:
    """555 astable: f = 1.44/((R1+2·R2)·C), duty = (R1+R2)/(R1+2·R2)."""
    c = c_uf * 1e-6
    f = 1.44 / ((r1_ohm + 2 * r2_ohm) * c)
    duty = (r1_ohm + r2_ohm) / (r1_ohm + 2 * r2_ohm)
    return {"freq_hz": round(f, 4), "duty_pct": round(duty * 100, 3),
            "t_high_ms": round(0.693 * (r1_ohm + r2_ohm) * c * 1e3, 6),
            "t_low_ms": round(0.693 * r2_ohm * c * 1e3, 6)}


def adc_resolution(vref: float, bits: float) -> dict:
    """ADC LSB voltage and ideal dynamic range."""
    codes = 2 ** int(bits)
    lsb = vref / codes
    return {"lsb_v": lsb, "lsb_mv": round(lsb * 1e3, 6), "lsb_uv": round(lsb * 1e6, 4),
            "codes": codes, "dynamic_range_db": round(6.02 * bits + 1.76, 2)}


def dbm_convert(dbm: float) -> dict:
    """dBm ↔ power/voltage (Vrms into 50 Ω)."""
    watts = 10 ** ((dbm - 30) / 10)
    vrms = math.sqrt(watts * 50.0)
    return {"milliwatts": round(10 ** (dbm / 10), 6), "watts": round(watts, 9),
            "vrms_50ohm": round(vrms, 6), "vpp_50ohm": round(vrms * 2 * math.sqrt(2), 6)}


def shunt_sense(current_a: float, rshunt_mohm: float) -> dict:
    """Current-sense shunt: Vsense = I·R, dissipation = I²·R."""
    r = rshunt_mohm * 1e-3
    v = current_a * r
    p = current_a ** 2 * r
    return {"vsense_mv": round(v * 1e3, 4), "power_mw": round(p * 1e3, 4),
            "recommend_rating_w": _std_power(p * 2)}


def cap_energy(c_uf: float, v: float) -> dict:
    """Capacitor stored energy E = ½CV² and charge Q = CV."""
    c = c_uf * 1e-6
    return {"energy_j": round(0.5 * c * v * v, 9), "energy_mj": round(0.5 * c * v * v * 1e3, 6),
            "charge_uc": round(c * v * 1e6, 4)}


def buck_duty(vin: float, vout: float, eff: float = 0.9) -> dict:
    """Ideal-CCM buck duty D = Vout/Vin; input current from power balance."""
    if not (0 < vout < vin):
        raise ValueError("require 0 < Vout < Vin for a buck")
    d = vout / vin
    return {"duty_pct": round(d * 100, 3), "duty_ideal": round(d, 4),
            "note": f"add ~{round((1 - eff) * 100)}% for losses; iin ~ iout*Vout/(Vin*eff)"}


def wavelength(freq_mhz: float, vf: float = 1.0) -> dict:
    """Free-space (×velocity-factor) wavelength and antenna lengths."""
    f = freq_mhz * 1e6
    lam = C_LIGHT * vf / f
    return {"wavelength_m": round(lam, 6), "wavelength_mm": round(lam * 1e3, 3),
            "quarter_wave_mm": round(lam / 4 * 1e3, 3), "half_wave_mm": round(lam / 2 * 1e3, 3)}


def _std_power(p: float) -> str:
    for s in (0.0625, 0.1, 0.125, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0):
        if p <= s:
            return f"{s} W"
    return ">5 W"


CALCS = {
    "divider": design_divider,
    "power_budget": power_budget,
    "lc_filter": lc_lowpass,
    "lmatch": l_match,
    "microstrip": microstrip_z0,
    "decoupling": decoupling_advisor,
    "esp32_pins": check_esp32_pins,
    "led_resistor": led_resistor,
    "rc_cutoff": rc_cutoff,
    "rl_cutoff": rl_cutoff,
    "lc_resonant": lc_resonant,
    "opamp_noninv": opamp_noninverting,
    "opamp_inv": opamp_inverting,
    "trace_width": trace_width,
    "thermal": thermal_junction,
    "timer555": timer_555_astable,
    "adc": adc_resolution,
    "dbm": dbm_convert,
    "shunt": shunt_sense,
    "cap_energy": cap_energy,
    "buck": buck_duty,
    "wavelength": wavelength,
}

CALC_META = [
    {"id": "divider", "name": "Resistor divider (E24)", "fields": [
        {"k": "vin", "label": "Vin (V)", "default": 5.0}, {"k": "vout", "label": "Vout (V)", "default": 3.3},
        {"k": "r_low_hint", "label": "R-low hint (Ω)", "default": 10000}]},
    {"id": "lc_filter", "name": "LC low-pass", "fields": [
        {"k": "fc", "label": "Cutoff (Hz)", "default": 1000000}, {"k": "z0", "label": "Impedance (Ω)", "default": 50}]},
    {"id": "lmatch", "name": "L-network match", "fields": [
        {"k": "rs", "label": "Source R (Ω)", "default": 50}, {"k": "rl", "label": "Load R (Ω)", "default": 200},
        {"k": "f", "label": "Frequency (Hz)", "default": 100000000}]},
    {"id": "microstrip", "name": "Microstrip Z₀", "fields": [
        {"k": "w", "label": "Trace width (mm)", "default": 0.3}, {"k": "h", "label": "Dielectric h (mm)", "default": 0.2},
        {"k": "er", "label": "εr", "default": 4.4}]},
    {"id": "decoupling", "name": "Decoupling advisor", "fields": [
        {"k": "n_power_pins", "label": "# power pins", "default": 4}, {"k": "supply_v", "label": "Supply (V)", "default": 3.3}]},
    {"id": "led_resistor", "name": "LED series resistor", "fields": [
        {"k": "vsupply", "label": "Vsupply (V)", "default": 5.0}, {"k": "vf", "label": "LED Vf (V)", "default": 2.0},
        {"k": "if_ma", "label": "If (mA)", "default": 20.0}]},
    {"id": "rc_cutoff", "name": "RC filter / time constant", "fields": [
        {"k": "r_ohm", "label": "R (Ω)", "default": 10000.0}, {"k": "c_uf", "label": "C (µF)", "default": 0.1}]},
    {"id": "rl_cutoff", "name": "RL filter / time constant", "fields": [
        {"k": "r_ohm", "label": "R (Ω)", "default": 100.0}, {"k": "l_mh", "label": "L (mH)", "default": 1.0}]},
    {"id": "lc_resonant", "name": "LC resonance (Q, BW)", "fields": [
        {"k": "l_uh", "label": "L (µH)", "default": 10.0}, {"k": "c_nf", "label": "C (nF)", "default": 1.0},
        {"k": "r_ohm", "label": "Series R (Ω, opt)", "default": 0.0}]},
    {"id": "opamp_noninv", "name": "Op-amp gain (non-inv)", "fields": [
        {"k": "rf", "label": "Rf (Ω)", "default": 10000.0}, {"k": "rg", "label": "Rg (Ω)", "default": 1000.0}]},
    {"id": "opamp_inv", "name": "Op-amp gain (inverting)", "fields": [
        {"k": "rf", "label": "Rf (Ω)", "default": 10000.0}, {"k": "rin", "label": "Rin (Ω)", "default": 1000.0}]},
    {"id": "trace_width", "name": "PCB trace width (IPC-2221)", "fields": [
        {"k": "current_a", "label": "Current (A)", "default": 2.0}, {"k": "temp_rise_c", "label": "ΔT (°C)", "default": 10.0},
        {"k": "copper_oz", "label": "Copper (oz)", "default": 1.0}]},
    {"id": "thermal", "name": "Junction temperature", "fields": [
        {"k": "power_w", "label": "Power (W)", "default": 1.0}, {"k": "theta_ja_c_w", "label": "θJA (°C/W)", "default": 50.0},
        {"k": "ambient_c", "label": "Ambient (°C)", "default": 25.0}]},
    {"id": "timer555", "name": "555 astable", "fields": [
        {"k": "r1_ohm", "label": "R1 (Ω)", "default": 1000.0}, {"k": "r2_ohm", "label": "R2 (Ω)", "default": 10000.0},
        {"k": "c_uf", "label": "C (µF)", "default": 0.1}]},
    {"id": "adc", "name": "ADC resolution / LSB", "fields": [
        {"k": "vref", "label": "Vref (V)", "default": 3.3}, {"k": "bits", "label": "Bits", "default": 12.0}]},
    {"id": "dbm", "name": "dBm ↔ W / V (50 Ω)", "fields": [
        {"k": "dbm", "label": "Power (dBm)", "default": 0.0}]},
    {"id": "shunt", "name": "Current-sense shunt", "fields": [
        {"k": "current_a", "label": "Current (A)", "default": 1.0}, {"k": "rshunt_mohm", "label": "Rshunt (mΩ)", "default": 100.0}]},
    {"id": "cap_energy", "name": "Capacitor energy", "fields": [
        {"k": "c_uf", "label": "C (µF)", "default": 100.0}, {"k": "v", "label": "Voltage (V)", "default": 12.0}]},
    {"id": "buck", "name": "Buck duty cycle", "fields": [
        {"k": "vin", "label": "Vin (V)", "default": 12.0}, {"k": "vout", "label": "Vout (V)", "default": 3.3}]},
    {"id": "wavelength", "name": "Wavelength / antenna", "fields": [
        {"k": "freq_mhz", "label": "Frequency (MHz)", "default": 100.0}, {"k": "vf", "label": "Velocity factor", "default": 1.0}]},
]
