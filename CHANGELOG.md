# Changelog

Notable changes per release. Versions follow [semantic versioning](https://semver.org/),
with the caveat that anything below 1.0 can break between minor versions.

## [Unreleased]

## [0.1.0] - 2026-08-15

First public release. The code predates it by about six weeks of private development.

### Instruments

- Oscilloscope, multimeter, spectrum analyzer, power supply, function generator and
  electronic load, each on its own tab with a Discover / Connect / Verify / Disconnect bar.
- VISA transport that tries the system VISA layer first (Keysight IO Libraries, NI-VISA) and
  falls back to `pyvisa-py`. USB (USBTMC), LAN (VXI-11, HiSLIP, raw socket), serial and GPIB.
- 19 vendors recognised from `*IDN?` and mapped to a SCPI dialect. Most bench gear is
  SCPI-1999 enough that one Keysight-style scope driver covers Keysight, Rigol, Siglent,
  Rohde & Schwarz and GW Instek; Tektronix gets its own driver for its different waveform and
  measurement commands. Per-model capability profiles keep the UI from offering controls the
  connected instrument does not implement.
- Keysight waveform preamble decoding with an IEEE-488.2 definite-length block parser. The
  sim transports encode through the inverse of the same code, so tests exercise the real
  decode path.
- Live streams over WebSocket for scope, DMM and spectrum. CSV export on every tab, PNG
  export of the app canvas, and native instrument screenshots for scope and spectrum.
- Server-side DMM session recording.

### Safety and provenance

- Three-level provenance (`SIMULATED`, `UNVERIFIED_HW`, `VERIFIED_HW`) that a reading cannot
  be constructed without, and that can only be lowered. A connection is unverified until a
  live `*IDN?` plus a clean error-queue read-back passes.
- `SafetyInvariantEngine` returning ALLOW, REQUIRE_CONFIRM or BLOCK against a declared DUT
  envelope and the instrument's own ratings, most restrictive rule winning.
- `PresetRunner` sets and reads back OVP/OCP before any output is enabled, and forces the
  output off on any failure.
- Native `:AUToScale` is refused; scope front-end limits are computed from live attenuation,
  coupling and input impedance instead.
- Append-only JSONL audit log with a monotonic sequence number.

### Design

- Power-stage designer with SPICE verification through LTspice or ngspice, closed-loop margin
  analysis via `python-control`, magnetics design through PyOpenMagnetics, and capacitor bank
  sizing.
- 20 calculators in the UI plus 2 reachable only from the API: dividers with E24 snapping, LC
  filter, L-match network, microstrip impedance, decoupling, LED resistor, RC and RL cutoff,
  LC resonance, op-amp gain, trace width, junction temperature, 555 astable, ADC resolution,
  dBm conversion, shunt sense, capacitor energy, buck duty and wavelength.
- Parts search over an offline catalog, with live Nexar and Digi-Key adapters when credentials
  are present. Parts-by-URL import.
- KiCad schematic analysis: components, nets and circuit-pattern detection.
- STM32 tab that reads and edits CubeMX `.ioc` pin, mux and timer configuration.

### RTL and FPGA

- Write, lint, simulate and synthesize Verilog, SystemVerilog and VHDL through Icarus,
  Verilator, GHDL, Yosys and Verible. Place-and-route plus timing through nextpnr.
- Vendor project export for Xilinx, Intel and Lattice, including CPLD targets.
- Register-map generator.
- Optional model-assisted RTL generation, gated on the toolchain actually passing lint and
  simulation before anything is called validated.

### Integration

- MCU flashing and firmware readback through `pymcuprog`.
- Logic and CAN protocol decoding (SPI, I²C, UART).
- LabVIEW automation through NI's LabVIEWCLI, plus VI Server over COM.
- One-click installers for freely redistributable third-party tools; login-gated vendors open
  their official download page rather than working around the login.
- MCP server (`ece_suite.mcp_server`) exposing the bench to external agent clients, and an
  in-process agent bridge limited to the read-only tool surface.

### Notes on partial installs

- Optional dependencies are genuinely optional. `test_mcp_server.py`, `test_programmer.py` and
  one magnetics case skip themselves when their extra is absent, so a core-only install gives a
  clean run rather than a collection error.
- SPICE verification treats running the netlist and parsing the `.raw` as separate
  capabilities, both reported by `GET /api/spice/status`. A machine with KiCad's bundled
  ngspice but without the `spice` extra is told which half is missing instead of failing after
  the simulation has already run.
- The MCU programmer returns an honest error with the install command when `pymcuprog` is
  absent, rather than raising `ModuleNotFoundError` from the hardware path.
- The assistant drawer collapses to a 36 px rail and remembers the choice.

### Packaging

- Electron shell owning the sidecar lifecycle: single-instance lock, free-port fallback from
  8848, per-launch nonce so it will not adopt a foreign server, and an error page carrying the
  sidecar's own output when startup fails.
- NSIS installer and single-file portable build carrying a relocatable CPython 3.12 runtime,
  so the target machine needs nothing preinstalled.

[Unreleased]: https://github.com/karimrayttu/ece-tool-suite/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/karimrayttu/ece-tool-suite/releases/tag/v0.1.0
