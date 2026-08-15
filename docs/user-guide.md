# User guide

How to get from a fresh install to a verified reading off a real instrument. For how the code
is put together, read the [tutorial](tutorial/01-getting-started.md) instead.

## Starting the app

From an installed build, launch **ECE Tool Suite** from the Start menu. From a source
checkout:

```powershell
npm run app     # native Electron window; it starts the Python sidecar itself
npm run dev     # backend plus the Vite dev server at http://localhost:5173
```

The top bar shows the mode and the connected-instrument count. With nothing plugged in it
reads `NO INSTRUMENTS`, which is the expected state until you connect something.

## Connecting an instrument

Open the tab for the role you want (Oscilloscope, Multimeter, Spectrum, Sources). Each one has
the same four-step bar.

**Discover** lists the VISA resources it can see over USB and LAN, marking Keysight units with
a star. You can also type a resource yourself:

| Interface | Example |
|---|---|
| LAN, VXI-11 | `TCPIP0::192.168.0.50::inst0::INSTR` |
| LAN, HiSLIP | `TCPIP0::192.168.0.50::hislip0::INSTR` |
| LAN, raw socket | `TCPIP0::192.168.0.50::5025::SOCKET` |
| USB (USBTMC) | `USB0::0x2A8D::0x1234::MY51234567::INSTR` |
| Serial | `ASRL3::INSTR` (or just type `COM3` in the address box) |
| GPIB | `GPIB0::22::INSTR` |

**Connect** opens the session. It tries the system VISA layer first and falls back to
`pyvisa-py`. The instrument is now tagged `UNVERIFIED_HW`.

**Verify** queries `*IDN?` and drains the error queue. If both come back clean the tag becomes
`VERIFIED_HW` and the status bar turns green. Until then, nothing the instrument reports is
presented as a real measurement.

**Disconnect** closes the session and releases the lock.

If Discover finds nothing over USB, install Keysight IO Libraries Suite or NI-VISA. Those
provide the VISA layer that enumerates USBTMC devices. LAN instruments work without either,
through the bundled `pyvisa-py`.

## The tabs

**Oscilloscope.** CH1 to CH4 with V/div, offset, coupling, probe attenuation, timebase and
trigger. Run, Stop and Single. Auto-setup presets and a guided bring-up sequence. Live
multi-channel waveform with Vpp, Vrms, Vmax, Vmin, frequency and period. Exports CSV, saves
the app canvas as PNG, and can pull a native screenshot off the instrument.

**Multimeter.** Eleven functions, range and NPLC control, a large readout with min/max/average
and a rolling trend. CSV export client-side, plus a server-side recorder that logs a session
to disk and exports it as CSV.

**Spectrum.** Center, span, RBW, reference level and attenuation, with a live trace and peak
marker.

**Sources.** Power supply, function generator and electronic load. Before anything can be
energized you declare the DUT's maximum voltage and current. The safety verdict updates as you
type. Enabling an output needs the confirm checkbox, and the protective limits are written and
read back first. Output OFF is always available and never gated.

**Parts.** Offline catalog search, with live Nexar results when `NEXAR_CLIENT_ID` and
`NEXAR_CLIENT_SECRET` are in the environment, and Digi-Key when its credentials are entered on
the Connections tab.

**KiCad.** Paste a `.kicad_sch` and get components, nets and detected circuit patterns.

**Calculators.** Twenty in the UI, two more on the API. Resistor divider with E24 snapping, LC
low-pass, L-match, microstrip impedance, decoupling advisor, LED series resistor, RC and RL
time constants, LC resonance, op-amp gain both ways, IPC-2221 trace width, junction
temperature, 555 astable, ADC resolution, dBm conversion, current-sense shunt, capacitor
energy, buck duty cycle and antenna wavelength.

**RTL / HDL, Programmer, LabVIEW, CAN, Logic, STM32.** Each detects the tools it needs and
tells you what is missing rather than failing. See chapters
[5](tutorial/05-rtl-fpga.md) and [6](tutorial/06-labview-setup-mcp.md).

**System and Connections.** Instrument overview, the agent bridge, and the config block for
pointing an external MCP client at the bench.

**Assistant drawer.** The in-app chatbox on the right. Collapse it to a rail with the chevron
in its header when you want the width back; the choice is remembered across launches. Set
`ANTHROPIC_API_KEY` in the backend environment and restart to enable it. Default model is
`claude-sonnet-4-6`, overridable with `ECE_SUITE_MODEL`. Without a key the drawer says so
instead of failing on send.

## What the app will not do

No source output turns on unless all four of these hold: a DUT envelope is declared, the
requested level sits inside both that envelope and the instrument's own rating, the protective
limits were written and read back, and you ticked confirm. If any step fails, the run rolls
back with the output forced off.

Nothing is presented as a measurement unless it is tagged `VERIFIED_HW`. The assistant sees
the tag on every reading it is given, and no tool it can reach is able to energize a DUT.

Native `:AUToScale` is not used. It commands the instrument to change its own front end,
which invalidates the attenuation and coupling values the safety check was based on.

## Auto-connecting at startup

Set these before launching to skip the manual connect:

```
ECE_SUITE_SCOPE_RESOURCE=TCPIP0::192.168.0.50::inst0::INSTR
ECE_SUITE_DMM_RESOURCE=USB0::0x2A8D::0x1234::MY51234567::INSTR
```

Roles are `SCOPE`, `DMM`, `SA`, `PSU`, `AWG` and `ELOAD`. A failed auto-connect is written to
the audit log and leaves that role disconnected; it does not stop the app from starting.

## Where the app writes

Everything lands under `~/.ece-suite`, or wherever `ECE_SUITE_DATA` points:

- `audit.log.jsonl`, append-only, one line per instrument operation.
- DMM recorder sessions.
