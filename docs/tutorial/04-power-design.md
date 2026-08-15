# Power Design Suite

[← Bench Instruments](03-instruments.md) · [Index](01-getting-started.md) · [RTL / HDL & FPGA →](05-rtl-fpga.md)

The Power Design Suite is the design-side half of the app: everything here runs offline math or headless simulation, no bench hardware involved. It spans three sidebar tabs:

| Tab key | Component | What lives there |
|---|---|---|
| `stm32` | `apps/renderer/src/components/Stm32Tab.tsx` | Tool detection/launch, CubeMX `.ioc` editor, the power supply designer (auto-design, SPICE verify, loop margin, magnetics, capacitor bank), Digi-Key WEBENCH adapter |
| `circuit` | `apps/renderer/src/components/CalculatorsPanel.tsx` | The 20 design calculators |
| `parts` | `apps/renderer/src/components/PartsPanel.tsx` | Parts search with normalized parametric specs |

The pipeline is deliberately staged: **size → verify the power stage in SPICE → verify the loop with python-control → pick the magnetics → size the caps**. Each stage returns explicit PASS/FAIL checks and an honesty note about what it did *not* model.

![The STM32 & Tools tab: the design-tool grid, the .ioc card, and the power supply designer with a completed buck design](img/stm32.png)
*The STM32 & Tools tab after Auto-design on a 12 V to 3.3 V, 2 A, 500 kHz buck. Top to bottom: the design-tool grid reporting 9 of 11 tools found on this PC, the `.ioc` card, and the designer's result: the topology decision with its reason, five candidate TI parts, a type-II compensation starting point (fc 50 kHz, Rc 1179 Ω, Cc1 6.37 nF, Cc2 539.8 pF), and the sized L and Cout ready for the SPICE verification step below.*

### Design-tool detection and launch

`backend/ece_suite/design_tools.py` keeps a catalog of glob patterns for the tools an EE workstation typically has (CubeMX, CubeProgrammer, CubeIDE, CubeCLT, TI Power Stage Designer, UniFlash, CCS, KiCad, Altium, LTspice, ngspice) and resolves them on disk:

```python
# backend/ece_suite/design_tools.py
def detect_tools() -> list[dict]:
    """Which design tools are installed on this PC (path + launchable)."""
    out: list[dict] = []
    for tid, (name, kind, paths) in _CANDIDATES.items():
        path = _resolve(paths)
        out.append({"id": tid, "name": name, "kind": kind,
                    "installed": bool(path), "path": path,
                    "launchable": bool(path and path.lower().endswith((".exe", ".lnk")))})
    return out


def launch_tool(tool_id: str) -> dict:
    """Open an installed tool the way a double-click would (.exe/.lnk)."""
    match = next((t for t in detect_tools() if t["id"] == tool_id), None)
    if not match or not match["installed"]:
        return {"ok": False, "error": f"{tool_id} is not installed"}
```

Every tool gets reported whether installed or not, so the UI can render the full grid with "not found" badges instead of silently hiding gaps. Launching goes through `shell_open.open_path`, which is `os.startfile` on Windows and `open` / `xdg-open` elsewhere, so both `.exe` and `.lnk` work: TI Power Stage Designer, for example, is often only reachable through its Start-menu shortcut. The detection paths in `_CANDIDATES` are Windows install locations, so on other platforms the grid honestly reports everything as not found.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/tools/detect` | GET | List all catalog tools with `installed`/`launchable`/`path` |
| `/api/tools/launch/{tool_id}` | POST | Launch an installed tool (audited) |

### CubeMX `.ioc` parse and edit

A CubeMX project file is a flat `key=value` properties file, so the backend parses it directly, with no CubeMX needed for reading or editing:

```python
# backend/ece_suite/design_tools.py
_PIN_RE = re.compile(r"^(P[A-Z]\d+)\.(\w+)$")
_TIM_RE = re.compile(r"^(TIM\d+)\.(.+)$")
_IP_RE = re.compile(r"^Mcu\.IP\d+$")

def apply_ioc_edits(text: str, edits: dict[str, str | None]) -> str:
    """Return a new .ioc text with edits applied. edits={key: value}; value None deletes the key;
    new keys are appended. Existing line order is preserved."""
    remaining = dict(edits)
    out: list[str] = []
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in remaining:
                val = remaining.pop(k)
                if val is None:
                    continue  # delete
                out.append(f"{k}={val}")
                continue
        out.append(line)
```

`parse_ioc` buckets keys into pins (`PA5.Signal`, `PA5.GPIO_Label`, …), timers (`TIM3.Prescaler`, …) and enabled peripherals (`Mcu.IPn`), which drives the pin/mux table and timer editors in the UI. `apply_ioc_edits` is a line-preserving rewrite: untouched keys keep their exact position and text, so CubeMX can reopen the file without complaint. The frontend never writes the file in place: `saveIoc()` downloads a modified copy, and the UI note tells you to open it in CubeMX and regenerate code. Editing is honest key-value surgery, not a CubeMX reimplementation.

| Endpoint | Method | Body | Purpose |
|---|---|---|---|
| `/api/ioc/parse` | POST | `{text}` | Parse `.ioc` into MCU, pins, peripherals, timers |
| `/api/ioc/edit` | POST | `{text, edits}` | Apply `{key: value|null}` edits, return new text |

### Auto-design flow (WEBENCH-class, offline)

`backend/ece_suite/power_designer.py` reproduces WEBENCH's *design math* natively: topology recommendation → candidate TI parts → passive sizing → type-II compensation. Its own docstring is explicit that it is not TI's optimizer or full part database.

**Topology recommendation.** Isolation cannot be inferred from Vin/Vout/Iout, so it is an explicit checkbox (`isolated`) in the UI:

```python
# backend/ece_suite/power_designer.py
def recommend_topology(vin: float, vout: float, iout: float, isolated: bool = False) -> dict:
    if isolated:
        pout = vout * iout
        return {"topology": "flyback", "reason": f"Galvanic isolation requested: flyback suits "
                f"{pout:.1f} W (transformer sets Vout via turns ratio; primary-side or opto feedback)."}
    if vout < vin * 0.9:
        dropout_w = (vin - vout) * iout
        if (vin - vout) <= 3.0 and iout <= 1.0 and dropout_w <= 1.5:
            return {"topology": "ldo", "reason": f"Small drop ({vin - vout:.1f} V) at low current — an LDO is simpler; {dropout_w:.2f} W dissipated."}
        return {"topology": "buck", "reason": f"Vout ({vout} V) < Vin ({vin} V): step down with a buck."}
    if vout > vin * 1.1:
        return {"topology": "boost", "reason": f"Vout ({vout} V) > Vin ({vin} V): step up with a boost."}
    return {"topology": "buck-boost", "reason": f"Vin ({vin} V) straddles Vout ({vout} V): use a buck-boost."}
```

The linear-vs-switcher heuristic picks an LDO only when all three of drop ≤ 3 V, Iout ≤ 1 A and dissipation ≤ 1.5 W hold; otherwise the wasted watts justify a buck. A ±10 % band around Vin routes to buck-boost. `isolated=True` short-circuits everything to flyback, since that is the transformer topology the curated database covers.

**TI part candidates.** `TI_PARTS` is a curated list of 16 real TI power ICs (buck/boost/buck-boost/flyback/LDO) with approximate Vin/Vout/Iout envelopes: `TPS54560` (4.5–60 V in, 5 A buck), `LM5116` (100 V sync buck controller), `LM5180` (PSR flyback), and so on. `candidate_parts()` filters by topology and envelope; each hit carries `integrated_fet`, the note, and a `ti.com/product/<MPN>` datasheet link. The header comment says it plainly: *approximate spec envelopes; verify against the datasheet*. Note that per the project's parts-selection rule, distributor stock is never a criterion.

**Sizing.** `size_stage()` dispatches per topology. Buck and boost delegate to the CCM formulas in `design_tools.py`:

```python
# backend/ece_suite/design_tools.py
def buck_stage(vin: float, vout: float, iout: float, fsw_khz: float = 500.0,
               ripple_pct: float = 30.0, vf_diode: float = 0.0) -> dict:
    """Synchronous/async buck power-stage design (CCM)."""
    if not (0 < vout < vin):
        raise ValueError("require 0 < Vout < Vin")
    fsw = fsw_khz * 1e3
    d = (vout + vf_diode) / vin
    di = ripple_pct / 100.0 * iout
    L = (vout * (vin - vout)) / (vin * fsw * di) if di > 0 else float("inf")
    ipk = iout + di / 2.0
    cout = di / (8 * fsw * (0.01 * vout)) if vout > 0 else 0.0     # for 1% Vout ripple
    return {"topology": "buck", "duty_pct": round(d * 100, 2),
            "inductor_uH": round(L * 1e6, 3), "ripple_current_A": round(di, 4),
            "peak_current_A": round(ipk, 4),
            "output_cap_uF_for_1pct": round(cout * 1e6, 2),
            "note": f"CCM, fsw={fsw_khz} kHz, dIL={ripple_pct}% of Iout"}
```

Textbook CCM sizing: L from the volt-second balance for a chosen ripple percentage (default 30 % of Iout), Cout from the charge triangle for 1 % output ripple. Buck-boost sizing accounts for the inductor carrying `Iin + Iout`; flyback returns a DCM estimate (turns ratio from Dmax = 0.45, primary inductance from energy balance) plus a note to add a snubber. LDO "sizing" is a dropout + thermal check (`Tj = Ta + Pd·θJA`).

**Type-II compensation.** For buck/boost/buck-boost, `design()` appends a compensation starting point:

```python
# backend/ece_suite/power_designer.py: compensation()
    fc = fsw / 10.0
    fp_load = 1.0 / (2 * math.pi * rload * Cout)          # output pole (current-mode dominant)
    fz_esr = 1.0 / (2 * math.pi * esr * Cout) if esr > 0 else float("inf")
    # type-II: comp zero at fp_load, comp pole at fz_esr (or fsw/2), integrator for fc
    gm = gm_ea_uA_V * 1e-6
    rc = 1.0 / (gm) * (fc / max(fp_load, 1.0)) * 0.5      # scaled starting value
    rc = max(1e3, min(rc, 200e3))
    cc1 = 1.0 / (2 * math.pi * fp_load * rc)              # zero at load pole
    fp_hi = min(fz_esr, fsw / 2.0)
    cc2 = 1.0 / (2 * math.pi * fp_hi * rc) if fp_hi > 0 else 0.0
```

Classic current-mode type-II placement: crossover at fsw/10, compensator zero on the load pole, high-frequency pole on the ESR zero (or fsw/2, whichever is lower), assuming a transconductance error amp. Rc is clamped to a sane 1 kΩ–200 kΩ. The returned note is part of the contract: this is a *starting point* to refine against the controller datasheet or LTpowerCAD, and the achieved margin is checked by the loop verifier below, not assumed.

In the UI, **Auto-design** (`autoDesign()` in `Stm32Tab.tsx`) calls `/api/power/design`, adopts the recommended topology into the topology selector when it is buck or boost, and pre-fills the SPICE-verify L/Cout fields from the sizing, so the verify button one click later simulates exactly what the designer proposed. **Sizing only** (`computePower()`) runs just the buck/boost stage math.

| Endpoint | Method | Params | Purpose |
|---|---|---|---|
| `/api/power/design` | GET | `vin, vout, iout, fsw_khz, ripple_pct, isolated` | Full auto-design: topology + TI candidates + sizing + type-II comp |
| `/api/power/buck` | GET | `vin, vout, iout, fsw_khz, ripple_pct` | Buck CCM sizing only |
| `/api/power/boost` | GET | same | Boost CCM sizing only |
| `/api/power/webench` | GET | `vin_min, vin_max, vout, iout` | Pre-filled deep link into TI WEBENCH Power Designer |

**Honest note:** TI WEBENCH is an online-only proprietary service with no public API. `webench_url()` just builds `https://webench.ti.com/power-designer/switching-regulator?VinMin=…&VinMax=…&O1V=…&O1I=…`; the "Open in WEBENCH" button opens it in the external browser with ±10 % around your Vin.

### SPICE power-stage verification (PASS/FAIL)

`backend/ece_suite/spice_verify.py` is a verification method, not a simulation playground: it generates a self-contained switching netlist for the sized buck or boost, runs it headless, parses the `.raw`, and checks measured behaviour against targets.

**Engine detection.** LTspice is preferred (found via the tool catalog), ngspice is the fallback, including the copy KiCad bundles:

```python
# backend/ece_suite/spice_verify.py
def engines() -> list[dict]:
    """Available SPICE engines for verification (LTspice preferred, ngspice fallback)."""
    from . import design_tools
    lt = next((t["path"] for t in design_tools.detect_tools() if t["id"] == "ltspice" and t["installed"]), None)
    ng = shutil.which("ngspice") or shutil.which("ngspice_con")
    # KiCad bundles ngspice
    if not ng:
        import glob
        hits = glob.glob(r"C:\Program Files\KiCad\*\bin\ngspice.exe")
        ng = hits[-1] if hits else None
```

**What the netlist models.** The buck netlist is a synchronous stage with ideal switches (Ron), non-overlapping gate drives with dead-time, a freewheel diode so the dead-time interval has a current path, inductor DCR, cap ESR, and a behavioural current load that steps +50 % at 70 % of the run:

```python
# backend/ece_suite/spice_verify.py: buck_netlist()
    # loss-compensated duty so the open-loop stage settles near Vout (a real loop would do this);
    # covers DCR + switch Ron + the dead-time freewheel-diode drop.
    d_loss = iout * (dcr_mohm + ron_mohm) * 1e-3 + 0.4 * (2 * dt / T)
    D = min(0.95, (vout + d_loss) / vin)
    ...
    return f"""* buck power-stage verification (open-loop, D={D:.4f})
Vin in 0 {vin:.6g}
Vg1 g1 0 PULSE(0 5 0 1n 1n {hs_w:.9g} {T:.9g})
Vg2 g2 0 PULSE(0 5 {D * T + dt:.9g} 1n 1n {ls_w:.9g} {T:.9g})
S1 in sw g1 0 SWM
S2 sw 0 g2 0 SWM
.model SWM SW(Ron={ron_mohm * 1e-3:.6g} Roff=1Meg Vt=2.5 Vh=0.1)
Dfw 0 sw DFW
L1 sw nx {L_uH * 1e-6:.9g} Rser={dcr_mohm * 1e-3:.6g}
Resr nx out {esr_mohm * 1e-3:.6g}
Cout out 0 {Cout_uF * 1e-6:.9g} ic={vout:.6g}
```

The stage is *open-loop at fixed duty*: the duty is pre-compensated for DCR/Ron/diode losses so it settles near Vout without a controller. Behavioural switches mean it always converges without hunting vendor models. Initial conditions (`ic=`, `.ic`, `uic`) start the sim at the operating point so 800 cycles is enough. Metric extraction (`_steady_metrics`, via `spicelib.RawRead`) measures switching ripple over a *narrow* window (~20 cycles just before the load step) so slow open-loop drift cannot inflate it, and computes efficiency from the energy integral of input current over a wider settled window, discarding unphysical values (>101 % or ≤0) as "not settled".

**The PASS/FAIL checks** (defaults, overridable via `targets`):

| Check | Default limit | Direction |
|---|---|---|
| Output ripple (pk-pk) | max(50 mV, 1 % of Vout) | ≤ |
| Inductor ripple | 40 % of Iout | ≤ |
| Efficiency | 85 % | ≥ |

**Why regulation is not checked:** `regulation_pct` and `load_step_dip_mv` are returned as *informational* metrics only. An open-loop fixed-duty stage cannot regulate; holding Vout against line/load changes is the feedback loop's job. The result's note states it directly: ripple/inductor/efficiency verify the L/C sizing; design the compensator, then closed-loop verify. That closed-loop step is the next block.

The UI (`verifyInSpice()`) shows a VERIFIED / FAILS TARGETS banner, per-check chips with value vs. limit, and draws the V(out) waveform (downsampled to ≤800 points by the backend) on a canvas.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/spice/status` | GET | List available engines (LTspice / ngspice) |
| `/api/spice/verify` | POST | Run the netlist, return metrics + checks + `verified` (audited) |

**Degradation:** with neither LTspice nor ngspice installed, `/api/spice/verify` returns `{ok: false}` with an error telling you no SPICE engine was found and to install LTspice (adi.com) or ngspice, plus the ADI download URL in `install`; the Verify button is disabled ("no engine"). Installing KiCad also satisfies the fallback, since its bundled `ngspice.exe` is picked up.

### Closed-loop margin (python-control)

`backend/ece_suite/loop_verify.py` closes the gap the designer leaves: `compensation()` *targets* a phase margin but never computes the achieved one. This module builds the small-signal loop gain T(s) = plant × compensator × divider for a **peak current-mode buck** and asks python-control for the real numbers:

```python
# backend/ece_suite/loop_verify.py: verify()
    # --- power stage: peak current-mode control-to-output ---
    wp1 = 1.0 / (rload * cout)                 # dominant load pole
    wp2 = 2 * math.pi * (fsw / 2.0)            # sampling / high-frequency pole
    gcm0 = rload / ri_ohm                       # current-mode DC gain (V/V)
    plant = gcm0 / ((1 + s / wp1) * (1 + s / wp2))
    if esr > 0:
        wz_esr = 1.0 / (esr * cout)
        plant = plant * (1 + s / wz_esr)

    # --- type-II transconductance compensator: vc/vsense = gm * Zc(s) ---
    cpar = cc1 * cc2 / (cc1 + cc2)
    zc = (1 + s * rc * cc1) / (s * (cc1 + cc2) * (1 + s * rc * cpar))
    comp_tf = gm * zc

    loop = plant * comp_tf * hdiv              # open-loop gain T(s)

    gain_margin, phase_margin, _wcg, wcp = (float(x) for x in control.margin(loop))
```

It re-derives the exact type-II values from `power_designer.compensation()` (so what gets verified is what was designed), builds the standard low-frequency current-mode model (dominant load pole, ESR zero, one sampling pole at fsw/2) and PASS/FAILs the *achieved* phase margin (≥ 45° default) and gain margin (≥ 6 dB default). If T(s) never crosses −180°, python-control returns an infinite gain margin; the code treats that as healthy and force-passes the check, with the UI showing "∞". A downsampled Bode dataset (`f_hz`, `mag_db`, `phase_deg`) comes back for the canvas plot, with the crossover marked.

**Honesty boundaries** (stated in the module and returned in the response): the plant is *not* the full Ridley sampled-data model, with no slope compensation and no subharmonic Q-peaking. The current-mode DC gain depends on the controller's current-sense transresistance `Ri` and reference `Vref`, both IC-specific; defaults (0.1 Ω, 0.8 V) are used and *returned in `assumptions`* so you can refine them from the datasheet. Treat the margins as a design-review sanity check, then confirm on the bench.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/power/loop/status` | GET | `{available}`: is python-control importable |
| `/api/power/loop` | POST | Achieved crossover / PM / GM + Bode data + assumptions (audited) |

**Degradation:** if `control` is not importable, `/api/power/loop` returns `{ok: false, error: "python-control not installed", install: "pip install control"}` and the UI disables the button with "install python-control to enable".

### Inductor magnetics (OpenMagnetics / MKF)

Textbook sizing gives you an inductance; it cannot pick a core or predict losses. `backend/ece_suite/magnetics.py` drives the OpenMagnetics MKF engine (`PyOpenMagnetics`) to search a real multi-vendor core/material/wire database and return complete core+winding designs with physics-grade losses (Steinmetz/iGSE core loss, skin/proximity copper loss):

```python
# backend/ece_suite/magnetics.py: advise_inductor()
    i_peak = i_dc + i_ripple_pp / 2.0
    i_rms = math.sqrt(i_dc ** 2 + (i_ripple_pp ** 2) / 12.0)     # DC + triangular ripple
    inputs = {
        "designRequirements": {"magnetizingInductance": {"nominal": inductance_uH * 1e-6},
                               "name": "L", "turnsRatios": []},
        "operatingPoints": [{
            "name": "op", "conditions": {"ambientTemperature": ambient_c},
            "excitationsPerWinding": [{
                "frequency": fsw_khz * 1e3,
                "current": {"processed": {"label": "Triangular", "offset": i_dc, "peak": i_peak,
                                          "peakToPeak": i_ripple_pp, "rms": i_rms,
                                          "dutyCycle": max(0.01, min(0.99, duty))}}}]}],
    }
    res = om.calculate_advised_magnetics(inputs, max(1, min(n_results, 8)), mode)
```

The excitation is the DC-biased triangular current a buck inductor actually carries (offset = Idc, peak-to-peak = the ripple from your sizing), with the RMS computed analytically. The frontend feeds it automatically: `designMagnetics()` uses the sized L and the actual `ripple_current_A` from the last sizing run (falling back to `ripple_pct × Iout`). Results come back flattened per design: core shape, material, gap, turns, core loss, winding loss, total loss, temperature rise, and the MKF score, rendered as a comparison table.

Two implementation notes worth knowing:

- **Version workaround:** the pinned wheel (1.6.1) has a broken high-level converter→magnetics pipeline (`design_magnetics_from_converter` raises `key 'designRequirements' not found`). The module deliberately bypasses it and drives the adviser directly with a hand-built MAS `Inputs` dict. That path is validated working.
- **Catalog mode:** default is `"standard cores"` (datasheet-fit catalog, faster) rather than `"available cores"`, consistent with the suite's rule that distributor stock is never a selection criterion. If nothing satisfies the requirement, the error suggests retrying with `mode='available cores'`.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/power/magnetics/status` | GET | DB summary: material/shape/wire counts, vendor list |
| `/api/power/magnetics` | POST | Top-N core+winding designs with computed losses (audited) |

**Degradation:** without `PyOpenMagnetics` installed, status reports `{available: false, install: "pip install PyOpenMagnetics"}` and the Design magnetics button is disabled. The result note is the honesty boundary: real catalog parts with real loss math, but still a starting point. Confirm the chosen core's saturation and thermal margin against its datasheet.

### Capacitor bank sizing

`backend/ece_suite/capacitor_bank.py` sizes the input *and* output banks for a buck or boost stage on a **candidate capacitor you specify** (default: 22 µF / 5 mΩ / 2 A-rms / 25 V MLCC), using standard Erickson & Maksimovic math. The topology- and location-dependent RMS currents are the core of it:

```python
# backend/ece_suite/capacitor_bank.py: size()
    if t == "buck":
        d = min(0.98, max(0.02, vout / vin))
        in_irms = iout * math.sqrt(d * (1 - d))                # classic buck input-cap RMS
        out_irms = ripple / math.sqrt(12.0)                    # triangular inductor ripple
    else:                                                       # boost
        d = min(0.98, max(0.02, 1.0 - vin / vout))
        in_irms = ripple / math.sqrt(12.0)                     # boost input = inductor current
        out_irms = iout * math.sqrt(d / (1 - d))               # pulsed diode current
```

A buck's input cap eats chopped square-wave current (worst at D = 0.5), while its output cap only sees the triangular inductor ripple. A boost is the mirror image: smooth inductor current in, brutal pulsed diode current out. From the required RMS, `_bank()` computes the parallel count as the max of (count to meet the per-cap ripple rating, count to meet a target capacitance), then bank ESR, ESR power loss (`I²·R`), per-cap temperature rise (via an optional Rth), resulting ripple voltage (ESR term + capacitive term), and a **voltage-derating check per dielectric family**:

| Dielectric | Max fraction of rated voltage |
|---|---|
| MLCC / X7R / X5R / ceramic | 80 % |
| Polymer | 90 % |
| Aluminum electrolytic | 80 % |
| Tantalum | 50 % |
| Film | 60 % |

Each bank returns `derating_ok`, `ripple_current_ok` and a combined `ok`, rendered as green/amber cards for input and output. The stated boundary: first-order model, **MLCC DC-bias capacitance loss is not modelled**, so derate C from the part's bias curve and check ripple-current rating vs. frequency and temperature on the bench.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/power/capacitors` | POST | Input+output bank sizing on a candidate cap (`CapBankIn` model) |

### Digi-Key WEBENCH adapter

`backend/ece_suite/digikey.py` is the one networked piece: since WEBENCH has no public API, Digi-Key's developer API is the supported route to WEBENCH-backed part data. It does the OAuth2 client-credentials flow with *your* free Digi-Key developer app, searches the V4 keyword endpoint, and attaches a per-part WEBENCH launch link (`webench.ti.com/webench5/power/launch_wb.cgi?part=<MPN>&fromdisty=digikey`). Credentials come from the Connect card or `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET` env vars, are held in memory for the session, and are never written to the repo. Until connected, `/api/digikey/search` returns a clear "not connected" error with the registration URL.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/digikey/status` | GET | configured / connected / error + registration URL |
| `/api/digikey/connect` | POST | Store credentials, try a token, report success |
| `/api/digikey/search` | GET | Keyword search → MPN, description, datasheet, WEBENCH link |

### The 20 design calculators (`circuit` tab)

`backend/ece_suite/calculators.py` is a set of pure functions ported from oh-my-embedded: no I/O, no keys, no hardware. `CALC_META` describes 20 of them for the UI (labels, fields, defaults); `CalculatorsPanel.tsx` renders that metadata generically, so adding a calculator is backend-only work:

```python
# backend/ece_suite/calculators.py
def trace_width(current_a: float, temp_rise_c: float, copper_oz: float = 1.0) -> dict:
    """PCB trace width for a current, per IPC-2221:
    A[mil²] = (I / (k·ΔT^0.44))^(1/0.725); width = A / thickness."""
    if temp_rise_c <= 0 or current_a <= 0:
        raise ValueError("current and temperature rise must be > 0")
    th_mil = copper_oz * 1.378  # 1 oz ≈ 1.378 mil
    def width(k: float) -> dict:
        area = (current_a / (k * temp_rise_c ** 0.44)) ** (1 / 0.725)
        w_mil = area / th_mil
        return {"width_mil": round(w_mil, 2), "width_mm": round(w_mil * 0.0254, 4)}
    return {"external": width(0.048), "internal": width(0.024),
            "copper_oz": copper_oz, "thickness_mil": round(th_mil, 4), "standard": "IPC-2221"}
```

Representative of the set: a cited formula (IPC-2221, with both external and internal k factors), input validation that raises instead of returning garbage, and a plain dict that serves the REST endpoint and the tests identically.

| Calculator (`id`) | Computes |
|---|---|
| `divider` | E24-snapped R1/R2 pair for a target Vout, with error % and divider current |
| `lc_filter` | L and C for an LC low-pass into Z₀ |
| `lmatch` | Narrowband L-network match (Q, low-pass and high-pass variants) |
| `microstrip` | Microstrip Z₀ (Hammerstad/Wheeler), εeff |
| `decoupling` | Per-pin 100 nF + edge + bulk cap recommendation |
| `led_resistor` | Series R (ideal + E24) and resistor power rating |
| `rc_cutoff` / `rl_cutoff` | First-order corner frequency and time constant |
| `lc_resonant` | f₀, characteristic impedance, series-RLC Q and bandwidth |
| `opamp_noninv` / `opamp_inv` | Gain in V/V and dB |
| `trace_width` | IPC-2221 width for current/ΔT/copper weight |
| `thermal` | Tj = Ta + P·θJA |
| `timer555` | Astable frequency, duty, t-high/t-low |
| `adc` | LSB voltage, code count, ideal dynamic range |
| `dbm` | dBm ↔ W / Vrms / Vpp into 50 Ω |
| `shunt` | Sense voltage, dissipation, recommended rating |
| `cap_energy` | ½CV², charge |
| `buck` | Ideal CCM duty + loss note |
| `wavelength` | λ, quarter/half-wave lengths with velocity factor |

Two more calculators are registered in `CALCS` and callable via the API but absent from the UI: `power_budget` (battery runtime from a duty-cycled load list) and `esp32_pins` (ESP32 pin-hazard checker: flash pins, input-only, strapping, ADC2-vs-WiFi). Both take structured inputs the generic number-field UI does not render, so they are API/MCP-only. That is 20 in the UI and 22 in total.

![The Calculators tab: all 20 calculators as picker chips, with a computed resistor-divider result below the inputs](img/circuit.png)
*The Calculators tab (`circuit`): all 20 UI calculators as picker chips, with the resistor divider computed for 5 V in, 3.3 V out and a 10 kΩ low-side hint. The result grid gives the E24 pair (4.7 kΩ / 9.1 kΩ), the voltage it actually produces (3.2971 V), the error against the target (0.0878 %) and the divider current (362.32 µA).*

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/calc` | GET | `CALC_META`: the calculator list with fields and defaults |
| `/api/calc/{name}` | POST | Run one calculator; body is the kwargs dict; 404 on unknown name |

### Parts search + normalized specs (`parts` tab)

`backend/ece_suite/parts.py` is a provider abstraction with two providers. The default is a small deterministic **offline catalog** (15 parts spanning resistors to MCUs) that works with no keys and no network; `load_external()` can fold in a large normalized catalog (e.g. a jlcparts export) at runtime, deliberately schema-generic and with stock/price ignored. The **Nexar** provider is a key-gated stub: it reports `available` when `NEXAR_CLIENT_ID`/`NEXAR_CLIENT_SECRET` are set, but live GraphQL calls are intentionally disabled in this build and raise a clear error; the UI only surfaces the configured/not-configured status.

The parametric normalizer in `backend/ece_suite/param_parse.py` turns vendor free-text specs into typed SI values, so parts become numerically filterable:

```python
# backend/ece_suite/param_parse.py
def parse_value(text: str, default_unit: str | None = None) -> dict | None:
    """Parse one value string to {raw, value (SI base), unit, display}. None if unparseable."""
    if text is None:
        return None
    s = str(text).strip().replace("µ", "u").replace("μ", "u").replace("Ω", "ohm")
    if not s:
        return None

    m = _ENG.match(s)
    if m and (default_unit in (None, "Ω", "ohm") or m.group(2) in "Rr"):
        whole, letter, frac = m.group(1), m.group(2), m.group(3)
        val = float(f"{whole}.{frac}" if frac else whole) * _ENG_MULT.get(letter, 1.0)
        unit = "Ω" if letter in "Rr" or default_unit in ("Ω", "ohm") else (default_unit or "")
        return {"raw": text, "value": val, "unit": unit, "display": _fmt(val, unit)}
```

It handles both plain SI-prefixed strings ("4.7µF", "10 mΩ", "6.3V", with µ/μ folded to `u`) and the engineering decimal-as-prefix notation resistors ship with ("4k7" = 4.7 kΩ, "4R7" = 4.7 Ω, "1M5" = 1.5 MΩ). A spec-key→unit map (`resistance`→Ω, `capacitance`→F, `iout`→A, …) disambiguates bare numbers, and tolerances ("±10 %") become fractions. `normalize_specs()` enriches every part with `<key>_value` / `<key>_unit` / `<key>_display` fields; `search_offline()` can then range-filter numerically via `spec_key`/`vmin`/`vmax` (e.g. capacitance between 1 µF and 100 µF), and the UI shows the `_display` strings as chips in the "Specs (normalized)" column.

![Parts search: catalog hits with normalized spec chips, package and price columns](img/parts.png)
*Parts search over the offline catalog for "regulator": two hits, an AMS1117-3.3 LDO and a TPS62840DLCR buck, each with the parametric values pulled out into normalized spec chips, its package and an indicative 1k price. The card header notes Nexar is not configured, so these results are local only.*

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/parts/status` | GET | Catalog sizes, provider availability, category list |
| `/api/parts/search` | GET | Query + category + optional `spec_key`/`vmin`/`vmax` numeric range filter |
| `/api/parts/parse` | GET | Normalize one value string (`?text=4k7`) to `{value, unit, display}` |

### What needs what: dependency summary

| Feature | Requires | Behaviour when missing |
|---|---|---|
| Auto-design, sizing, compensation | nothing (pure Python) | always works |
| SPICE verify | LTspice **or** ngspice (KiCad's bundled copy counts) | `{ok:false}` with install link; Verify button disabled |
| Loop margin | `pip install control` | `{ok:false, install}`; button disabled |
| Magnetics | `pip install PyOpenMagnetics` | status `available:false`; button disabled |
| Capacitor bank, calculators, offline parts | nothing | always work |
| Digi-Key search / WEBENCH links | free Digi-Key developer app credentials + network | clear "not connected" error with registration URL |
| Nexar parts provider | env keys, but live calls are disabled in this build | explicit RuntimeError, never a silent empty result |
| Tool launch, `.ioc` round-trip into CubeMX | the respective tool installed (detection is automatic) | tool card shows "not found" |

Every gated feature degrades to an explicit, actionable error rather than a fake result: the same lab-truth discipline the instrument tabs use, applied to design math.

---
[← Bench Instruments](03-instruments.md) · [RTL / HDL & FPGA →](05-rtl-fpga.md)
