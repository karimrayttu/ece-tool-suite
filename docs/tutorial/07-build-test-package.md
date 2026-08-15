# Development, Testing & Packaging

[← LabVIEW, Software Setup, Assistant & MCP](06-labview-setup-mcp.md) · [Index](01-getting-started.md)

This section covers the day-to-day dev loop, the pytest suite, the recipe for adding a new feature end-to-end (backend module → endpoint → tab), and the full packaging pipeline that turns the repo into a Windows installer.

### Repo layout for this workflow

| Path | Role |
|---|---|
| `backend/` | Python FastAPI sidecar (`ece_suite` package) + `tests/` |
| `apps/renderer/` | React + Vite + Tailwind UI |
| `apps/desktop/` | Electron shell: `main.js`, `sidecar.js`, `smoke.js`, electron-builder config |
| `backend/runtime/` | Self-contained CPython runtime (gitignored, built per release) |
| `release/` | electron-builder output (gitignored) |
| `docs/packaging.md` | The canonical packaging notes this section is based on |

`.gitignore` deliberately excludes everything that is generated or machine-specific: `.venv/`, `backend/runtime/`, `backend/_bundled_runtime/`, `release/`, `node_modules/`, `dist/`, plus `.env` secrets and local `*.db` data files. If you clone fresh, you build the venv and (only for packaging) the runtime yourself.

### Dev workflow

Three processes matter in dev: the Python backend, the Vite renderer dev server, and (optionally) the Electron window. The root `package.json` wires them up:

```json
"scripts": {
  "dev": "node scripts/dev.js",
  "app": "npm --workspace apps/desktop start",
  "backend": "node scripts/python.js -m ece_suite.main",
  "build": "npm --workspace apps/renderer run build",
  "test": "node scripts/python.js -m pytest -q",
  "lint": "node scripts/python.js -m ruff check ece_suite tests",
  "smoke": "node apps/desktop/smoke.js",
  "dist": "npm --workspace apps/desktop run dist"
}
```
*`package.json` (repo root)*: npm workspaces let one root command target `apps/renderer` or `apps/desktop` without `cd`-ing around. The Python entry points go through `scripts/python.js`, which finds the interpreter in `backend/.venv/Scripts` on Windows, `backend/.venv/bin` elsewhere, or the bundled `backend/runtime` in a packaged build.

First-time setup, from the repo root:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[hw,assistant,mcu,labview,power,spice,rtl,dev]"
cd ..
npm install
```

`scripts/setup.ps1` (and `scripts/setup.sh` on Linux/macOS) runs exactly this for you, including the `npm install`. Pass `-Minimal` / `--minimal` to install `dev` only.

Then the usual loop:

```powershell
npm run dev      # sidecar on http://127.0.0.1:8848 + Vite dev server, both at once
npm run backend  # just the sidecar
npm run build    # rebuild apps/renderer/dist
npm run app      # the real Electron window (spawns its own sidecar)
```

For pure UI work `npm run dev` is fastest, since Vite hot-reloads on save. `npm run app` starts Electron, which owns the sidecar lifecycle itself: it picks a free port off 8848, passes a per-launch nonce that `/health` must echo back (so it never adopts a stale orphaned server), and loads the *built* renderer from `apps/renderer/dist`, so a stale-looking UI under Electron usually just means you haven't run `npm run build`.

The optional-dependency extras in `backend/pyproject.toml` decide what the venv can do:

| Extra | Pulls in | Needed for |
|---|---|---|
| *(base)* | fastapi, uvicorn, pydantic, numpy, pyvisa, pyvisa-py, websockets | Core API + LAN/SOCKET instruments |
| `hw` | psutil, pyusb, libusb-package, pyserial, zeroconf | USB-TMC, serial, LXI/HiSLIP discovery |
| `assistant` | anthropic, claude-agent-sdk, mcp | In-app Claude chatbox + agent + MCP server |
| `mcu` | pymcuprog | Programmer tab (flash read/erase/write) |
| `labview` | pywin32 (Windows only) | LabVIEW VI Server automation over COM |
| `power` | control, pyopenmagnetics | Loop/magnetics power verification |
| `spice` | spicelib | LTspice/ngspice `.raw` parsing for the SPICE verification path |
| `rtl` | cocotb | Optional Python testbenches in the RTL tab |
| `dev` | pytest, pytest-asyncio, ruff | Running the test suite and the linter |

Install them all for development. The tests that need an extra skip themselves when it is absent, so a partial install still gives a green run. `spice` is the one left out of the runtime build below: spicelib is GPL-3.0, so pulling it into something you redistribute drags the copyleft along with it. On your own bench that does not matter, and `scripts/setup.ps1` installs it for you. `docs/packaging.md` and [THIRD-PARTY-NOTICES.md](../../THIRD-PARTY-NOTICES.md) have the licensing detail.

### Running the tests

```powershell
npm test
# or directly:
cd backend && .venv\Scripts\python -m pytest -q
```

Current state of the suite: **328 passed, 1 skipped**. `pytest.ini_options` in `pyproject.toml` sets `testpaths = ["tests"]` and `asyncio_mode = "auto"`, so async tests need no decorator.

No test needs hardware. The runtime app is hardware-first (nothing connected at startup, no simulator reachable through the UI), but the `SimXxx` instrument classes still exist *for the tests*, which wire them in via `manager.set(...)`. The major files:

| Test file | What it covers |
|---|---|
| `test_spine.py` | End-to-end spine: sim transport → SCPI path → decode, registry safety contracts |
| `test_contract.py` | Load-bearing contract: autonomous MCP surface ⊆ chatbox surface, never `SOURCE_CONTROL` |
| `test_provenance.py` / `test_verification.py` | Honesty contract + lab-truth gate: a sim can never be promoted to `VERIFIED_HW` |
| `test_safety.py` / `test_presets.py` | SafetyInvariantEngine forbidden states; transactional preset runner (confirm, verify, rollback, fault injection) |
| `test_preamble.py` | Keysight waveform preamble math on the shared sim/real decode path |
| `test_visa_api.py` / `test_psu_api.py` / `test_presets_api.py` | REST endpoint contracts (instruments disconnected by default; sims connected per-test) |
| `test_websockets.py` | All 7 `/ws/*` telemetry streams the UI depends on |
| `test_dmm_multivendor.py` / `test_vendors_multivendor.py` / `test_io_env.py` | Vendor detection from `*IDN?`, Fluke legacy DMM, role classification, USB VID mapping |
| `test_rtl.py` | HDL engine: parsing/language logic always; live iverilog/yosys runs only when installed; AI loop via a fake Anthropic client |
| `test_labview_pld.py` | LabVIEWCLI integration + Xilinx/Intel/Lattice PLD target map and vendor project export |
| `test_spice_verify.py` / `test_loop_verify.py` / `test_magnetics.py` / `test_capacitor_bank.py` / `test_power_designer.py` | Power verification stack (netlists, control-loop margins, OpenMagnetics, cap banks, native designer) |
| `test_assistant.py` / `test_mcp_bridge.py` / `test_mcp_server.py` | Claude assistant loop (fake client, no API key), Layer-B read-only bridge, standalone MCP server |
| `test_programmer.py` | pymcuprog device catalog offline; hardware paths error honestly |
| `test_logic_decode.py` / `test_can_decode.py` | Round-trip decoder tests: generate a known waveform, decode, compare bytes |
| `test_parts.py` / `test_param_parse.py` / `test_kicad.py` / `test_calculators.py` / `test_design_tools.py` | Parts search + parametric normalizer, KiCad analysis, calculators, CubeMX `.ioc` parse/edit |
| `test_setup_tools.py` | One-click installer: host allowlist, safe extraction, install state machine (download monkeypatched) |
| `test_screenshot.py` / `test_datalog.py` / `test_source_extras.py` / `test_keysight.py` / `test_instruments.py` | Instrument screenshot PNG path, CSV session logging, AWG/e-load presets, driver behavior |

Tests that shell out to external tools (RTL toolchain, SPICE engines, LabVIEWCLI) probe for the tool first and test the degrade-with-install-pointer path when it's absent, so the suite passes on a machine with none of them installed. The 1 skip is such a conditional.

### Adding a feature: module → endpoint → tab (worked example: RTL)

Every feature in the suite follows the same three-file pattern. The RTL/HDL feature is the cleanest template to copy.

**1. Write a pure-Python module in `backend/ece_suite/`.** It should not import FastAPI; it takes plain arguments and returns dicts. Crucially, it must *degrade honestly* when its external tool is missing:

```python
"""HDL / RTL design + verification engine (Verilog / SystemVerilog / VHDL).
...
Nothing here trusts the source blindly; the toolchain's own diagnostics are
the verdict ... When no toolchain is installed every entry point degrades
gracefully with an install pointer (OSS CAD Suite bundles all of these).
"""
_OSS_HINT = "https://github.com/YosysHQ/oss-cad-suite-build/releases (...)"

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
```
*`backend/ece_suite/rtl.py`*: the module locates its toolchain itself (PATH, known unpack dirs, `ECE_SUITE_HDL_BIN` override) and returns an install pointer instead of crashing when nothing is found. This is what lets the packaged app ship without bundling iverilog/yosys/ghdl.

**2. Expose it as endpoints in `backend/ece_suite/main.py`.** Define a Pydantic request model, import the module *lazily inside the handler* (keeps startup fast and optional deps optional), and audit-log anything meaningful:

```python
class RtlSourceIn(BaseModel):
    source: str
    language: str | None = None
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
```
*`backend/ece_suite/main.py`*: the `/api/rtl/status` + action-endpoint pair is the house style: the tab polls `status` to render installed/missing tool state, then calls the action endpoints. All endpoints live in `main.py` directly (no APIRouter indirection in this codebase).

If the feature should also be callable by the Claude chatbox or the autonomous MCP bridge, register it on the shared `ToolRegistry` with the right `Capability`:

```python
registry.register(ToolSpec(
    "rtl_lint",
    "Lint Verilog/SystemVerilog/VHDL RTL with the real toolchain (Verilator / "
    "Icarus / GHDL); returns structured error+warning diagnostics.",
    _rtl_lint_tool, Capability.ANALYZE, provenance_bearing=False,
    input_schema={"type": "object", "properties": {
        "source": {"type": "string"},
        "language": {"type": "string", "enum": ["verilog", "systemverilog", "vhdl"]},
        "top": {"type": "string"}}, "required": ["source"]}))
```
*`backend/ece_suite/main.py`*: `Capability.ANALYZE` means pure software, safe on every surface. Anything that energizes hardware uses `SOURCE_CONTROL` with `confirm_required=True`, and `test_contract.py` structurally guarantees the autonomous surface never gets those tools, so your new registration is automatically covered by that test.

**3. Add the tab in the renderer.** Create `apps/renderer/src/components/RtlTab.tsx`, then register it in two places:

```tsx
// apps/renderer/src/components/Sidebar.tsx: add a NavItem
{ key: "rtl", label: "RTL / HDL", icon: FileCode },

// apps/renderer/src/App.tsx: import and route it
import { RtlTab } from "./components/RtlTab";
...
{view === "rtl" && <RtlTab />}
```
*`apps/renderer/src/components/Sidebar.tsx`, `apps/renderer/src/App.tsx`*: the sidebar `key` is the tab's identity ("rtl", "scope", "labview", …); `App.tsx` switches on that key. Put the fetch helpers in `apps/renderer/src/lib/api.ts` alongside the existing ones.

**4. Write the test file.** `backend/tests/test_rtl.py` is the template: exercise the pure logic unconditionally, gate the live-tool assertions on the tool being installed, and fake any AI client. Run `pytest -q` and update your expected count.

![The RTL / HDL tab on a machine with the OSS CAD Suite installed: toolchain badges, SystemVerilog design and testbench editors, lint/simulate/synthesize controls](img/rtl.png)
*The RTL / HDL tab on a machine with the OSS CAD Suite installed. The badge row across the top reports each detected tool (Icarus Verilog, Icarus vvp, Verilator, GHDL, Yosys, Verible lint, Verible format, AI RTL); below it are the SystemVerilog design and testbench editors, the lint / simulate / synthesize / format buttons, the FPGA target row, and the top of the GenAI RTL panel.*

### The portable Python runtime (why a venv cannot ship)

A dev `.venv` is not relocatable. Its `pyvenv.cfg` hardcodes the absolute path of the *base interpreter on the build machine* (and uv's launcher stub bakes it in too), so copying a venv to another PC produces a Python that points at an interpreter that doesn't exist there. The distributable therefore ships a **self-contained CPython 3.12** at `backend/runtime/`: a copy of the relocatable python-build-standalone dist with `ece_suite` and every dependency pip-installed *into the runtime itself*.

Build (or refresh) it once per machine/release:

```bat
robocopy %APPDATA%\uv\python\cpython-3.12-windows-x86_64-none backend\runtime /E
backend\runtime\python.exe -m ensurepip --default-pip
del backend\runtime\Lib\EXTERNALLY-MANAGED
backend\runtime\python.exe -m pip install -c backend\runtime-constraints.txt "backend[hw,assistant,mcu,labview,power,dev]"
backend\runtime\python.exe -m pytest backend -q
```
*from `docs/packaging.md`*. The last line is the gate: the runtime must pass the exact same suite as the venv (328 passed, 1 skipped) before it's allowed into a build. `backend/runtime-constraints.txt` is committed and pins every version the suite validates, so a rebuilt runtime can't silently drift to newer wheels. The extras list here is the venv's, minus `spice` and `rtl`: a redistributable build must not carry GPL-3.0 spicelib, which is why that extra sits outside `power`; cocotb is a development-only testbench runner and has no business in a shipped runtime.

`sidecar.js` resolves the interpreter with a fixed priority so one code path serves dev, packaged, and smoke-test layouts:

```js
function resolvePython() {
  const repoRoot = path.resolve(__dirname, "..", "..");
  const res = process.env.ECE_SUITE_RESOURCES || process.resourcesPath || repoRoot;
  const candidates = [];
  if (process.env.ECE_SUITE_RESOURCES) {
    candidates.push({ python: path.join(res, "backend", "runtime", "python.exe"),
                      cwd: path.join(res, "backend") });
  }
  candidates.push(
    { python: path.join(repoRoot, "backend", ".venv", "Scripts", "python.exe"), ... }, // dev
    { python: path.join(res, "backend", "runtime", "python.exe"), ... },      // packaged
    { python: path.join(repoRoot, "backend", "runtime", "python.exe"), ... }, // in-repo runtime
  );
  for (const c of candidates) if (fs.existsSync(c.python)) return c;
}
```
*`apps/desktop/sidecar.js`*: dev venv wins by default; `ECE_SUITE_RESOURCES` force-overrides everything so you can point at a built artifact's `resources` folder and test the *real* packaged interpreter on the dev machine. `sidecar.js` also always drains the child's stdout/stderr into a 60-line tail: uvicorn logs synchronously, and an undrained 64 KB OS pipe buffer would eventually block the backend mid-session.

### The electron-builder pipeline

`npm run dist` in `apps/desktop` runs a `predist` hook first, then electron-builder:

```json
"scripts": {
  "predist": "node ../../scripts/check-runtime.js && npm run build --prefix ../renderer && ..\\..\\backend\\runtime\\python.exe -m pip install --quiet --no-warn-script-location --no-deps --force-reinstall ..\\..\\backend",
  "dist": "electron-builder",
  "predist:dir": "npm run predist",
  "dist:dir": "electron-builder --dir"
},
"build": {
  "electronVersion": "33.4.11",
  "npmRebuild": false,
  "files": ["main.js", "preload.js", "sidecar.js"],
  "extraResources": [
    { "from": "../renderer/dist", "to": "renderer/dist" },
    { "from": "../../assets", "to": "assets" },
    { "from": "../../backend/runtime", "to": "backend/runtime",
      "filter": ["**/*", "!**/__pycache__/**"] }
  ],
  "win": { "target": ["nsis", "portable"], "icon": "../../assets/ece-tool-suite.ico" }
}
```
*`apps/desktop/package.json`*. The load-bearing details:

- **`predist` chain**: `scripts/check-runtime.js` runs first and aborts with the build instructions if `backend/runtime` is missing or the host is not Windows, because electron-builder will otherwise produce an installer that dies on first launch. Then it rebuilds the renderer (so `renderer/dist` is fresh) and force-reinstalls `ece_suite` into the runtime with `--no-deps` (deps are already pinned there; only your latest source needs refreshing). Skipping the reinstall is the #1 cause of "my code change isn't in the build."
- **`extraResources`**: ships exactly three things: the built renderer, the icon assets, and `backend/runtime` (with `__pycache__` filtered out). No venv, no tests, no source tree.
- **`electronVersion` pin**: required because the npm workspace hoists `electron` to the repo root, where electron-builder's auto-detection can't find it.
- **`npmRebuild: false`**: the Electron shell has zero native production dependencies, so rebuilding native modules is pointless work.
- **Two artifacts**: `release/ECE-Tool-Suite-<ver>-setup.exe` (NSIS, per-user, user-choosable install dir, not one-click) and `ECE-Tool-Suite-<ver>-portable.exe` (single self-extracting file). Use `dist:dir` for a fast unpacked build in `release/win-unpacked` while iterating.

### Smoke-testing the packaged build

`smoke.js` spawns the sidecar *exactly* as Electron would (same `sidecar.js` code path) and asserts the health contract, headless:

```js
const checks = [
  ["status ok", health.status === "ok"],
  ["launch nonce echoed (identity check)", health.nonce === NONCE],
  ["mode is hardware (no sim in runtime)", health.mode === "hardware"],
  ["all instrument roles start disconnected",
    Object.values(health.instruments || {}).every((i) => i.connected === false)],
  ["hardware NOT claimed connected",
    health.hardware_connected === false && health.any_connected === false],
  ["autonomous surface ⊆ chatbox surface",
    health.capabilities_autonomous.every((n) => health.capabilities_chatbox.includes(n))],
];
```
*`apps/desktop/smoke.js`*. These are the app's non-negotiables restated as a boot check: identity (nonce echo), hardware-first honesty (nothing connected, nothing claimed verified), and the safety contract (the autonomous tool surface is a strict subset of the chatbox surface).

Run it against both layouts:

```powershell
# dev layout (venv)
npm run smoke

# packaged layout: force sidecar.js onto the bundled runtime
cd apps\desktop
npm run dist:dir
set ECE_SUITE_RESOURCES=<repo>\release\win-unpacked\resources
node smoke.js
```

Without `ECE_SUITE_RESOURCES`, the smoke test would always find the dev venv first and pass even if the bundled runtime were broken, so the env var is what makes it a real packaging test. If the sidecar never comes up, the `catch` in `smoke.js` prints `SMOKE FAILED:` plus the captured output tail from `sidecar.js` and exits non-zero, which is normally the Python traceback you need.

### Build-machine quirk: app-builder-bin vs antivirus

electron-builder 25 pins `app-builder-bin@5.0.0-alpha.10`, whose unsigned Go binary (`win/x64/app-builder.exe`) some AV engines silently delete: only the Windows PE vanishes from `node_modules`; the mac/linux binaries survive, which makes the resulting "spawn ENOENT" confusing. The workaround touches no security settings:

```bat
npm pack app-builder-bin@4.2.0
tar -xf app-builder-bin-4.2.0.tgz
set CUSTOM_APP_BUILDER_PATH=<extracted>\package\win\x64\app-builder.exe
npx electron-builder
```
*from `docs/packaging.md`*. The stable 4.2.0 binary has a different hash that isn't flagged, and electron-builder honors `CUSTOM_APP_BUILDER_PATH` natively. If `dist` fails with a missing `app-builder.exe`, check your AV quarantine before debugging anything else.

### Code signing

The build is currently unsigned, so first launch on a new machine trips Windows SmartScreen ("Windows protected your PC"). That's expected for internal use; click *More info → Run anyway*. Before distributing outside your own bench, add an OV/EV certificate to the electron-builder `win` block (`certificateFile` / `certificateSubjectName`); nothing else in the pipeline changes.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Electron window shows an error page with Python output | Backend failed to start; `main.js` renders the sidecar's last 60 output lines plus the interpreter path it tried | Read the tail; it's the actual uvicorn/import traceback. Usually a missing extra in the venv or a broken runtime refresh |
| "port 8848 busy" warning in the console | Another process (or an orphaned backend) holds 8848 | Nothing to do: `main.js` finds a free port automatically and the nonce check guarantees it never adopts the stranger on 8848 |
| UI in Electron doesn't show your renderer changes | Electron loads the *built* `renderer/dist`, not the Vite dev server | `npm run build` in `apps/renderer`, or just `npm run dist`/`dist:dir`, whose `predist` does it for you |
| Packaged app runs old backend code | `predist` pip-reinstall was skipped (ran `electron-builder` directly) | Always go through `npm run dist` / `dist:dir` so `ece_suite` is force-reinstalled into `backend/runtime` |
| `smoke.js` passes but the installer's app is broken | Smoke ran against the dev venv | Set `ECE_SUITE_RESOURCES` to `release\win-unpacked\resources` and rerun |
| `dist` dies with missing `app-builder.exe` | AV deleted the alpha app-builder binary | `CUSTOM_APP_BUILDER_PATH` workaround above |
| Runtime pytest run diverges from venv run | Runtime wheels drifted from the pinned set | Reinstall with `-c backend\runtime-constraints.txt`; never ship a runtime whose suite result differs from the venv's 328 passed / 1 skipped |
| SmartScreen blocks first run on a target machine | Unsigned build | Expected until a signing cert is added; *More info → Run anyway* |

Two honest hardware/tool caveats carry over from packaging into anything you ship: USB (USBTMC) instruments need **Keysight IO Libraries Suite** installed on the target machine (LAN/LXI works out of the box via the bundled `pyvisa-py`), and the RTL tab's toolchain (iverilog/verilator/yosys/nextpnr/ghdl/verible) is detected on the target, not bundled; every RTL feature degrades to an install pointer until the OSS CAD Suite is present.

---
[← LabVIEW, Software Setup, Assistant & MCP](06-labview-setup-mcp.md) · [Back to index](01-getting-started.md)
