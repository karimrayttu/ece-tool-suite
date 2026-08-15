"""I/O environment: what instrument software is installed, what's physically plugged in,
and (if a plugged-in device can't be driven yet) which package to install.

This lets the app say "you plugged in a Keysight scope but the VISA layer isn't installed —
here's the download link", then auto-connect the instant the layer is present.
"""

from __future__ import annotations

import re
import subprocess

from .instruments.vendors import vendor_display, vendor_for_vid

# capability -> (display name, download URL). Keysight IO Libraries covers USBTMC for *all*
# vendors, so it's the default recommendation; NI-VISA is the common alternative.
SOFTWARE = {
    "keysight_io": ("Keysight IO Libraries Suite", "https://www.keysight.com/find/iosuite"),
    "ni_visa": ("NI-VISA", "https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html"),
    "tekvisa": ("TekVISA", "https://www.tek.com/en/support/software/driver/tekvisa-connectivity-software"),
}


def visa_backends() -> list[dict]:
    """Which VISA implementations load (system Keysight/NI/R&S + pyvisa-py)."""
    import pyvisa

    out: list[dict] = []
    for cand, label in (("", "System VISA (Keysight / NI / R&S)"), ("@py", "pyvisa-py (pure Python)")):
        info: dict = {"backend": cand or "system", "label": label, "available": False}
        try:
            rm = pyvisa.ResourceManager(cand)
            info["available"] = True
            try:
                info["spec"] = str(getattr(rm.visalib, "library_path", "")) or type(rm.visalib).__name__
            except Exception:  # noqa: BLE001
                pass
            rm.close()
        except Exception as e:  # noqa: BLE001
            info["error"] = str(e)
        out.append(info)
    return out


def usb_backend_ok() -> bool:
    """Can pyvisa-py talk USBTMC? (needs pyusb + a libusb backend present)."""
    try:
        import usb.backend.libusb1 as libusb1
        import usb.core  # noqa: F401
        return libusb1.get_backend() is not None
    except Exception:  # noqa: BLE001
        return False


_INSTID_VIDPID = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")
# USB Test & Measurement class: bInterfaceClass 0xFE, bInterfaceSubClass 0x03. Any instrument
# that speaks USBTMC advertises this in its compatible IDs, regardless of vendor.
_USBTMC_RE = re.compile(r"Class_FE&SubClass_03", re.IGNORECASE)


def _compat_list(dev: dict) -> list[str]:
    c = dev.get("CompatibleID")
    if c is None:
        return []
    if isinstance(c, str):
        return [c]
    return [str(x) for x in c]


def detect_usb_instruments() -> list[dict]:
    """List attached USB bench instruments from the Windows PnP tree — works with NO VISA/driver
    installed. A device counts as an instrument if its VID is a known test-equipment vendor OR
    it advertises the USBTMC device class (vendor-agnostic)."""
    ps = (
        "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
        "Where-Object { $_.PNPDeviceID -like 'USB\\VID_*' } | "
        "Select-Object Name, PNPDeviceID, CompatibleID, Status | "
        "ConvertTo-Json -Compress -Depth 3"
    )
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=10)
        raw = res.stdout.strip()
    except Exception:  # noqa: BLE001
        return []
    if not raw:
        return []

    import json
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]

    seen: set[str] = set()
    found: list[dict] = []
    for dev in data:
        iid = str(dev.get("PNPDeviceID", ""))
        m = _INSTID_VIDPID.search(iid)
        if not m:
            continue
        vid = int(m.group(1), 16)
        vendor = vendor_for_vid(vid)
        usbtmc = any(_USBTMC_RE.search(c) for c in _compat_list(dev))
        if vendor == "unknown" and not usbtmc:
            continue  # neither a known instrument vendor nor a USBTMC device
        key = f"{m.group(1)}:{m.group(2)}"
        if key in seen:
            continue
        seen.add(key)
        name = str(dev.get("Name") or "").strip()
        if not name:
            name = f"{vendor_display(vendor)} USB instrument" if vendor != "unknown" else "USB test instrument (USBTMC)"
        found.append({
            "vendor": vendor,
            "vendor_name": vendor_display(vendor) if vendor != "unknown" else "USBTMC instrument",
            "vid": f"0x{m.group(1).upper()}",
            "pid": f"0x{m.group(2).upper()}",
            "name": name,
            "usbtmc": usbtmc,
            "status": str(dev.get("Status", "")),
        })
    return found


def discover_lan(timeout: float = 1.5) -> list[dict]:
    """Best-effort mDNS/LXI discovery of instruments on the local network. Returns hosts with a
    ready-to-open VISA resource. Empty if zeroconf isn't available or nothing answers."""
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except Exception:  # noqa: BLE001
        return []

    import time

    services = ["_scpi-raw._tcp.local.", "_lxi._tcp.local.", "_vxi-11._tcp.local.", "_hislip._tcp.local."]
    found: dict[str, dict] = {}

    class _L(ServiceListener):
        def _add(self, zc: Zeroconf, type_: str, name: str) -> None:  # noqa: D401
            try:
                info = zc.get_service_info(type_, name, timeout=int(timeout * 1000))
            except Exception:  # noqa: BLE001
                return
            if not info:
                return
            addrs = []
            try:
                addrs = info.parsed_addresses()
            except Exception:  # noqa: BLE001
                pass
            host = addrs[0] if addrs else None
            if not host:
                return
            if "_scpi-raw" in type_:
                resource = f"TCPIP0::{host}::{info.port or 5025}::SOCKET"
            else:
                resource = f"TCPIP0::{host}::inst0::INSTR"
            found[host + type_] = {
                "host": host, "name": name.split(".")[0], "service": type_.split(".")[0].lstrip("_"),
                "resource": resource,
            }

        def add_service(self, zc, type_, name): self._add(zc, type_, name)
        def update_service(self, zc, type_, name): self._add(zc, type_, name)
        def remove_service(self, zc, type_, name): pass

    zc = None
    try:
        zc = Zeroconf()
        ServiceBrowser(zc, services, _L())
        time.sleep(timeout)
    except Exception:  # noqa: BLE001
        return []
    finally:
        if zc is not None:
            try:
                zc.close()
            except Exception:  # noqa: BLE001
                pass
    return list(found.values())


def assess() -> dict:
    """Full picture: VISA backends, drivability, plugged-in instruments, and — if any USB
    instrument can't be driven yet — the software to install."""
    backends = visa_backends()
    system_visa = any(b["backend"] == "system" and b["available"] for b in backends)
    lan_ok = any(b["available"] for b in backends)  # pyvisa-py alone drives LAN
    usb_ok = system_visa or usb_backend_ok()

    usb_instruments = detect_usb_instruments()
    recommendations: list[dict] = []
    if usb_instruments and not usb_ok:
        name, url = SOFTWARE["keysight_io"]
        vendors = ", ".join(sorted({d["vendor_name"] for d in usb_instruments}))
        recommendations.append({
            "reason": f"USB instrument detected ({vendors}) but no VISA layer can talk USBTMC.",
            "software": name, "url": url,
            "alt": {"software": SOFTWARE["ni_visa"][0], "url": SOFTWARE["ni_visa"][1]},
        })

    return {
        "backends": backends,
        "system_visa": system_visa,
        "usb_drivable": usb_ok,
        "lan_drivable": lan_ok,
        "usb_instruments": usb_instruments,
        "recommendations": recommendations,
        "ready": usb_ok or lan_ok,
    }
