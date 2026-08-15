"""EDA / MCU toolchain integration — detect and launch the design tools installed on this PC,
parse & edit STM32CubeMX ``.ioc`` projects (pinout / mux / timers), and bridge to TI's power
design tools.

Honest scope:
* CubeMX ``.ioc`` is a flat ``key=value`` properties file — fully parseable/editable here.
* Local tools (CubeMX, CubeProgrammer, CubeIDE, Power Stage Designer, UniFlash, CCS, KiCad,
  Altium, LTspice) can be detected on disk and launched.
* TI **WEBENCH** Power/Analog "bench" tools are a proprietary online service with no public
  API — they cannot be embedded offline. We reimplement the core power-stage math natively and
  provide a pre-filled deep link into WEBENCH.
"""

from __future__ import annotations

import glob
import os
import re
from urllib.parse import urlencode

from . import shell_open

# --- tool catalog: id -> (display name, kind, candidate paths [globs]) ----------
_CANDIDATES: dict[str, tuple[str, str, list[str]]] = {
    "cubemx": ("STM32CubeMX", "stm32", [
        r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeMX\STM32CubeMX.exe",
        r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeMX\STM32CubeMX.exe"]),
    "cubeprog": ("STM32CubeProgrammer", "stm32", [
        r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32CubeProgrammer.exe"]),
    "cubeide": ("STM32CubeIDE", "stm32", [r"C:\ST\STM32CubeIDE_*\STM32CubeIDE\stm32cubeide.exe"]),
    "cubeclt": ("STM32CubeCLT", "stm32", [r"C:\ST\STM32CubeCLT_*"]),
    "powerstage": ("TI Power Stage Designer", "ti-power", [
        r"C:\Program Files\Power Stage Designer*\Power Stage Designer*.lnk",
        r"C:\Program Files\Power Stage Designer*\bin\*.exe",
        r"C:\Program Files\Power Stage Designer*\*.exe"]),
    "uniflash": ("TI UniFlash", "ti-mcu", [
        r"C:\ti\uniflash_*\uniflash.exe", r"C:\ti\uniflash_*\node-webkit\nw.exe",
        r"C:\ti\uniflash_*"]),
    "ccs": ("TI Code Composer Studio", "ti-mcu", [r"C:\ti\ccs*\ccs\eclipse\ccstudio.exe"]),
    "kicad": ("KiCad", "eda", [r"C:\Program Files\KiCad\*\bin\kicad.exe"]),
    "altium": ("Altium Designer", "eda", [r"C:\Program Files\Altium\AD*\X2.EXE"]),
    "ltspice": ("LTspice", "sim", [
        r"C:\Program Files\ADI\LTspice\LTspice.exe", r"C:\Program Files\LTC\LTspice*\XVIIx64.exe"]),
    "ngspice": ("ngspice", "sim", [r"C:\Program Files\ngspice*\bin\ngspice.exe"]),
}


def _resolve(paths: list[str]) -> str | None:
    for p in paths:
        if any(c in p for c in "*?"):
            hits = [h for h in sorted(glob.glob(p))
                    if not os.path.basename(h).lower().startswith("uninstall")]
            if hits:
                return hits[-1]  # newest-ish (glob sorts lexically; version dirs sort up)
        elif os.path.exists(p):
            return p
    return None


def detect_tools() -> list[dict]:
    """Which design tools are installed on this PC (path + launchable)."""
    out: list[dict] = []
    for tid, (name, kind, paths) in _CANDIDATES.items():
        path = _resolve(paths)
        out.append({"id": tid, "name": name, "kind": kind,
                    "installed": bool(path), "path": path,
                    "launchable": bool(path and path.lower().endswith((".exe", ".lnk")))})
    return out


def launch_tool(tool_id: str) -> dict:
    """Open an installed tool the way a double-click would (.exe/.lnk)."""
    match = next((t for t in detect_tools() if t["id"] == tool_id), None)
    if not match or not match["installed"]:
        return {"ok": False, "error": f"{tool_id} is not installed"}
    if not match["launchable"]:
        return {"ok": False, "error": f"{match['name']} found at {match['path']} but no runnable exe"}
    try:
        shell_open.open_path(match["path"])
        return {"ok": True, "launched": match["name"], "path": match["path"]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# --- STM32CubeMX .ioc parsing + editing (pinout / mux / timers) ----------------
_PIN_RE = re.compile(r"^(P[A-Z]\d+)\.(\w+)$")
_TIM_RE = re.compile(r"^(TIM\d+)\.(.+)$")
_IP_RE = re.compile(r"^Mcu\.IP\d+$")


def parse_ioc(text: str) -> dict:
    kv: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv.append((k.strip(), v.strip()))
    d = dict(kv)

    pins: dict[str, dict] = {}
    timers: dict[str, dict] = {}
    peripherals: list[str] = []
    for k, v in kv:
        mp = _PIN_RE.match(k)
        if mp:
            pins.setdefault(mp.group(1), {})[mp.group(2)] = v
            continue
        mt = _TIM_RE.match(k)
        if mt:
            timers.setdefault(mt.group(1), {})[mt.group(2)] = v
            continue
        if _IP_RE.match(k):
            peripherals.append(v)

    pin_list = [{"pin": p, "signal": a.get("Signal", ""), "mode": a.get("Mode", ""),
                 "label": a.get("GPIO_Label", ""), "pupd": a.get("GPIO_PuPd", "")}
                for p, a in sorted(pins.items()) if a.get("Signal") or a.get("GPIO_Label")]
    timer_list = [{"name": t, "params": prm} for t, prm in sorted(timers.items())]

    return {
        "mcu": d.get("Mcu.UserName") or d.get("ProjectManager.DeviceId") or d.get("Mcu.Name", ""),
        "family": d.get("Mcu.Family", ""),
        "project": d.get("ProjectManager.ProjectName", ""),
        "pins": pin_list,
        "peripherals": sorted(set(peripherals)),
        "timers": timer_list,
        "n_keys": len(kv),
    }


def apply_ioc_edits(text: str, edits: dict[str, str | None]) -> str:
    """Return a new .ioc text with edits applied. edits={key: value}; value None deletes the key;
    new keys are appended. Existing line order is preserved."""
    remaining = dict(edits)
    out: list[str] = []
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in remaining:
                val = remaining.pop(k)
                if val is None:
                    continue  # delete
                out.append(f"{k}={val}")
                continue
        out.append(line)
    for k, v in remaining.items():  # appended new keys
        if v is not None:
            out.append(f"{k}={v}")
    return "\n".join(out) + "\n"


# --- TI power-stage math (Power Stage Designer function, reimplemented) + WEBENCH link ---
def buck_stage(vin: float, vout: float, iout: float, fsw_khz: float = 500.0,
               ripple_pct: float = 30.0, vf_diode: float = 0.0) -> dict:
    """Synchronous/async buck power-stage design (CCM)."""
    if not (0 < vout < vin):
        raise ValueError("require 0 < Vout < Vin")
    fsw = fsw_khz * 1e3
    d = (vout + vf_diode) / vin
    di = ripple_pct / 100.0 * iout
    L = (vout * (vin - vout)) / (vin * fsw * di) if di > 0 else float("inf")
    ipk = iout + di / 2.0
    cout = di / (8 * fsw * (0.01 * vout)) if vout > 0 else 0.0     # for 1% Vout ripple
    return {"topology": "buck", "duty_pct": round(d * 100, 2),
            "inductor_uH": round(L * 1e6, 3), "ripple_current_A": round(di, 4),
            "peak_current_A": round(ipk, 4),
            "output_cap_uF_for_1pct": round(cout * 1e6, 2),
            "note": f"CCM, fsw={fsw_khz} kHz, dIL={ripple_pct}% of Iout"}


def boost_stage(vin: float, vout: float, iout: float, fsw_khz: float = 500.0,
                ripple_pct: float = 30.0) -> dict:
    """Boost power-stage design (CCM)."""
    if not (0 < vin < vout):
        raise ValueError("require 0 < Vin < Vout")
    fsw = fsw_khz * 1e3
    d = 1.0 - vin / vout
    iin = iout / (1.0 - d) if d < 1 else float("inf")
    di = ripple_pct / 100.0 * iin
    L = (vin * d) / (fsw * di) if di > 0 else float("inf")
    cout = (iout * d) / (fsw * 0.01 * vout) if vout > 0 else 0.0
    return {"topology": "boost", "duty_pct": round(d * 100, 2),
            "input_current_A": round(iin, 4), "inductor_uH": round(L * 1e6, 3),
            "peak_current_A": round(iin + di / 2, 4),
            "output_cap_uF_for_1pct": round(cout * 1e6, 2),
            "note": f"CCM, fsw={fsw_khz} kHz, input ripple {ripple_pct}%"}


def webench_url(vin_min: float, vin_max: float, vout: float, iout: float) -> str:
    """A pre-filled deep link into TI WEBENCH Power Designer (opens in the browser — WEBENCH is
    an online tool and can't be embedded offline)."""
    q = urlencode({"VinMin": vin_min, "VinMax": vin_max, "O1V": vout, "O1I": iout})
    return f"https://webench.ti.com/power-designer/switching-regulator?{q}"
