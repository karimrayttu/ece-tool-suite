# Packaging a Windows build

Packaging is Windows-only. There is no `mac` or `linux` block in the electron-builder config,
and the bundled interpreter is a Windows CPython. On other platforms, run from source.

## Running the native window from a checkout

```
npm run build     # produce apps/renderer/dist
npm run app       # electron: spawns the Python sidecar, loads the built renderer
```

`apps/desktop/main.js` detects the built renderer and owns the sidecar's lifecycle: a
single-instance lock, a free-port fallback from 8848, a per-launch nonce that `/health` echoes
so it never adopts a stale or foreign server, a kill on quit, and an error page carrying the
sidecar's own output when startup fails.

## The bundled Python runtime

A development `.venv` is not relocatable. Its `pyvenv.cfg` points at the base interpreter on
the machine that created it, so copying it to another PC gives you an interpreter that cannot
start. The distributable therefore ships a self-contained CPython instead: a copy of the
relocatable [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
3.12 distribution with `ece_suite` and its dependencies installed into it.

Build it once per machine or per release. `uv` is the easiest way to get the standalone
distribution:

```
uv python install 3.12
robocopy %APPDATA%\uv\python\cpython-3.12-windows-x86_64-none backend\runtime /E
backend\runtime\python.exe -m ensurepip --default-pip
del backend\runtime\Lib\EXTERNALLY-MANAGED
backend\runtime\python.exe -m pip install -c backend\runtime-constraints.txt "backend[hw,assistant,mcu,labview,power,dev]"
backend\runtime\python.exe -m pytest backend -q
```

That test run has to match what the dev venv gives you (328 passed, 1 skipped as of 0.1.0).
If it does not, the runtime is missing something and the packaged app will fail at whatever
feature that something belongs to.

`backend/runtime-constraints.txt` is committed and pins every version the suite was tested
against. Note that the `spice` extra is deliberately absent from that install line: spicelib is
GPL-3.0, and bundling it into a redistributable build brings the GPL with it. See
[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).

### The VC++ runtime has to come with it

python-build-standalone bundles `vcruntime140.dll` and `vcruntime140_1.dll`, but some native
extensions link the C++ runtime instead, and numpy and scipy hide their own copies under
`*.libs` behind a delvewheel hash so no other module can find them.

`PyOpenMagnetics\KirchhoffApi.dll` imports a plain `msvcp140.dll`. That file is present on any
machine with the Visual C++ redistributable installed, and absent on a fresh Windows without
it, where the magnetics feature then fails with an unhelpful import error. The
`api-ms-win-crt-*` dependencies are the UCRT and do ship with Windows 10 and 11, so those are
fine.

After building the runtime, copy the redistributable DLLs into both the runtime root and the
PyOpenMagnetics package directory:

```
for %d in (msvcp140.dll msvcp140_1.dll msvcp140_2.dll mfc140u.dll vcruntime140.dll vcruntime140_1.dll) do (
  copy /y %WINDIR%\System32\%d backend\runtime\%d
  copy /y %WINDIR%\System32\%d backend\runtime\Lib\site-packages\PyOpenMagnetics\%d
)
```

To check the result is actually self-contained: every `msvcp*`, `vcruntime*` and `mfc*` import
of every `.pyd` and `.dll` under `backend/runtime` has to resolve inside the bundle, either at
the root or in a `*.libs` directory.

`sidecar.js` resolves the interpreter in this order: the dev venv, then
`resources/backend/runtime` (the packaged layout), then an in-repo `backend/runtime`, then
whatever `python` is on PATH. Set `ECE_SUITE_RESOURCES` to force the packaged layout so you
can smoke-test a built artifact on the build machine.

## Building the installer

```
npm run dist
```

`predist` rebuilds the renderer and refreshes `ece_suite` inside the runtime, then
electron-builder produces `release/ECE-Tool-Suite-<version>-setup.exe` (NSIS) and
`release/ECE-Tool-Suite-<version>-portable.exe`.

`extraResources` ships only `renderer/dist`, `assets/` and `backend/runtime`: no venv, no
tests. `electronVersion` is pinned because the workspace hoists electron to the repo root,
and `npmRebuild` is off since the shell has no native production dependencies.

### If app-builder.exe disappears

electron-builder 25 pins `app-builder-bin@5.0.0-alpha.10`, whose unsigned Go binary
(`win/x64/app-builder.exe`) gets quarantined by some antivirus products. The tell is that only
the Windows PE vanishes while the mac and linux binaries survive. The workaround changes no
security settings:

```
npm pack app-builder-bin@4.2.0 && tar -xf app-builder-bin-4.2.0.tgz
set CUSTOM_APP_BUILDER_PATH=<extracted>\package\win\x64\app-builder.exe
npx electron-builder
```

The 4.2.0 binary has a different hash and is not flagged, and electron-builder honours
`CUSTOM_APP_BUILDER_PATH` natively.

## Release checklist

1. Bump the version in all five places: `package.json`, `apps/desktop/package.json`,
   `apps/renderer/package.json`, `backend/pyproject.toml` and
   `backend/ece_suite/__init__.py`. electron-builder reads `${version}` from the desktop
   manifest, and `/health` reports the one from `__init__.py`.
2. Update `CHANGELOG.md`.
3. Rebuild `backend/runtime` and run its test suite.
4. Sweep the release output for anything machine-specific before publishing.
5. Confirm `LICENSES.chromium.html` and Electron's `LICENSE` landed in
   `release/win-unpacked/`.
6. Tag the commit.

## Two things the target machine still needs

USB (USBTMC) instruments need Keysight IO Libraries or NI-VISA installed, because that is what
enumerates USBTMC devices. LAN instruments work with the bundled `pyvisa-py`.

The HDL toolchain (Icarus, Verilator, Yosys, nextpnr, GHDL, Verible) is detected, not bundled.
Install the OSS CAD Suite on the target, drop the GHDL zip into `oss-cad-suite\ghdl\` and the
Verible executables into `oss-cad-suite\bin\`. Until then every feature that needs them shows
an install pointer instead of a broken button.

An unsigned build trips SmartScreen on first run. Add a certificate to electron-builder's
`win.certificateFile` before distributing to anyone else.
