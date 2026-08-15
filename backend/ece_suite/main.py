"""FastAPI sidecar — hardware-first (Keysight over VISA).

The running app talks to REAL Keysight instruments: it starts with every role disconnected
and you connect a scope / DMM / spectrum analyzer by VISA resource (system VISA / Keysight IO
Libraries first, pyvisa-py fallback; USB + LAN). There is NO simulator in this runtime —
the SimXxx classes exist only for the automated test suite, which connects them via
`manager.set(...)`.

Provenance still rides every reading: a fresh connection is UNVERIFIED_HW until the lab-truth
gate (`*IDN?` + read-back) promotes it to VERIFIED_HW.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import (
    __version__,
    calculators,
    can_decode,
    kicad_analyze,
    logic_decode,
    mcp_bridge,
    parts,
    shell_open,
)
from .assistant import Assistant
from .audit import AuditLog
from .datalog import Recorder
from .instruments.dmm import make_dmm
from .instruments.keysight import KeysightScope, KeysightSpectrumAnalyzer
from .instruments.manager import InstrumentManager
from .instruments.preamble import parse_definite_length_block
from .instruments.scope_drivers import make_scope
from .instruments.scpi import drain_error_queue, safe_float
from .instruments.transport import Transport, VisaTransport
from .presets import PresetRunner, PresetStep
from .presets_library import Preset, build_presets
from .provenance import Reading, to_wire
from .registry import Capability, Surface, ToolRegistry, ToolSpec
from .safety import DUTSafetyEnvelope, OpType, RatingModel, SafetyInvariantEngine

# --- app singletons (hardware-first: everything starts disconnected) ------
DATA_DIR = Path(os.environ.get("ECE_SUITE_DATA", Path.home() / ".ece-suite"))
audit = AuditLog(DATA_DIR / "audit.log.jsonl")

manager = InstrumentManager(
    {"scope": None, "dmm": None, "sa": None, "psu": None, "awg": None, "eload": None}, audit=audit
)
engine = SafetyInvariantEngine()
registry = ToolRegistry()
recorder = Recorder()


def _apply_env_resources() -> None:
    """Auto-connect any instrument whose ECE_SUITE_<ROLE>_RESOURCE env var is set."""
    for role in ("scope", "dmm", "sa", "psu", "awg", "eload"):
        res = os.environ.get(f"ECE_SUITE_{role.upper()}_RESOURCE")
        if res:
            try:
                manager.connect_visa(role, res)
            except Exception as e:  # noqa: BLE001
                audit.record("startup_connect_failed", role=role, resource=res, error=str(e))


_apply_env_resources()


# --- driver helpers -------------------------------------------------------
def scope_driver() -> KeysightScope | None:
    t = manager.get("scope")
    return make_scope(t, engine) if t is not None else None


def dmm_driver():
    t = manager.get("dmm")
    return make_dmm(t) if t is not None else None


def sa_driver() -> KeysightSpectrumAnalyzer | None:
    t = manager.get("sa")
    return KeysightSpectrumAnalyzer(t) if t is not None else None


def _require(role: str) -> Transport:
    t = manager.get(role)
    if t is None:
        raise RuntimeError(f"{role} not connected — connect a Keysight instrument first")
    return t


# --- registry tools (used by chatbox + agent; error honestly if disconnected) ----
def _scope_capture() -> dict:
    wf = KeysightScope(_require("scope"), engine).capture(1)
    out = to_wire(wf)
    out["provenance"] = wf.provenance.value
    return out


def _scope_measure_vpp() -> dict:
    t = _require("scope")
    r = Reading(KeysightScope(t, engine).measure_vpp(1), "V", t.default_provenance, source="CHAN1")
    out = to_wire(r)
    out["provenance"] = r.provenance.value
    return out


def _dmm_measure_vdc() -> dict:
    t = _require("dmm")
    d = make_dmm(t)
    d.configure("VDC")
    val = d.read()["value"]
    r = Reading(val if val is not None else float("nan"), "V", t.default_provenance, source="DMM:VDC")
    out = to_wire(r)
    out["provenance"] = r.provenance.value
    return out


def _sa_peak() -> dict:
    t = _require("sa")
    pk = KeysightSpectrumAnalyzer(t).marker_peak()
    r = Reading(pk["amp"] if pk["amp"] is not None else float("nan"), "dBm",
                t.default_provenance, source="SA:peak", meta={"freq_hz": pk["freq"]})
    out = to_wire(r)
    out["provenance"] = r.provenance.value
    return out


def _psu_apply_preset(voltage, current, ovp, ocp, dut_max_v, dut_max_i, confirm=False) -> dict:
    t = _require("psu")
    env = DUTSafetyEnvelope(max_voltage=dut_max_v, max_current=dut_max_i)
    rating = RatingModel(max_output_voltage=30.0, max_output_current=5.0)
    runner = PresetRunner(t, engine, instrument="psu", audit=audit)
    res = runner.run(build_presets()["psu_3v3_rail"].steps, envelope=env, rating=rating, confirm=confirm)
    return {"ok": res.ok, "provenance": res.provenance, "summary": res.summary, "rolled_back": res.rolled_back,
            "steps": [{"description": s.description, "verdict": s.verdict, "executed": s.executed,
                       "verified": s.verified, "error": s.error} for s in res.steps]}


registry.register(ToolSpec("scope_capture", "Capture one CHAN1 waveform.", _scope_capture, Capability.READ_INSTRUMENT))
registry.register(ToolSpec("scope_measure_vpp", "Measure CHAN1 peak-to-peak voltage.", _scope_measure_vpp, Capability.READ_INSTRUMENT))
registry.register(ToolSpec("dmm_measure_vdc", "Measure DC volts on the DMM.", _dmm_measure_vdc, Capability.READ_INSTRUMENT))
registry.register(ToolSpec("sa_peak", "Spectrum-analyzer peak (frequency + amplitude).", _sa_peak, Capability.READ_INSTRUMENT))
registry.register(ToolSpec(
    "psu_apply_preset", "Configure + enable the PSU 3.3 V rail via a safety-gated preset.",
    _psu_apply_preset, Capability.SOURCE_CONTROL, confirm_required=True,
    input_schema={"type": "object", "properties": {
        "voltage": {"type": "number"}, "current": {"type": "number"}, "ovp": {"type": "number"},
        "ocp": {"type": "number"}, "dut_max_v": {"type": "number"}, "dut_max_i": {"type": "number"},
        "confirm": {"type": "boolean"}},
        "required": ["voltage", "current", "ovp", "ocp", "dut_max_v", "dut_max_i"]},
))


# --- RTL / HDL analysis tools (pure software: safe on every surface) -------
# Registering these on the shared registry lets BOTH the in-app chatbox and the autonomous
# MCP bridge write RTL and get it graded by the real toolchain — the GenAI-with-ground-truth
# loop. They are ANALYZE (never energize a DUT) and carry no instrument provenance.
def _rtl_lint_tool(source: str, language: str = "systemverilog", top: str | None = None) -> dict:
    from . import rtl
    return rtl.lint(source, language, top=top)


def _rtl_sim_tool(source: str, testbench: str, language: str = "systemverilog",
                  top: str | None = None) -> dict:
    from . import rtl
    return rtl.simulate(source, testbench, language, top=top)


def _rtl_fpga_tool(source: str, family: str = "ice40", language: str = "systemverilog",
                   top: str | None = None) -> dict:
    from . import rtl
    return rtl.fpga_synth(source, family, language, top=top)


registry.register(ToolSpec(
    "rtl_lint",
    "Lint Verilog/SystemVerilog/VHDL RTL with the real toolchain (Verilator / Icarus / GHDL); "
    "returns structured error+warning diagnostics with file/line/message.",
    _rtl_lint_tool, Capability.ANALYZE, provenance_bearing=False,
    input_schema={"type": "object", "properties": {
        "source": {"type": "string", "description": "the RTL module source"},
        "language": {"type": "string", "enum": ["verilog", "systemverilog", "vhdl"]},
        "top": {"type": "string"}}, "required": ["source"]}))
registry.register(ToolSpec(
    "rtl_simulate",
    "Compile a DUT + testbench and run it (Icarus vvp / GHDL); returns simulator stdout, a "
    "pass/fail verdict and any dumped VCD signals. The testbench decides pass/fail.",
    _rtl_sim_tool, Capability.ANALYZE, provenance_bearing=False,
    input_schema={"type": "object", "properties": {
        "source": {"type": "string"}, "testbench": {"type": "string"},
        "language": {"type": "string", "enum": ["verilog", "systemverilog", "vhdl"]},
        "top": {"type": "string"}}, "required": ["source", "testbench"]}))
registry.register(ToolSpec(
    "rtl_fpga_synth",
    "Synthesize Verilog/SystemVerilog to a real FPGA family (iCE40/ECP5/MachXO2/Gowin via "
    "Yosys) and report device utilization (LUTs, FFs, BRAM, DSP, carry, IO).",
    _rtl_fpga_tool, Capability.ANALYZE, provenance_bearing=False,
    input_schema={"type": "object", "properties": {
        "source": {"type": "string"},
        "family": {"type": "string", "enum": ["ice40", "ecp5", "machxo2", "gowin"]},
        "language": {"type": "string", "enum": ["verilog", "systemverilog"]},
        "top": {"type": "string"}}, "required": ["source"]}))

PRESETS: dict[str, Preset] = build_presets()


# --- request models -------------------------------------------------------
class ConnectIn(BaseModel):
    resource: str = ""
    backend: str | None = None  # "system" | "@py" | None=auto
    # optional: build the VISA resource from a friendly address + interface
    host: str | None = None
    interface: str | None = None   # lan | socket | hislip | usb | serial | gpib
    port: int | None = None        # raw-socket port (default 5025)
    vendor_hint: str | None = None # explicit brand pick ("auto" = *IDN? detection)


def build_visa_resource(host: str, interface: str, port: int | None = None) -> str:
    """Turn a friendly (host/address, interface) into a VISA resource string.

    Mirrors the interface choices in Keysight Connection Expert: LAN (VXI-11/INSTR), LAN raw
    socket, LAN HiSLIP, USB, RS-232 serial and GPIB.
    """
    iface = (interface or "lan").lower()
    host = host.strip()
    if iface in ("lan", "vxi11", "vxi-11", "instr"):
        return f"TCPIP0::{host}::inst0::INSTR"
    if iface in ("socket", "raw", "scpi-raw"):
        return f"TCPIP0::{host}::{port or 5025}::SOCKET"
    if iface in ("hislip", "hs"):
        return f"TCPIP0::{host}::hislip0::INSTR"
    if iface == "serial":
        # host is the COM port name/number, e.g. "COM3" or "3"
        return f"ASRL{host.replace('COM', '') or host}::INSTR" if host.upper().startswith("COM") or host.isdigit() else host
    if iface == "gpib":
        return f"GPIB0::{host}::INSTR"
    # usb (host already a full USB resource) or anything pre-formed
    return host


class ScopeChannelIn(BaseModel):
    ch: int
    enabled: bool | None = None
    scale: float | None = None
    offset: float | None = None
    coupling: str | None = None
    probe: float | None = None
    bwlimit: bool | None = None
    invert: bool | None = None
    label: str | None = None
    unit: str | None = None


class ScopeConfigIn(BaseModel):
    channels: list[ScopeChannelIn] = []
    timebase_scale: float | None = None
    timebase_position: float | None = None
    timebase_reference: str | None = None
    trig_mode: str | None = None
    trig_source: str | None = None
    trig_level: float | None = None
    trig_slope: str | None = None
    trig_coupling: str | None = None
    trig_holdoff: float | None = None
    trig_sweep: str | None = None
    acq_type: str | None = None
    acq_count: int | None = None
    acq_points: int | None = None
    run: str | None = None  # run | stop | single


class DmmConfigIn(BaseModel):
    function: str
    range: str | float = "AUTO"
    nplc: float | None = None
    math: str | None = None       # OFF | NULL | DB | DBM
    autozero: bool | None = None


class SaConfigIn(BaseModel):
    center: float | None = None
    span: float | None = None
    start: float | None = None
    stop: float | None = None
    rbw: float | None = None
    vbw: float | None = None
    rbw_auto: bool | None = None
    vbw_auto: bool | None = None
    ref_level: float | None = None
    atten: float | None = None
    preamp: bool | None = None
    sweep_points: int | None = None
    trace_mode: str | None = None
    detector: str | None = None
    averages: int | None = None


class EnvelopeIn(BaseModel):
    max_voltage: float
    max_current: float


class PresetApplyIn(BaseModel):
    envelope: EnvelopeIn | None = None
    confirm: bool = False


class AgentRunIn(BaseModel):
    prompt: str


# --- FastAPI app ----------------------------------------------------------
app = FastAPI(title="ECE Tool Suite backend", version=__version__)
app.add_middleware(
    # Localhost-only sidecar: allow any origin so the packaged Electron window (file:// →
    # Origin "null") can reach it, in addition to the dev server. No credentials are used.
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        # Launch identity: the Electron shell passes a per-launch nonce and only adopts a
        # server that echoes it — never a stale orphan or an unrelated app on the same port.
        "nonce": os.environ.get("ECE_SUITE_NONCE", ""),
        "mode": "hardware",
        "instruments": manager.status(),
        "any_connected": manager.any_connected(),
        "hardware_connected": manager.any_hardware_verified(),
        "capabilities_chatbox": sorted(registry.names_for(Surface.CHATBOX)),
        "capabilities_autonomous": sorted(registry.names_for(Surface.AUTONOMOUS)),
    }


# --- VISA discovery + connection -----------------------------------------
@app.get("/api/visa/resources")
def visa_resources() -> dict:
    import pyvisa

    found: list[dict] = []
    for backend in ("", "@py"):
        try:
            rm = pyvisa.ResourceManager(backend)
        except Exception:  # noqa: BLE001
            continue
        try:
            resources = list(rm.list_resources())
        except Exception:  # noqa: BLE001
            resources = []
        for res in resources:
            idn = None
            keysight = False
            try:
                inst = rm.open_resource(res)
                inst.timeout = 1500
                idn = inst.query("*IDN?").strip()
                keysight = "KEYSIGHT" in idn.upper() or "AGILENT" in idn.upper()
                inst.close()
            except Exception:  # noqa: BLE001
                pass
            found.append({"resource": res, "idn": idn, "keysight": keysight, "backend": backend or "system"})
        if found:
            break
    return {"resources": found}


@app.get("/api/io/backends")
def io_backends() -> dict:
    """Which VISA implementations are installed (Keysight IO Libs / NI-VISA / R&S / pyvisa-py)."""
    from . import io_env
    return {"backends": io_env.visa_backends()}


class ScpiIn(BaseModel):
    role: str
    command: str
    query: bool = False
    timeout_ms: int | None = None


@app.get("/api/io/details/{role}")
def io_details(role: str) -> dict:
    """Full instrument identity + connection info for a role (Connection Expert style)."""
    from .instruments.scpi import parse_idn
    from .instruments.vendors import canonical_vendor, vendor_display

    t = manager.get(role)
    if t is None:
        return {"connected": False, "role": role}
    idn = None
    vendor = "unknown"
    err = None
    try:
        raw = t.query("*IDN?").strip()
        i = parse_idn(raw)
        idn = {"raw": raw, "vendor": i.vendor, "model": i.model, "serial": i.serial, "firmware": i.firmware}
        vendor = canonical_vendor(i.vendor)
    except Exception as e:  # noqa: BLE001
        err = str(e)
    resource = t.resource if isinstance(t, VisaTransport) else None
    return {"connected": True, "role": role, "resource": resource,
            "backend": type(t).__name__, "provenance": t.default_provenance.value,
            "vendor": vendor, "vendor_name": vendor_display(vendor) if vendor != "unknown" else None,
            "idn": idn, "error": err}


@app.post("/api/io/scpi")
def io_scpi(body: ScpiIn) -> dict:
    """Interactive IO: send a raw SCPI command (write) or query (write+read) to a connected
    instrument. Every command is audit-logged. NOTE: this is a direct passthrough and bypasses
    the app's safety gates — the caller is responsible (same as Keysight Interactive IO)."""
    t = manager.get(body.role)
    if t is None:
        return {"ok": False, "error": f"{body.role} not connected"}
    cmd = body.command.strip()
    if not cmd:
        return {"ok": False, "error": "empty command"}
    is_query = body.query or cmd.endswith("?")
    if body.timeout_ms and isinstance(t, VisaTransport):
        try:
            t._inst.timeout = int(body.timeout_ms)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    audit.record("interactive_io", role=body.role, command=cmd, query=is_query,
                 provenance=t.default_provenance.value)
    try:
        if is_query:
            return {"ok": True, "query": True, "response": t.query(cmd).strip()}
        t.write(cmd)
        return {"ok": True, "query": False, "response": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/io/environment")
def io_environment() -> dict:
    """Plug-and-play status: VISA backends, plugged-in USB instruments, and — if a device
    can't be driven yet — which software to install (with a link)."""
    from . import io_env
    return io_env.assess()


# --- MCU flash programming / firmware extraction (pymcuprog) --------------
class McuReadIn(BaseModel):
    device: str
    tool_serial: str | None = None
    memory: str = "flash"
    max_bytes: int = 0


class McuEraseIn(BaseModel):
    device: str
    tool_serial: str | None = None
    confirm: bool = False


class McuWriteIn(BaseModel):
    device: str
    tool_serial: str | None = None
    hex: str
    confirm: bool = False


@app.get("/api/mcu/status")
def mcu_status() -> dict:
    from . import programmer
    return programmer.status()


@app.get("/api/mcu/devices")
def mcu_devices() -> dict:
    from . import programmer
    return {"devices": programmer.supported_devices()}


@app.get("/api/mcu/device/{name}")
def mcu_device(name: str) -> dict:
    from . import programmer
    return programmer.device_info(name)


@app.post("/api/mcu/read")
def mcu_read(body: McuReadIn) -> dict:
    from . import programmer
    audit.record("mcu_read", device=body.device, memory=body.memory)
    return programmer.read_target(body.device, body.tool_serial, body.memory, body.max_bytes)


@app.post("/api/mcu/erase")
def mcu_erase(body: McuEraseIn) -> dict:
    from . import programmer
    audit.record("mcu_erase", device=body.device, confirm=body.confirm)
    return programmer.chip_erase(body.device, body.tool_serial, body.confirm)


@app.post("/api/mcu/write")
def mcu_write(body: McuWriteIn) -> dict:
    from . import programmer
    audit.record("mcu_write", device=body.device, confirm=body.confirm, bytes=len(body.hex))
    return programmer.write_hex(body.device, body.tool_serial, body.hex, body.confirm)


# --- design-tool integration (CubeMX .ioc, TI tools, power stage) --------
class IocIn(BaseModel):
    text: str


class IocEditIn(BaseModel):
    text: str
    edits: dict[str, str | None]


@app.get("/api/tools/detect")
def tools_detect() -> dict:
    from . import design_tools
    return {"tools": design_tools.detect_tools()}


@app.post("/api/tools/launch/{tool_id}")
def tools_launch(tool_id: str) -> dict:
    from . import design_tools
    audit.record("tool_launch", tool=tool_id)
    return design_tools.launch_tool(tool_id)


@app.post("/api/ioc/parse")
def ioc_parse(body: IocIn) -> dict:
    from . import design_tools
    try:
        return {"ok": True, **design_tools.parse_ioc(body.text)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.post("/api/ioc/edit")
def ioc_edit(body: IocEditIn) -> dict:
    from . import design_tools
    try:
        return {"ok": True, "text": design_tools.apply_ioc_edits(body.text, body.edits)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/power/buck")
def power_buck(vin: float, vout: float, iout: float, fsw_khz: float = 500.0, ripple_pct: float = 30.0) -> dict:
    from . import design_tools
    try:
        return {"ok": True, **design_tools.buck_stage(vin, vout, iout, fsw_khz, ripple_pct)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/power/boost")
def power_boost(vin: float, vout: float, iout: float, fsw_khz: float = 500.0, ripple_pct: float = 30.0) -> dict:
    from . import design_tools
    try:
        return {"ok": True, **design_tools.boost_stage(vin, vout, iout, fsw_khz, ripple_pct)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/power/webench")
def power_webench(vin_min: float, vin_max: float, vout: float, iout: float) -> dict:
    from . import design_tools
    return {"url": design_tools.webench_url(vin_min, vin_max, vout, iout)}


@app.get("/api/power/design")
def power_design(vin: float, vout: float, iout: float, fsw_khz: float = 500.0, ripple_pct: float = 30.0,
                 isolated: bool = False) -> dict:
    """WEBENCH-class native design: topology + candidate TI parts + sizing + loop compensation."""
    from . import power_designer
    try:
        return {"ok": True, **power_designer.design(vin, vout, iout, fsw_khz, ripple_pct, isolated)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# --- Digi-Key WEBENCH API adapter (the only real WEBENCH-data route) ------
class DigikeyConnectIn(BaseModel):
    client_id: str
    client_secret: str


@app.get("/api/digikey/status")
def digikey_status() -> dict:
    from . import digikey
    return digikey.status()


@app.post("/api/digikey/connect")
def digikey_connect(body: DigikeyConnectIn) -> dict:
    from . import digikey
    return digikey.connect(body.client_id, body.client_secret)


@app.get("/api/digikey/search")
def digikey_search(q: str, limit: int = 10) -> dict:
    from . import digikey
    return digikey.search_parts(q, limit)


class SpiceVerifyIn(BaseModel):
    topology: str = "buck"
    vin: float
    vout: float
    iout: float
    L_uH: float
    Cout_uF: float
    fsw_khz: float = 500.0
    esr_mohm: float = 10.0
    dcr_mohm: float = 20.0
    targets: dict | None = None
    engine_id: str | None = None


@app.get("/api/spice/status")
def spice_status() -> dict:
    from . import spice_verify
    return {"engines": spice_verify.engines(),
            "raw_parser": spice_verify.can_read_raw(),
            "raw_parser_install": spice_verify.RAW_PARSER_INSTALL}


@app.post("/api/spice/verify")
def spice_verify_ep(body: SpiceVerifyIn) -> dict:
    from . import spice_verify
    audit.record("spice_verify", topology=body.topology, vin=body.vin, vout=body.vout, iout=body.iout)
    return spice_verify.verify(body.topology, body.vin, body.vout, body.iout, body.L_uH,
                               body.Cout_uF, body.fsw_khz, targets=body.targets,
                               esr_mohm=body.esr_mohm, dcr_mohm=body.dcr_mohm, engine_id=body.engine_id)


class LoopVerifyIn(BaseModel):
    vin: float
    vout: float
    iout: float
    L_uH: float
    Cout_uF: float
    fsw_khz: float = 500.0
    esr_mohm: float = 10.0
    ri_ohm: float = 0.1
    vref_v: float = 0.8
    gm_ea_uA_V: float = 1000.0
    pm_min_deg: float = 45.0
    gm_min_db: float = 6.0


@app.get("/api/power/loop/status")
def power_loop_status() -> dict:
    from . import loop_verify
    return {"available": loop_verify._available(), "engine": "python-control"}


class MagneticsIn(BaseModel):
    inductance_uH: float
    i_dc: float
    i_ripple_pp: float
    fsw_khz: float = 500.0
    ambient_c: float = 25.0
    duty: float = 0.5
    n_results: int = 3
    mode: str = "standard cores"


@app.get("/api/power/magnetics/status")
def magnetics_status() -> dict:
    from . import magnetics
    return magnetics.db_summary()


@app.post("/api/power/magnetics")
def magnetics_advise(body: MagneticsIn) -> dict:
    """OpenMagnetics/MKF: real-catalog inductor core+winding designs with computed core/copper losses."""
    from . import magnetics
    audit.record("magnetics_advise", inductance_uH=body.inductance_uH, i_dc=body.i_dc, fsw_khz=body.fsw_khz)
    return magnetics.advise_inductor(body.inductance_uH, body.i_dc, body.i_ripple_pp, body.fsw_khz,
                                     ambient_c=body.ambient_c, duty=body.duty,
                                     n_results=body.n_results, mode=body.mode)


class CapBankIn(BaseModel):
    topology: str = "buck"
    vin: float
    vout: float
    iout: float
    fsw_khz: float = 500.0
    il_ripple_pp_a: float | None = None
    c_each_uF: float = 22.0
    esr_each_mohm: float = 5.0
    irms_each_a: float = 2.0
    vrated: float = 25.0
    dielectric: str = "mlcc"
    rth_c_w: float | None = 40.0
    target_out_uF: float | None = None
    target_in_uF: float | None = None


@app.post("/api/power/capacitors")
def power_capacitors(body: CapBankIn) -> dict:
    """Size the input+output capacitor banks (RMS ripple current, parallels, ESR loss, temp rise,
    voltage derating, ripple voltage) for a buck/boost stage on a candidate cap."""
    from . import capacitor_bank
    return capacitor_bank.size(body.topology, body.vin, body.vout, body.iout, body.fsw_khz,
                               il_ripple_pp_a=body.il_ripple_pp_a, c_each_uF=body.c_each_uF,
                               esr_each_mohm=body.esr_each_mohm, irms_each_a=body.irms_each_a,
                               vrated=body.vrated, dielectric=body.dielectric, rth_c_w=body.rth_c_w,
                               target_out_uF=body.target_out_uF, target_in_uF=body.target_in_uF)


@app.post("/api/power/loop")
def power_loop_verify(body: LoopVerifyIn) -> dict:
    """Closed-loop stability verification (python-control): achieved crossover / phase / gain margin
    of the designed type-II compensator on a current-mode buck plant."""
    from . import loop_verify
    audit.record("loop_verify", vin=body.vin, vout=body.vout, iout=body.iout, L_uH=body.L_uH, Cout_uF=body.Cout_uF)
    return loop_verify.verify(body.vin, body.vout, body.iout, body.L_uH, body.Cout_uF, body.fsw_khz,
                              esr_mohm=body.esr_mohm, ri_ohm=body.ri_ohm, vref_v=body.vref_v,
                              gm_ea_uA_V=body.gm_ea_uA_V, pm_min_deg=body.pm_min_deg, gm_min_db=body.gm_min_db)


# --- RTL / HDL: write, lint, simulate, synthesize, format, AI design ------
class RtlSourceIn(BaseModel):
    source: str
    language: str | None = None
    top: str | None = None


class RtlSimIn(BaseModel):
    source: str
    testbench: str
    language: str | None = None
    top: str | None = None


class RtlGenerateIn(BaseModel):
    spec: str
    language: str = "systemverilog"
    testbench: str | None = None
    top: str | None = None
    max_rounds: int = 3


class RtlOptimizeIn(BaseModel):
    source: str
    goal: str = "area"
    language: str | None = None
    testbench: str | None = None
    top: str | None = None


@app.get("/api/rtl/status")
def rtl_status() -> dict:
    """Installed HDL toolchain (per-language capabilities) + whether AI RTL is configured."""
    from . import rtl, rtl_ai
    tc = rtl.toolchain()
    tc["ai"] = rtl_ai.available()
    return tc


@app.post("/api/rtl/lint")
def rtl_lint(body: RtlSourceIn) -> dict:
    from . import rtl
    audit.record("rtl_lint", language=body.language, bytes=len(body.source))
    return rtl.lint(body.source, body.language, top=body.top)


@app.post("/api/rtl/simulate")
def rtl_simulate(body: RtlSimIn) -> dict:
    from . import rtl
    audit.record("rtl_simulate", language=body.language, bytes=len(body.source))
    return rtl.simulate(body.source, body.testbench, body.language, top=body.top)


@app.post("/api/rtl/synth")
def rtl_synth(body: RtlSourceIn) -> dict:
    from . import rtl
    return rtl.synthesize(body.source, body.language, top=body.top)


class RtlFpgaIn(BaseModel):
    source: str
    family: str = "ice40"
    language: str | None = None
    top: str | None = None


@app.post("/api/rtl/fpga")
def rtl_fpga(body: RtlFpgaIn) -> dict:
    """Synthesize to a real FPGA family (Yosys synth_ice40/ecp5/…) and report device utilization."""
    from . import rtl
    audit.record("rtl_fpga_synth", family=body.family, language=body.language)
    return rtl.fpga_synth(body.source, body.family, body.language, top=body.top)


class RtlTimingIn(BaseModel):
    source: str
    family: str = "ice40"
    device: str | None = None
    language: str | None = None
    top: str | None = None
    target_mhz: float | None = None


@app.post("/api/rtl/timing")
def rtl_timing(body: RtlTimingIn) -> dict:
    """Place-and-route with nextpnr and report real Fmax + device utilisation (timing analysis)."""
    from . import rtl
    audit.record("rtl_timing", family=body.family, target_mhz=body.target_mhz)
    return rtl.fpga_timing(body.source, body.family, body.device, body.language,
                           top=body.top, target_mhz=body.target_mhz)


class RegmapIn(BaseModel):
    spec: dict
    lint: bool = True


@app.post("/api/rtl/regmap")
def rtl_regmap(body: RegmapIn) -> dict:
    """Generate a SystemVerilog register block + Markdown docs from a register-map spec."""
    from . import regmap
    audit.record("rtl_regmap", name=body.spec.get("name"))
    return regmap.generate(body.spec, lint=body.lint)


class ConstraintIn(BaseModel):
    fmt: str
    ports: list[dict] = []


@app.post("/api/rtl/constraints")
def rtl_constraints(body: ConstraintIn) -> dict:
    """Generate a vendor pin-constraint file template (XDC/PCF/LPF/PDC/QSF)."""
    from . import rtl
    return rtl.constraint_template(body.fmt, body.ports)


@app.post("/api/rtl/format")
def rtl_format(body: RtlSourceIn) -> dict:
    from . import rtl
    return rtl.format_src(body.source, body.language)


@app.post("/api/rtl/generate")
async def rtl_generate(body: RtlGenerateIn) -> dict:
    """AI designs RTL from a spec, iterating until the toolchain (lint + optional sim) is clean."""
    from . import rtl_ai
    audit.record("rtl_generate", language=body.language, has_tb=bool(body.testbench))
    return await rtl_ai.generate(body.spec, body.language, testbench=body.testbench,
                                 top=body.top, max_rounds=body.max_rounds)


@app.post("/api/rtl/optimize")
async def rtl_optimize(body: RtlOptimizeIn) -> dict:
    """AI optimizes RTL for a goal, accepted only if it still validates against the toolchain."""
    from . import rtl_ai
    audit.record("rtl_optimize", goal=body.goal, language=body.language)
    return await rtl_ai.optimize(body.source, body.goal, body.language,
                                 testbench=body.testbench, top=body.top)


# --- LabVIEW (NI LabVIEWCLI: detect, projects, run VI, build, mass-compile) ---
class LvRunIn(BaseModel):
    vi_path: str


class LvDirIn(BaseModel):
    directory: str


class LvBuildIn(BaseModel):
    project: str
    build_spec: str | None = None
    target: str = "My Computer"


class LvLaunchIn(BaseModel):
    project: str | None = None


@app.get("/api/labview/status")
def labview_status() -> dict:
    from . import labview
    return labview.status()


@app.get("/api/labview/projects")
def labview_projects() -> dict:
    from . import labview
    return {"projects": labview.list_projects()}


@app.post("/api/labview/run-vi")
def labview_run_vi(body: LvRunIn) -> dict:
    from . import labview
    audit.record("labview_run_vi", vi=body.vi_path)
    return labview.run_vi(body.vi_path)


@app.post("/api/labview/mass-compile")
def labview_mass_compile(body: LvDirIn) -> dict:
    from . import labview
    audit.record("labview_mass_compile", directory=body.directory)
    return labview.mass_compile(body.directory)


@app.post("/api/labview/build")
def labview_build(body: LvBuildIn) -> dict:
    from . import labview
    audit.record("labview_build", project=body.project, spec=body.build_spec)
    return labview.execute_build_spec(body.project, body.build_spec, body.target)


@app.post("/api/labview/launch")
def labview_launch(body: LvLaunchIn) -> dict:
    from . import labview
    audit.record("labview_launch", project=body.project)
    return labview.launch(body.project)


@app.post("/api/labview/close")
def labview_close() -> dict:
    from . import labview
    return labview.close_labview()


# --- Xilinx / Intel / Lattice FPGA + CPLD targets --------------------------
class VendorProjectIn(BaseModel):
    source: str
    vendor: str
    family: str
    part: str | None = None
    top: str | None = None
    language: str | None = None
    ports: list[dict] = []


@app.get("/api/rtl/pld-targets")
def rtl_pld_targets() -> dict:
    """Vendor→family→part map (FPGAs and CPLDs) + which vendor tools are installed."""
    from . import rtl
    return {"vendors": rtl.pld_targets()}


@app.post("/api/rtl/vendor-project")
def rtl_vendor_project(body: VendorProjectIn) -> dict:
    """Generate a ready-to-run Vivado/Quartus/Radiant (or open-flow) project for the RTL."""
    from . import rtl
    audit.record("rtl_vendor_project", vendor=body.vendor, family=body.family)
    return rtl.vendor_project(body.source, body.vendor, body.family, body.part,
                              body.top, body.ports, body.language)


# --- parts from URL + local parts list -------------------------------------
class PartUrlIn(BaseModel):
    url: str
    add: bool = True
    fetch: bool = True


@app.post("/api/parts/from-url")
def parts_from_url(body: PartUrlIn) -> dict:
    """Paste a distributor/manufacturer link → extract the part's info (URL structure +
    best-effort page JSON-LD) and optionally add it to the local parts list."""
    from . import parts_url
    audit.record("parts_from_url", url=body.url[:200])
    info = parts_url.part_from_url(body.url, fetch=body.fetch)
    if info.get("ok") and body.add:
        return {**info, **{k: v for k, v in parts_url.add_part(info).items() if k != "ok"}}
    return info


@app.get("/api/parts/list")
def parts_list() -> dict:
    from . import parts_url
    return {"parts": parts_url.list_parts()}


@app.delete("/api/parts/list/{part_id}")
def parts_list_remove(part_id: int) -> dict:
    from . import parts_url
    return parts_url.remove_part(part_id)


@app.get("/api/parts/list/export")
def parts_list_export() -> Response:
    import csv
    import io

    from . import parts_url
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["mpn", "manufacturer", "name", "vendor", "price", "source_url", "added"])
    w.writerows(parts_url.export_rows())
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="parts_list.csv"'})


# --- FPGA bring-up: detect → bitstream → program → vendor hand-off ---------
class BitstreamIn(BaseModel):
    source: str
    family: str = "ice40"
    device: str | None = None
    top: str | None = None
    language: str | None = None
    ports: list[dict] = []


class ProgramIn(BaseModel):
    bitstream: str
    board: str | None = None
    cable: str | None = None


class VendorExportIn(BaseModel):
    source: str
    vendor: str
    family: str
    part: str | None = None
    top: str | None = None
    language: str | None = None
    ports: list[dict] = []


class VendorLaunchIn(BaseModel):
    project_dir: str
    vendor: str | None = None


@app.get("/api/rtl/jtag")
def rtl_jtag() -> dict:
    from . import rtl
    audit.record("fpga_detect")
    return rtl.fpga_detect()


@app.get("/api/rtl/boards")
def rtl_boards() -> dict:
    from . import rtl
    return rtl.fpga_boards()


@app.post("/api/rtl/bitstream")
def rtl_bitstream(body: BitstreamIn) -> dict:
    from . import rtl
    audit.record("fpga_bitstream", family=body.family)
    return rtl.fpga_bitstream(body.source, body.family, body.device, body.top,
                              body.language, body.ports or None)


@app.post("/api/rtl/program")
def rtl_program(body: ProgramIn) -> dict:
    from . import rtl
    audit.record("fpga_program", bitstream=body.bitstream, board=body.board)
    return rtl.fpga_program(body.bitstream, body.board, body.cable)


@app.post("/api/rtl/vendor-export")
def rtl_vendor_export(body: VendorExportIn) -> dict:
    from . import rtl
    audit.record("vendor_export", vendor=body.vendor, family=body.family)
    return rtl.vendor_export(body.source, body.vendor, body.family, body.part,
                             body.top, body.ports or None, body.language)


@app.post("/api/rtl/vendor-launch")
def rtl_vendor_launch(body: VendorLaunchIn) -> dict:
    from . import rtl
    audit.record("vendor_launch", dir=body.project_dir, vendor=body.vendor)
    return rtl.vendor_launch(body.project_dir, body.vendor)


# --- LabVIEW VI Server (COM): run/set/get + templates + dashboard codegen --
class LvViRunIn(BaseModel):
    vi_path: str
    inputs: dict = {}
    outputs: list[str] = []


class LvValueIn(BaseModel):
    vi_path: str
    control: str
    value: None | str | float | int | bool = None
    set_it: bool = False


class LvTemplateIn(BaseModel):
    save_path: str
    template: str
    open_in_labview: bool = True


class LvDashboardIn(BaseModel):
    spec: dict
    output_path: str


@app.get("/api/labview/com-status")
def labview_com_status() -> dict:
    from . import labview
    return labview.com_status()


@app.post("/api/labview/vi-run")
def labview_vi_run(body: LvViRunIn) -> dict:
    from . import labview
    audit.record("labview_vi_run", vi=body.vi_path)
    return labview.vi_run_com(body.vi_path, body.inputs, body.outputs)


@app.post("/api/labview/vi-value")
def labview_vi_value(body: LvValueIn) -> dict:
    from . import labview
    return labview.vi_value(body.vi_path, body.control, body.value, body.set_it)


@app.get("/api/labview/templates")
def labview_templates() -> dict:
    from . import labview
    return labview.list_templates()


@app.post("/api/labview/create-vi")
def labview_create_vi(body: LvTemplateIn) -> dict:
    from . import labview
    audit.record("labview_create_vi", template=body.template, path=body.save_path)
    return labview.create_from_template(body.save_path, body.template, body.open_in_labview)


@app.get("/api/labview/builder-status")
def labview_builder_status() -> dict:
    from . import labview
    return labview.builder_status()


@app.post("/api/labview/dashboard")
def labview_dashboard(body: LvDashboardIn) -> dict:
    from . import labview
    audit.record("labview_dashboard", path=body.output_path)
    return labview.generate_dashboard(body.spec, body.output_path)


# --- RTL professional workflow: dev stack, snippets, waveforms, export -----
class VcdIn(BaseModel):
    vcd: str
    name: str = "wave"


class ExportProjectIn(BaseModel):
    files: dict[str, str]
    dest: str
    open_in: str | None = None   # vscode | explorer


class OpenPathIn(BaseModel):
    path: str


@app.get("/api/rtl/devenv")
def rtl_devenv() -> dict:
    """Detected professional-workflow stack (VS Code, Git, Python, GTKWave, Vivado, cocotb)."""
    from . import rtl
    return rtl.dev_environment()


@app.get("/api/rtl/snippets")
def rtl_snippets() -> dict:
    """Engineering pattern library: CDC, reset sync, self-checking TB, XDC, ILA, cocotb."""
    from . import rtl
    return {"snippets": rtl.snippets()}


@app.post("/api/rtl/gtkwave")
def rtl_gtkwave(body: VcdIn) -> dict:
    from . import rtl
    audit.record("rtl_gtkwave", name=body.name)
    return rtl.open_vcd_in_gtkwave(body.vcd, body.name)


@app.post("/api/rtl/export-project")
def rtl_export_project(body: ExportProjectIn) -> dict:
    from . import rtl
    audit.record("rtl_export_project", dest=body.dest, files=len(body.files))
    return rtl.export_project(body.files, body.dest, body.open_in)


@app.post("/api/rtl/open-vscode")
def rtl_open_vscode(body: OpenPathIn) -> dict:
    from . import rtl
    return rtl.open_in_vscode(body.path)


# --- one-click third-party software setup ---------------------------------
@app.get("/api/setup/catalog")
def setup_catalog() -> dict:
    """Third-party tools the suite can use: installed-state + one-click installability."""
    from . import setup_tools
    return {"tools": setup_tools.catalog()}


@app.post("/api/setup/install/{tool_id}")
def setup_install(tool_id: str) -> dict:
    """Start a one-click install (official source only); progress via /api/setup/status."""
    from . import setup_tools
    audit.record("setup_install", tool=tool_id)
    return setup_tools.start_install(tool_id)


@app.get("/api/setup/status")
def setup_status() -> dict:
    from . import setup_tools
    return {"installs": setup_tools.status()}


@app.get("/api/mcp/info")
def mcp_info() -> dict:
    """Config for driving this bench from an external MCP client (Claude Desktop / Code).

    Exposes the app as a standalone MCP server — the same idea as the LeCroy / pymcuprog MCP
    servers, but for whatever multi-vendor gear the suite has connected.
    """
    import json
    import sys

    try:
        from .mcp_server import mcp as _srv  # noqa: F401
        available = True
    except Exception:  # noqa: BLE001
        available = False

    port = int(os.environ.get("ECE_SUITE_PORT", 8848))
    url = f"http://127.0.0.1:{port}"
    python = sys.executable
    tools = ["list_instruments", "io_environment", "autoconnect", "scope_measure", "dmm_read",
             "spectrum_peak", "scpi", "list_calculators", "run_calculator", "decode_logic",
             "mcu_status", "mcu_device_info", "mcu_read_firmware",
             "detect_design_tools", "parse_cubemx_ioc", "power_stage", "power_verify", "power_design",
             "power_loop_verify", "magnetics_advise", "capacitor_bank"]
    config = {"mcpServers": {"ece-tool-suite": {
        "command": python, "args": ["-m", "ece_suite.mcp_server"], "env": {"ECE_SUITE_URL": url}}}}
    return {
        "available": available, "server_name": "ece-tool-suite",
        "command": python, "args": ["-m", "ece_suite.mcp_server"], "url": url, "tools": tools,
        "config_json": json.dumps(config, indent=2),
        "note": "Keep the app running, then add this to your MCP client. Claude can then list "
                "instruments, auto-connect, measure, send SCPI and run calculators on your bench.",
    }


def _probe_idn(rm, res: str) -> tuple[str | None, str | None]:
    """Return (idn_raw, model). Falls back to the Fluke 28x handheld ``ID`` query on a serial
    port that doesn't answer ``*IDN?``."""
    try:
        inst = rm.open_resource(res)
        inst.timeout = 2000
        try:
            idn = inst.query("*IDN?").strip()
            if idn:
                return idn, None
        except Exception:  # noqa: BLE001
            pass
        if res.upper().startswith("ASRL"):  # maybe a Fluke 287/289 handheld
            try:
                rid = inst.query("ID").strip()
                if "FLUKE" in rid.upper():
                    return f"Fluke,{rid}", rid
            except Exception:  # noqa: BLE001
                pass
        return None, None
    except Exception:  # noqa: BLE001
        return None, None
    finally:
        try:
            inst.close()  # type: ignore[has-type]
        except Exception:  # noqa: BLE001
            pass


@app.post("/api/io/autoconnect")
def io_autoconnect(lan: bool = False) -> dict:
    """Discover instruments (USB/GPIB/serial via VISA, plus LAN via mDNS/LXI when ``lan=1``),
    identify each via *IDN? (Fluke handhelds via ID), classify its bench role, and connect any
    role that isn't already connected. Returns what was connected and what was seen.

    LAN mDNS discovery is opt-in (it multicasts + takes ~1.5 s) so the periodic USB watcher
    stays cheap; the manual "Scan & connect now" button passes ``lan=1``.
    """
    import pyvisa

    from . import io_env
    from .instruments.scpi import parse_idn
    from .instruments.vendors import canonical_vendor, classify_role

    connected: list[dict] = []
    detected: list[dict] = []
    seen: set[str] = set()

    rm = None
    for backend in ("", "@py"):
        try:
            rm = pyvisa.ResourceManager(backend)
            rm_backend = backend
            break
        except Exception:  # noqa: BLE001
            continue
    if rm is None:
        return {"connected": [], "detected": [], "error": "no VISA backend"}

    # candidate resources: everything VISA can list + anything mDNS/LXI advertises on the LAN
    resources: list[str] = []
    try:
        resources.extend(rm.list_resources())
    except Exception:  # noqa: BLE001
        pass
    if lan:
        for dev in io_env.discover_lan():
            if dev["resource"] not in resources:
                resources.append(dev["resource"])

    for res in resources:
        if res in seen:
            continue
        seen.add(res)
        idn_raw, fluke_model = _probe_idn(rm, res)
        if not idn_raw:
            detected.append({"resource": res, "idn": None, "role": None, "connected": False})
            continue
        idn = parse_idn(idn_raw)
        model = fluke_model or idn.model
        role = "dmm" if fluke_model else classify_role(model)
        vendor = canonical_vendor(idn.vendor)
        entry = {"resource": res, "idn": idn_raw, "role": role, "vendor": vendor, "connected": False}
        if role and role in manager.roles() and not manager.connected(role):
            try:
                t = manager.connect_visa(role, res, backend=rm_backend or "auto")
                t._vendor = vendor  # type: ignore[attr-defined]
                entry["connected"] = True
                connected.append(entry)
            except Exception as e:  # noqa: BLE001
                entry["error"] = str(e)
        detected.append(entry)
    return {"connected": connected, "detected": detected}


@app.get("/api/instruments/supported")
def instruments_supported() -> dict:
    """Vendor/dialect menu per instrument role — what the app can actually speak."""
    from .instruments.vendors import SUPPORTED_BY_ROLE
    return {"roles": SUPPORTED_BY_ROLE}


@app.get("/api/instruments/{role}/capabilities")
def instrument_capabilities(role: str) -> dict:
    """The CONNECTED unit's real feature set (channels, couplings, DMM functions…),
    resolved from its vendor + model. Disconnected → the family baseline for 'auto'."""
    from .instruments.capabilities import dmm_capabilities, scope_capabilities
    from .instruments.scpi import parse_idn
    from .instruments.vendors import canonical_vendor

    t = manager.get(role)
    vendor, model = "keysight", ""
    if t is not None:
        vendor = getattr(t, "_vendor", None) or "keysight"
        try:
            idn = parse_idn(t.query("*IDN?").strip())
            model = idn.model
            if not getattr(t, "_vendor", None):
                v = canonical_vendor(idn.vendor)
                if v != "unknown":
                    vendor = v
        except Exception:  # noqa: BLE001
            pass
    if role == "scope":
        caps = scope_capabilities(vendor, model)
    elif role == "dmm":
        d = getattr(t, "_dmm_dialect", None) if t is not None else None
        caps = dmm_capabilities(d or vendor, model)
    else:
        caps = {"vendor": vendor, "model": model or None}
    caps["connected"] = t is not None
    return caps


@app.post("/api/instruments/{role}/connect")
def connect_instrument(role: str, body: ConnectIn) -> dict:
    if role not in manager.roles():
        raise HTTPException(status_code=404, detail="no such role")
    backend = body.backend or "auto"
    resource = body.resource
    if not resource and body.host:
        resource = build_visa_resource(body.host, body.interface or "lan", body.port)
    if not resource:
        return {"ok": False, "role": role, "error": "no resource or host provided"}
    try:
        t = manager.connect_visa(role, resource, backend=backend)
        idn = ""
        vendor = "unknown"
        try:
            idn = t.query("*IDN?").strip()
            from .instruments.scpi import parse_idn
            from .instruments.vendors import canonical_vendor
            vendor = canonical_vendor(parse_idn(idn).vendor)
        except Exception:  # noqa: BLE001
            pass
        # explicit user choice wins over (or fills in for) *IDN? detection — some gear
        # answers with OEM strings or nothing at all; the dialect must still be right
        hint = (body.vendor_hint or "").strip().lower()
        if hint and hint != "auto":
            vendor = hint
            audit.record("vendor_override", role=role, vendor=hint, idn=idn or None)
        if vendor != "unknown":
            t._vendor = vendor  # type: ignore[attr-defined]
        return {"ok": True, "role": role, "resource": resource, "vendor": vendor,
                "provenance": t.default_provenance.value, "idn": idn}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "role": role, "resource": resource, "error": str(e)}


@app.post("/api/instruments/{role}/verify")
def verify_instrument(role: str) -> dict:
    if role not in manager.roles():
        raise HTTPException(status_code=404, detail="no such role")
    if not manager.connected(role):
        return {"ok": False, "connected": False, "error": "not connected"}
    r = manager.verify(role)
    return {"ok": r.ok, "provenance": r.provenance, "idn": (r.idn.raw if r.idn else None), "reasons": r.reasons}


@app.post("/api/instruments/{role}/disconnect")
def disconnect_instrument(role: str) -> dict:
    if role not in manager.roles():
        raise HTTPException(status_code=404, detail="no such role")
    manager.disconnect(role)
    return {"ok": True, "role": role, "connected": manager.connected(role)}


# --- scope ---------------------------------------------------------------
@app.post("/api/scope/config")
def scope_config(body: ScopeConfigIn) -> dict:
    drv = scope_driver()
    if drv is None:
        return {"ok": False, "connected": False}
    try:
        for c in body.channels:
            drv.set_channel(c.ch, enabled=c.enabled, scale=c.scale, offset=c.offset,
                            coupling=c.coupling, probe=c.probe, bwlimit=c.bwlimit,
                            invert=c.invert, label=c.label, unit=c.unit)
        if (body.timebase_scale is not None or body.timebase_position is not None
                or body.timebase_reference is not None):
            drv.set_timebase(scale=body.timebase_scale, position=body.timebase_position,
                             reference=body.timebase_reference)
        if any(v is not None for v in (body.trig_mode, body.trig_source, body.trig_level,
                                       body.trig_slope, body.trig_coupling, body.trig_holdoff,
                                       body.trig_sweep)):
            drv.set_trigger(mode=body.trig_mode, source=body.trig_source, level=body.trig_level,
                            slope=body.trig_slope, coupling=body.trig_coupling,
                            holdoff=body.trig_holdoff, sweep=body.trig_sweep)
        if any(v is not None for v in (body.acq_type, body.acq_count, body.acq_points)):
            drv.set_acquisition(atype=body.acq_type, count=body.acq_count, points=body.acq_points)
        if body.run == "run":
            drv.run()
        elif body.run == "stop":
            drv.stop()
        elif body.run == "single":
            drv.single()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/scope/measure")
def scope_measure(ch: int = 1) -> dict:
    drv = scope_driver()
    if drv is None:
        return {"connected": False}
    try:
        return {"connected": True, "ch": ch, "measurements": drv.measure_all(ch)}
    except Exception as e:  # noqa: BLE001
        return {"connected": True, "error": str(e)}


@app.post("/api/scope/bringup")
def scope_bringup() -> dict:
    from .instruments.keysight import run_bringup

    if not manager.connected("scope"):
        return {"ok": False, "connected": False, "error": "scope not connected"}
    return run_bringup(manager.get("scope"), engine, audit=audit)


@app.websocket("/ws/scope")
async def ws_scope(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            drv = scope_driver()
            if drv is None:
                await ws.send_json({"connected": False})
            else:
                try:
                    await ws.send_json(await asyncio.to_thread(drv.snapshot))
                except Exception as e:  # noqa: BLE001
                    await ws.send_json({"connected": True, "error": str(e)})
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return


# --- instrument screenshot (scope / spectrum analyzer) -------------------
_SCREENSHOT_CMD = {"scope": ":DISPlay:DATA? PNG,COLor", "sa": ":DISP:DATA?"}
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _extract_png(raw: bytes) -> bytes | None:
    if raw[:8] == _PNG_SIG:
        return raw
    try:
        payload = parse_definite_length_block(raw)
    except Exception:  # noqa: BLE001
        payload = raw
    return payload if payload[:8] == _PNG_SIG else None


@app.get("/api/{role}/screenshot")
def screenshot(role: str):
    if role not in _SCREENSHOT_CMD:
        raise HTTPException(status_code=404, detail="screenshot not supported for this instrument")
    t = manager.get(role)
    if t is None:
        raise HTTPException(status_code=409, detail=f"{role} not connected")
    try:
        raw = t.query_raw(_SCREENSHOT_CMD[role])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"screenshot query failed: {e}") from e
    png = _extract_png(raw)
    if png is None:
        raise HTTPException(status_code=502, detail="instrument did not return a PNG")
    return Response(content=png, media_type="image/png")


# --- DMM -----------------------------------------------------------------
@app.post("/api/dmm/config")
def dmm_config(body: DmmConfigIn) -> dict:
    drv = dmm_driver()
    if drv is None:
        return {"ok": False, "connected": False}
    try:
        return {"ok": True, **drv.configure(body.function, body.range, body.nplc,
                                            math=body.math, autozero=body.autozero)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/dmm/read")
def dmm_read() -> dict:
    """One DMM reading (for REST/MCP callers that don't hold the websocket open)."""
    drv = dmm_driver()
    if drv is None:
        return {"connected": False}
    try:
        return drv.read()
    except Exception as e:  # noqa: BLE001
        return {"connected": True, "error": str(e)}


@app.websocket("/ws/dmm")
async def ws_dmm(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            drv = dmm_driver()
            if drv is None:
                await ws.send_json({"connected": False})
            else:
                try:
                    data = await asyncio.to_thread(drv.read)
                    if recorder.active("dmm") and data.get("value") is not None:
                        recorder.record("dmm", {"value": data["value"], "unit": data.get("unit", ""), "function": data.get("function", "")})
                    await ws.send_json(data)
                except Exception as e:  # noqa: BLE001
                    await ws.send_json({"connected": True, "error": str(e)})
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        return


# --- session logging (server-side) ---------------------------------------
@app.post("/api/log/{role}/start")
def log_start(role: str) -> dict:
    recorder.start(role)
    return {"ok": True, "active": True}


@app.post("/api/log/{role}/stop")
def log_stop(role: str) -> dict:
    recorder.stop(role)
    return {"ok": True, "active": False}


@app.post("/api/log/{role}/clear")
def log_clear(role: str) -> dict:
    recorder.clear(role)
    return {"ok": True}


@app.get("/api/log/{role}/status")
def log_status(role: str) -> dict:
    return {"active": recorder.active(role), "count": recorder.count(role)}


@app.get("/api/log/{role}/export")
def log_export(role: str) -> Response:
    return Response(content=recorder.to_csv(role), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{role}_log.csv"'})


# --- spectrum analyzer ---------------------------------------------------
@app.post("/api/sa/config")
def sa_config(body: SaConfigIn) -> dict:
    drv = sa_driver()
    if drv is None:
        return {"ok": False, "connected": False}
    try:
        drv.configure(center=body.center, span=body.span, start=body.start, stop=body.stop,
                      rbw=body.rbw, vbw=body.vbw, rbw_auto=body.rbw_auto, vbw_auto=body.vbw_auto,
                      ref_level=body.ref_level, atten=body.atten, preamp=body.preamp,
                      sweep_points=body.sweep_points, trace_mode=body.trace_mode,
                      detector=body.detector, averages=body.averages)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.websocket("/ws/sa")
async def ws_sa(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            drv = sa_driver()
            if drv is None:
                await ws.send_json({"connected": False})
            else:
                try:
                    frame = await asyncio.to_thread(drv.trace)
                    frame["peak"] = await asyncio.to_thread(drv.marker_peak)
                    await ws.send_json(frame)
                except Exception as e:  # noqa: BLE001
                    await ws.send_json({"connected": True, "error": str(e)})
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


# --- source (PSU) — safety-gated ------------------------------------------
class PsuApplyIn(BaseModel):
    vset: float
    iset: float
    ovp: float
    ocp: float
    dut_max_v: float
    dut_max_i: float
    confirm: bool = False


def _psu_steps(vset: float, iset: float, ovp: float, ocp: float) -> list[PresetStep]:
    return [
        PresetStep(OpType.SET_PROTECTION, f":VOLT:PROT {ovp}", verify_query=":VOLT:PROT?", expected=ovp, description=f"OVP = {ovp} V"),
        PresetStep(OpType.SET_PROTECTION, f":CURR:PROT {ocp}", verify_query=":CURR:PROT?", expected=ocp, description=f"OCP = {ocp} A"),
        PresetStep(OpType.SET_LEVEL, f":VOLT {vset}", capability=Capability.SOURCE_CONTROL, params={"voltage": vset}, verify_query=":VOLT?", expected=vset, description=f"Vset = {vset} V"),
        PresetStep(OpType.SET_LEVEL, f":CURR {iset}", capability=Capability.SOURCE_CONTROL, params={"current": iset}, verify_query=":CURR?", expected=iset, description=f"Ilim = {iset} A"),
        PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL, description="enable output (last)"),
    ]


def _psu_runner_env_rating(body: PsuApplyIn):
    t = manager.get("psu")
    if t is None:
        return None, None, None
    runner = PresetRunner(t, engine, instrument="psu", audit=audit)
    env = DUTSafetyEnvelope(body.dut_max_v, body.dut_max_i)
    rating = RatingModel(max_output_voltage=30.0, max_output_current=5.0)
    return runner, env, rating


@app.post("/api/psu/preview")
def psu_preview(body: PsuApplyIn) -> dict:
    runner, env, rating = _psu_runner_env_rating(body)
    if runner is None:
        return {"connected": False, "overall": "BLOCK", "ok_to_run": False, "steps": []}
    return runner.preview(_psu_steps(body.vset, body.iset, body.ovp, body.ocp), envelope=env, rating=rating)


@app.post("/api/psu/apply")
def psu_apply(body: PsuApplyIn) -> dict:
    runner, env, rating = _psu_runner_env_rating(body)
    if runner is None:
        return {"ok": False, "connected": False, "summary": "PSU not connected"}
    res = runner.run(_psu_steps(body.vset, body.iset, body.ovp, body.ocp), envelope=env, rating=rating, confirm=body.confirm)
    audit.record("psu_apply", ok=res.ok, rolled_back=res.rolled_back)
    return {"ok": res.ok, "provenance": res.provenance, "summary": res.summary, "rolled_back": res.rolled_back,
            "steps": [{"description": s.description, "verdict": s.verdict, "executed": s.executed,
                       "verified": s.verified, "error": s.error} for s in res.steps]}


@app.post("/api/psu/off")
def psu_off() -> dict:
    t = manager.get("psu")
    if t is None:
        return {"ok": False, "connected": False}
    t.write(":OUTP OFF")
    drain_error_queue(t)
    audit.record("psu_output_off_manual")
    return {"ok": True}


@app.websocket("/ws/psu")
async def ws_psu(ws: WebSocket) -> None:
    await ws.accept()

    def snap() -> dict:
        t = manager.get("psu")
        if t is None:
            return {"connected": False}

        def q(cmd: str) -> str:
            try:
                return t.query(cmd).strip()
            except Exception:  # noqa: BLE001
                return ""
        return {"connected": True, "provenance": t.default_provenance.value,
                "vset": safe_float(q(":VOLT?")), "iset": safe_float(q(":CURR?")),
                "vout": safe_float(q(":MEAS:VOLT?")), "iout": safe_float(q(":MEAS:CURR?")),
                "output_on": q(":OUTP?") in ("1", "ON", "on")}

    try:
        while True:
            try:
                await ws.send_json(await asyncio.to_thread(snap))
            except Exception as e:  # noqa: BLE001
                await ws.send_json({"connected": True, "error": str(e)})
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        return


# --- source: function generator (AWG) — safety-gated ----------------------
class AwgApplyIn(BaseModel):
    func: str = "SIN"
    freq: float
    vpp: float
    offset: float = 0.0
    dut_max_v: float
    dut_max_i: float = 1.0
    confirm: bool = False


def _awg_steps(func: str, freq: float, vpp: float, offset: float) -> list[PresetStep]:
    peak = abs(offset) + vpp / 2.0
    return [
        PresetStep(OpType.SET_PROTECTION, f":VOLT:LIMIT:HIGH {peak}", verify_query=":VOLT:LIMIT:HIGH?", expected=peak, description=f"Vhi limit = {peak} V"),
        PresetStep(OpType.SET_PROTECTION, f":VOLT:LIMIT:LOW {-peak}", verify_query=":VOLT:LIMIT:LOW?", expected=-peak, description=f"Vlo limit = {-peak} V"),
        PresetStep(OpType.CONFIGURE, ":VOLT:LIMIT:STAT ON", description="enable output limits"),
        PresetStep(OpType.CONFIGURE, f":FUNC {func}", description=f"shape = {func}"),
        PresetStep(OpType.CONFIGURE, f":FREQ {freq}", description=f"freq = {freq} Hz"),
        PresetStep(OpType.CONFIGURE, f":VOLT:OFFS {offset}", description=f"offset = {offset} V"),
        PresetStep(OpType.SET_LEVEL, f":VOLT {vpp}", capability=Capability.SOURCE_CONTROL, params={"voltage": peak}, verify_query=":VOLT?", expected=vpp, description=f"amplitude = {vpp} Vpp"),
        PresetStep(OpType.ENABLE_OUTPUT, ":OUTP ON", capability=Capability.SOURCE_CONTROL, description="enable output (last)"),
    ]


def _awg_runner_env_rating(body: AwgApplyIn):
    t = manager.get("awg")
    if t is None:
        return None, None, None
    return (PresetRunner(t, engine, instrument="awg", audit=audit),
            DUTSafetyEnvelope(body.dut_max_v, body.dut_max_i),
            RatingModel(max_output_voltage=10.0, max_output_current=1.0))


@app.post("/api/awg/preview")
def awg_preview(body: AwgApplyIn) -> dict:
    runner, env, rating = _awg_runner_env_rating(body)
    if runner is None:
        return {"connected": False, "overall": "BLOCK", "ok_to_run": False, "steps": []}
    return runner.preview(_awg_steps(body.func, body.freq, body.vpp, body.offset), envelope=env, rating=rating)


@app.post("/api/awg/apply")
def awg_apply(body: AwgApplyIn) -> dict:
    runner, env, rating = _awg_runner_env_rating(body)
    if runner is None:
        return {"ok": False, "connected": False, "summary": "AWG not connected"}
    res = runner.run(_awg_steps(body.func, body.freq, body.vpp, body.offset), envelope=env, rating=rating, confirm=body.confirm)
    audit.record("awg_apply", ok=res.ok, rolled_back=res.rolled_back)
    return {"ok": res.ok, "provenance": res.provenance, "summary": res.summary, "rolled_back": res.rolled_back,
            "steps": [{"description": s.description, "verdict": s.verdict, "executed": s.executed, "verified": s.verified, "error": s.error} for s in res.steps]}


@app.post("/api/awg/off")
def awg_off() -> dict:
    t = manager.get("awg")
    if t is None:
        return {"ok": False, "connected": False}
    t.write(":OUTP OFF")
    drain_error_queue(t)
    audit.record("awg_output_off_manual")
    return {"ok": True}


@app.websocket("/ws/awg")
async def ws_awg(ws: WebSocket) -> None:
    await ws.accept()

    def snap() -> dict:
        t = manager.get("awg")
        if t is None:
            return {"connected": False}

        def q(cmd: str) -> str:
            try:
                return t.query(cmd).strip()
            except Exception:  # noqa: BLE001
                return ""
        return {"connected": True, "provenance": t.default_provenance.value,
                "func": q(":FUNC?"), "freq": safe_float(q(":FREQ?")), "vpp": safe_float(q(":VOLT?")),
                "offset": safe_float(q(":VOLT:OFFS?")), "output_on": q(":OUTP?") in ("1", "ON", "on")}

    try:
        while True:
            try:
                await ws.send_json(await asyncio.to_thread(snap))
            except Exception as e:  # noqa: BLE001
                await ws.send_json({"connected": True, "error": str(e)})
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        return


# --- source: electronic load — safety-gated -------------------------------
class EloadApplyIn(BaseModel):
    mode: str = "CURR"
    level: float
    ocp: float
    dut_max_v: float = 100.0
    dut_max_i: float
    confirm: bool = False


# Constant-Current / Voltage / Resistance / Power: the level command + safety param follow the mode.
_ELOAD_MODE = {
    "CC": ("CURR", ":CURR", "A", "current"), "CURR": ("CURR", ":CURR", "A", "current"),
    "CV": ("VOLT", ":VOLT", "V", "voltage"), "VOLT": ("VOLT", ":VOLT", "V", "voltage"),
    "CR": ("RES", ":RES", "Ω", None), "RES": ("RES", ":RES", "Ω", None),
    "CP": ("POW", ":POW", "W", None), "POW": ("POW", ":POW", "W", None),
}


def _eload_steps(mode: str, level: float, ocp: float) -> list[PresetStep]:
    scpi_mode, lvl_cmd, unit, param = _ELOAD_MODE.get(mode.upper(), _ELOAD_MODE["CURR"])
    params = {param: level} if param else {}
    return [
        PresetStep(OpType.SET_PROTECTION, f":CURR:PROT {ocp}", verify_query=":CURR:PROT?", expected=ocp, description=f"OCP = {ocp} A"),
        PresetStep(OpType.CONFIGURE, f":FUNC {scpi_mode}", description=f"mode = {scpi_mode}"),
        PresetStep(OpType.SET_LEVEL, f"{lvl_cmd} {level}", capability=Capability.SOURCE_CONTROL, params=params,
                   verify_query=(":CURR?" if scpi_mode == "CURR" else None),
                   expected=(level if scpi_mode == "CURR" else None), description=f"{scpi_mode} level = {level} {unit}"),
        PresetStep(OpType.ENABLE_OUTPUT, ":INP ON", capability=Capability.SOURCE_CONTROL, description="enable input (last)"),
    ]


def _eload_runner_env_rating(body: EloadApplyIn):
    t = manager.get("eload")
    if t is None:
        return None, None, None
    return (PresetRunner(t, engine, instrument="eload", audit=audit, output_off_scpi=":INP OFF"),
            DUTSafetyEnvelope(body.dut_max_v, body.dut_max_i),
            RatingModel(max_output_voltage=150.0, max_output_current=30.0))


@app.post("/api/eload/preview")
def eload_preview(body: EloadApplyIn) -> dict:
    runner, env, rating = _eload_runner_env_rating(body)
    if runner is None:
        return {"connected": False, "overall": "BLOCK", "ok_to_run": False, "steps": []}
    return runner.preview(_eload_steps(body.mode, body.level, body.ocp), envelope=env, rating=rating)


@app.post("/api/eload/apply")
def eload_apply(body: EloadApplyIn) -> dict:
    runner, env, rating = _eload_runner_env_rating(body)
    if runner is None:
        return {"ok": False, "connected": False, "summary": "e-load not connected"}
    res = runner.run(_eload_steps(body.mode, body.level, body.ocp), envelope=env, rating=rating, confirm=body.confirm)
    audit.record("eload_apply", ok=res.ok, rolled_back=res.rolled_back)
    return {"ok": res.ok, "provenance": res.provenance, "summary": res.summary, "rolled_back": res.rolled_back,
            "steps": [{"description": s.description, "verdict": s.verdict, "executed": s.executed, "verified": s.verified, "error": s.error} for s in res.steps]}


@app.post("/api/eload/off")
def eload_off() -> dict:
    t = manager.get("eload")
    if t is None:
        return {"ok": False, "connected": False}
    t.write(":INP OFF")
    drain_error_queue(t)
    audit.record("eload_input_off_manual")
    return {"ok": True}


@app.websocket("/ws/eload")
async def ws_eload(ws: WebSocket) -> None:
    await ws.accept()

    def snap() -> dict:
        t = manager.get("eload")
        if t is None:
            return {"connected": False}

        def q(cmd: str) -> str:
            try:
                return t.query(cmd).strip()
            except Exception:  # noqa: BLE001
                return ""
        return {"connected": True, "provenance": t.default_provenance.value,
                "mode": q(":FUNC?"), "level": safe_float(q(":CURR?")), "ocp": safe_float(q(":CURR:PROT?")),
                "vout": safe_float(q(":MEAS:VOLT?")), "iout": safe_float(q(":MEAS:CURR?")),
                "input_on": q(":INP?") in ("1", "ON", "on")}

    try:
        while True:
            try:
                await ws.send_json(await asyncio.to_thread(snap))
            except Exception as e:  # noqa: BLE001
                await ws.send_json({"connected": True, "error": str(e)})
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        return


# --- presets (operate on the connected instrument) -----------------------
def _runner_and_rating(preset: Preset):
    t = manager.get(preset.instrument)
    if t is None:
        return None, None
    runner = PresetRunner(t, engine, instrument=preset.instrument, audit=audit)
    rating = RatingModel(max_output_voltage=30.0, max_output_current=5.0) if preset.instrument == "psu" else None
    return runner, rating


def _envelope_from(body: PresetApplyIn) -> DUTSafetyEnvelope | None:
    if body.envelope is None:
        return None
    return DUTSafetyEnvelope(body.envelope.max_voltage, body.envelope.max_current)


@app.get("/api/presets")
def list_presets() -> list[dict]:
    return [{"id": p.id, "name": p.name, "instrument": p.instrument, "testing_for": p.testing_for,
             "requires_envelope": p.requires_envelope, "requires_confirm": p.requires_confirm,
             "suggested_envelope": p.suggested_envelope, "n_steps": len(p.steps)} for p in PRESETS.values()]


@app.post("/api/presets/{pid}/preview")
def preview_preset(pid: str, body: PresetApplyIn | None = None) -> dict:
    preset = PRESETS.get(pid)
    if preset is None:
        raise HTTPException(status_code=404, detail="no such preset")
    body = body or PresetApplyIn()
    runner, rating = _runner_and_rating(preset)
    if runner is None:
        return {"ok_to_run": False, "overall": "BLOCK", "ordering_error": None,
                "provenance": None, "steps": [], "connected": False}
    return runner.preview(preset.steps, envelope=_envelope_from(body), rating=rating)


@app.post("/api/presets/{pid}/apply")
def apply_preset(pid: str, body: PresetApplyIn | None = None) -> dict:
    preset = PRESETS.get(pid)
    if preset is None:
        raise HTTPException(status_code=404, detail="no such preset")
    body = body or PresetApplyIn()
    runner, rating = _runner_and_rating(preset)
    if runner is None:
        return {"ok": False, "connected": False, "summary": f"{preset.instrument} not connected"}
    res = runner.run(preset.steps, envelope=_envelope_from(body), rating=rating, confirm=body.confirm)
    audit.record("preset_apply", preset=pid, ok=res.ok, rolled_back=res.rolled_back)
    return {"ok": res.ok, "provenance": res.provenance, "summary": res.summary, "rolled_back": res.rolled_back,
            "steps": [{"description": s.description, "verdict": s.verdict, "executed": s.executed,
                       "verified": s.verified, "error": s.error} for s in res.steps]}


# --- calculators / parts / kicad -----------------------------------------
class KicadIn(BaseModel):
    path: str | None = None
    text: str | None = None


@app.get("/api/calc")
def calc_list() -> dict:
    return {"calculators": calculators.CALC_META}


@app.post("/api/calc/{name}")
def calc_run(name: str, body: dict | None = None) -> dict:
    fn = calculators.CALCS.get(name)
    if fn is None:
        raise HTTPException(status_code=404, detail="no such calculator")
    try:
        return {"ok": True, "result": fn(**(body or {}))}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/parts/status")
def parts_status() -> dict:
    return parts.status()


@app.get("/api/parts/search")
def parts_search(query: str = "", category: str | None = None, provider: str = "offline", limit: int = 20,
                 spec_key: str | None = None, vmin: float | None = None, vmax: float | None = None) -> dict:
    try:
        return {"ok": True, **parts.search(query, category, limit, provider, spec_key, vmin, vmax)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/parts/parse")
def parts_parse(text: str, unit: str | None = None) -> dict:
    """Normalize a component-value string (e.g. '4k7', '4.7µF', '±10%') to typed {value, unit, display}."""
    return parts.parse_value(text, unit)


@app.post("/api/kicad/analyze")
def kicad_analyze_ep(body: KicadIn) -> dict:
    try:
        if body.text:
            return {"ok": True, **kicad_analyze.analyze_text(body.text)}
        if body.path:
            return {"ok": True, **kicad_analyze.analyze_path(body.path)}
        raise ValueError("provide 'text' or 'path'")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# --- CAN bus (offline DBC decode) ----------------------------------------
class CanDecodeIn(BaseModel):
    dbc: str
    log: str


@app.post("/api/can/decode")
def can_decode_ep(body: CanDecodeIn) -> dict:
    try:
        msgs = can_decode.parse_dbc(body.dbc)
        frames = can_decode.parse_log(body.log)
        return {"ok": True, "messages": len(msgs), "decoded": can_decode.decode_frames(msgs, frames)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# --- logic analyzer (SPI / I2C / UART) -----------------------------------
class LogicDecodeIn(BaseModel):
    protocol: str
    sample_rate: float
    channels: dict[str, list[int]]
    mapping: dict[str, str] = {}
    options: dict = {}


_LOGIC_REQUIRED = {"spi": ["clk"], "i2c": ["scl", "sda"], "uart": ["rx"]}


@app.get("/api/logic/sample")
def logic_sample(protocol: str = "spi") -> dict:
    return logic_decode.sample_capture(protocol)


@app.post("/api/logic/decode")
def logic_decode_ep(body: LogicDecodeIn) -> dict:
    p = body.protocol.lower()
    if p not in logic_decode.DECODERS:
        return {"ok": False, "error": f"unknown protocol {p!r}"}
    m, ch = body.mapping, body.channels
    missing = [r for r in _LOGIC_REQUIRED.get(p, []) if not ch.get(m.get(r, r))]
    if missing:
        return {"ok": False, "error": f"missing channel mapping for: {', '.join(missing)}"}

    def sig(role: str):
        name = m.get(role, role)
        return ch.get(name)

    opt = body.options
    try:
        if p == "spi":
            frames = logic_decode.decode_spi(
                sig("clk"), sig("mosi"), sig("miso"), sig("cs"), body.sample_rate,
                cpol=int(opt.get("cpol", 0)), cpha=int(opt.get("cpha", 0)),
                bitorder=opt.get("bitorder", "msb"), word_size=int(opt.get("word_size", 8)))
        elif p == "i2c":
            frames = logic_decode.decode_i2c(sig("scl"), sig("sda"), body.sample_rate)
        else:
            frames = logic_decode.decode_uart(
                sig("rx"), body.sample_rate, float(opt.get("baud", 9600)),
                int(opt.get("databits", 8)), opt.get("parity", "none"), int(opt.get("stopbits", 1)))
        return {"ok": True, "protocol": p, "count": len(frames), "frames": frames}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _find_sigrok_cli() -> str | None:
    """sigrok-cli on PATH or in its standard install locations (PATH alone misses most installs)."""
    import glob as _glob
    import shutil

    hit = shutil.which("sigrok-cli")
    if hit:
        return hit
    for pat in (r"C:\Program Files\sigrok\sigrok-cli\sigrok-cli.exe",
                r"C:\Program Files (x86)\sigrok\sigrok-cli\sigrok-cli.exe",
                r"C:\Program Files\sigrok\*\sigrok-cli.exe"):
        hits = _glob.glob(pat)
        if hits:
            return hits[0]
    return None


def _find_pulseview() -> str | None:
    import glob as _glob
    for pat in (r"C:\Program Files\sigrok\PulseView\pulseview.exe",
                r"C:\Program Files (x86)\sigrok\PulseView\pulseview.exe"):
        hits = _glob.glob(pat)
        if hits:
            return hits[0]
    return None


@app.get("/api/logic/sources")
def logic_sources() -> dict:
    """Available capture paths: sigrok-cli (in-app capture), PulseView (GUI capture →
    export CSV → import here), Saleae automation API."""
    sigrok = _find_sigrok_cli()
    pv = _find_pulseview()
    try:
        import saleae  # noqa: F401
        saleae_ok = True
    except Exception:  # noqa: BLE001
        saleae_ok = False
    return {"sources": [
        {"id": "sigrok", "name": "sigrok-cli — in-app capture (FX2LA + many brands)",
         "available": bool(sigrok), "path": sigrok,
         "install": {"software": "sigrok-cli", "url": "https://sigrok.org/wiki/Downloads"}},
        {"id": "pulseview", "name": "PulseView — GUI capture, then import the CSV here",
         "available": bool(pv), "path": pv, "launchable": bool(pv),
         "install": {"software": "PulseView", "url": "https://sigrok.org/wiki/Downloads"}},
        {"id": "saleae", "name": "Saleae Logic 2 (automation API)",
         "available": saleae_ok,
         "install": {"software": "Saleae Logic 2", "url": "https://www.saleae.com/downloads/"}},
    ]}


@app.post("/api/logic/launch-pulseview")
def logic_launch_pulseview() -> dict:
    pv = _find_pulseview()
    if not pv:
        return {"ok": False, "error": "PulseView not found"}
    shell_open.open_path(pv)
    audit.record("pulseview_launch")
    return {"ok": True, "launched": pv}


class LogicCaptureIn(BaseModel):
    driver: str = "fx2lafw"        # sigrok driver, e.g. fx2lafw / saleae-logic
    channels: int = 8
    sample_rate: int = 1_000_000
    samples: int = 200_000


@app.post("/api/logic/capture")
def logic_capture(body: LogicCaptureIn) -> dict:
    """Capture from a real device via sigrok-cli (brand-agnostic). Honest error if sigrok
    isn't installed or no device answers."""
    import subprocess

    exe = _find_sigrok_cli()
    if not exe:
        pv = _find_pulseview()
        hint = ("PulseView is installed — capture there and import the CSV, or install "
                "sigrok-cli for in-app capture") if pv else "install sigrok-cli"
        return {"ok": False, "error": f"sigrok-cli not found — {hint}",
                "install": "https://sigrok.org/wiki/Downloads"}
    cmd = [exe, "--driver", body.driver, "--config", f"samplerate={body.sample_rate}",
           "--samples", str(body.samples), "-O", "csv"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    if res.returncode != 0:
        return {"ok": False, "error": (res.stderr or res.stdout or "capture failed").strip()[:300]}
    rows = [ln for ln in res.stdout.splitlines() if ln and not ln.startswith(";")]
    if not rows:
        return {"ok": False, "error": "no samples returned"}
    header = [h.strip() for h in rows[0].split(",")]
    channels: dict[str, list[int]] = {h: [] for h in header}
    for ln in rows[1:]:
        for h, v in zip(header, ln.split(",")):
            channels[h].append(1 if v.strip() in ("1", "1.0") else 0)
    return {"ok": True, "sample_rate": body.sample_rate, "channels": channels}


# --- assistant + agent bridge --------------------------------------------
@app.get("/api/assistant/status")
def assistant_status() -> dict:
    a = Assistant(registry)
    return {"available": a.available(), "model": a.model}


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()
    assistant = Assistant(registry)
    history: list[dict] = []
    try:
        while True:
            data = await ws.receive_json()
            msg = str(data.get("message", "")).strip()
            if not msg:
                continue
            full = ""
            async for ev in assistant.run(msg, history):
                await ws.send_json(ev)
                if ev.get("type") == "text":
                    full += ev["text"]
            await ws.send_json({"type": "turn_end"})
            history.append({"role": "user", "content": msg})
            if full:
                history.append({"role": "assistant", "content": full})
    except WebSocketDisconnect:
        return


@app.get("/api/agent/status")
def agent_status() -> dict:
    return mcp_bridge.status(registry)


@app.post("/api/agent/run")
async def agent_run(body: AgentRunIn) -> dict:
    return await mcp_bridge.run_agent_task(registry, body.prompt)


# --- serve the built renderer (portable / browser mode) ---------------------------------
# Mounted LAST so every /api and /ws route above still wins. In the portable bundle RUN.cmd sets
# ECE_SUITE_DIST to the shipped renderer/dist; in the dev repo we fall back to the repo layout.
def _mount_ui() -> None:
    dist = os.environ.get("ECE_SUITE_DIST")
    if not dist:
        cand = Path(__file__).resolve().parents[2] / "apps" / "renderer" / "dist"
        dist = str(cand) if cand.is_dir() else None
    if dist and Path(dist).is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")


_mount_ui()


def main() -> None:
    parser = argparse.ArgumentParser(description="ECE Tool Suite backend sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ECE_SUITE_PORT", "8848")))
    args = parser.parse_args()

    import uvicorn

    audit.record("sidecar_start", host=args.host, port=args.port, version=__version__, mode="hardware")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
