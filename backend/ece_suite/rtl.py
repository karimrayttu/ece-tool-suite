"""HDL / RTL design + verification engine (Verilog / SystemVerilog / VHDL).

Same lab-truth spirit as :mod:`spice_verify`: a human — or a GenAI model — can *write*
RTL, but it is not "good" until the real toolchain confirms it. This module shells out to
the open-source EDA toolchain to give honest, tool-grounded feedback:

* **lint**      — Verilator ``--lint-only`` (Verilog/SystemVerilog) or GHDL analyze (VHDL);
                  Icarus Verilog is the fallback linter when Verilator isn't present.
* **simulate**  — Icarus Verilog (``iverilog`` + ``vvp``) for Verilog/SV, GHDL for VHDL,
                  running a user testbench, capturing ``$display``/assertions and a VCD.
* **synthesize**— Yosys ``synth`` + ``stat`` for a real cell/area report.
* **format**    — Verible ``verible-verilog-format`` (Verilog/SystemVerilog).

Nothing here trusts the source blindly — the toolchain's own diagnostics are the verdict,
which is exactly what lets a GenAI generate/optimize RTL and then be held to ground truth
(see :mod:`rtl_ai`). When no toolchain is installed every entry point degrades gracefully
with an install pointer (OSS CAD Suite bundles all of these in one download).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import shell_open

# OSS CAD Suite (YosysHQ) ships iverilog, verilator, ghdl, yosys, verible + gtkwave in one
# bundle; look in the usual unpack locations in addition to PATH and an explicit override.
_OSS_HINT = "https://github.com/YosysHQ/oss-cad-suite-build/releases (one bundle: iverilog + verilator + ghdl + yosys + verible)"


def _search_dirs() -> list[str]:
    dirs: list[str] = []
    env = os.environ.get("ECE_SUITE_HDL_BIN")
    if env:
        dirs.append(env)
    home = Path.home()
    for base in (
        Path(r"C:\oss-cad-suite"), Path(r"C:\tools\oss-cad-suite"),
        home / "oss-cad-suite", Path(r"C:\ProgramData\oss-cad-suite"),
        Path("/opt/oss-cad-suite"), home / "oss-cad-suite",
    ):
        dirs.append(str(base / "bin"))
        # GHDL's Windows build ships its own mingw DLLs that could collide with the suite's,
        # so it lives in an isolated ghdl/ subdir (DLLs resolve from the exe's own dir).
        dirs.append(str(base / "ghdl" / "bin"))
        dirs.append(str(base))
    return dirs


def _which(name: str) -> str | None:
    """``shutil.which`` plus the OSS CAD Suite unpack locations."""
    hit = shutil.which(name)
    if hit:
        return hit
    exe = name + (".exe" if os.name == "nt" else "")
    for d in _search_dirs():
        cand = Path(d) / exe
        if cand.exists():
            return str(cand)
    return None


def _verilator() -> str | None:
    """The runnable Verilator binary. On Windows the plain ``verilator`` in OSS CAD Suite is a
    POSIX shell-script launcher that won't run natively — ``verilator_bin.exe`` is the real
    executable; on POSIX the ``verilator`` wrapper is correct."""
    if os.name == "nt":
        return _which("verilator_bin") or _which("verilator")
    return shutil.which("verilator") or _which("verilator") or _which("verilator_bin")


_ENV_CACHE: dict | None = None


def _suite_root() -> Path | None:
    """If our tools live inside an OSS CAD Suite tree, return its root (the dir holding ``bin``)."""
    for tool in ("iverilog", "yosys", "vvp"):
        p = _which(tool)
        if p:
            root = Path(p).parent.parent  # <root>/bin/<tool> -> <root>
            if (root / "bin").is_dir():
                return root
    return None


def _tool_env() -> dict:
    """Environment for running the toolchain. OSS CAD Suite tools spawn helper exes from
    ``bin``/``lib`` (iverilog -> ivl/ivlpp, yosys -> yosys-abc) and Verilator reads its data
    via ``VERILATOR_ROOT`` — without these the tools crash or can't find their built-ins."""
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE
    env = os.environ.copy()
    # nextpnr (and other tools) embed a Python interpreter; if it inherits the host venv's
    # PYTHONHOME/PYTHONPATH it loads the wrong stdlib and crashes ("failed to get the Python
    # codec of the filesystem encoding"). Drop them so the bundled interpreter is used.
    for var in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        env.pop(var, None)
    root = _suite_root()
    if root:
        extra = os.pathsep.join(str(root / d) for d in ("bin", "lib", "py3bin") if (root / d).is_dir())
        if extra:
            env["PATH"] = extra + os.pathsep + env.get("PATH", "")
        vroot = root / "share" / "verilator"
        if vroot.is_dir():
            env.setdefault("VERILATOR_ROOT", str(vroot))
    _ENV_CACHE = env
    return env


# --- toolchain discovery --------------------------------------------------
_TOOLS = {
    "iverilog": ("Icarus Verilog", "Verilog/SystemVerilog compile"),
    "vvp": ("Icarus vvp", "Verilog/SystemVerilog simulate"),
    "verilator": ("Verilator", "Verilog/SystemVerilog lint"),
    "ghdl": ("GHDL", "VHDL analyze/simulate"),
    "yosys": ("Yosys", "synthesis / cell stats"),
    "verible-verilog-lint": ("Verible lint", "SystemVerilog style lint"),
    "verible-verilog-format": ("Verible format", "SystemVerilog formatter"),
}


def toolchain() -> dict:
    """Detect every HDL tool we can drive, with paths and a per-language capability summary."""
    tools: list[dict] = []
    found: dict[str, str] = {}
    for tool_id, (name, purpose) in _TOOLS.items():
        path = _verilator() if tool_id == "verilator" else _which(tool_id)
        tools.append({"id": tool_id, "name": name, "purpose": purpose,
                      "installed": path is not None, "path": path})
        if path:
            found[tool_id] = path

    verilog = "iverilog" in found and "vvp" in found          # can simulate Verilog/SV
    vhdl = "ghdl" in found                                     # can simulate VHDL
    caps = {
        "lint_verilog": ("verilator" in found) or ("iverilog" in found),
        "lint_vhdl": vhdl,
        "simulate_verilog": verilog,
        "simulate_vhdl": vhdl,
        "synthesize": "yosys" in found,
        "format": "verible-verilog-format" in found,
    }
    languages = []
    if verilog or "verilator" in found or "iverilog" in found:
        languages += ["verilog", "systemverilog"]
    if vhdl:
        languages += ["vhdl"]
    fams = fpga_families()
    return {
        "tools": tools,
        "capabilities": caps,
        "languages": languages,
        "fpga": {"available": any(f["available"] for f in fams), "families": fams},
        "vendors": vendor_fpga_tools(),
        "any": bool(found),
        "install": _OSS_HINT,
    }


# --- language / source helpers -------------------------------------------
def _norm_lang(language: str | None, source: str = "") -> str:
    lang = (language or "").strip().lower()
    if lang in ("sv", "systemverilog", "system-verilog"):
        return "systemverilog"
    if lang in ("v", "verilog"):
        return "verilog"
    if lang in ("vhd", "vhdl"):
        return "vhdl"
    # sniff: VHDL has 'entity'/'architecture'; SV has 'logic'/'always_ff'/'module' + ';'
    if re.search(r"\bentity\b|\barchitecture\b", source, re.I):
        return "vhdl"
    if re.search(r"\balways_ff\b|\balways_comb\b|\blogic\b|\btypedef\b", source):
        return "systemverilog"
    return "verilog"


def _ext(lang: str) -> str:
    return {"verilog": ".v", "systemverilog": ".sv", "vhdl": ".vhd"}[lang]


def module_names(source: str) -> list[str]:
    """Verilog/SV module names, in source order."""
    return re.findall(r"^\s*module\s+([A-Za-z_]\w*)", source, re.M)


def entity_names(source: str) -> list[str]:
    """VHDL entity names, in source order."""
    return re.findall(r"^\s*entity\s+([A-Za-z_]\w*)", source, re.I | re.M)


# --- diagnostic parsing (pure — unit-testable without any toolchain) -------
# Matches "path:line:col: severity: message", "path:line: message", verilator's
# "%Error: path:line:col: message" / "%Warning-NAME: ...", and verible "path:line:col: msg [rule]".
_VERILATOR_RE = re.compile(
    r"^%(?P<sev>Error|Warning)(?:-(?P<code>[A-Z0-9_]+))?:\s*"
    r"(?:(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*)?(?P<msg>.*)$")
_GENERIC_RE = re.compile(
    r"^(?P<file>[^:\s][^:]*):(?P<line>\d+)(?::(?P<col>\d+))?:\s*"
    r"(?:(?P<sev>error|warning|note):\s*)?(?P<msg>.*)$", re.I)


def _sev_norm(s: str | None) -> str:
    s = (s or "").lower()
    if s.startswith("err"):
        return "error"
    if s.startswith("warn"):
        return "warning"
    return "note" if s == "note" else "info"


def parse_diagnostics(text: str, kind: str = "generic") -> list[dict]:
    """Parse a compiler/linter stderr blob into structured diagnostics.

    ``kind`` selects the primary matcher ("verilator" | "iverilog" | "ghdl" | "verible" |
    "generic"); the generic ``path:line[:col]: msg`` matcher is always tried as a fallback so
    one function covers every tool we shell out to.
    """
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = _VERILATOR_RE.match(line) if kind == "verilator" else None
        if m:
            out.append({
                "severity": _sev_norm(m.group("sev")),
                "code": m.group("code"),
                "file": m.group("file"), "line": int(m.group("line")) if m.group("line") else None,
                "col": int(m.group("col")) if m.group("col") else None,
                "message": m.group("msg").strip(),
            })
            continue
        m = _GENERIC_RE.match(line)
        if m and m.group("line"):
            msg = m.group("msg").strip()
            sev = m.group("sev")
            # verible/verilator sometimes carry a trailing "[rule]" code
            code = None
            cm = re.search(r"\[([A-Za-z0-9_-]+)\]\s*$", msg)
            if cm:
                code = cm.group(1)
            # heuristic severity when the tool didn't label it
            if not sev:
                low = msg.lower()
                sev = "error" if ("error" in low or "syntax" in low) else "warning"
            out.append({
                "severity": _sev_norm(sev), "code": code,
                "file": os.path.basename(m.group("file")),
                "line": int(m.group("line")),
                "col": int(m.group("col")) if m.group("col") else None,
                "message": msg,
            })
    return out


def _counts(diags: list[dict]) -> dict:
    return {
        "errors": sum(1 for d in diags if d["severity"] == "error"),
        "warnings": sum(1 for d in diags if d["severity"] == "warning"),
    }


def _run(cmd: list[str], cwd: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="replace", env=_tool_env())


# --- lint -----------------------------------------------------------------
def lint(source: str, language: str | None = None, top: str | None = None,
         timeout: float = 60.0) -> dict:
    lang = _norm_lang(language, source)
    tc = toolchain()
    with tempfile.TemporaryDirectory() as wd:
        if lang == "vhdl":
            if not tc["capabilities"]["lint_vhdl"]:
                return {"ok": False, "language": lang, "error": "GHDL not installed", "install": _OSS_HINT}
            src = Path(wd) / ("dut" + _ext(lang))
            src.write_text(source, encoding="utf-8")
            cp = _run([_which("ghdl"), "-s", "--std=08", str(src)], wd, timeout)
            diags = parse_diagnostics(cp.stderr + "\n" + cp.stdout, "ghdl")
            tool = "ghdl"
        else:
            src = Path(wd) / ("dut" + _ext(lang))
            src.write_text(source, encoding="utf-8")
            if not source.endswith("\n"):
                src.write_text(source + "\n", encoding="utf-8")  # avoid a spurious EOF-newline lint
            vl = _verilator()
            if vl:
                # -Wall for real lints, but suppress artifacts of our temp-file harness (the
                # module name won't match the temp filename).
                args = [vl, "--lint-only", "-Wall", "-Wno-DECLFILENAME"]
                if lang == "systemverilog":
                    args.append("-sv")
                if top:
                    args += ["--top-module", top]
                args.append(str(src))
                cp = _run(args, wd, timeout)
                diags = parse_diagnostics(cp.stderr, "verilator")
                tool = "verilator"
            elif _which("iverilog"):
                gen = "-g2012" if lang == "systemverilog" else "-g2005"
                cp = _run([_which("iverilog"), gen, "-t", "null", "-Wall", str(src)], wd, timeout)
                diags = parse_diagnostics(cp.stderr, "iverilog")
                tool = "iverilog"
            else:
                return {"ok": False, "language": lang,
                        "error": "no Verilog linter (install Verilator or Icarus Verilog)",
                        "install": _OSS_HINT}
            # defensive: a non-zero exit that produced no parseable error still means "not clean"
            if cp.returncode != 0 and not any(d["severity"] == "error" for d in diags):
                tail = " ".join((cp.stderr or cp.stdout or "").strip().splitlines()[-3:])
                diags.append({"severity": "error", "code": None, "file": None, "line": None,
                              "col": None, "message": tail or f"{tool} exited with code {cp.returncode}"})
    c = _counts(diags)
    return {"ok": True, "language": lang, "tool": tool, "diagnostics": diags,
            "clean": c["errors"] == 0, **c}


# --- simulate -------------------------------------------------------------
_PASS_RE = re.compile(r"\b(pass|passed|all tests? passed|ok|success)\b", re.I)
_FAIL_RE = re.compile(r"\b(fail|failed|error|mismatch|assertion|fatal)\b", re.I)


def _summarize_vcd(vcd_path: Path) -> dict | None:
    if not vcd_path.exists():
        return None
    signals: list[str] = []
    t_end = 0
    try:
        with vcd_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("$var"):
                    parts = line.split()
                    if len(parts) >= 5 and parts[4] not in signals:
                        signals.append(parts[4])   # dedupe: same net appears per scope
                elif line.startswith("#"):
                    try:
                        t_end = max(t_end, int(line[1:]))
                    except ValueError:
                        pass
    except OSError:
        return None
    text = ""
    try:
        if vcd_path.stat().st_size <= 256 * 1024:
            text = vcd_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return {"signals": signals, "time_end": t_end, "text": text}


def simulate(source: str, testbench: str, language: str | None = None,
             top: str | None = None, timeout: float = 60.0) -> dict:
    """Compile DUT+testbench and run it; capture stdout, a PASS/FAIL verdict, and any VCD.

    The testbench drives the verdict: if it prints pass/fail (or uses ``$fatal``/assertions),
    that text is what we report — the model never gets to *claim* a pass the simulator didn't
    produce. Have the testbench ``$dumpfile("dump.vcd"); $dumpvars;`` to get a waveform back.
    """
    lang = _norm_lang(language, source)
    tc = toolchain()
    with tempfile.TemporaryDirectory() as wd:
        wdp = Path(wd)
        if lang == "vhdl":
            if not tc["capabilities"]["simulate_vhdl"]:
                return {"ok": False, "language": lang, "error": "GHDL not installed", "install": _OSS_HINT}
            ghdl = _which("ghdl")
            (wdp / "dut.vhd").write_text(source, encoding="utf-8")
            (wdp / "tb.vhd").write_text(testbench, encoding="utf-8")
            tb_top = top or (entity_names(testbench)[0] if entity_names(testbench) else "tb")
            an = _run([ghdl, "-a", "--std=08", "dut.vhd", "tb.vhd"], wd, timeout)
            if an.returncode != 0:
                return {"ok": True, "language": lang, "compiled": False,
                        "diagnostics": parse_diagnostics(an.stderr, "ghdl"),
                        "stdout": "", "verdict": "compile_error"}
            _run([ghdl, "-e", "--std=08", tb_top], wd, timeout)
            run = _run([ghdl, "-r", "--std=08", tb_top, "--vcd=dump.vcd", "--stop-time=" + "10ms"],
                       wd, timeout)
            log = run.stdout + run.stderr
            tool = "ghdl"
        else:
            if not tc["capabilities"]["simulate_verilog"]:
                return {"ok": False, "language": lang,
                        "error": "Icarus Verilog (iverilog + vvp) not installed", "install": _OSS_HINT}
            iverilog, vvp = _which("iverilog"), _which("vvp")
            (wdp / "dut" ).with_suffix(_ext(lang)).write_text(source, encoding="utf-8")
            (wdp / "tb").with_suffix(_ext(lang)).write_text(testbench, encoding="utf-8")
            gen = "-g2012" if lang == "systemverilog" else "-g2005"
            args = [iverilog, gen, "-o", "sim.vvp"]
            if top:
                args += ["-s", top]
            args += ["dut" + _ext(lang), "tb" + _ext(lang)]
            comp = _run(args, wd, timeout)
            diags = parse_diagnostics(comp.stderr, "iverilog")
            if comp.returncode != 0 or not (wdp / "sim.vvp").exists():
                return {"ok": True, "language": lang, "compiled": False, "diagnostics": diags,
                        "stdout": "", "verdict": "compile_error"}
            run = _run([vvp, "sim.vvp"], wd, timeout)
            log = run.stdout + ("\n" + run.stderr if run.stderr.strip() else "")
            tool = "iverilog"

        vcd = _summarize_vcd(wdp / "dump.vcd")

    # verdict from the testbench's own output (fail wins over pass; assertion => fail)
    fail = bool(_FAIL_RE.search(log))
    passed = bool(_PASS_RE.search(log))
    verdict = "fail" if fail else ("pass" if passed else "ran")
    return {"ok": True, "language": lang, "tool": tool, "compiled": True,
            "verdict": verdict, "stdout": log.strip(), "vcd": vcd,
            "diagnostics": parse_diagnostics(log, "generic") if fail else []}


# --- synthesize (Yosys cell/area stats) -----------------------------------
# Yosys >=0.40 prints "<N> wires / <N> cells / <N> $_AND_"; older prints "Number of cells: N".
_STAT_SUMMARY = {"wires", "wire bits", "public wires", "public wire bits", "ports",
                 "port bits", "cells", "memories", "memory bits", "processes"}


def _parse_yosys_stat(out: str) -> tuple[dict, dict]:
    """Parse the final ``stat`` table into {summary_key: n} and {cell_type: n}."""
    idx = out.rfind("\n=== ")            # isolate the last module's stat block
    block = out[idx:] if idx != -1 else out
    stats: dict[str, int] = {}
    cells: dict[str, int] = {}
    for m in re.finditer(r"^\s+(\d+)\s+(\S[^\n]*?)\s*$", block, re.M):
        n, label = int(m.group(1)), m.group(2).strip()
        if label.lower() in _STAT_SUMMARY:
            stats[label.lower().replace(" ", "_")] = n
        elif re.match(r"^\$?[\\A-Za-z_][\w:.$\\]*$", label):
            cells[label] = n
    for k, v in re.findall(r"Number of (\w[\w ]*?):\s+(\d+)", out):  # old-format fallback
        stats[k.strip().replace(" ", "_")] = int(v)
    return stats, cells


def synthesize(source: str, language: str | None = None, top: str | None = None,
               timeout: float = 120.0) -> dict:
    lang = _norm_lang(language, source)
    if lang == "vhdl":
        # Yosys VHDL needs the GHDL plugin; keep the first cut Verilog/SV-only and say so.
        return {"ok": False, "language": lang,
                "error": "VHDL synthesis needs the yosys-ghdl plugin; use Verilog/SystemVerilog for stats"}
    yosys = _which("yosys")
    if not yosys:
        return {"ok": False, "language": lang, "error": "Yosys not installed", "install": _OSS_HINT}
    with tempfile.TemporaryDirectory() as wd:
        src = Path(wd) / ("dut" + _ext(lang))
        src.write_text(source, encoding="utf-8")
        read = "read_verilog -sv" if lang == "systemverilog" else "read_verilog"
        tops = module_names(source)
        top = top or (tops[-1] if tops else None)
        synth = f"synth -top {top}" if top else "synth -auto-top"
        script = f"{read} dut{_ext(lang)}; {synth}; stat"
        cp = _run([yosys, "-p", script], wd, timeout)
    if cp.returncode != 0:
        return {"ok": True, "language": lang, "synthesized": False,
                "diagnostics": parse_diagnostics(cp.stderr, "generic"),
                "log": (cp.stderr or cp.stdout).strip()}
    stats, cells = _parse_yosys_stat(cp.stdout)
    return {"ok": True, "language": lang, "synthesized": True, "top": top,
            "stats": stats, "cells": cells, "log": cp.stdout.strip()}


# --- FPGA synthesis (real device mapping via Yosys synth_<family>) --------
# These are the real Lattice/Gowin flows shipped in OSS CAD Suite; nextpnr (also bundled) can
# take it the rest of the way to place-and-route + bitstream.
_FPGA_FAMILIES = {
    "ice40": {"flow": "synth_ice40", "name": "Lattice iCE40", "pnr": "nextpnr-ice40",
              "pack": "icepack", "boards": "iCEstick / iCE40-HX8K / TinyFPGA / Icebreaker"},
    "ecp5": {"flow": "synth_ecp5", "name": "Lattice ECP5", "pnr": "nextpnr-ecp5",
             "pack": "ecppack", "boards": "ULX3S / ECP5 Evn / OrangeCrab / Colorlight"},
    "machxo2": {"flow": "synth_machxo2", "name": "Lattice MachXO2", "pnr": "nextpnr-machxo2",
                "pack": "ecppack", "boards": "MachXO2 breakout / TinyFPGA A"},
    "gowin": {"flow": "synth_gowin", "name": "Gowin LittleBee", "pnr": "nextpnr-himbaechel",
              "pack": "gowin_pack", "boards": "Tang Nano 9K/20K / Tang Primer"},
}

# regex → utilization bucket, matched against the synth cell-type names of any family
_UTIL_BUCKETS = [
    ("luts", re.compile(r"(SB_LUT4|TRELLIS_COMB|\bLUT[1-6]?\b|CCU2|ALU54|GW_LUT)", re.I)),
    ("ffs", re.compile(r"(DFF|_FF\b|TRELLIS_FF|GW_DFF|FD1)", re.I)),
    ("carry", re.compile(r"(SB_CARRY|CCU2|CARRY)", re.I)),
    ("bram", re.compile(r"(RAM40|DP16KD|PDPW16KD|BRAM|GW_BRAM|EBR|RAMW)", re.I)),
    ("dsp", re.compile(r"(SB_MAC16|MULT|MAC|DSP|ALU54)", re.I)),
    ("io", re.compile(r"(SB_IO|TRELLIS_IO|GW_IOB|IOB|BB\b|OBUF|IBUF)", re.I)),
]


def fpga_families() -> list[dict]:
    """FPGA targets this install can actually synthesize + place-and-route (flow + PnR present)."""
    out = []
    yosys_ok = _which("yosys") is not None
    for fam_id, meta in _FPGA_FAMILIES.items():
        pnr = _which(meta["pnr"]) is not None
        out.append({"id": fam_id, "name": meta["name"], "boards": meta["boards"],
                    "synth": yosys_ok, "pnr": pnr, "available": yosys_ok})
    return out


def fpga_synth(source: str, family: str = "ice40", language: str | None = None,
               top: str | None = None, timeout: float = 180.0) -> dict:
    """Synthesize RTL to a real FPGA family and report device utilization (LUT/FF/BRAM/DSP/…).

    This is technology mapping to actual vendor primitives (SB_LUT4 for iCE40, TRELLIS_* for
    ECP5, …), not a generic gate count — the numbers are what the part would really use.
    """
    lang = _norm_lang(language, source)
    if lang == "vhdl":
        return {"ok": False, "family": family, "error": "VHDL FPGA synth needs the yosys-ghdl plugin; use Verilog/SystemVerilog"}
    meta = _FPGA_FAMILIES.get(family)
    if not meta:
        return {"ok": False, "error": f"unknown family {family!r}", "families": list(_FPGA_FAMILIES)}
    yosys = _which("yosys")
    if not yosys:
        return {"ok": False, "family": family, "error": "Yosys not installed", "install": _OSS_HINT}
    with tempfile.TemporaryDirectory() as wd:
        src = Path(wd) / ("dut" + _ext(lang))
        src.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
        read = "read_verilog -sv" if lang == "systemverilog" else "read_verilog"
        tops = module_names(source)
        top = top or (tops[-1] if tops else None)
        flow = f"{meta['flow']} -top {top}" if top else meta["flow"]
        cp = _run([yosys, "-p", f"{read} dut{_ext(lang)}; {flow}; stat"], wd, timeout)
    if cp.returncode != 0:
        return {"ok": True, "family": family, "synthesized": False,
                "diagnostics": parse_diagnostics(cp.stderr, "generic"),
                "log": (cp.stderr or cp.stdout).strip()[-2000:]}
    stats, cells = _parse_yosys_stat(cp.stdout)
    util: dict[str, int] = {}
    for name, n in cells.items():
        for bucket, rx in _UTIL_BUCKETS:
            if rx.search(name):
                util[bucket] = util.get(bucket, 0) + n
                break
    return {"ok": True, "family": family, "device": meta["name"], "synthesized": True,
            "top": top, "utilization": util, "cells": cells,
            "total_cells": stats.get("cells", sum(cells.values())),
            "pnr_available": _which(meta["pnr"]) is not None,
            "note": f"Mapped to {meta['name']} primitives. nextpnr ({meta['pnr']}) "
                    f"{'is' if _which(meta['pnr']) else 'is not'} available for place-and-route.",
            "boards": meta["boards"]}


# --- FPGA place-and-route + timing (nextpnr Fmax) -------------------------
# Default parts per family; nextpnr device selection differs per architecture.
_ICE40_DEVICES = {"hx8k": "ct256", "hx1k": "tq144", "up5k": "sg48", "lp8k": "cm81", "u4k": "sg48"}
_ECP5_DENSITY = {"25k", "45k", "85k", "12k"}

_FMAX_RE = re.compile(r"Max frequency for clock\s+'([^']+)':\s+([\d.]+)\s*MHz"
                      r"(?:\s*\((PASS|FAIL) at ([\d.]+)\s*MHz\))?")
# nextpnr prefixes log lines with "Info:" and tabs; match "<NAME>: used/ total pct%" anywhere.
_UTIL_RE = re.compile(r"([A-Z][A-Z0-9_]+):\s+(\d+)\s*/\s*(\d+)\s+(\d+)\s*%")


def fpga_timing(source: str, family: str = "ice40", device: str | None = None,
                language: str | None = None, top: str | None = None,
                target_mhz: float | None = None, timeout: float = 300.0) -> dict:
    """Place-and-route with nextpnr and report real Fmax + device utilisation.

    This is the "compilation and timing analysis" step: Yosys maps RTL to the family, then
    nextpnr actually places and routes it on the chosen part and computes the achievable clock
    frequency (and PASS/FAIL against a target constraint if given). iCE40 and ECP5 are wired;
    other families synth fine but their nextpnr device flags are part-specific.
    """
    lang = _norm_lang(language, source)
    if lang == "vhdl":
        return {"ok": False, "error": "VHDL P&R needs the yosys-ghdl plugin; use Verilog/SystemVerilog"}
    if family not in ("ice40", "ecp5"):
        return {"ok": False, "family": family,
                "error": f"timing analysis is wired for iCE40/ECP5; {family} P&R needs part-specific device flags"}
    yosys = _which("yosys")
    pnr = _which(f"nextpnr-{family}")
    if not yosys or not pnr:
        miss = "Yosys" if not yosys else f"nextpnr-{family}"
        return {"ok": False, "family": family, "error": f"{miss} not installed", "install": _OSS_HINT}

    with tempfile.TemporaryDirectory() as wd:
        src = Path(wd) / ("dut" + _ext(lang))
        src.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
        read = "read_verilog -sv" if lang == "systemverilog" else "read_verilog"
        tops = module_names(source)
        top = top or (tops[-1] if tops else None)
        flow = f"synth_{family}" + (f" -top {top}" if top else "")
        ys = _run([yosys, "-p", f"{read} dut{_ext(lang)}; {flow} -json dut.json"], wd, timeout)
        if ys.returncode != 0 or not (Path(wd) / "dut.json").exists():
            return {"ok": True, "family": family, "routed": False, "stage": "synthesis",
                    "diagnostics": parse_diagnostics(ys.stderr, "generic"),
                    "log": (ys.stderr or ys.stdout).strip()[-2000:]}

        if family == "ice40":
            dev = device if device in _ICE40_DEVICES else "hx8k"
            args = [pnr, f"--{dev}", "--package", _ICE40_DEVICES[dev], "--json", "dut.json",
                    "--pcf-allow-unconstrained", "--placer", "heap"]
        else:  # ecp5
            dev = device if device in _ECP5_DENSITY else "25k"
            args = [pnr, f"--{dev}", "--json", "dut.json", "--lpf-allow-unconstrained"]
        if target_mhz:
            args += ["--freq", str(target_mhz)]
        pr = _run(args, wd, timeout)
        log = pr.stderr + "\n" + pr.stdout

    # nextpnr reports Fmax at several stages; keep the last (post-route) value per clock.
    by_clock: dict[str, dict] = {}
    for m in _FMAX_RE.finditer(log):
        by_clock[m.group(1)] = {"clock": m.group(1), "fmax_mhz": float(m.group(2)),
                                "verdict": m.group(3),
                                "target_mhz": float(m.group(4)) if m.group(4) else None}
    clocks = list(by_clock.values())
    util = {m.group(1): {"used": int(m.group(2)), "total": int(m.group(3)), "pct": int(m.group(4))}
            for m in _UTIL_RE.finditer(log)}
    routed = "Info: Program finished normally" in log or bool(clocks) or pr.returncode == 0
    return {"ok": True, "family": family, "device": dev, "top": top, "routed": routed,
            "clocks": clocks, "utilization": util,
            "met_timing": (all(c["verdict"] != "FAIL" for c in clocks) if clocks else None),
            "log_tail": "\n".join(log.strip().splitlines()[-40:])}


# --- vendor FPGA toolchains + constraint templates ------------------------
# Detect the big-three vendor toolchains (if installed) and generate pin-constraint file
# templates in each ecosystem's format — the "Xilinx / Intel / Lattice design tools" side.
_VENDOR_FPGA = {
    "vivado": {"name": "AMD/Xilinx Vivado", "exe": "vivado", "constraint": "xdc",
               "globs": [r"C:\Xilinx\Vivado\*\bin", r"C:\Xilinx\Vitis\*\bin"]},
    "quartus": {"name": "Intel Quartus Prime", "exe": "quartus_sh", "constraint": "qsf/sdc",
                "globs": [r"C:\intelFPGA*\*\quartus\bin64", r"C:\altera\*\quartus\bin64"]},
    "radiant": {"name": "Lattice Radiant", "exe": "radiantc", "constraint": "pdc",
                "globs": [r"C:\lscc\radiant\*\bin\nt64"]},
    "diamond": {"name": "Lattice Diamond", "exe": "pnmainc", "constraint": "lpf",
                "globs": [r"C:\lscc\diamond\*\bin\nt64"]},
}


def vendor_fpga_tools() -> list[dict]:
    """Detect installed vendor FPGA toolchains (Vivado / Quartus / Radiant / Diamond)."""
    import glob
    out = []
    for vid, meta in _VENDOR_FPGA.items():
        path = shutil.which(meta["exe"])
        if not path:
            for pat in meta["globs"]:
                hits = glob.glob(str(Path(pat) / (meta["exe"] + (".exe" if os.name == "nt" else ""))))
                hits += glob.glob(str(Path(pat) / (meta["exe"] + ".bat")))
                if hits:
                    path = sorted(hits)[-1]
                    break
        out.append({"id": vid, "name": meta["name"], "constraint": meta["constraint"],
                    "installed": path is not None, "path": path})
    return out


_CONSTRAINT_FMTS = {
    "xdc": "AMD/Xilinx (Vivado)", "pcf": "Lattice iCE40 (nextpnr/icestorm)",
    "lpf": "Lattice ECP5 / Diamond", "pdc": "Lattice Radiant", "qsf": "Intel Quartus",
}


def constraint_template(fmt: str, ports: list[dict]) -> dict:
    """Generate a pin-constraint file. ports: [{port, pin, iostd?, is_clock?, period_ns?}]."""
    fmt = fmt.lower()
    if fmt not in _CONSTRAINT_FMTS:
        return {"ok": False, "error": f"unknown format {fmt!r}", "formats": _CONSTRAINT_FMTS}
    lines: list[str] = []
    for p in ports:
        name, pin = str(p.get("port", "")), str(p.get("pin", ""))
        io = str(p.get("iostd", "LVCMOS33"))
        if not name:
            continue
        if fmt == "xdc":
            if pin:
                lines.append(f"set_property PACKAGE_PIN {pin} [get_ports {{{name}}}]")
            lines.append(f"set_property IOSTANDARD {io} [get_ports {{{name}}}]")
            if p.get("is_clock") and p.get("period_ns"):
                lines.append(f"create_clock -period {p['period_ns']} -name {name} [get_ports {{{name}}}]")
        elif fmt == "pcf":
            lines.append(f"set_io {name} {pin}")
        elif fmt == "lpf":
            lines.append(f'LOCATE COMP "{name}" SITE "{pin}";')
            lines.append(f'IOBUF PORT "{name}" IO_TYPE={io};')
            if p.get("is_clock") and p.get("period_ns"):
                freq = 1000.0 / float(p["period_ns"])
                lines.append(f'FREQUENCY PORT "{name}" {freq:.3f} MHZ;')
        elif fmt == "pdc":
            lines.append(f'ldc_set_location -site {{{pin}}} [get_ports {{{name}}}]')
            lines.append(f'ldc_set_port -iobuf {{IO_TYPE={io}}} [get_ports {{{name}}}]')
        elif fmt == "qsf":
            if pin:
                lines.append(f"set_location_assignment PIN_{pin} -to {name}")
            lines.append(f'set_instance_assignment -name IO_STANDARD "{io}" -to {name}')
    return {"ok": True, "format": fmt, "ecosystem": _CONSTRAINT_FMTS[fmt],
            "text": "\n".join(lines) + "\n"}


# --- Xilinx / Intel / Lattice FPGA + CPLD targets and vendor project export -----------
# Curated family map (FPGAs *and* CPLDs) with a sensible default part each — the parts are
# common dev-board devices so a generated project runs unmodified on real hardware.
PLD_FAMILIES: dict[str, dict] = {
    "xilinx": {
        "vendor": "AMD / Xilinx", "tool": "vivado",
        "families": {
            "artix7": {"name": "Artix-7 (FPGA)", "part": "xc7a35tcpg236-1", "board": "Basys-3"},
            "spartan7": {"name": "Spartan-7 (FPGA)", "part": "xc7s50csga324-1", "board": "Arty S7"},
            "kintex7": {"name": "Kintex-7 (FPGA)", "part": "xc7k70tfbg484-2", "board": None},
            "zynq7000": {"name": "Zynq-7000 (SoC FPGA)", "part": "xc7z020clg400-1", "board": "PYNQ-Z2"},
            "coolrunner2": {"name": "CoolRunner-II (CPLD)", "part": "xc2c64a-7vq44",
                            "board": None, "cpld": True,
                            "note": "CPLD flow needs legacy ISE 14.7, not Vivado"},
        },
    },
    "intel": {
        "vendor": "Intel / Altera", "tool": "quartus",
        "families": {
            "cyclone4": {"name": "Cyclone IV E (FPGA)", "part": "EP4CE22F17C6", "board": "DE0-Nano"},
            "cyclone5": {"name": "Cyclone V (FPGA)", "part": "5CSEMA5F31C6", "board": "DE1-SoC"},
            "max10": {"name": "MAX 10 (FPGA, CPLD-class)", "part": "10M50DAF484C7G", "board": "DE10-Lite"},
            "max2": {"name": "MAX II (CPLD)", "part": "EPM240T100C5", "board": None, "cpld": True},
            "max5": {"name": "MAX V (CPLD)", "part": "5M570ZT144C5", "board": None, "cpld": True},
        },
    },
    "lattice": {
        "vendor": "Lattice", "tool": "radiant",
        "families": {
            "ice40": {"name": "iCE40 (FPGA)", "part": "iCE40HX8K-CT256", "board": "iCE40-HX8K breakout",
                      "open_flow": "ice40"},
            "ecp5": {"name": "ECP5 (FPGA)", "part": "LFE5U-25F-6BG256C", "board": "ULX3S / Colorlight",
                     "open_flow": "ecp5"},
            "machxo2": {"name": "MachXO2 (CPLD-class)", "part": "LCMXO2-7000HC-4TG144C",
                        "board": "MachXO2 breakout", "cpld": True, "open_flow": "machxo2",
                        "note": "classic tool is Diamond, not Radiant"},
            "machxo3": {"name": "MachXO3 (CPLD-class)", "part": "LCMXO3LF-6900C-5BG256C",
                        "board": None, "cpld": True},
        },
    },
}


def pld_targets() -> dict:
    """The vendor/family/part map + whether each vendor's design tool is installed here."""
    tools = {t["id"]: t for t in vendor_fpga_tools()}
    out = {}
    for vid, v in PLD_FAMILIES.items():
        tool = tools.get(v["tool"], {})
        out[vid] = {
            "vendor": v["vendor"], "tool": v["tool"],
            "tool_installed": bool(tool.get("installed")),
            "tool_path": tool.get("path"),
            "families": v["families"],
        }
    return out


def _fmt_ports_tcl(ports: list[dict]) -> str:
    return constraint_template("xdc", ports)["text"] if ports else "# add pin constraints here\n"


def vendor_project(source: str, vendor: str, family: str, part: str | None = None,
                   top: str | None = None, ports: list[dict] | None = None,
                   language: str | None = None) -> dict:
    """Generate a ready-to-run vendor tool project (build script + constraints + runner).

    The scripts use each vendor's OFFICIAL batch flow (Vivado -mode batch, quartus_sh flows,
    Radiant Tcl). They run as-is when that tool is installed — and for Lattice families with
    an open-source flow the bundled yosys+nextpnr build script needs no vendor tool at all.
    """
    lang = _norm_lang(language, source)
    v = PLD_FAMILIES.get(vendor)
    if not v:
        return {"ok": False, "error": f"unknown vendor {vendor!r}", "vendors": list(PLD_FAMILIES)}
    fam = v["families"].get(family)
    if not fam:
        return {"ok": False, "error": f"unknown family {family!r} for {vendor}",
                "families": list(v["families"])}
    part = part or fam["part"]
    tops = module_names(source) or entity_names(source)
    top = top or (tops[-1] if tops else "top")
    ports = ports or []
    src_name = f"{top}{_ext(lang)}"
    files: dict[str, str] = {src_name: source if source.endswith("\n") else source + "\n"}
    notes: list[str] = []
    read_sv = lang == "systemverilog"

    if vendor == "xilinx":
        if fam.get("cpld"):
            return {"ok": False, "error": "CoolRunner-II CPLDs need legacy ISE 14.7 "
                    "(Vivado has no CPLD support) — install ISE from AMD's archive"}
        read_cmd = ("read_vhdl" if lang == "vhdl" else
                    ("read_verilog -sv" if read_sv else "read_verilog"))
        files["constraints.xdc"] = constraint_template("xdc", ports)["text"] if ports \
            else "# set_property PACKAGE_PIN / IOSTANDARD per port, create_clock for clocks\n"
        files["build.tcl"] = f"""# Vivado non-project batch flow — vivado -mode batch -source build.tcl
{read_cmd} {src_name}
read_xdc constraints.xdc
synth_design -top {top} -part {part}
opt_design
place_design
route_design
report_utilization -file utilization.rpt
report_timing_summary -file timing.rpt
write_bitstream -force {top}.bit
"""
        files["run.bat"] = "@echo off\r\nvivado -mode batch -source build.tcl\r\n"
        notes.append(f"Runs in Vivado batch mode against {part}; program with the Hardware Manager.")

    elif vendor == "intel":
        hdl_type = {"vhdl": "VHDL_FILE", "systemverilog": "SYSTEMVERILOG_FILE",
                    "verilog": "VERILOG_FILE"}[lang]
        qsf_pins = "".join(
            f"set_location_assignment PIN_{p['pin']} -to {p['port']}\n"
            f"set_instance_assignment -name IO_STANDARD \"{p.get('iostd', '3.3-V LVTTL')}\" -to {p['port']}\n"
            for p in ports if p.get("pin"))
        files[f"{top}.qsf"] = f"""set_global_assignment -name FAMILY "{fam['name'].split(' (')[0]}"
set_global_assignment -name DEVICE {part}
set_global_assignment -name TOP_LEVEL_ENTITY {top}
set_global_assignment -name {hdl_type} {src_name}
set_global_assignment -name SDC_FILE timing.sdc
{qsf_pins}"""
        files["timing.sdc"] = "".join(
            f"create_clock -period {p['period_ns']} [get_ports {p['port']}]\n"
            for p in ports if p.get("is_clock") and p.get("period_ns")) or "# create_clock here\n"
        files[f"{top}.qpf"] = f"PROJECT_REVISION = \"{top}\"\n"
        files["run.bat"] = f"@echo off\r\nquartus_sh --flow compile {top}\r\n"
        notes.append(f"quartus_sh --flow compile runs full synthesis→fitter→assembler for {part}"
                     + (" (CPLD)" if fam.get("cpld") else "") + ".")

    else:  # lattice
        if fam.get("open_flow"):
            flow = fam["open_flow"]
            pcf = constraint_template("pcf", ports)["text"] if ports and flow == "ice40" else None
            lpf = constraint_template("lpf", ports)["text"] if ports and flow != "ice40" else None
            if flow == "ice40":
                if pcf:
                    files["pins.pcf"] = pcf
                files["build_open.bat"] = ("@echo off\r\n"
                    f"yosys -p \"read_verilog {'-sv ' if read_sv else ''}{src_name}; synth_ice40 -top {top} -json {top}.json\"\r\n"
                    f"nextpnr-ice40 --hx8k --package ct256 --json {top}.json {'--pcf pins.pcf ' if pcf else '--pcf-allow-unconstrained '}--asc {top}.asc\r\n"
                    f"icepack {top}.asc {top}.bin\r\n"
                    f"openFPGALoader {top}.bin\r\n")
            else:
                if lpf:
                    files["pins.lpf"] = lpf
                pack = "ecppack" if flow == "ecp5" else "ecppack"
                files["build_open.bat"] = ("@echo off\r\n"
                    f"yosys -p \"read_verilog {'-sv ' if read_sv else ''}{src_name}; synth_{flow} -top {top} -json {top}.json\"\r\n"
                    f"nextpnr-{flow} --25k --json {top}.json {'--lpf pins.lpf ' if lpf else '--lpf-allow-unconstrained '}--textcfg {top}.cfg\r\n"
                    f"{pack} {top}.cfg {top}.bit\r\n"
                    f"openFPGALoader {top}.bit\r\n")
            notes.append("build_open.bat uses the bundled OSS CAD Suite (yosys + nextpnr + "
                         "openFPGALoader) — no vendor tool needed at all.")
        files["pins.pdc"] = constraint_template("pdc", ports)["text"] if ports \
            else "# ldc_set_location -site {pin} [get_ports port]\n"
        files["build_radiant.tcl"] = f"""# Lattice Radiant batch flow — radiantc build_radiant.tcl
prj_create -name {top} -impl impl_1 -dev {part}
prj_add_source {src_name}
prj_add_source pins.pdc
prj_set_impl_opt top {top}
prj_run Synthesis -impl impl_1
prj_run Map -impl impl_1
prj_run PAR -impl impl_1
prj_run Export -impl impl_1 -task Bitgen
prj_close
"""
        files["run_radiant.bat"] = "@echo off\r\nradiantc build_radiant.tcl\r\n"
        if fam.get("note"):
            notes.append(fam["note"])

    tool = next((t for t in vendor_fpga_tools() if t["id"] == v["tool"]), {})
    return {"ok": True, "vendor": vendor, "family": family, "part": part, "top": top,
            "language": lang, "is_cpld": bool(fam.get("cpld")),
            "tool": v["tool"], "tool_installed": bool(tool.get("installed")),
            "files": files, "notes": notes}


# --- FPGA bring-up: JTAG detect → bitstream → program (openFPGALoader) -----
# The complete end-to-end path onto real hardware: detect the cable/board over USB/JTAG,
# build an actual bitstream with the open flow, flash it, and report every step honestly.
_BUILD_ROOT = Path(os.environ.get("ECE_SUITE_DATA", Path.home() / ".ece-suite")) / "rtl_builds"


def _ofl() -> str | None:
    return _which("openFPGALoader")


def fpga_boards() -> dict:
    """Boards/cables openFPGALoader supports (for the bring-up board picker)."""
    ofl = _ofl()
    if not ofl:
        return {"ok": False, "error": "openFPGALoader not installed", "install": _OSS_HINT}
    cp = _run([ofl, "--list-boards"], str(Path.home()), 30)
    boards = re.findall(r"^\s{0,4}([\w][\w.-]+)\s", cp.stdout + cp.stderr, re.M)
    return {"ok": True, "boards": sorted(set(boards) - {"name"}), "count": len(set(boards))}


def fpga_detect() -> dict:
    """Probe USB/JTAG for a connected FPGA (openFPGALoader --detect / --scan-usb).

    Honest by construction: with no cable attached this returns the tool's own
    'no device found' — never a fabricated detection.
    """
    ofl = _ofl()
    if not ofl:
        return {"ok": False, "error": "openFPGALoader not installed", "install": _OSS_HINT}
    scan = _run([ofl, "--scan-usb"], str(Path.home()), 20)
    det = _run([ofl, "--detect"], str(Path.home()), 25)
    out = (det.stdout + "\n" + det.stderr).strip()
    idcodes = re.findall(r"idcode\s*(?:0x)?([0-9a-fA-F]+)[^\n]*?(?:manufacturer\s*(\S+))?[^\n]*?(?:model\s*(.+))?$",
                         out, re.M)
    found = det.returncode == 0 and "idcode" in out.lower()
    return {"ok": True, "found": found,
            "devices": [{"idcode": i[0], "manufacturer": i[1] or None, "model": (i[2] or "").strip() or None}
                        for i in idcodes] if found else [],
            "usb": (scan.stdout + scan.stderr).strip()[-1200:],
            "log": out[-1500:]}


def fpga_bitstream(source: str, family: str = "ice40", device: str | None = None,
                   top: str | None = None, language: str | None = None,
                   ports: list[dict] | None = None, timeout: float = 420.0) -> dict:
    """Full open-flow build to a REAL bitstream file: yosys → nextpnr → icepack/ecppack.

    Artifacts land in ~/.ece-suite/rtl_builds/<stamp>/ so the Program step (and the user)
    can pick them up. Returns per-step results + the bitstream path/size + post-route Fmax.
    """
    lang = _norm_lang(language, source)
    if lang == "vhdl":
        return {"ok": False, "error": "VHDL needs the yosys-ghdl plugin; use Verilog/SystemVerilog"}
    if family not in ("ice40", "ecp5"):
        return {"ok": False, "error": f"open bitstream flow wired for ice40/ecp5 (got {family!r})"}
    yosys, pnr = _which("yosys"), _which(f"nextpnr-{family}")
    pack = _which("icepack" if family == "ice40" else "ecppack")
    missing = [n for n, p in (("yosys", yosys), (f"nextpnr-{family}", pnr),
                              ("icepack/ecppack", pack)) if not p]
    if missing:
        return {"ok": False, "error": f"missing tools: {', '.join(missing)}", "install": _OSS_HINT}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    wd = _BUILD_ROOT / f"{family}-{stamp}"
    wd.mkdir(parents=True, exist_ok=True)
    src = wd / ("top" + _ext(lang))
    src.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
    tops = module_names(source)
    top = top or (tops[-1] if tops else None)
    steps: list[dict] = []

    def step(name: str, cmd: list[str], tmo: float) -> subprocess.CompletedProcess:
        cp = _run(cmd, str(wd), tmo)
        steps.append({"step": name, "ok": cp.returncode == 0,
                      "log_tail": ((cp.stderr or "") + (cp.stdout or "")).strip()[-800:]})
        return cp

    read = "read_verilog -sv" if lang == "systemverilog" else "read_verilog"
    flow = f"synth_{family}" + (f" -top {top}" if top else "")
    ys = step("synthesis (yosys)", [yosys, "-p", f"{read} {src.name}; {flow} -json top.json"], timeout)
    if ys.returncode != 0:
        return {"ok": True, "built": False, "dir": str(wd), "steps": steps, "stage": "synthesis"}

    if family == "ice40":
        dev = device if device in _ICE40_DEVICES else "hx8k"
        if ports:
            (wd / "pins.pcf").write_text(constraint_template("pcf", ports)["text"], encoding="utf-8")
        pnr_cmd = [pnr, f"--{dev}", "--package", _ICE40_DEVICES[dev], "--json", "top.json",
                   "--asc", "top.asc"] + (["--pcf", "pins.pcf"] if ports else ["--pcf-allow-unconstrained"])
        pack_cmd = [pack, "top.asc", "top.bin"]
        bit = wd / "top.bin"
    else:
        dev = device if device in _ECP5_DENSITY else "25k"
        if ports:
            (wd / "pins.lpf").write_text(constraint_template("lpf", ports)["text"], encoding="utf-8")
        pnr_cmd = [pnr, f"--{dev}", "--json", "top.json", "--textcfg", "top.cfg"] + \
                  (["--lpf", "pins.lpf"] if ports else ["--lpf-allow-unconstrained"])
        pack_cmd = [pack, "top.cfg", "top.bit"]
        bit = wd / "top.bit"

    pr = step("place & route (nextpnr)", pnr_cmd, timeout)
    if pr.returncode != 0:
        return {"ok": True, "built": False, "dir": str(wd), "steps": steps, "stage": "place-route"}
    fmax = None
    m = list(_FMAX_RE.finditer(pr.stderr + pr.stdout))
    if m:
        fmax = float(m[-1].group(2))
    pk = step("bitstream (pack)", pack_cmd, 120)
    built = pk.returncode == 0 and bit.exists()
    return {"ok": True, "built": built, "dir": str(wd),
            "bitstream": str(bit) if built else None,
            "size_bytes": bit.stat().st_size if built else None,
            "fmax_mhz": fmax, "device": dev, "top": top, "steps": steps}


def fpga_program(bitstream: str, board: str | None = None, cable: str | None = None,
                 timeout: float = 180.0) -> dict:
    """Flash a built bitstream onto the connected board via openFPGALoader."""
    ofl = _ofl()
    if not ofl:
        return {"ok": False, "error": "openFPGALoader not installed", "install": _OSS_HINT}
    p = Path(bitstream)
    if not p.exists():
        return {"ok": False, "error": f"bitstream not found: {bitstream}"}
    cmd = [ofl]
    if board:
        cmd += ["-b", board]
    if cable:
        cmd += ["-c", cable]
    cmd.append(str(p))
    cp = _run(cmd, str(p.parent), timeout)
    log = (cp.stdout + "\n" + cp.stderr).strip()
    return {"ok": cp.returncode == 0, "programmed": cp.returncode == 0,
            "log": log[-2000:],
            "hint": None if cp.returncode == 0 else
                    "connect the board's USB/JTAG (and pick the right --board), then retry"}


# --- seamless vendor-tool hand-off ----------------------------------------
_VENDOR_ROOT = Path(os.environ.get("ECE_SUITE_DATA", Path.home() / ".ece-suite")) / "vendor_projects"


def vendor_export(source: str, vendor: str, family: str, part: str | None = None,
                  top: str | None = None, ports: list[dict] | None = None,
                  language: str | None = None) -> dict:
    """Write the generated vendor project to a real folder, ready for the vendor tool."""
    r = vendor_project(source, vendor, family, part, top, ports, language)
    if not r.get("ok"):
        return r
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = _VENDOR_ROOT / f"{vendor}-{family}-{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    for name, content in r["files"].items():
        (dest / name).write_text(content, encoding="utf-8")
    r["dir"] = str(dest)
    r["files_written"] = sorted(r.pop("files").keys())
    return r


def vendor_launch(project_dir: str, vendor: str | None = None) -> dict:
    """Open the exported project: folder in Explorer + the vendor tool if installed."""
    d = Path(project_dir)
    if not d.is_dir():
        return {"ok": False, "error": f"not a directory: {project_dir}"}
    shell_open.open_path(d)
    launched_tool = None
    if vendor:
        meta = PLD_FAMILIES.get(vendor)
        tool = next((t for t in vendor_fpga_tools()
                     if meta and t["id"] == meta["tool"] and t["installed"]), None)
        if tool and tool.get("path"):
            try:
                shell_open.open_path(tool["path"])
                launched_tool = tool["id"]
            except OSError:
                pass
    return {"ok": True, "opened": str(d), "launched_tool": launched_tool,
            "note": None if launched_tool else
                    "vendor tool not installed — run.bat works once it is (see Software Setup)"}


# --- professional dev environment (the skills stack around the toolchain) --
def _find_vscode() -> str | None:
    hit = shutil.which("code")
    if hit:
        return hit
    for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
              Path(r"C:\Program Files\Microsoft VS Code\Code.exe")):
        if p.exists():
            return str(p)
    return None


def _cocotb_available() -> tuple[bool, str | None]:
    try:
        import cocotb  # noqa: F401
        return True, getattr(cocotb, "__version__", "?")
    except Exception:  # noqa: BLE001
        return False, None


def dev_environment() -> dict:
    """The workflow stack around the HDL toolchain — what a professional flow actually uses:
    editor + version control + scripting + waveforms + vendor sim. Detected, never assumed."""
    import sys

    git = shutil.which("git")
    code = _find_vscode()
    gtkwave = _which("gtkwave")
    vivado = next((t for t in vendor_fpga_tools() if t["id"] == "vivado" and t["installed"]), None)
    ct_ok, ct_ver = _cocotb_available()
    items = [
        {"id": "vscode", "name": "VS Code", "purpose": "HDL editing (open sources/projects from here)",
         "installed": bool(code), "path": code,
         "install": "https://code.visualstudio.com/"},
        {"id": "git", "name": "Git", "purpose": "version control for RTL projects",
         "installed": bool(git), "path": git, "install": "https://git-scm.com/download/win"},
        {"id": "python", "name": "Python", "purpose": "scripting + cocotb testbenches",
         "installed": True, "path": sys.executable, "install": None},
        {"id": "gtkwave", "name": "GTKWave", "purpose": "waveform viewing (simulation VCDs open here)",
         "installed": bool(gtkwave), "path": gtkwave,
         "install": "bundled with OSS CAD Suite — Software Setup tab"},
        {"id": "xsim", "name": "Vivado / XSim", "purpose": "vendor simulation + implementation",
         "installed": bool(vivado), "path": vivado["path"] if vivado else None,
         "install": "https://www.xilinx.com/support/download.html"},
        {"id": "cocotb", "name": "cocotb", "purpose": "Python-driven testbenches on Icarus/Verilator",
         "installed": ct_ok, "path": ct_ver, "install": "pip install cocotb"},
    ]
    return {"items": items,
            "stack_note": "Core flow: SystemVerilog + simulator + VS Code + Git. "
                          "Then Verilator + GTKWave + Python/cocotb for serious verification."}


def open_in_vscode(path: str) -> dict:
    code = _find_vscode()
    if not code:
        return {"ok": False, "error": "VS Code not found", "install": "https://code.visualstudio.com/"}
    shell_open.spawn_detached([code, path])
    return {"ok": True, "opened": path}


def open_vcd_in_gtkwave(vcd_text: str, name: str = "wave") -> dict:
    """Persist a simulation VCD and open it in GTKWave (the pro waveform-triage loop)."""
    gtkwave = _which("gtkwave")
    if not gtkwave:
        return {"ok": False, "error": "GTKWave not found — it ships with the OSS CAD Suite"}
    out = Path.home() / ".ece-suite" / "waves"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{re.sub(r'[^A-Za-z0-9_-]', '_', name)}.vcd"
    f.write_text(vcd_text, encoding="utf-8")
    shell_open.spawn_detached([gtkwave, str(f)], env=_tool_env())
    return {"ok": True, "file": str(f)}


def export_project(files: dict[str, str], dest: str, open_in: str | None = None) -> dict:
    """Write a generated vendor project to a real folder (then optionally open it)."""
    d = Path(dest).expanduser()
    if not d.is_absolute():
        return {"ok": False, "error": "destination must be an absolute path"}
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in files.items():
        safe = Path(name).name           # flat: no path escapes
        (d / safe).write_text(content, encoding="utf-8")
        written.append(safe)
    result = {"ok": True, "dir": str(d), "written": written}
    if open_in == "vscode":
        result["opened"] = open_in_vscode(str(d))
    elif open_in == "explorer":
        shell_open.open_path(d)
        result["opened"] = {"ok": True}
    return result


# --- engineering snippet library (CDC / reset / TB / constraints / ILA) ----
# Curated, synthesizable reference implementations of the patterns every FPGA engineer
# is expected to carry: clock-domain crossing, reset synchronization, self-checking
# testbenches, XDC timing constraints, ILA debug insertion, cocotb tests.
SNIPPETS: list[dict] = [
    {"id": "cdc-2ff", "name": "CDC: 2-flop synchronizer (single bit)", "language": "systemverilog",
     "note": "The baseline CDC primitive. ASYNC_REG groups the flops for placement; never "
             "synchronize multi-bit buses this way — use a handshake or gray-coded pointer.",
     "code": """// Single-bit clock-domain crossing: 2-flop synchronizer.
module sync_2ff #(parameter int STAGES = 2) (
  input  logic clk_dst,
  input  logic rst_dst_n,
  input  logic d_async,
  output logic q_sync
);
  (* ASYNC_REG = "TRUE" *) logic [STAGES-1:0] ff;
  always_ff @(posedge clk_dst or negedge rst_dst_n) begin
    if (!rst_dst_n) ff <= '0;
    else            ff <= {ff[STAGES-2:0], d_async};
  end
  assign q_sync = ff[STAGES-1];
endmodule"""},
    {"id": "cdc-pulse", "name": "CDC: toggle-handshake pulse crossing", "language": "systemverilog",
     "note": "Transfers single-cycle pulses between unrelated clocks. The source toggles a "
             "level; the destination synchronizes it and detects edges.",
     "code": """// Pulse CDC via toggle + edge detect (safe for any clock ratio).
module cdc_pulse (
  input  logic clk_src, rst_src_n, pulse_src,
  input  logic clk_dst, rst_dst_n,
  output logic pulse_dst
);
  logic toggle_src;
  always_ff @(posedge clk_src or negedge rst_src_n)
    if (!rst_src_n) toggle_src <= 1'b0;
    else if (pulse_src) toggle_src <= ~toggle_src;

  (* ASYNC_REG = "TRUE" *) logic [2:0] sync;
  always_ff @(posedge clk_dst or negedge rst_dst_n)
    if (!rst_dst_n) sync <= '0;
    else            sync <= {sync[1:0], toggle_src};

  assign pulse_dst = sync[2] ^ sync[1];
endmodule"""},
    {"id": "reset-sync", "name": "Reset synchronizer (async assert, sync release)", "language": "systemverilog",
     "note": "Reset asserts asynchronously (works with no clock) but releases synchronously, "
             "so every flop leaves reset on the same edge — the standard reset discipline.",
     "code": """// Asynchronous-assert / synchronous-release reset bridge.
module reset_sync (
  input  logic clk,
  input  logic arst_n,      // asynchronous reset in (button, POR, PLL lock)
  output logic rst_n        // synchronized reset for this clock domain
);
  (* ASYNC_REG = "TRUE" *) logic [1:0] ff;
  always_ff @(posedge clk or negedge arst_n)
    if (!arst_n) ff <= 2'b00;
    else         ff <= {ff[0], 1'b1};
  assign rst_n = ff[1];
endmodule"""},
    {"id": "tb-selfcheck", "name": "Self-checking testbench skeleton", "language": "systemverilog",
     "note": "Reference model + scoreboard pattern: stimulus drives DUT and model together, "
             "mismatches fail loudly, and the run ends with an unambiguous PASS/FAIL count.",
     "code": """// Self-checking TB: drives DUT + golden model in lockstep, counts mismatches.
module tb;
  logic clk = 0, rst_n = 0;
  always #5 clk = ~clk;

  logic [7:0] din, dut_q, model_q;
  int unsigned errors = 0, checks = 0;

  my_dut dut (.clk(clk), .rst_n(rst_n), .din(din), .q(dut_q));

  // golden reference model (behavioral)
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) model_q <= '0;
    else        model_q <= din;   // replace with the real expected behavior

  task automatic check;
    checks++;
    if (dut_q !== model_q) begin
      errors++;
      $display("FAIL @%0t: din=%h dut=%h expected=%h", $time, din, dut_q, model_q);
    end
  endtask

  initial begin
    $dumpfile("dump.vcd"); $dumpvars(0, tb);
    @(negedge clk) rst_n = 1;
    repeat (200) begin
      din = $urandom_range(0, 255);
      @(posedge clk); #1 check();
    end
    if (errors == 0) $display("PASS: %0d checks, 0 errors", checks);
    else             $display("FAIL: %0d/%0d mismatches", errors, checks);
    $finish;
  end
endmodule"""},
    {"id": "xdc-timing", "name": "XDC: clocks, I/O delay, false paths", "language": "xdc",
     "note": "The three constraint classes every Vivado project needs: clock definition, "
             "I/O timing relative to that clock, and exceptions for true asynchronous paths.",
     "code": """# --- clock definition (100 MHz on pin W5) ---------------------------------
create_clock -period 10.000 -name sys_clk [get_ports clk]
set_property PACKAGE_PIN W5 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports clk]

# --- input/output timing relative to sys_clk ------------------------------
set_input_delay  -clock sys_clk -max 2.5 [get_ports din*]
set_input_delay  -clock sys_clk -min 0.5 [get_ports din*]
set_output_delay -clock sys_clk -max 3.0 [get_ports dout*]
set_output_delay -clock sys_clk -min 0.0 [get_ports dout*]

# --- exceptions: async inputs go through a 2-FF synchronizer --------------
set_false_path -to [get_pins -hier -filter {NAME =~ */sync_2ff*/ff_reg[0]/D}]
# generated clock example (divided by 4 inside clk_div)
create_generated_clock -name clk_div4 -source [get_ports clk] -divide_by 4 \\
  [get_pins clk_div/q_reg/Q]"""},
    {"id": "ila-tcl", "name": "Vivado: insert ILA debug core (Tcl)", "language": "tcl",
     "note": "Marks nets for debug and inserts an Integrated Logic Analyzer after synthesis — "
             "run in the Vivado Tcl console, then refine in the Set Up Debug wizard.",
     "code": """# mark signals in RTL first:  (* mark_debug = "true" *) logic [7:0] state;
# then after synth_design:
create_debug_core u_ila_0 ila
set_property C_DATA_DEPTH 4096 [get_debug_cores u_ila_0]
set_property C_TRIGIN_EN false [get_debug_cores u_ila_0]
connect_debug_port u_ila_0/clk [get_nets sys_clk]
set dbg [get_nets -hier -filter {MARK_DEBUG}]
set_property port_width [llength $dbg] [get_debug_ports u_ila_0/probe0]
connect_debug_port u_ila_0/probe0 $dbg
implement_debug_core
write_debug_probes -force debug.ltx"""},
    {"id": "cocotb-test", "name": "cocotb: Python testbench + runner", "language": "python",
     "note": "Python-driven verification on the same Icarus install this tab uses. "
             "pip install cocotb, save next to your RTL, run with python.",
     "code": """# test_dut.py — cocotb 2.x python runner (no Makefiles needed)
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

@cocotb.test()
async def counter_counts(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    dut.rst_n.value = 0
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    start = int(dut.q.value)
    for _ in range(16):
        await RisingEdge(dut.clk)
    assert int(dut.q.value) == (start + 16) % 256, f"q={int(dut.q.value)}"

if __name__ == "__main__":
    from cocotb_tools.runner import get_runner
    r = get_runner("icarus")
    r.build(sources=["counter.sv"], hdl_toplevel="counter")
    r.test(hdl_toplevel="counter", test_module="test_dut")"""},
]


def snippets() -> list[dict]:
    return SNIPPETS


# --- format (Verible) -----------------------------------------------------
def format_src(source: str, language: str | None = None, timeout: float = 30.0) -> dict:
    lang = _norm_lang(language, source)
    if lang == "vhdl":
        return {"ok": False, "language": lang, "error": "no VHDL formatter wired (Verible is Verilog/SV)"}
    fmt = _which("verible-verilog-format")
    if not fmt:
        return {"ok": False, "language": lang, "error": "verible-verilog-format not installed", "install": _OSS_HINT}
    with tempfile.TemporaryDirectory() as wd:
        src = Path(wd) / ("dut" + _ext(lang))
        src.write_text(source, encoding="utf-8")
        cp = _run([fmt, str(src)], wd, timeout)
    if cp.returncode != 0:
        return {"ok": False, "language": lang, "error": (cp.stderr or "format failed").strip()}
    return {"ok": True, "language": lang, "formatted": cp.stdout}
