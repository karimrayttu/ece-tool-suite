# Bench Instruments

[← Architecture & Core Concepts](02-architecture.md) · [Index](01-getting-started.md) · [Power Design Suite →](04-power-design.md)

The bench half of the suite drives real Keysight-class instruments over VISA. There is no simulator in the runtime path: every tab talks to a `VisaTransport` behind a named **role** (`scope`, `dmm`, `sa`, `psu`, `awg`, `eload`), and every reading carries a provenance label (`UNVERIFIED_HW` until the verification gate promotes the connection to `VERIFIED_HW`).

> **Hardware required.** Everything in this section needs a physical instrument reachable over USB (USBTMC), LAN (VXI-11 / HiSLIP / raw socket :5025), serial, or GPIB. LAN works with the bundled pure-Python `pyvisa-py` backend alone; USB needs either a system VISA (Keysight IO Libraries, NI-VISA) or `pyusb`+libusb. The app detects the gap and offers the download link itself (see IoWatcher below).

### Architecture: one transport per role

`backend/ece_suite/instruments/transport.py` defines the only interface drivers ever see:

```python
class VisaTransport(Transport):
    def __init__(self, resource, *, backend="auto", timeout_ms=5000, ...):
        # pyvisa instrument handles are NOT thread-safe: two threads issuing write/read on the
        # same handle corrupt command/response framing. Serialize every I/O call on this
        # transport so concurrent callers (e.g. a WS stream + the chatbox/agent) can't interleave.
        self._io_lock = threading.Lock()
        self.default_provenance = Provenance.UNVERIFIED_HW
        # "auto": prefer the system VISA (Keysight IO Libraries / NI-VISA), fall back to the
        # pure-Python pyvisa-py backend. This handles both USB (USBTMC) and LAN (LXI).
        candidates = ["", "@py"] if backend == "auto" else [backend]

    def promote_to_verified(self) -> None:
        self.default_provenance = Provenance.VERIFIED_HW

    def query(self, cmd: str) -> str:
        with self._io_lock:                 # write+read held together: atomic query
            return self._inst.query(cmd)
```
*`backend/ece_suite/instruments/transport.py`*

One class wraps pyvisa with an internal lock so a streaming websocket and the AI chatbox can hit the same instrument without corrupting SCPI framing, and with an instance-level provenance flag that starts pessimistic (`UNVERIFIED_HW`) and can only be raised by the gate. The `"auto"` backend tries system VISA first, then `pyvisa-py`, so LAN instruments work with zero vendor installs.

`InstrumentManager` (`instruments/manager.py`) is the single source of truth for "what is behind `scope` right now": `connect_visa(role, resource)` swaps in a fresh transport (closing the old one), `disconnect(role)` closes it, `verify(role)` runs the gate, and `status()` feeds the `/health` payload every tab's connection badge reads.

### Connecting an instrument

There are three ways in, and every instrument tab has all of them via the shared `ConnectionBar` (`apps/renderer/src/components/ConnectionBar.tsx`).

![The Connections tab listing six bound roles with identity, state and per-role actions, above the add-by-address form and the Interactive IO console](img/connections.png)
*The Connections tab acting as a connection expert for the bench. The inventory reads "6 connected" and each role (Scope, Dmm, Sa, Psu, Awg, Eload) carries its identity string, serial and firmware, its provenance state, and Verify / Disconnect actions. Below it: the add-by-address form, and the Interactive IO console with its raw-SCPI warning banner.*

**1. Discover.** `GET /api/visa/resources` lists everything both VISA backends can see, probing each with a 1.5 s `*IDN?`. The ConnectionBar puts the results in a datalist; pick one and hit Connect.

**2. By address.** Type a host and pick an interface; the backend turns it into a VISA resource string:

```python
def build_visa_resource(host: str, interface: str, port: int | None = None) -> str:
    iface = (interface or "lan").lower()
    if iface in ("lan", "vxi11", "vxi-11", "instr"):
        return f"TCPIP0::{host}::inst0::INSTR"
    if iface in ("socket", "raw", "scpi-raw"):
        return f"TCPIP0::{host}::{port or 5025}::SOCKET"
    if iface in ("hislip", "hs"):
        return f"TCPIP0::{host}::hislip0::INSTR"
    if iface == "serial":
        return f"ASRL{host.replace('COM', '') or host}::INSTR" ...
    if iface == "gpib":
        return f"GPIB0::{host}::INSTR"
    return host   # usb / pre-formed resource passes through
```
*`backend/ece_suite/main.py`*

This mirrors Keysight Connection Expert's interface choices so you can type `192.168.0.10` or `COM3` instead of a full VISA resource. USB expects the full `USB0::0x2A8D::…::INSTR` string (get it from Discover).

**3. Auto-connect.** `POST /api/io/autoconnect` enumerates every VISA resource (plus mDNS/LXI hosts when called with `lan=1`), identifies each one, classifies its bench role by model prefix, and connects any role that's still free:

```python
idn_raw, fluke_model = _probe_idn(rm, res)      # *IDN?, falling back to Fluke-28x "ID"
idn = parse_idn(idn_raw)
model = fluke_model or idn.model
role = "dmm" if fluke_model else classify_role(model)
vendor = canonical_vendor(idn.vendor)
if role and role in manager.roles() and not manager.connected(role):
    t = manager.connect_visa(role, res, backend=rm_backend or "auto")
    t._vendor = vendor
```
*`backend/ece_suite/main.py`, `io_autoconnect`*

`classify_role` in `instruments/vendors.py` maps model families to roles: `DSO/MSO/DPO/TDS/SDS/DHO/EDUX → scope`, `3446x/8845/8846/8808/287/289/SDM → dmm`, `N90xx/CXA/EXA/FSV/SSA → sa`, `E36xx/SPD/DP8 → psu`, `335xx/AFG/DG/SDG → awg`, `EL34/IT85/SDL/DL30 → eload`. LAN discovery (`io_env.discover_lan`) browses the `_scpi-raw`, `_lxi`, `_vxi-11`, and `_hislip` mDNS service types via zeroconf and returns ready-to-open resource strings; it's opt-in (the button passes `lan=1`) because the multicast sweep takes ~1.5 s.

**Plug-and-play watcher.** `IoWatcher.tsx` mounts globally, polls `GET /api/io/environment` every 5 s, and auto-connects the moment a plugged-in instrument becomes drivable. The backend side (`io_env.py`) reads the Windows PnP tree (no VISA needed) and recognizes an instrument two ways: a known test-equipment VID (`vendors.VENDOR_VIDS`: Keysight 0x2A8D/0x0957, Tektronix 0x0699, Rigol 0x1AB1, Siglent 0xF4EC, …) or the vendor-agnostic USBTMC class signature:

```python
# USB Test & Measurement class: bInterfaceClass 0xFE, bInterfaceSubClass 0x03. Any instrument
# that speaks USBTMC advertises this in its compatible IDs, regardless of vendor.
_USBTMC_RE = re.compile(r"Class_FE&SubClass_03", re.IGNORECASE)
...
usb_instruments = detect_usb_instruments()
if usb_instruments and not usb_ok:
    name, url = SOFTWARE["keysight_io"]
    recommendations.append({
        "reason": f"USB instrument detected ({vendors}) but no VISA layer can talk USBTMC.",
        "software": name, "url": url,
        "alt": {"software": SOFTWARE["ni_visa"][0], "url": SOFTWARE["ni_visa"][1]},
    })
```
*`backend/ece_suite/io_env.py`*

If you plug in a scope before installing any VISA layer, the app shows a banner ("USB instrument detected but no VISA layer can talk USBTMC") with an Install button for Keysight IO Libraries (NI-VISA as the alternate). Once the layer appears, the same poll auto-connects, no restart needed. This detection path is Windows-only (it shells out to `Get-CimInstance Win32_PnPEntity`).

### The VERIFY gate: UNVERIFIED_HW → VERIFIED_HW

Connecting is not trusting. A connection stays `UNVERIFIED_HW` until `POST /api/instruments/{role}/verify` runs the lab-truth gate:

```python
# 1) *IDN?
raw = transport.query("*IDN?")
idn = parse_idn(raw)
if not idn.vendor or not idn.model:
    reasons.append("*IDN? response incomplete (missing vendor/model)")

# 2) read-back: the error queue must drain empty
errs = drain_error_queue(transport)
if errs:
    reasons.append(f"instrument error queue not empty: {errs}")

if not is_hardware:
    reasons.append("transport is SIMULATED — a simulator can never be VERIFIED_HW")

ok = is_hardware and not reasons
if ok:
    transport.promote_to_verified()
```
*`backend/ece_suite/verification.py`*

Promotion requires a live `*IDN?` with vendor and model, plus a clean `:SYST:ERR?` drain, meaning an instrument that acknowledged its identity and has no queued command rejections. The result is recorded in the audit log and the ConnectionBar badge flips from amber `UNVERIFIED_HW` to green `VERIFIED_HW`. Every waveform, reading, and trace frame carries this provenance value, so downstream consumers (dashboard, AI agent, exports) always know whether the data came from a verified instrument. Disconnecting a role destroys the transport, and with it the promotion; a reconnect starts back at `UNVERIFIED_HW`.

### Oscilloscope tab

![Scope tab running: a gate-drive PWM trace on CH1 with the measurement strip populated, plus the channel column and the Horizontal / Trigger / Acquire control groups](img/scope.png)
*Scope tab in RUN. CH1 shows a 2.5 kHz gate-drive waveform with the rising-edge ring visible, five periods across ten divisions at the 200 µs/div the header reports. The measurement strip underneath carries Vpp, Vampl, Vmax, Vmin, Vtop, Vbase, Vavg and Vrms, all read back from the instrument rather than computed in the browser. Channel controls sit on the right; Horizontal, Trigger and Acquire below.*

`ScopeTab.tsx` renders a Keysight-style front panel: a 10×8 graticule canvas fed by `/ws/scope` at 5 Hz, four channel buttons (click = select, double-click = on/off), and three control groups. Channel knobs live-apply (change a value, it writes immediately); Horizontal/Trigger/Acquire apply on their group button. Everything funnels through `POST /api/scope/config`, which fans out to the driver's setters.

Control-to-SCPI mapping (Keysight dialect, `instruments/keysight.py`; every vendor except Tektronix uses this):

| UI control | Driver call | SCPI (Keysight/SCPI-1999) | SCPI (Tektronix) |
|---|---|---|---|
| CH display | `set_channel(enabled=)` | `:CHANn:DISP 1/0` | `SELect:CHn ON/OFF` |
| V/div | `set_channel(scale=)` | `:CHANn:SCAL x` | `CHn:SCAle x` |
| Offset | `set_channel(offset=)` | `:CHANn:OFFS x` | `CHn:OFFSet x` |
| Coupling DC/AC | `set_channel(coupling=)` | `:CHANn:COUP DC` | `CHn:COUPling DC` |
| Probe × | `set_channel(probe=)` | `:CHANn:PROB 10` | `CHn:PRObe:GAIN 0.1` (gain = 1/atten) |
| BW limit / Invert | `set_channel(bwlimit=/invert=)` | `:CHANn:BWL` / `:CHANn:INV` | `CHn:BANdwidth TWEnty` / `CHn:INVert` |
| s/div, position | `set_timebase()` | `:TIM:SCAL` / `:TIM:POS` | `HORizontal:SCAle` / `HORizontal:DELay:TIMe` |
| Trigger source/slope/level | `set_trigger()` | `:TRIG:EDGE:SOUR/SLOP/LEV` | `TRIGger:A:EDGE:SOUrce/SLOpe`, `TRIGger:A:LEVel` |
| Sweep AUTO/NORM, holdoff | `set_trigger()` | `:TRIG:SWE`, `:TRIG:HOLD` | `TRIGger:A:MODe`, `TRIGger:A:HOLDoff:TIMe` |
| Acquire type/averages/points | `set_acquisition()` | `:ACQ:TYPE/:ACQ:COUN/:WAV:POIN` | `ACQuire:MODe/NUMAVg`, `HORizontal:RECOrdlength` |
| Run / Stop / Single | `run()/stop()/single()` | `:RUN` / `:STOP` / `:SINGle` | `ACQuire:STATE` + `STOPAfter` |

Vendor routing is automatic: `make_scope` (`scope_drivers.py`) reads `*IDN?` once, caches the dialect on the transport, and returns `TektronixScope` for Tek or the Keysight driver for Keysight/Rigol/Siglent/R&S/GW-Instek (they share InfiniiVision-style SCPI for these operations). The Tek capture path handles a real-world trap:

```python
def capture(self, ch: int = 1) -> Waveform:
    self.t.write(f"DATa:SOUrce CH{ch}")
    self.t.write("DATa:ENCdg RIBinary")  # signed integer, MSB first
    self.t.write("DATa:WIDth 2")
    self.t.write("DATa:STARt 1")
    # DATa:STOP is a persistent setting that does NOT track the record length; without
    # setting it the CURVe? transfer is silently truncated to a stale value. Pull the full
    # acquired record.
    rec = int(_safe_float(self.t.query("HORizontal:RECOrdlength?")) or 0)
    if rec > 0:
        self.t.write(f"DATa:STOP {rec}")
    payload = _parse_ieee_block(self.t.query_raw("CURVe?"))
    codes = np.frombuffer(payload, dtype=">i2").astype(np.float64)
    v = (codes - yoff) * ymult + yzero
```
*`backend/ece_suite/instruments/scope_drivers.py`, `TektronixScope.capture`*

Tek's `DATa:STOP` persists across record-length changes, so a naive `CURVe?` silently returns a truncated waveform. The driver re-pins it to the live record length on every capture, then scales the raw 16-bit codes with the `WFMOutpre` preamble values. The Keysight equivalent uses `:WAV:PRE?` + `:WAV:DATA?` (WORD, LSB-first) decoded in `preamble.py`.

**Auto Setup is bounded, never native.** The Auto Setup button calls `POST /api/scope/bringup`, a guided sequence (identify → `*RST`+`*CLS` → verify gate → bounded autoset → capture). `bounded_autoset` computes V/div and s/div from the *expected* signal (`vdiv = snap125(vpp/6)`, `tdiv = snap125(3 periods / 10 div)`) and is evaluated by the safety engine against the scope's live front end (probe attenuation, coupling and input impedance, which is what separates a 5 V abs-max at 50 Ω from 300 V at 1 MΩ). The instrument-native `:AUToScale` is a hard BLOCK in any automated path, because it can slam a 50 Ω front end into an overrange signal.

**Measurements.** The measurement strip under the graticule polls `GET /api/scope/measure` (1 Hz, active channel): the full 16-item InfiniiVision set (Vpp, Vampl, Vmax/Vmin, Vtop/Vbase, Vavg, Vrms, Freq, Period, Duty, ±Width, Rise, Fall, Overshoot) via `:MEAS:VPP?` etc. (Tek: `MEASUrement:IMMed:TYPe PK2pk…` per key). Keysight's ~9.9E37 "invalid" sentinel is filtered to `null`. The 5 Hz WS frame only carries the light 6-measurement set per displayed channel to keep streaming cheap on real hardware.

### Multimeter tab

![DMM tab reading 3.299 V DC, with min/max/average beneath the readout and the server-log controls below](img/dmm.png)
*DMM tab on VDC. The large mint-green readout shows 3.299 V with the dialect it came from underneath, and min, max and average track alongside it. Function keys run across the top, range, NPLC, math and auto-zero below them, then the auto-setup chips. The server-side recorder is idle at 0 records until you press Start recording.*

`DmmTab.tsx` gives one-click function keys (V⎓ V∼ A⎓ A∼ Ω 4WΩ Hz F ▷| •)))), range/NPLC/math/auto-zero fields, a large live readout fed by `/ws/dmm` (2.5 Hz), a trend chart, and min/max/avg stats. `POST /api/dmm/config` maps to:

| UI | SCPI dialect (Keysight Truevolt, Fluke 8845/8846) | Fluke 45/8808A legacy | Fluke 287/289 handheld |
|---|---|---|---|
| Function | `:CONF:VOLT:DC` (+range) | `VDC` / `VAC` / `ADC` / `OHMS`… | n/a; rotary switch on the meter |
| NPLC | `:SENS:<fn>:NPLC x` (DC fns only) | ignored | n/a |
| Auto-zero | `:SENS:<fn>:ZERO:AUTO 1/0` | ignored | n/a |
| Math Null/dB/dBm | `:CALC:FUNC NULL` + `:CALC:STAT ON` | ignored | n/a |
| Read | `:READ?` | `MEAS?` | `QM` (primary display value+unit) |

The dialect is chosen once per connection by `make_dmm` (`instruments/dmm.py`) and cached on the transport. Fluke 8845A/8846A speak the HP 34401 SCPI set, so they use the same driver as Keysight; the Fluke 45/8808A get the legacy driver; and the 287/289 handhelds, which don't answer `*IDN?` at all, are caught by a fallback probe:

```python
if not idn_ok:
    # No *IDN? — could be a Fluke 28x handheld, which answers "ID".
    try:
        resp = transport.query("ID").upper()
        if "FLUKE" in resp and ("287" in resp or "289" in resp or "28X" in resp):
            _cache_dialect(transport, "fluke-28x")
            return Fluke28xDmm(transport)
    except Exception:
        pass
dialect = "fluke-legacy" if _is_fluke_legacy(vendor, model) else "scpi"
```
*`backend/ece_suite/instruments/dmm.py`, `make_dmm`*

The 28x handhelds use a short serial protocol over the IR cable: `ID` for identity, `QM` for whatever the primary display shows. There is no remote function configuration; the driver parses the value and unit out of the `QM` reply (`QM,+1.23456E+0,VDC,NORMAL,NONE`) and reports whatever the rotary switch selected. The same `ID` probe runs inside auto-connect's `_probe_idn` on serial resources, so a plugged-in 287 auto-assigns to the `dmm` role.

### Spectrum analyzer tab

![Spectrum tab with a live trace: a tone at the centre frequency above the noise floor, peak marker read out below the grid](img/sa.png)
*Spectrum tab streaming. A single tone sits at the centre frequency above a flat noise floor, drawn as a violet trace with a gradient fill, and the peak marker under the grid reads 100.000 MHz @ -20.00 dBm. Trace mode, detector and preamp controls sit below, then centre, span, RBW, VBW, reference level, attenuation and averaging.*

`SaTab.tsx` streams `/ws/sa` at 2 Hz: each frame is a full `:TRAC? TRACE1` ASCII trace plus a `marker → peak` search (`:CALC:MARK:MAX` then `:CALC:MARK:X?/Y?`). Trace-mode buttons and the detector/preamp controls live-apply; the numeric fields apply as a group. `POST /api/sa/config` (Keysight X-series SA mode) maps:

| UI control | SCPI |
|---|---|
| Center / Span / Start / Stop | `:FREQ:CENT` / `:FREQ:SPAN` / `:FREQ:STAR` / `:FREQ:STOP` |
| RBW (+auto) / VBW (+auto) | `:BAND` (`:BAND:AUTO`) / `:BAND:VID` (`:BAND:VID:AUTO`) |
| Ref level / Atten / Preamp | `:DISP:WIND:TRAC:Y:RLEV` / `:POW:ATT` / `:POW:GAIN` |
| Sweep points / Averages | `:SWE:POIN` / `:AVER:COUN` |
| Trace mode WRITE/MAXHOLD/MINHOLD/AVERAGE | `:TRAC1:TYPE WRIT/MAXH/MINH/AVER` |
| Detector NORM/POS/NEG/SAMP/AVER/RMS | `:DET x` |

The frequency axis is reconstructed server-side: the backend queries center and span and linspaces across the trace length, so the CSV export has real Hz values.

### Sources tab: the safety-gated path

![Sources tab, PSU panel: analog measured-voltage meter, setpoint and OVP/OCP fields, DUT envelope declared, and a REQUIRE_CONFIRM verdict next to the unticked Confirm-energize box](img/source.png)
*Sources tab, Power Supply panel. The analog meter and current readout report the measured output, which is zero because the output is still off. Vset and Ilim knobs read 3.3 V and 0.5 A, with OVP 3.6 V, OCP 0.6 A and a DUT envelope of 3.6 V / 0.6 A declared underneath. The verdict badge reads REQUIRE_CONFIRM: the request is inside the envelope and the rating, so the only thing left is the Confirm energize tick, which is still unticked. Output OFF is never gated.*

The Sources tab (`SourcesTab.tsx`) hosts three sub-panels (Power Supply, Function Gen, Electronic Load), and none of them can touch an output directly. Every apply goes through the **preview → confirm → transactional run** pipeline built on `SafetyInvariantEngine` (`safety.py`) and `PresetRunner` (`presets.py`).

**Preview verdicts.** As you type, the panel calls `POST /api/psu/preview` (or `/awg/`, `/eload/`) on every field change. The engine evaluates each planned step and returns `ALLOW`, `REQUIRE_CONFIRM`, or `BLOCK` (most-restrictive-wins), with cited reasons. The badge updates live, and the Enable button is disabled unless `ok_to_run` *and* the "Confirm energize" checkbox is ticked.

**The DUT envelope is default-deny.** A source operation without a declared device-under-test envelope is blocked outright; there is no safe default:

```python
# 2) Default-deny: any source op needs a declared DUT envelope.
if is_source and action.op in (OpType.SET_LEVEL, OpType.ENABLE_OUTPUT):
    if envelope is None:
        findings.append((Verdict.BLOCK,
            "SOURCE_CONTROL is default-denied until a DUT SafetyEnvelope is declared"))

# 3) Set-level must be within BOTH the DUT envelope and the instrument rating.
if v is not None and envelope is not None:
    if v > envelope.max_voltage:
        findings.append((Verdict.BLOCK,
            f"voltage {v} V exceeds DUT envelope max {envelope.max_voltage} V"))
...
# 4) Enabling an output energizes the DUT -> always needs explicit human confirm.
if is_source and action.op is OpType.ENABLE_OUTPUT:
    findings.append((Verdict.REQUIRE_CONFIRM,
        "enabling an output energizes the DUT; explicit human confirmation required"))
```
*`backend/ece_suite/safety.py`, `SafetyInvariantEngine.evaluate`*

The panel's "DUT max V / DUT max I" fields aren't decoration; they become a `DUTSafetyEnvelope` that every setpoint is checked against, alongside the instrument's own `RatingModel`. `ENABLE_OUTPUT` always demands human confirmation regardless of levels. The engine is deliberately a *secondary* guard: the instrument's hardware OVP/OCP is the real protection, which is why the runner forces those to be programmed and verified first.

**Transactional apply with ordering + rollback.** `POST /api/psu/apply` builds an ordered step list (OVP, OCP, Vset, Ilim, then output-enable *last*) and hands it to `PresetRunner.run`. The runner rejects any plan where enable isn't last or protection isn't set beforehand, then executes step-by-step: safety-evaluate → write → drain `:SYST:ERR?` (must be empty) → verify-read the value back within tolerance. Any failure aborts:

```python
def _abort(self, results, prov, *, reason: str) -> PresetResult:
    # rollback: unconditional output-off FIRST, no matter what
    try:
        self.t.write(self.output_off_scpi)
        drain_error_queue(self.t)
    except Exception:  # rollback must never raise
        pass
    self._audit("preset_rollback", instrument=self.instrument, reason=reason)
    return PresetResult(False, prov, results, True, f"ABORTED + rolled back: {reason}")
```
*`backend/ece_suite/presets.py`, `PresetRunner._abort`*

Whether the failure is a blocked verdict, a missing confirm, an instrument error after a write, or a verify-read mismatch, the very first rollback action is an unconditional `:OUTP OFF` (`:INP OFF` for the load): the DUT is de-energized before anything else, and the whole event is audit-logged.

**Per-source step lists** (`main.py`): the PSU programs `:VOLT:PROT` / `:CURR:PROT` / `:VOLT` / `:CURR` / `:OUTP ON`. The AWG first sets `:VOLT:LIMIT:HIGH/LOW` to ±(|offset| + Vpp/2) and enables `:VOLT:LIMIT:STAT ON` before shape (`:FUNC`), frequency, offset, amplitude, and `:OUTP ON`. Its safety param is the computed *peak*, not Vpp. The e-load sets `:CURR:PROT`, `:FUNC CURR/VOLT/RES/POW` (CC/CV/CR/CP), the level, and `:INP ON` last. Each panel also has an always-available **Output OFF** button (`POST /api/psu/off` etc.) that writes output-off directly, with no gates in the way: the software emergency stop.

The instrument `RatingModel`s are currently hard-coded in `main.py` (PSU 30 V/5 A, AWG ±10 V, e-load 150 V/30 A), matched to an E36xx-class bench; adjust them if your source is bigger.

### Auto-setup presets

`presets_library.py` defines 13 one-click presets, surfaced by `PresetButtons` on the scope/DMM/SA tabs and listed by `GET /api/presets`: scope I²C debug, power-rail ripple (AC-coupled 20 mV/div), UART capture, PWM/gate-drive; DMM DC rail, diode, continuity, current; SA 2.4 GHz band, harmonics, spur hunt; and two PSU bring-up presets (3V3, 5V) that require an envelope + confirm and live behind the same PresetRunner. Measurement presets are CONFIGURE-only and preview as ALLOW; every step with a `verify_query` is read back after write. `POST /api/presets/{pid}/preview` and `/apply` use the exact same machinery as the source panels.

### Streaming, logging, export, screenshots

**Websockets.** Each tab opens a role websocket; the server loop snapshots the instrument in a worker thread (`asyncio.to_thread`) so slow SCPI never blocks the event loop, and pushes `{"connected": false}` frames when the role is empty:

| WS endpoint | Rate | Frame contents |
|---|---|---|
| `/ws/scope` | 5 Hz | per displayed channel: `t[]`, `v[]`, meta (points, Vpp), 6 quick measurements; provenance |
| `/ws/dmm` | 2.5 Hz | value, unit, function, dialect, provenance (feeds the server recorder when logging) |
| `/ws/sa` | 2 Hz | `freqs[]`, `amps[]`, center, span, peak marker, provenance |
| `/ws/psu` | 2.5 Hz | Vset/Iset (`:VOLT?`/`:CURR?`), measured V/I (`:MEAS:VOLT?`/`:MEAS:CURR?`), `output_on` |
| `/ws/awg` | 2.5 Hz | func, freq, Vpp, offset, `output_on` |
| `/ws/eload` | 2.5 Hz | mode, level, OCP, measured V/I, `input_on` |

The Workbench tab (`WorkbenchTab.tsx`) opens the scope, DMM, and SA sockets simultaneously in mini-cards: three instruments streaming at once, each with its own ConnectionBar, plus an "Auto-connect all" button that calls autoconnect with LAN discovery on.

![Workbench with three minis streaming: scope, multimeter and spectrum cards, each with its own ConnectionBar](img/workbench.png)
*Workbench with all three minis live at once: the scope trace, the multimeter readout and the spectrum trace, each card carrying its own ConnectionBar so roles can be brought up independently. The "Auto-connect all" button sits at the top right.*

**CSV export** exists in two flavors. Client-side: each tab's Export CSV button snapshots what the browser has buffered (scope: `time_s, ch1_v, …` from the last frame; DMM: every WS reading with ISO + elapsed timestamps; SA: `freq_hz, amp_dbm`). Server-side: the `Recorder` (`datalog.py`) is a thread-safe per-role buffer fed by the WS loop itself, so a long DMM soak keeps recording while you navigate to other tabs. Controlled by `POST /api/log/dmm/start|stop|clear`, polled via `/status`, exported as a CSV attachment via `GET /api/log/dmm/export`.

**Instrument screenshots.** `GET /api/{role}/screenshot` (scope and sa only) pulls the instrument's own front-panel image (`:DISPlay:DATA? PNG,COLor` on the scope, `:DISP:DATA?` on the SA), strips the IEEE-488.2 block header, validates the PNG signature, and returns `image/png`. The `ScreenshotButton` shows it inline with a Save PNG option. This is the real screen of the real instrument, distinct from the canvas "Save PNG" which renders the app's own plot.

### Connections tab

The Connections tab is the bench-wide Connection Expert: a role inventory table (vendor, model, serial, firmware from `GET /api/io/details/{role}`, address, provenance state, per-row Verify/Disconnect), Discover and Auto-connect-all buttons, the add-by-address form for all six interface types, and two power tools:

- **Interactive IO.** A raw SCPI console against any connected role via `POST /api/io/scpi`, with quick-command chips (`*IDN?`, `*RST`, `:SYST:ERR?`, …). It is deliberately a direct passthrough that bypasses the safety gates (same contract as Keysight Interactive IO); the UI shows a warning banner and every command is audit-logged with its provenance.
- **AI control (MCP server).** `GET /api/mcp/info` returns a ready-to-paste MCP client config so Claude Desktop / Claude Code can drive the connected bench as tools; the tab lists the exposed tool names and offers one-click copy.

### Endpoint reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | version, per-role status, provenance, any-hardware-verified |
| GET | `/api/visa/resources` | list VISA resources on both backends, with `*IDN?` probe |
| GET | `/api/io/backends` | which VISA implementations load (system / pyvisa-py) |
| GET | `/api/io/environment` | plug-and-play assessment: backends, USB instruments, install recommendations |
| POST | `/api/io/autoconnect?lan=1` | discover + identify + classify + connect free roles (mDNS opt-in) |
| GET | `/api/io/details/{role}` | full identity (vendor/model/serial/fw) + connection info |
| POST | `/api/io/scpi` | raw SCPI write/query passthrough (audit-logged, ungated) |
| POST | `/api/instruments/{role}/connect` | connect by resource string or `{host, interface, port}` |
| POST | `/api/instruments/{role}/verify` | run the lab-truth gate; promotes to VERIFIED_HW |
| POST | `/api/instruments/{role}/disconnect` | close the transport |
| POST | `/api/scope/config` | channels / timebase / trigger / acquisition / run-state |
| GET | `/api/scope/measure?ch=n` | full 16-measurement set for one channel |
| POST | `/api/scope/bringup` | guided bring-up: identify → reset → verify → bounded autoset → capture |
| POST | `/api/dmm/config` | function / range / NPLC / math / auto-zero |
| GET | `/api/dmm/read` | one reading (for REST/MCP callers without the WS) |
| POST | `/api/sa/config` | freq / BW / amplitude / trace / detector / averaging |
| GET | `/api/{role}/screenshot` | instrument front-panel PNG (scope, sa) |
| POST | `/api/psu/preview` · `/apply` · `/off` | safety preview / transactional apply / unconditional output-off |
| POST | `/api/awg/preview` · `/apply` · `/off` | same, function generator |
| POST | `/api/eload/preview` · `/apply` · `/off` | same, electronic load (`:INP OFF`) |
| GET | `/api/presets` | preset catalog with envelope/confirm requirements |
| POST | `/api/presets/{pid}/preview` · `/apply` | dry-run verdicts / transactional run |
| POST | `/api/log/{role}/start` · `stop` · `clear` | server-side session recorder control |
| GET | `/api/log/{role}/status` · `export` | record count / CSV download |
| WS | `/ws/scope` `/ws/dmm` `/ws/sa` `/ws/psu` `/ws/awg` `/ws/eload` | live streaming frames (rates above) |

---
[← Architecture & Core Concepts](02-architecture.md) · [Power Design Suite →](04-power-design.md)
