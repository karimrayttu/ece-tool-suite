"""MCU flash programming / firmware extraction — native integration of Microchip's pymcuprog.

Drives a UPDI/PDI/debugWIRE debugger (Curiosity Nano, Atmel-ICE, MPLAB SNAP, PICkit) to read a
target's device ID, supply voltage, and **flash memory** — i.e. dump firmware off an AVR/PIC —
and (behind a confirm gate) erase or write it. This is the pymcuprog-MCP capability built
directly into the app rather than as a separate server.

Hardware-first: with no debugger attached, discovery returns an empty list and reads error
honestly. The device catalog + device info work offline (metadata only).
"""

from __future__ import annotations

import base64
import io
from functools import lru_cache


def available() -> bool:
    try:
        import pymcuprog  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def supported_devices() -> list[str]:
    try:
        from pymcuprog.deviceinfo.deviceinfo import get_supported_devices
        return sorted(get_supported_devices())
    except Exception:  # noqa: BLE001
        return []


def device_info(name: str) -> dict:
    try:
        from pymcuprog.deviceinfo import deviceinfo
        di = deviceinfo.getdeviceinfo(name)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    out: dict = {}
    for k, v in di.items():
        if isinstance(v, (int, str, bool)):
            out[k] = v
    return out


def list_tools() -> list[dict]:
    """Connected debuggers/programmers (empty if none attached)."""
    try:
        from pymcuprog.backend import Backend
        tools = Backend().get_available_hid_tools()
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for t in tools:
        out.append({
            "product": getattr(t, "product_string", None) or getattr(t, "product", None) or str(t),
            "serial": getattr(t, "serial_number", None) or getattr(t, "serial", None),
            "manufacturer": getattr(t, "manufacturer_string", None),
        })
    return out


def status() -> dict:
    if not available():
        return {"available": False, "tools": [], "n_devices": 0,
                "install": {"software": "pymcuprog", "url": "https://pypi.org/project/pymcuprog/"}}
    return {"available": True, "tools": list_tools(), "n_devices": len(supported_devices())}


def _intel_hex(base: int, data: bytes) -> str:
    try:
        from intelhex import IntelHex
        ih = IntelHex()
        ih.frombytes(bytes(data), offset=base)
        s = io.StringIO()
        ih.write_hex_file(s)
        return s.getvalue()
    except Exception:  # noqa: BLE001
        return ""


def _with_session(device: str, tool_serial: str | None, fn):
    """Connect → start_session(device) → fn(backend) → clean up. Honest errors, no hardware."""
    if not available():
        return {"ok": False,
                "error": "pymcuprog is not installed, so no debugger can be driven",
                "install": 'pip install -e "backend[mcu]"'}

    from pymcuprog.backend import Backend, SessionConfig
    from pymcuprog.toolconnection import ToolUsbHidConnection

    be = Backend()
    tools = be.get_available_hid_tools(serialnumber_substring=tool_serial or "")
    if not tools:
        return {"ok": False, "error": "no debugger connected (Curiosity Nano / Atmel-ICE / SNAP / PICkit)"}
    try:
        be.connect_to_tool(ToolUsbHidConnection(serialnumber=tool_serial or ""))
        be.start_session(SessionConfig(device))
        result = fn(be)
        be.end_session()
        return result
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    finally:
        try:
            be.disconnect_from_tool()
        except Exception:  # noqa: BLE001
            pass


def read_target(device: str, tool_serial: str | None = None, memory: str = "flash",
                max_bytes: int = 0) -> dict:
    """Read the target's device ID, supply voltage, and a memory region (default flash) — the
    firmware dump. Returns Intel-HEX text + base64 raw bytes for download."""
    info = device_info(device)
    size = max_bytes or int(info.get(f"{memory}_size_bytes", 0) or 0)

    def _do(be) -> dict:
        did = be.read_device_id()
        try:
            volt = be.read_target_voltage()
        except Exception:  # noqa: BLE001
            volt = None
        segs = be.read_memory(memory, 0, size)
        data = bytearray()
        base = None
        for s in segs:
            if base is None:
                base = int(getattr(s, "offset", 0) or 0)
            data += bytes(getattr(s, "data", b"") or b"")
        base = base or 0
        return {
            "ok": True, "device": device, "memory": memory,
            "device_id": did.hex() if isinstance(did, (bytes, bytearray)) else str(did),
            "voltage": volt, "bytes": len(data), "base_address": base,
            "data_b64": base64.b64encode(bytes(data)).decode(),
            "intel_hex": _intel_hex(base, bytes(data)),
        }

    return _with_session(device, tool_serial, _do)


def chip_erase(device: str, tool_serial: str | None, confirm: bool = False) -> dict:
    """Full chip erase — DESTRUCTIVE. Requires confirm=True."""
    if not confirm:
        return {"ok": False, "error": "chip erase requires confirm=true (this wipes the target)"}

    def _do(be) -> dict:
        be.erase("all", None)
        return {"ok": True, "device": device, "action": "chip_erase"}

    return _with_session(device, tool_serial, _do)


def write_hex(device: str, tool_serial: str | None, hex_text: str, confirm: bool = False) -> dict:
    """Program an Intel-HEX image to the target — DESTRUCTIVE. Requires confirm=True."""
    if not confirm:
        return {"ok": False, "error": "write requires confirm=true (this reprograms the target)"}
    import tempfile

    def _do(be) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".hex", delete=False) as f:
            f.write(hex_text)
            path = f.name
        be.write_hex_to_target(path)
        return {"ok": True, "device": device, "action": "write_hex", "bytes": len(hex_text)}

    return _with_session(device, tool_serial, _do)
