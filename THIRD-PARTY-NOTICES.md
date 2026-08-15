# Third-party notices

ECE Tool Suite is MIT licensed. It depends on the packages below, whose licenses are their
own. Versions and license fields were read from the installed distribution metadata rather
than transcribed from memory; re-check them when you bump a dependency.

## Read this before you redistribute a build

Running from source, none of this constrains you. Shipping a binary that bundles these
packages does.

**spicelib is GPL-3.0.** It parses LTspice and ngspice `.raw` output for the power-stage
verification path. It lives in its own `spice` extra precisely so that a build you intend to
distribute can leave it out, which is why `pip install -e ".[hw,assistant,mcu,power,dev]"`
does not pull it in. If you bundle it, the GPL's terms apply to what you distribute.

**zeroconf is LGPL-2.1-or-later**, and **libusb-package** ships a native `libusb-1.0` binary
that is also LGPL-2.1-or-later even though the Python wrapper around it is Apache-2.0. LGPL
does not conflict with an MIT release, but distributing them obliges you to keep them
replaceable and to pass the license text along. Both stay as separately importable files
inside `backend/runtime/Lib/site-packages/`, which satisfies that.

**Electron** embeds Chromium, V8 and Node.js. electron-builder copies `LICENSES.chromium.html`
and Electron's own `LICENSE` into the packaged output. Confirm both files are present in
`release/win-unpacked/` before publishing an installer.

## Python

| Package | Version verified | License |
|---|---|---|
| fastapi | 0.141.1 | MIT |
| uvicorn | 0.52.3 | BSD-3-Clause |
| pydantic | 2.13.4 | MIT |
| numpy | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| PyVISA | 1.16.2 | MIT |
| PyVISA-py | 0.8.1 | MIT |
| websockets | 17.0.1 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| psutil | 7.2.2 | BSD-3-Clause |
| pyusb | 1.3.1 | BSD-3-Clause |
| libusb-package | 1.0.30.0 | Apache-2.0 (bundles libusb, LGPL-2.1-or-later) |
| pyserial | 3.5 | BSD-3-Clause |
| zeroconf | 0.150.0 | LGPL-2.1-or-later |
| anthropic | 0.122.0 | MIT |
| claude-agent-sdk | 0.2.139 | MIT |
| mcp | 1.29.0 | MIT |
| pymcuprog | 3.19.4.61 | MIT |
| intelhex | 2.3.0 | BSD |
| pywin32 | 312 | PSF |
| control | 0.10.2 | BSD-3-Clause |
| PyOpenMagnetics | 1.6.1 | MIT |
| spicelib | 1.6.3 | **GPL-3.0** |
| cocotb | optional | BSD-3-Clause |
| pytest | 9.1.1 | MIT |

## JavaScript

| Package | Version verified | License |
|---|---|---|
| react, react-dom | 18.3.1 | MIT |
| clsx | 2.1.1 | MIT |
| class-variance-authority | 0.7.1 | Apache-2.0 |
| tailwind-merge | 2.6.1 | MIT |
| lucide-react | 0.468.0 | ISC |
| tailwindcss | 3.4.19 | MIT |
| autoprefixer | 10.5.4 | MIT |
| postcss | 8.5.26 | MIT |
| vite | 5.4.21 | MIT |
| @vitejs/plugin-react | 4.7.0 | MIT |
| typescript | 5.9.3 | Apache-2.0 |
| electron | 33.4.11 | MIT |
| electron-builder | 25.1.8 | MIT |

## Tools the app detects but does not ship

The Software Setup tab installs some of these and links to the vendor's download page for the
rest. None of them are redistributed here, and each keeps its own license: the OSS CAD Suite
(Yosys, nextpnr, Icarus Verilog, Verilator, GTKWave), GHDL, Verible, KiCad and its bundled
ngspice, LTspice, sigrok and PulseView, STM32CubeMX, TI Code Composer Studio, Vivado, Quartus,
Radiant, Diamond, LabVIEW, and the Keysight and NI VISA runtimes.

## Design and assets

The application icon (`assets/ece-tool-suite.ico` and `.png`) is original artwork for this
project and is covered by the repository's MIT license.

The instrument-panel styling was worked out with reference to knob, display and rack UI kits
published on the Figma Community. No asset, component or extracted file from any of them is
present in this repository or in the built application; every control in
`apps/renderer/src/components/ui/` is written from scratch in SVG and CSS.

Typography uses Inter when the system has it installed and falls back to the platform UI font
otherwise. No font file is bundled and none is fetched at runtime, so the app renders the same
on a lab machine with no network.
