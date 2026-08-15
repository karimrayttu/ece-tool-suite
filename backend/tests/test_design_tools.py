"""Design-tool integration: tool detection, CubeMX .ioc parse/edit, power-stage math."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ece_suite import design_tools as D
from ece_suite import main as _main

IOC = """#MicroXplorer Configuration
Mcu.Family=STM32G4
Mcu.Name=STM32G474R(B-C-E)Tx
Mcu.UserName=STM32G474RETx
ProjectManager.DeviceId=STM32G474RETx
Mcu.IP0=ADC1
Mcu.IP1=TIM2
Mcu.IP2=USART2
PA0.Signal=ADC1_IN1
PA0.GPIO_Label=I_SENSE
PA15.Signal=TIM2_CH1
PB2.Signal=GPIO_Output
PB2.GPIO_Label=MOT_DIR
TIM2.Prescaler=170
TIM2.Period=1000
"""


def test_detect_tools_catalog_complete():
    tools = D.detect_tools()
    ids = {t["id"] for t in tools}
    assert {"cubemx", "cubeprog", "powerstage", "uniflash", "kicad", "altium", "ltspice"} <= ids
    for t in tools:
        assert set(t) >= {"id", "name", "kind", "installed", "path", "launchable"}


def test_resolve_skips_uninstall():
    # the resolver must never pick an uninstaller as the launch target
    for t in D.detect_tools():
        if t["path"]:
            assert not t["path"].lower().split("\\")[-1].startswith("uninstall")


def test_parse_ioc():
    p = D.parse_ioc(IOC)
    assert p["mcu"] == "STM32G474RETx" and p["family"] == "STM32G4"
    assert "ADC1" in p["peripherals"] and "TIM2" in p["peripherals"]
    pa0 = next(x for x in p["pins"] if x["pin"] == "PA0")
    assert pa0["signal"] == "ADC1_IN1" and pa0["label"] == "I_SENSE"
    tim2 = next(t for t in p["timers"] if t["name"] == "TIM2")
    assert tim2["params"]["Prescaler"] == "170" and tim2["params"]["Period"] == "1000"


def test_apply_ioc_edits_roundtrip():
    edited = D.apply_ioc_edits(IOC, {"PB2.GPIO_Label": "MOTOR_DIR", "TIM2.Prescaler": "84",
                                     "PA0.GPIO_PuPd": "GPIO_PULLUP", "Mcu.IP2": None})
    p = D.parse_ioc(edited)
    assert next(x for x in p["pins"] if x["pin"] == "PB2")["label"] == "MOTOR_DIR"
    assert next(t for t in p["timers"] if t["name"] == "TIM2")["params"]["Prescaler"] == "84"
    assert "USART2" not in p["peripherals"]        # deleted
    assert "GPIO_PULLUP" in edited                  # appended new key


def test_power_stage_math():
    b = D.buck_stage(12, 3.3, 2)
    assert abs(b["duty_pct"] - 27.5) < 0.1 and b["inductor_uH"] > 0
    bo = D.boost_stage(5, 12, 1)
    assert abs(bo["duty_pct"] - 58.33) < 0.1
    assert "webench.ti.com" in D.webench_url(9, 16, 3.3, 3) and "O1V=3.3" in D.webench_url(9, 16, 3.3, 3)


def test_endpoints():
    c = TestClient(_main.app)
    assert "tools" in c.get("/api/tools/detect").json()
    p = c.post("/api/ioc/parse", json={"text": IOC}).json()
    assert p["ok"] and p["mcu"] == "STM32G474RETx"
    e = c.post("/api/ioc/edit", json={"text": IOC, "edits": {"TIM2.Period": "2000"}}).json()
    assert e["ok"] and "TIM2.Period=2000" in e["text"]
    assert c.get("/api/power/buck", params={"vin": 12, "vout": 3.3, "iout": 2}).json()["ok"]
