import math

from ece_suite.calculators import (
    CALC_META,
    CALCS,
    adc_resolution,
    buck_duty,
    cap_energy,
    check_esp32_pins,
    dbm_convert,
    decoupling_advisor,
    design_divider,
    e24_nearest,
    l_match,
    lc_lowpass,
    lc_resonant,
    led_resistor,
    microstrip_z0,
    opamp_inverting,
    opamp_noninverting,
    power_budget,
    rc_cutoff,
    shunt_sense,
    thermal_junction,
    timer_555_astable,
    trace_width,
    voltage_divider,
    wavelength,
)


def test_e24_nearest():
    assert e24_nearest(5151) == 5100.0
    assert e24_nearest(9800) == 9100.0
    assert e24_nearest(1000) == 1000.0


def test_voltage_divider():
    assert abs(voltage_divider(5.0, 10_000, 10_000) - 2.5) < 1e-9


def test_design_divider_5_to_3v3():
    d = design_divider(5.0, 3.3)
    assert abs(d["vout_actual"] - 3.3) < 0.05
    assert d["error_pct"] < 2.0


def test_lc_lowpass_known():
    r = lc_lowpass(1e6, 50)
    assert abs(r["L_uH"] - 7.9577) < 0.01
    assert abs(r["C_nF"] - 3.1831) < 0.01


def test_microstrip_plausible():
    r = microstrip_z0(0.3, 0.2, 4.4)  # u = 1.5
    assert 45 < r["z0_ohm"] < 70
    assert r["eeff"] > 1.0


def test_l_match_q():
    r = l_match(50, 200, 100e6)
    assert abs(r["Q"] - math.sqrt(200 / 50 - 1)) < 1e-3  # Q is rounded to 4 dp


def test_power_budget():
    r = power_budget([{"name": "mcu", "current_ma": 20}, {"name": "radio", "current_ma": 120, "duty": 0.1}], 3.7, 2000)
    assert abs(r["avg_current_ma"] - 32.0) < 1e-6
    assert r["runtime_hours"] and r["runtime_hours"] > 0


def test_decoupling_advisor():
    r = decoupling_advisor(4, 3.3)
    assert any(c["value"] == "100nF" for c in r["caps"])


def test_esp32_flash_and_input_only():
    r = check_esp32_pins([{"gpio": 6, "function": "output"}, {"gpio": 34, "function": "output"}])
    assert not r["ok"]
    joined = " ".join(r["issues"]).lower()
    assert "flash" in joined and "input-only" in joined


def test_esp32_clean():
    r = check_esp32_pins([{"gpio": 21, "function": "i2c"}, {"gpio": 22, "function": "i2c"}])
    assert r["ok"]


def test_led_resistor():
    r = led_resistor(5.0, 2.0, 20.0)
    assert abs(r["r_ideal_ohm"] - 150.0) < 1e-6 and r["r_e24_ohm"] == 150.0


def test_rc_cutoff():
    assert abs(rc_cutoff(10_000, 0.1)["fc_hz"] - 159.1549) < 1e-2


def test_lc_resonant_and_q():
    r = lc_resonant(10.0, 1.0, 5.0)
    assert abs(r["f0_hz"] - 1_591_549.43) < 1.0
    assert abs(r["Q_series"] - 20.0) < 1e-6


def test_opamp_gains():
    assert opamp_noninverting(10_000, 1_000)["gain_v_v"] == 11.0
    assert opamp_inverting(10_000, 1_000)["gain_v_v"] == -10.0


def test_trace_width_ipc2221():
    r = trace_width(2.0, 10.0, 1.0)
    # external must be narrower than internal for the same current/rise
    assert r["external"]["width_mil"] < r["internal"]["width_mil"]
    assert 20 < r["external"]["width_mil"] < 45  # sane for 2 A / 10 C / 1 oz


def test_thermal_and_555_and_adc():
    assert thermal_junction(1.0, 50.0, 25.0)["tj_c"] == 75.0
    assert abs(timer_555_astable(1_000, 10_000, 0.1)["duty_pct"] - 52.381) < 1e-2
    assert abs(adc_resolution(3.3, 12)["lsb_uv"] - 805.664) < 1e-2


def test_dbm_shunt_cap_buck_wavelength():
    assert abs(dbm_convert(0.0)["milliwatts"] - 1.0) < 1e-9
    assert abs(shunt_sense(1.0, 100.0)["vsense_mv"] - 100.0) < 1e-6
    assert abs(cap_energy(100.0, 12.0)["energy_mj"] - 7.2) < 1e-3
    assert abs(buck_duty(12.0, 3.3)["duty_pct"] - 27.5) < 1e-3
    assert abs(wavelength(100.0)["quarter_wave_mm"] - 749.48) < 1.0


def test_all_meta_calcs_are_registered_and_runnable():
    for meta in CALC_META:
        fn = CALCS[meta["id"]]
        args = {f["k"]: f["default"] for f in meta["fields"]}
        assert isinstance(fn(**args), dict)
