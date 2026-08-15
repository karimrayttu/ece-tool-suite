"""One-click acquisition of the suite's third-party tools — from OFFICIAL sources only.

Two honest classes of dependency:

* ``auto``   — freely redistributed from the project's own official channel (GitHub releases
               of YosysHQ / ghdl / chipsalliance, or a pinned winget package ID, which is the
               vendor's silent-install channel). One click: the backend downloads with live
               progress, installs to the location the app's detection already probes, and
               re-runs detection to prove it worked.
* ``page``   — login/EULA-gated vendors (Keysight, ST, NI, …). No bypassing vendor auth:
               one click opens the OFFICIAL download page plus what-to-do notes.

Guardrails: downloads are restricted to an allowlist of official hosts, archive members are
sanity-checked before extraction, every install is user-initiated per tool per click, and the
result is verified by the same detection the rest of the app trusts (never "assume done").
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

# Hosts we will download bytes from. GitHub release assets redirect to
# *.githubusercontent.com; everything else is refused outright.
ALLOWED_HOSTS = {
    "github.com", "api.github.com",
    "objects.githubusercontent.com", "release-assets.githubusercontent.com",
    "codeload.github.com",
}

_LOCK = threading.Lock()
_STATUS: dict[str, dict] = {}   # tool_id -> {state, progress, detail, error, finished}
_THREADS: dict[str, threading.Thread] = {}


# --- install locations ----------------------------------------------------
def suite_root() -> Path:
    """Where the HDL toolchain lives (existing install if detected, else the default)."""
    from . import rtl
    root = rtl._suite_root()
    return root if root else (Path.home() / "oss-cad-suite")


# --- catalog --------------------------------------------------------------
# kind=auto entries carry a recipe; kind=page entries carry instructions only.
def _catalog() -> list[dict]:
    return [
        # --- HDL / FPGA toolchain (GitHub official releases, ISC/Apache/GPL FOSS) ---
        {
            "id": "oss-cad-suite", "group": "HDL / FPGA toolchain",
            "name": "OSS CAD Suite", "kind": "auto", "approx_mb": 320,
            "purpose": "Verilog/SystemVerilog simulate + lint + synthesize + FPGA place-and-route "
                       "(iverilog, vvp, Verilator, Yosys, nextpnr, openFPGALoader, gtkwave)",
            "source": "github.com/YosysHQ/oss-cad-suite-build (official releases)",
            "url": "https://github.com/YosysHQ/oss-cad-suite-build/releases/latest",
            "recipe": {"type": "github-sfx", "repo": "YosysHQ/oss-cad-suite-build",
                       "asset": r"windows-x64.*\.exe$"},
        },
        {
            "id": "ghdl", "group": "HDL / FPGA toolchain",
            "name": "GHDL (VHDL)", "kind": "auto", "approx_mb": 23,
            "purpose": "VHDL analysis + simulation for the RTL tab",
            "source": "github.com/ghdl/ghdl (official releases)",
            "url": "https://github.com/ghdl/ghdl/releases/latest",
            "recipe": {"type": "github-zip", "repo": "ghdl/ghdl",
                       "asset": r"ghdl-mcode-.*-ucrt64\.zip$", "target": "ghdl-subdir"},
        },
        {
            "id": "verible", "group": "HDL / FPGA toolchain",
            "name": "Verible (SV lint + format)", "kind": "auto", "approx_mb": 7,
            "purpose": "SystemVerilog style lint and the Format button",
            "source": "github.com/chipsalliance/verible (official releases)",
            "url": "https://github.com/chipsalliance/verible/releases/latest",
            "recipe": {"type": "github-zip", "repo": "chipsalliance/verible",
                       "asset": r"win64\.zip$", "target": "bin-exes"},
        },
        # --- simulation / EDA (vendor freeware via winget, the vendor's silent channel) ---
        {
            "id": "ltspice", "group": "Simulation / EDA",
            "name": "LTspice", "kind": "auto", "approx_mb": 400,
            "purpose": "SPICE power-stage verification engine (preferred over ngspice)",
            "source": "winget: ADI.LTspice (Analog Devices official package)",
            "url": "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html",
            "recipe": {"type": "winget", "package": "ADI.LTspice"},
        },
        {
            "id": "kicad", "group": "Simulation / EDA",
            "name": "KiCad 9", "kind": "auto", "approx_mb": 1200,
            "purpose": "Schematic/PCB analysis tab; also bundles ngspice (SPICE fallback engine)",
            "source": "winget: KiCad.KiCad (KiCad official package)",
            "url": "https://www.kicad.org/download/windows/",
            "recipe": {"type": "winget", "package": "KiCad.KiCad"},
        },
        # --- login/EULA-gated vendors: one click opens the OFFICIAL page ---
        {
            "id": "keysight-iolibs", "group": "Instruments / VISA",
            "name": "Keysight IO Libraries Suite", "kind": "page",
            "purpose": "System VISA that enumerates USB (USBTMC) bench instruments",
            "source": "keysight.com (requires free Keysight login)",
            "url": "https://www.keysight.com/find/iosuite",
            "note": "Download 'IO Libraries Suite', run the installer, then use Discover in the "
                    "Connections tab — USB instruments appear once the Keysight VISA is present.",
        },
        {
            "id": "ni-visa", "group": "Instruments / VISA",
            "name": "NI-VISA (alternative)", "kind": "page",
            "purpose": "Alternative system VISA if you prefer NI over Keysight",
            "source": "ni.com (requires free NI login)",
            "url": "https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html",
            "note": "Only one system VISA is needed — skip if Keysight IO Libraries is installed.",
        },
        {
            "id": "stm32cubeclt", "group": "MCU / vendor tools",
            "name": "STM32CubeCLT", "kind": "page",
            "purpose": "STM32 command-line build + flash toolchain used by the STM32 tab",
            "source": "st.com (requires free ST login)",
            "url": "https://www.st.com/en/development-tools/stm32cubeclt.html",
            "note": "Install with defaults; the STM32 tab's tool detection finds it under C:\\ST.",
        },
        {
            "id": "stm32cubemx", "group": "MCU / vendor tools",
            "name": "STM32CubeMX", "kind": "page",
            "purpose": ".ioc pin-mux editing companion for the STM32 tab",
            "source": "st.com (requires free ST login)",
            "url": "https://www.st.com/en/development-tools/stm32cubemx.html",
        },
        {
            "id": "labview", "group": "MCU / vendor tools",
            "name": "NI LabVIEW (+ LabVIEW CLI)", "kind": "page",
            "purpose": "LabVIEW tab: open projects, run VIs headless, execute build specs",
            "source": "ni.com (requires free NI login)",
            "url": "https://www.ni.com/en/support/downloads/software-products/download.labview.html",
            "note": "Install LabVIEW plus the 'LabVIEW CLI' component (in NI Package Manager) — "
                    "the suite drives LabVIEW through NI's official CLI.",
        },
        {
            "id": "vivado", "group": "FPGA vendor tools",
            "name": "AMD Vivado (Xilinx FPGAs)", "kind": "page",
            "purpose": "Synthesize/implement the RTL tab's generated Vivado projects "
                       "(Artix/Spartan/Kintex/Zynq); ~30+ GB install",
            "source": "amd.com (requires free AMD account)",
            "url": "https://www.xilinx.com/support/download.html",
            "note": "Vivado ML Standard is free for the parts the RTL tab targets. "
                    "CoolRunner-II CPLDs need legacy ISE 14.7 from the same archive page.",
        },
        {
            "id": "quartus", "group": "FPGA vendor tools",
            "name": "Intel Quartus Prime Lite", "kind": "page",
            "purpose": "Compile the RTL tab's generated Quartus projects "
                       "(Cyclone FPGAs, MAX 10, MAX II/V CPLDs)",
            "source": "intel.com (requires free Intel account)",
            "url": "https://www.intel.com/content/www/us/en/software-kit/785086/intel-quartus-prime-lite-edition-design-software.html",
            "note": "Lite edition is free and covers every Cyclone/MAX part the suite targets.",
        },
        {
            "id": "radiant", "group": "FPGA vendor tools",
            "name": "Lattice Radiant", "kind": "page",
            "purpose": "Vendor flow for iCE40/MachXO3/Nexus (free license); the open "
                       "yosys+nextpnr flow bundled with the suite covers iCE40/ECP5/MachXO2 without it",
            "source": "latticesemi.com (requires free Lattice account + free license)",
            "url": "https://www.latticesemi.com/latticeradiant",
        },
        {
            "id": "diamond", "group": "FPGA vendor tools",
            "name": "Lattice Diamond", "kind": "page",
            "purpose": "Classic vendor flow for MachXO2/MachXO3 CPLD-class parts",
            "source": "latticesemi.com (requires free Lattice account + free license)",
            "url": "https://www.latticesemi.com/latticediamond",
        },
        {
            "id": "sigrok-cli", "group": "Instruments / VISA",
            "name": "sigrok-cli", "kind": "page",
            "purpose": "Real logic-analyzer capture (FX2-based analyzers) for the Logic tab",
            "source": "sigrok.org (official builds)",
            "url": "https://sigrok.org/wiki/Downloads",
            "note": "Install the Windows sigrok-cli build; the Logic tab detects it on PATH.",
        },
    ]


# --- installed-state detection (reuse the app's own detectors) ------------
def _installed(tool_id: str) -> tuple[bool, str | None]:
    from . import rtl
    if tool_id == "oss-cad-suite":
        tc = rtl.toolchain()
        ok = tc["capabilities"]["simulate_verilog"] and tc["capabilities"]["synthesize"]
        path = next((t["path"] for t in tc["tools"] if t["id"] == "yosys" and t["path"]), None)
        return ok, path
    if tool_id == "ghdl":
        return rtl.toolchain()["capabilities"]["lint_vhdl"], rtl._which("ghdl")
    if tool_id == "verible":
        return rtl.toolchain()["capabilities"]["format"], rtl._which("verible-verilog-format")
    if tool_id in ("ltspice", "kicad"):
        from . import design_tools
        hit = next((t for t in design_tools.detect_tools()
                    if t["id"] == tool_id and t["installed"]), None)
        return (hit is not None), (hit["path"] if hit else None)
    if tool_id in ("keysight-iolibs", "ni-visa"):
        from . import io_env
        return any(b["backend"] == "system" and b["available"]
                   for b in io_env.visa_backends()), None
    if tool_id in ("stm32cubeclt", "stm32cubemx"):
        from . import design_tools
        did = "cubeclt" if tool_id == "stm32cubeclt" else "cubemx"
        hit = next((t for t in design_tools.detect_tools()
                    if t["id"] == did and t["installed"]), None)
        return (hit is not None), (hit["path"] if hit else None)
    if tool_id == "sigrok-cli":
        from .main import _find_pulseview, _find_sigrok_cli
        cli = _find_sigrok_cli()
        if cli:
            return True, cli
        pv = _find_pulseview()
        return (pv is not None), pv   # PulseView counts: GUI capture + CSV import works
    if tool_id == "labview":
        from . import labview
        st = labview.status()
        return st["installed"], st["default"]
    if tool_id in ("vivado", "quartus", "radiant", "diamond"):
        hit = next((t for t in rtl.vendor_fpga_tools()
                    if t["id"] == tool_id and t["installed"]), None)
        return (hit is not None), (hit["path"] if hit else None)
    return False, None


def catalog() -> list[dict]:
    out = []
    for entry in _catalog():
        e = {k: v for k, v in entry.items() if k != "recipe"}
        try:
            e["installed"], e["path"] = _installed(entry["id"])
        except Exception:  # noqa: BLE001 - detection must never break the catalog
            e["installed"], e["path"] = False, None
        e["one_click"] = entry["kind"] == "auto"
        if entry["kind"] == "auto" and entry["recipe"]["type"] == "winget":
            e["needs_winget"] = shutil.which("winget") is None
        out.append(e)
    return out


# --- status registry ------------------------------------------------------
def _set(tool_id: str, **kw) -> None:
    with _LOCK:
        st = _STATUS.setdefault(tool_id, {"state": "idle", "progress": 0, "detail": "", "error": None})
        st.update(kw)


def status() -> dict:
    with _LOCK:
        return {k: dict(v) for k, v in _STATUS.items()}


# --- download / extract helpers -------------------------------------------
def _check_host(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        raise RuntimeError(f"refusing download from non-official host: {host!r}")


def _github_asset(repo: str, pattern: str) -> tuple[str, int]:
    import httpx

    api = f"https://api.github.com/repos/{repo}/releases/latest"
    _check_host(api)
    r = httpx.get(api, headers={"User-Agent": "ece-tool-suite"}, timeout=30, follow_redirects=True)
    r.raise_for_status()
    for a in r.json().get("assets", []):
        if re.search(pattern, a["name"]):
            return a["browser_download_url"], int(a.get("size", 0))
    raise RuntimeError(f"no asset matching {pattern!r} in the latest {repo} release")


def _download(tool_id: str, url: str, dest: Path, total_hint: int = 0) -> None:
    import httpx

    _check_host(url)
    with httpx.stream("GET", url, headers={"User-Agent": "ece-tool-suite"},
                      timeout=60, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", total_hint) or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=1 << 18):
                f.write(chunk)
                done += len(chunk)
                if total:
                    _set(tool_id, progress=min(99, int(100 * done / total)),
                         detail=f"downloading {done // (1 << 20)} / {total // (1 << 20)} MB")
    _set(tool_id, progress=100, detail="download complete")


def _safe_extract(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        for m in z.namelist():           # defense-in-depth vs zip-slip
            p = Path(m)
            if p.is_absolute() or ".." in p.parts:
                raise RuntimeError(f"archive member escapes target dir: {m!r}")
        z.extractall(target)


# --- recipes --------------------------------------------------------------
def _install_github_zip(tool_id: str, recipe: dict) -> str:
    url, size = _github_asset(recipe["repo"], recipe["asset"])
    _set(tool_id, state="downloading", progress=0, detail=url.rsplit("/", 1)[-1])
    with tempfile.TemporaryDirectory() as td:
        zp = Path(td) / "pkg.zip"
        _download(tool_id, url, zp, size)
        _set(tool_id, state="extracting", detail="unpacking archive")
        root = suite_root()
        if recipe["target"] == "ghdl-subdir":
            # isolated subdir: GHDL ships its own mingw DLLs that must not collide with the
            # suite's (DLLs resolve from the exe's own dir)
            dest = root / "ghdl"
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            _safe_extract(zp, dest)
            return str(dest / "bin" / "ghdl.exe")
        if recipe["target"] == "bin-exes":
            xd = Path(td) / "x"
            _safe_extract(zp, xd)
            bin_dir = root / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            exes = list(xd.rglob("verible-*.exe"))
            if not exes:
                raise RuntimeError("archive contained no verible-*.exe")
            for e in exes:
                shutil.copy2(e, bin_dir / e.name)
            return str(bin_dir)
        raise RuntimeError(f"unknown zip target {recipe['target']!r}")


def _install_github_sfx(tool_id: str, recipe: dict) -> str:
    url, size = _github_asset(recipe["repo"], recipe["asset"])
    _set(tool_id, state="downloading", progress=0, detail=url.rsplit("/", 1)[-1])
    with tempfile.TemporaryDirectory() as td:
        exe = Path(td) / "setup.exe"
        _download(tool_id, url, exe, size)
        _set(tool_id, state="extracting", detail="self-extracting archive (about a minute)…")
        # the YosysHQ sfx extracts ./oss-cad-suite into its working directory
        parent = suite_root().parent
        parent.mkdir(parents=True, exist_ok=True)
        cp = subprocess.run([str(exe)], cwd=str(parent), capture_output=True, timeout=900)
        if cp.returncode != 0:
            raise RuntimeError(f"extractor exited {cp.returncode}")
    return str(suite_root())


def _install_winget(tool_id: str, recipe: dict) -> str:
    winget = shutil.which("winget")
    if not winget:
        raise RuntimeError("winget (App Installer) is not available — use the official page button")
    _set(tool_id, state="downloading", progress=0,
         detail=f"winget install {recipe['package']} (vendor's official package; a UAC prompt may appear)")
    cp = subprocess.run(
        [winget, "install", "--id", recipe["package"], "-e", "--silent",
         "--accept-package-agreements", "--accept-source-agreements",
         "--disable-interactivity"],
        capture_output=True, text=True, timeout=1800, encoding="utf-8", errors="replace")
    if cp.returncode != 0:
        tail = (cp.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError(f"winget exited {cp.returncode}: {' | '.join(tail) or cp.stderr[:200]}")
    return recipe["package"]


def _run_install(tool_id: str, entry: dict) -> None:
    from . import rtl

    t0 = time.monotonic()
    try:
        recipe = entry["recipe"]
        fn = {"github-zip": _install_github_zip, "github-sfx": _install_github_sfx,
              "winget": _install_winget}[recipe["type"]]
        where = fn(tool_id, recipe)
        # verification: the same detection the app trusts, never an assumption
        _set(tool_id, state="verifying", detail="re-running tool detection")
        rtl._ENV_CACHE = None            # env cache may predate the new install locations
        ok, path = _installed(tool_id)
        if not ok:
            raise RuntimeError("installed files present but detection still reports missing "
                               f"(looked at {where})")
        _set(tool_id, state="done", progress=100, finished=True,
             detail=f"installed + verified in {time.monotonic() - t0:.0f}s → {path or where}")
    except Exception as e:  # noqa: BLE001 - report honestly, never crash the server
        _set(tool_id, state="error", finished=True, error=str(e)[:500])


def start_install(tool_id: str) -> dict:
    entry = next((e for e in _catalog() if e["id"] == tool_id), None)
    if entry is None:
        return {"ok": False, "error": f"unknown tool {tool_id!r}"}
    if entry["kind"] != "auto":
        return {"ok": False, "error": "this tool is login/EULA-gated — use its official page",
                "url": entry["url"]}
    with _LOCK:
        th = _THREADS.get(tool_id)
        if th and th.is_alive():
            return {"ok": True, "already_running": True}
    _set(tool_id, state="starting", progress=0, detail="", error=None, finished=False)
    t = threading.Thread(target=_run_install, args=(tool_id, entry), daemon=True)
    _THREADS[tool_id] = t
    t.start()
    return {"ok": True, "started": True}
