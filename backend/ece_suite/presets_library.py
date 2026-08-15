"""Auto-setup preset library — the "one click configures the instrument for what I'm
testing" feature.

Measurement presets (scope/DMM/SA) are CONFIGURE-only and evaluate to ALLOW. The PSU
bring-up preset is SOURCE_CONTROL: it requires a declared DUT envelope and explicit confirm,
and the PresetRunner enforces OVP/OCP-before-enable ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .presets import PresetStep
from .registry import Capability
from .safety import OpType


@dataclass
class Preset:
    id: str
    name: str
    instrument: str            # key into INSTRUMENTS: scope|dmm|sa|psu
    testing_for: str
    steps: list[PresetStep] = field(default_factory=list)
    requires_envelope: bool = False
    requires_confirm: bool = False
    suggested_envelope: dict | None = None   # {"max_voltage":..,"max_current":..}


def build_presets() -> dict[str, Preset]:
    presets: list[Preset] = [
        Preset(
            id="scope_i2c",
            name="I²C / digital debug",
            instrument="scope",
            testing_for="Logic-level edges on a slow serial bus (DC coupled, 10× probe).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":CHAN1:COUP DC", description="DC coupling"),
                PresetStep(OpType.CONFIGURE, ":CHAN1:PROB 10", verify_query=":CHAN1:PROB?", expected=10.0, description="10× probe"),
                PresetStep(OpType.CONFIGURE, ":CHAN1:SCAL 1.0", description="1 V/div"),
                PresetStep(OpType.CONFIGURE, ":TIM:SCAL 1e-5", verify_query=":TIM:SCAL?", expected=1e-5, description="10 µs/div"),
            ],
        ),
        Preset(
            id="scope_ripple",
            name="Power-rail ripple",
            instrument="scope",
            testing_for="Small AC ripple riding on a DC rail (AC coupled, fine vertical).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":CHAN1:COUP AC", description="AC coupling"),
                PresetStep(OpType.CONFIGURE, ":CHAN1:SCAL 0.02", description="20 mV/div"),
                PresetStep(OpType.CONFIGURE, ":TIM:SCAL 2e-3", verify_query=":TIM:SCAL?", expected=2e-3, description="2 ms/div"),
            ],
        ),
        Preset(
            id="scope_uart",
            name="UART capture",
            instrument="scope",
            testing_for="Single-shot async serial byte (normal trigger, DC coupled).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":CHAN1:COUP DC", verify_query=":CHAN1:COUP?", expected="DC", description="DC coupling"),
                PresetStep(OpType.CONFIGURE, ":CHAN1:SCAL 1.0", description="1 V/div"),
                PresetStep(OpType.CONFIGURE, ":TRIG:SWE NORMAL", description="normal (triggered) sweep"),
                PresetStep(OpType.CONFIGURE, ":TIM:SCAL 1e-4", verify_query=":TIM:SCAL?", expected=1e-4, description="100 µs/div"),
            ],
        ),
        Preset(
            id="scope_pwm",
            name="PWM / gate drive",
            instrument="scope",
            testing_for="Motor/gate-drive PWM duty + edges (DC coupled, 10× probe, µs timebase).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":CHAN1:COUP DC", verify_query=":CHAN1:COUP?", expected="DC", description="DC coupling"),
                PresetStep(OpType.CONFIGURE, ":CHAN1:PROB 10", verify_query=":CHAN1:PROB?", expected=10.0, description="10× probe"),
                PresetStep(OpType.CONFIGURE, ":CHAN1:SCAL 2.0", description="2 V/div"),
                PresetStep(OpType.CONFIGURE, ":TIM:SCAL 5e-6", verify_query=":TIM:SCAL?", expected=5e-6, description="5 µs/div"),
            ],
        ),
        Preset(
            id="dmm_dc_rail",
            name="DC rail check",
            instrument="dmm",
            testing_for="Steady DC voltage on a power rail with extra averaging (10 NPLC).",
            steps=[
                PresetStep(OpType.CONFIGURE, ':CONF:VOLT:DC', description="DC volts function"),
                PresetStep(OpType.CONFIGURE, ":VOLT:DC:NPLC 10", description="10 NPLC (quieter)"),
            ],
        ),
        Preset(
            id="dmm_diode",
            name="Diode / junction",
            instrument="dmm",
            testing_for="Forward-voltage of a diode or B-E junction (diode test mode).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":CONF:DIOD", description="diode test"),
            ],
        ),
        Preset(
            id="dmm_continuity",
            name="Continuity",
            instrument="dmm",
            testing_for="Beep-on-short continuity for netlist / cable checks.",
            steps=[
                PresetStep(OpType.CONFIGURE, ":CONF:CONT", description="continuity"),
            ],
        ),
        Preset(
            id="dmm_current",
            name="DC current",
            instrument="dmm",
            testing_for="Quiescent / load DC current draw (10 NPLC average).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":CONF:CURR:DC", description="DC current function"),
                PresetStep(OpType.CONFIGURE, ":CURR:DC:NPLC 10", description="10 NPLC (quieter)"),
            ],
        ),
        Preset(
            id="sa_2g4",
            name="2.4 GHz ISM sweep",
            instrument="sa",
            testing_for="Wi-Fi/BLE activity across the 2.4 GHz ISM band (center 2.44 GHz, 100 MHz span).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":FREQ:CENT 2.44e9", verify_query=":FREQ:CENT?", expected=2.44e9, description="center 2.44 GHz"),
                PresetStep(OpType.CONFIGURE, ":FREQ:SPAN 100e6", verify_query=":FREQ:SPAN?", expected=100e6, description="span 100 MHz"),
            ],
        ),
        Preset(
            id="sa_harmonics",
            name="Harmonics @ 10 MHz",
            instrument="sa",
            testing_for="Fundamental + harmonics of a 10 MHz clock/oscillator (wide 60 MHz span).",
            steps=[
                PresetStep(OpType.CONFIGURE, ":FREQ:CENT 30e6", verify_query=":FREQ:CENT?", expected=30e6, description="center 30 MHz"),
                PresetStep(OpType.CONFIGURE, ":FREQ:SPAN 60e6", verify_query=":FREQ:SPAN?", expected=60e6, description="span 60 MHz"),
            ],
        ),
        Preset(
            id="sa_spur",
            name="Spur search @ 100 MHz",
            instrument="sa",
            testing_for="Unexpected spurs/emissions around 100 MHz over a 50 MHz span.",
            steps=[
                PresetStep(OpType.CONFIGURE, ":FREQ:CENT 100e6", verify_query=":FREQ:CENT?", expected=100e6, description="center 100 MHz"),
                PresetStep(OpType.CONFIGURE, ":FREQ:SPAN 50e6", verify_query=":FREQ:SPAN?", expected=50e6, description="span 50 MHz"),
            ],
        ),
        Preset(
            id="psu_3v3_rail",
            name="3.3 V rail bring-up",
            instrument="psu",
            testing_for="Energize a 3.3 V rail at up to 0.5 A with OVP/OCP set first. ENERGIZES THE DUT.",
            requires_envelope=True,
            requires_confirm=True,
            suggested_envelope={"max_voltage": 3.6, "max_current": 0.6},
            steps=[
                PresetStep(OpType.SET_PROTECTION, ":VOLT:PROT 3.6", verify_query=":VOLT:PROT?", expected=3.6, description="OVP = 3.6 V"),
                PresetStep(OpType.SET_PROTECTION, ":CURR:PROT 0.6", verify_query=":CURR:PROT?", expected=0.6, description="OCP = 0.6 A"),
                PresetStep(OpType.SET_LEVEL, ":VOLT 3.3", capability=Capability.SOURCE_CONTROL, params={"voltage": 3.3}, verify_query=":VOLT?", expected=3.3, description="Vset = 3.3 V"),
                PresetStep(OpType.SET_LEVEL, ":CURR 0.5", capability=Capability.SOURCE_CONTROL, params={"current": 0.5}, verify_query=":CURR?", expected=0.5, description="Ilim = 0.5 A"),
                PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL, description="enable output (last)"),
            ],
        ),
        Preset(
            id="psu_5v_rail",
            name="5 V rail bring-up",
            instrument="psu",
            testing_for="Energize a 5 V rail at up to 1 A with OVP/OCP set first. ENERGIZES THE DUT.",
            requires_envelope=True,
            requires_confirm=True,
            suggested_envelope={"max_voltage": 5.5, "max_current": 1.1},
            steps=[
                PresetStep(OpType.SET_PROTECTION, ":VOLT:PROT 5.5", verify_query=":VOLT:PROT?", expected=5.5, description="OVP = 5.5 V"),
                PresetStep(OpType.SET_PROTECTION, ":CURR:PROT 1.1", verify_query=":CURR:PROT?", expected=1.1, description="OCP = 1.1 A"),
                PresetStep(OpType.SET_LEVEL, ":VOLT 5.0", capability=Capability.SOURCE_CONTROL, params={"voltage": 5.0}, verify_query=":VOLT?", expected=5.0, description="Vset = 5.0 V"),
                PresetStep(OpType.SET_LEVEL, ":CURR 1.0", capability=Capability.SOURCE_CONTROL, params={"current": 1.0}, verify_query=":CURR?", expected=1.0, description="Ilim = 1.0 A"),
                PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL, description="enable output (last)"),
            ],
        ),
    ]
    return {p.id: p for p in presets}
