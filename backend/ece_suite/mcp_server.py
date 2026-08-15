"""Standalone MCP server — drive the ECE Tool Suite bench from any MCP client.

This is the "expose my instruments to an AI agent" pattern (à la the LeCroy / pymcuprog MCP
servers), but pointed at the whole app: whatever multi-vendor gear the running suite has
connected (Keysight / Fluke / Tektronix / Rigol / Siglent scope + DMM + spectrum + sources)
plus its decoders and design calculators.

It is a thin **stdio** MCP server that calls the running app's REST backend on localhost, so
instruments stay owned by the app (one lock, the same safety posture). Add it to Claude
Desktop / Claude Code with:

    {
      "mcpServers": {
        "ece-tool-suite": {
          "command": "<install-dir>\\\\backend\\\\.venv\\\\Scripts\\\\python.exe",
          "args": ["-m", "ece_suite.mcp_server"],
          "env": { "ECE_SUITE_URL": "http://127.0.0.1:8848" }
        }
      }
    }

(<install-dir> is wherever the suite lives; a packaged install uses backend\\runtime\\python.exe
instead of the dev venv. Don't hand-write this — the app's Connections tab / GET /api/mcp/info
returns a ready-to-paste config built from the actual interpreter path.)

Run the ECE Tool Suite first (the sidecar must be up); then the agent can list instruments,
auto-connect, measure, send SCPI, and run calculators.
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("ECE_SUITE_URL", "http://127.0.0.1:8848")
_TIMEOUT = 20.0

mcp = FastMCP("ece-tool-suite")


def _get(path: str, **params) -> dict:
    try:
        r = httpx.get(f"{BASE}{path}", params=params or None, timeout=_TIMEOUT)
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"cannot reach the ECE Tool Suite at {BASE} ({e}). Is the app running?"}


def _post(path: str, body: dict | None = None) -> dict:
    try:
        r = httpx.post(f"{BASE}{path}", json=body or {}, timeout=_TIMEOUT)
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"cannot reach the ECE Tool Suite at {BASE} ({e}). Is the app running?"}


@mcp.tool()
def list_instruments() -> dict:
    """List the bench instruments the app currently has connected, with vendor/model/provenance."""
    return _get("/health").get("instruments", {"error": "no data"})


@mcp.tool()
def io_environment() -> dict:
    """What's plugged in and whether the VISA layer can drive it (drivability + install hints)."""
    return _get("/api/io/environment")


@mcp.tool()
def autoconnect(lan: bool = False) -> dict:
    """Discover and connect instruments, assigning each to its role (scope/dmm/sa/psu/awg/eload).
    Set lan=True to also sweep the network via mDNS/LXI."""
    return _post(f"/api/io/autoconnect{'?lan=1' if lan else ''}")


@mcp.tool()
def scope_measure(ch: int = 1) -> dict:
    """Full oscilloscope measurement set (Vpp/Vrms/freq/period/duty/rise/fall…) for a channel."""
    return _get("/api/scope/measure", ch=ch)


@mcp.tool()
def dmm_read() -> dict:
    """Take one multimeter reading (value + unit + function) from the connected DMM."""
    return _get("/api/dmm/read")


@mcp.tool()
def spectrum_peak() -> dict:
    """Return the spectrum analyzer's peak marker (frequency + amplitude), via a raw query."""
    mk = scpi("sa", ":CALC:MARK:MAX", write=True)
    if mk.get("ok") is False:
        return mk
    freq = scpi("sa", ":CALC:MARK:X?")
    amp = scpi("sa", ":CALC:MARK:Y?")
    return {"freq_hz": freq.get("response"), "amp_dbm": amp.get("response")}


@mcp.tool()
def scpi(role: str, command: str, write: bool = False) -> dict:
    """Send a raw SCPI command to a connected instrument (role = scope/dmm/sa/psu/awg/eload).

    By default this is a QUERY and returns the instrument's response. Pass write=True to send a
    command that has no response. WARNING: raw writes bypass the app's safety gates — an
    output-enable or level command can energize your DUT. Every command is audit-logged.
    """
    return _post("/api/io/scpi", {"role": role, "command": command, "query": not write})


@mcp.tool()
def list_calculators() -> dict:
    """List the built-in EE design calculators and their input fields."""
    return _get("/api/calc")


@mcp.tool()
def run_calculator(name: str, params: dict) -> dict:
    """Run a design calculator by id (e.g. 'trace_width', 'led_resistor', 'lc_resonant') with
    its numeric params. Use list_calculators() to see ids and fields."""
    return _post(f"/api/calc/{name}", params)


@mcp.tool()
def detect_design_tools() -> dict:
    """Which EDA/MCU/power design tools are installed on this PC (CubeMX, CubeProgrammer, TI
    Power Stage Designer, UniFlash, CCS, KiCad, Altium, LTspice) with their paths."""
    return _get("/api/tools/detect")


@mcp.tool()
def parse_cubemx_ioc(ioc_text: str) -> dict:
    """Parse a STM32CubeMX .ioc project: MCU, peripherals, pin assignments (signal/mux + GPIO
    label) and timer configs. Pass the .ioc file contents."""
    return _post("/api/ioc/parse", {"text": ioc_text})


@mcp.tool()
def power_stage(topology: str, vin: float, vout: float, iout: float,
                fsw_khz: float = 500.0, ripple_pct: float = 30.0) -> dict:
    """Buck or boost power-stage design: duty, inductor, peak/input current, output cap."""
    t = "boost" if topology.lower().startswith("boost") else "buck"
    return _get(f"/api/power/{t}", vin=vin, vout=vout, iout=iout, fsw_khz=fsw_khz, ripple_pct=ripple_pct)


@mcp.tool()
def power_verify(topology: str, vin: float, vout: float, iout: float, L_uH: float,
                Cout_uF: float, fsw_khz: float = 500.0) -> dict:
    """Verify a buck/boost power-stage design by running a transient SPICE sim (LTspice/ngspice)
    and checking measured output ripple, inductor-ripple % and efficiency against targets.
    Returns PASS/FAIL per check plus the measured metrics."""
    return _post("/api/spice/verify", {"topology": topology, "vin": vin, "vout": vout, "iout": iout,
                                       "L_uH": L_uH, "Cout_uF": Cout_uF, "fsw_khz": fsw_khz})


@mcp.tool()
def power_design(vin: float, vout: float, iout: float,
                 fsw_khz: float = 500.0, ripple_pct: float = 30.0, isolated: bool = False) -> dict:
    """WEBENCH-class native power designer: auto-selects the topology (buck/boost/buck-boost/
    LDO; flyback when isolated=True — isolation is an explicit input, not inferred) for the
    Vin/Vout/Iout envelope, returns candidate real TI ICs with datasheet links, passive sizing,
    and a type-II compensation starting point. Verify the chosen sizing with power_verify
    before trusting it."""
    return _get("/api/power/design", vin=vin, vout=vout, iout=iout, fsw_khz=fsw_khz,
                ripple_pct=ripple_pct, isolated=isolated)


@mcp.tool()
def power_loop_verify(vin: float, vout: float, iout: float, L_uH: float, Cout_uF: float,
                      fsw_khz: float = 500.0, esr_mohm: float = 10.0, ri_ohm: float = 0.1,
                      vref_v: float = 0.8) -> dict:
    """Closed-loop stability check (python-control): builds the current-mode buck loop with the
    designed type-II compensator and returns the ACHIEVED crossover, phase margin and gain margin
    (PASS/FAIL). Ri/Vref are IC-specific modeling assumptions — a design-review sanity check, not a
    measured margin; confirm on the bench."""
    return _post("/api/power/loop", {"vin": vin, "vout": vout, "iout": iout, "L_uH": L_uH,
                                     "Cout_uF": Cout_uF, "fsw_khz": fsw_khz, "esr_mohm": esr_mohm,
                                     "ri_ohm": ri_ohm, "vref_v": vref_v})


@mcp.tool()
def magnetics_advise(inductance_uH: float, i_dc: float, i_ripple_pp: float,
                     fsw_khz: float = 500.0, ambient_c: float = 25.0) -> dict:
    """OpenMagnetics/MKF magnetics design: searches a real multi-vendor core/material/wire DB for an
    inductor of the given inductance carrying a DC-biased triangular current, returns the top core +
    winding designs with physics-computed core (Steinmetz/iGSE) and copper (skin/proximity) losses.
    A datasheet-grade starting point — verify saturation/thermal margin against the core datasheet."""
    return _post("/api/power/magnetics", {"inductance_uH": inductance_uH, "i_dc": i_dc,
                                          "i_ripple_pp": i_ripple_pp, "fsw_khz": fsw_khz, "ambient_c": ambient_c})


@mcp.tool()
def capacitor_bank(topology: str, vin: float, vout: float, iout: float, fsw_khz: float = 500.0,
                   c_each_uF: float = 22.0, esr_each_mohm: float = 5.0, irms_each_a: float = 2.0,
                   vrated: float = 25.0, dielectric: str = "mlcc") -> dict:
    """Size input+output capacitor banks for a buck/boost stage on a candidate cap: RMS ripple
    current, parallel-count for ripple + capacitance, ESR loss, temperature rise, output/input
    ripple voltage, and voltage-derating PASS/FAIL. First-order model — verify vs the cap datasheet."""
    return _post("/api/power/capacitors", {"topology": topology, "vin": vin, "vout": vout, "iout": iout,
                                           "fsw_khz": fsw_khz, "c_each_uF": c_each_uF,
                                           "esr_each_mohm": esr_each_mohm, "irms_each_a": irms_each_a,
                                           "vrated": vrated, "dielectric": dielectric})


@mcp.tool()
def mcu_status() -> dict:
    """Connected MCU debuggers/programmers (Curiosity Nano / Atmel-ICE / SNAP / PICkit) + count
    of supported devices. pymcuprog-backed."""
    return _get("/api/mcu/status")


@mcp.tool()
def mcu_device_info(device: str) -> dict:
    """Flash/EEPROM size, architecture and programming interface for a supported MCU
    (e.g. 'atmega4809', 'attiny1616')."""
    return _get(f"/api/mcu/device/{device}")


@mcp.tool()
def mcu_read_firmware(device: str, memory: str = "flash") -> dict:
    """Dump a target MCU's flash (firmware) through an attached debugger. Returns the byte count,
    device ID, supply voltage and Intel-HEX text. Requires a debugger + target wired up."""
    return _post("/api/mcu/read", {"device": device, "memory": memory})


@mcp.tool()
def decode_logic(protocol: str, sample_rate: float, channels: dict,
                 mapping: dict, options: dict | None = None) -> dict:
    """Decode captured digital channels as SPI / I2C / UART. `channels` maps a name to a list of
    0/1 samples; `mapping` maps protocol roles (clk/mosi/… or scl/sda or rx) to channel names."""
    return _post("/api/logic/decode", {"protocol": protocol, "sample_rate": sample_rate,
                                        "channels": channels, "mapping": mapping,
                                        "options": options or {}})


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
