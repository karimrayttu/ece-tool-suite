"""LabVIEW integration — detect installs and drive them through NI's official LabVIEWCLI.

Everything here is grounded in what is actually on disk: detection globs the National
Instruments install tree, project listing scans the user's real folders for ``.lvproj``,
and operations shell out to ``LabVIEWCLI.exe`` (NI's supported automation channel:
RunVI / MassCompile / ExecuteBuildSpec / CloseLabVIEW). No install → honest not-installed
status with the official download page; nothing is simulated.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
from pathlib import Path

from . import shell_open

_CLI_CANDIDATES = [
    r"C:\Program Files (x86)\National Instruments\Shared\LabVIEW CLI\LabVIEWCLI.exe",
    r"C:\Program Files\National Instruments\Shared\LabVIEW CLI\LabVIEWCLI.exe",
]

DOWNLOAD_URL = "https://www.ni.com/en/support/downloads/software-products/download.labview.html"


def _installs() -> list[dict]:
    out = []
    for base in (r"C:\Program Files\National Instruments", r"C:\Program Files (x86)\National Instruments"):
        for d in sorted(glob.glob(os.path.join(base, "LabVIEW *"))):
            exe = os.path.join(d, "LabVIEW.exe")
            if os.path.exists(exe):
                m = re.search(r"LabVIEW (\S+)$", d)
                out.append({"version": m.group(1) if m else os.path.basename(d),
                            "path": exe, "bitness": "32-bit" if "(x86)" in base else "64-bit"})
    return out


def _cli() -> str | None:
    return next((c for c in _CLI_CANDIDATES if os.path.exists(c)), None)


def status() -> dict:
    installs = _installs()
    return {
        "installed": bool(installs),
        "installs": installs,
        "default": installs[-1]["path"] if installs else None,   # newest version
        "cli": _cli(),
        "cli_available": _cli() is not None,
        "download": DOWNLOAD_URL,
    }


def list_projects(extra_roots: list[str] | None = None) -> list[dict]:
    """Real .lvproj files under the user's Documents / Desktop (bounded depth)."""
    roots = [Path.home() / "Documents", Path.home() / "Desktop"]
    roots += [Path(r) for r in (extra_roots or [])]
    seen: set[str] = set()
    out: list[dict] = []
    for root in roots:
        if not root.is_dir():
            continue
        for depth_pat in ("*.lvproj", "*/*.lvproj", "*/*/*.lvproj"):
            for hit in root.glob(depth_pat):
                key = str(hit.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append({"name": hit.stem, "path": str(hit),
                            "modified": hit.stat().st_mtime})
    out.sort(key=lambda p: -p["modified"])
    return out


def _run_cli(args: list[str], timeout: float) -> dict:
    cli = _cli()
    if not cli:
        return {"ok": False, "error": "LabVIEWCLI not installed", "install": DOWNLOAD_URL}
    st = status()
    cmd = [cli, *args, "-LogToConsole", "true"]
    if st["default"]:
        cmd += ["-LabVIEWPath", st["default"]]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"LabVIEWCLI timed out after {timeout:.0f}s"}
    log = (cp.stdout or "") + ("\n" + cp.stderr if (cp.stderr or "").strip() else "")
    return {"ok": cp.returncode == 0, "returncode": cp.returncode,
            "log": log.strip()[-4000:]}


def run_vi(vi_path: str, timeout: float = 300.0) -> dict:
    """Run a VI headless via the official CLI (LabVIEW opens, runs it, reports)."""
    p = Path(vi_path)
    if p.suffix.lower() != ".vi" or not p.exists():
        return {"ok": False, "error": f"not an existing .vi file: {vi_path}"}
    return _run_cli(["-OperationName", "RunVI", "-VIPath", str(p)], timeout)


def mass_compile(directory: str, timeout: float = 900.0) -> dict:
    d = Path(directory)
    if not d.is_dir():
        return {"ok": False, "error": f"not a directory: {directory}"}
    return _run_cli(["-OperationName", "MassCompile", "-DirectoryToCompile", str(d)], timeout)


def execute_build_spec(project: str, build_spec: str | None = None,
                       target: str = "My Computer", timeout: float = 1800.0) -> dict:
    p = Path(project)
    if p.suffix.lower() != ".lvproj" or not p.exists():
        return {"ok": False, "error": f"not an existing .lvproj: {project}"}
    args = ["-OperationName", "ExecuteBuildSpec", "-ProjectPath", str(p), "-TargetName", target]
    if build_spec:
        args += ["-BuildSpecName", build_spec]
    return _run_cli(args, timeout)


def close_labview(timeout: float = 60.0) -> dict:
    return _run_cli(["-OperationName", "CloseLabVIEW"], timeout)


# --- VI Server (ActiveX COM): run/set/get any VI + template scaffolding ----
# This is what makes LabVIEW usable FROM the app: pick a VI, set its front-panel
# controls, run it, read its indicators — and scaffold new dashboard VIs from
# LabVIEW's own templates. Uses the official LabVIEW.Application COM automation
# interface (VI Server); LabVIEW is launched on demand.
def _com_app():
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    return win32com.client.Dispatch("LabVIEW.Application")


def _com_done() -> None:
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:  # noqa: BLE001
        pass


def _py_val(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    try:
        return list(v)
    except Exception:  # noqa: BLE001
        return str(v)


def com_status() -> dict:
    """Is the ActiveX VI Server reachable (launches LabVIEW if needed)?"""
    try:
        app = _com_app()
        return {"ok": True, "connected": True, "version": str(app.Version)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "connected": False, "error": str(e)[:300],
                "hint": "LabVIEW Tools > Options > VI Server: enable ActiveX"}
    finally:
        _com_done()


def vi_run_com(vi_path: str, inputs: dict | None = None,
               outputs: list[str] | None = None) -> dict:
    """Set controls → run the VI (wait) → read indicators. The core automation primitive."""
    p = Path(vi_path)
    if p.suffix.lower() != ".vi" or not p.exists():
        return {"ok": False, "error": f"not an existing .vi: {vi_path}"}
    try:
        app = _com_app()
        vi = app.GetVIReference(str(p))
        for name, val in (inputs or {}).items():
            vi.SetControlValue(name, val)
        try:
            vi.Run(True)
        except Exception:  # noqa: BLE001 - some VIs need the no-arg form
            vi.Run()
        res = {name: _py_val(vi.GetControlValue(name)) for name in (outputs or [])}
        return {"ok": True, "vi": str(p.name), "inputs_set": list((inputs or {}).keys()),
                "outputs": res}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:400]}
    finally:
        _com_done()


def vi_value(vi_path: str, control: str, value=None, set_it: bool = False) -> dict:
    p = Path(vi_path)
    if not p.exists():
        return {"ok": False, "error": f"not found: {vi_path}"}
    try:
        app = _com_app()
        vi = app.GetVIReference(str(p))
        if set_it:
            vi.SetControlValue(control, value)
            return {"ok": True, "set": {control: value}}
        return {"ok": True, "control": control, "value": _py_val(vi.GetControlValue(control))}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:400]}
    finally:
        _com_done()


def list_templates() -> dict:
    """LabVIEW's own .vit templates (state machine, producer/consumer, blank VI, …)."""
    out: dict[str, str] = {}
    for inst in _installs():
        tdir = Path(inst["path"]).parent / "templates"
        if tdir.is_dir():
            for vit in tdir.rglob("*.vit"):
                out.setdefault(vit.stem, str(vit))
    return {"ok": True, "templates": [{"name": k, "path": v} for k, v in sorted(out.items())],
            "count": len(out)}


def create_from_template(save_path: str, template: str, open_in_labview: bool = True) -> dict:
    """Scaffold a new VI (dashboard starting point) by copying a LabVIEW template."""
    import shutil as _sh

    t = {x["name"]: x["path"] for x in list_templates()["templates"]}
    if template not in t:
        return {"ok": False, "error": f"unknown template {template!r}",
                "available": sorted(t)[:40]}
    dest = Path(save_path)
    if dest.suffix.lower() != ".vi":
        dest = dest.with_suffix(".vi")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _sh.copyfile(t[template], dest)
    opened = False
    open_error: str | None = None
    if open_in_labview:
        try:
            app = _com_app()
            vi = app.GetVIReference(str(dest))
            try:
                vi.FPWinOpen = True
            except Exception:  # noqa: BLE001
                pass
            app.BringToFront()
            opened = True
        except Exception as e:  # noqa: BLE001
            open_error = str(e)[:300]
        finally:
            _com_done()
    out = {"ok": True, "created": str(dest), "template": template, "opened": opened,
           "note": "File > Save once in LabVIEW to finalize it as a normal VI"}
    if open_error is not None:
        out["open_error"] = open_error
        out["hint"] = "LabVIEW Tools > Options > VI Server: enable ActiveX"
    return out


# --- dashboard codegen (G scripting), gated on the one-time VIBuilder build --
# VIBuilder.vi is a helper VI you build once inside LabVIEW; it is not shipped here because
# a .vi is a binary tied to a LabVIEW version. Drop it (and its guide) in the directory below,
# or point ECE_SUITE_LABVIEW_DIR somewhere else.
BUILDER_DIR = Path(
    os.environ.get("ECE_SUITE_LABVIEW_DIR", Path.home() / ".ece-suite" / "labview")
)
BUILDER_VI = BUILDER_DIR / "VIBuilder.vi"
BUILDER_GUIDE = BUILDER_DIR / "BUILDER_GUIDE.md"


def builder_status() -> dict:
    """Spec-driven VI generation needs VIBuilder.vi (a one-time build in LabVIEW).

    Honest status: present → generate_dashboard works; absent → here's the guide.
    """
    return {"available": BUILDER_VI.exists(), "builder_vi": str(BUILDER_VI),
            "guide": str(BUILDER_GUIDE) if BUILDER_GUIDE.exists() else None}


def generate_dashboard(spec: dict, output_path: str) -> dict:
    """Build a new VI from a JSON spec via VIBuilder.vi (LabVIEW G scripting)."""
    import json as _json

    if not BUILDER_VI.exists():
        return {"ok": False, "error": "VIBuilder.vi not built yet (one-time step in LabVIEW)",
                "guide": str(BUILDER_GUIDE)}
    out = Path(output_path)
    if out.suffix.lower() != ".vi":
        out = out.with_suffix(".vi")
    out.parent.mkdir(parents=True, exist_ok=True)
    r = vi_run_com(str(BUILDER_VI),
                   inputs={"Spec JSON": _json.dumps(spec), "Output Path": str(out)},
                   outputs=["Result", "Error Out"])
    if not r.get("ok"):
        return r
    err = (r["outputs"].get("Error Out") or "").strip()
    return {"ok": not err, "created": str(out) if not err else None,
            "result": r["outputs"].get("Result"), "error": err or None}


def launch(project: str | None = None) -> dict:
    """Open LabVIEW (optionally with a project) — a real GUI launch, user-facing."""
    st = status()
    if not st["installed"]:
        return {"ok": False, "error": "LabVIEW not installed", "install": DOWNLOAD_URL}
    try:
        if project and Path(project).exists():
            shell_open.open_path(project)   # the .lvproj association opens LabVIEW
            return {"ok": True, "launched": project}
        shell_open.open_path(st["default"])
        return {"ok": True, "launched": st["default"]}
    except OSError as e:
        return {"ok": False, "error": str(e)}
