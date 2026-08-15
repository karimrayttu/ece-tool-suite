// Backend client (hardware-first). Works inside Electron (window.ece.baseUrl) and in a
// plain browser (falls back to the dev sidecar port).

export type Provenance = "SIMULATED" | "UNVERIFIED_HW" | "VERIFIED_HW";

export const PROVENANCE_TONE: Record<Provenance, "sim" | "unverified" | "verified"> = {
  SIMULATED: "sim",
  UNVERIFIED_HW: "unverified",
  VERIFIED_HW: "verified",
};

export interface InstrumentStatus {
  connected: boolean;
  backend: string | null;
  provenance: Provenance | null;
  resource: string | null;
  vendor?: string | null;
}

export interface Health {
  status: string;
  version: string;
  mode: string;
  instruments: Record<string, InstrumentStatus>;
  any_connected: boolean;
  hardware_connected: boolean;
  capabilities_chatbox: string[];
  capabilities_autonomous: string[];
}

declare global {
  interface Window {
    ece?: { baseUrl: () => Promise<string>; openExternal?: (url: string) => void };
  }
}

export async function baseUrl(): Promise<string> {
  if (window.ece?.baseUrl) return window.ece.baseUrl();
  return "http://127.0.0.1:8848";
}

async function getJSON<T>(base: string, path: string, fallback: T): Promise<T> {
  try {
    const r = await fetch(`${base}${path}`);
    return r.ok ? ((await r.json()) as T) : fallback;
  } catch {
    return fallback;
  }
}

async function postJSON<T>(base: string, path: string, body: unknown): Promise<T> {
  const r = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return (await r.json()) as T;
}

export const getHealth = (base: string) =>
  getJSON<Health | null>(base, "/health", null);

// --- VISA discovery + connection ------------------------------------------
export interface VisaResource {
  resource: string;
  idn: string | null;
  keysight: boolean;
  backend: string;
}

export const getVisaResources = (base: string) =>
  getJSON<{ resources: VisaResource[] }>(base, "/api/visa/resources", { resources: [] });

export interface ConnectResult {
  ok: boolean;
  role: string;
  resource: string;
  vendor?: string;
  provenance?: string;
  idn?: string;
  error?: string;
}
export interface ConnectArgs {
  resource?: string;
  backend?: string;
  host?: string;
  interface?: string;
  port?: number;
  vendor_hint?: string;
}
export interface SupportedVendor { id: string; name: string; dialect: string }
export const instrumentsSupported = (base: string) =>
  getJSON<{ roles: Record<string, SupportedVendor[]> }>(base, "/api/instruments/supported", { roles: {} });
export interface InstrumentCaps {
  vendor: string; model?: string | null; family?: string; connected: boolean;
  channels?: number; couplings?: string[]; acq_types?: string[]; trig_modes?: string[];
  trig_coup?: string[]; probe_factors?: number[];
  functions?: string[]; math?: string[]; nplc?: boolean; autozero?: boolean; notes?: string;
}
export const instrumentCaps = (base: string, role: string) =>
  getJSON<InstrumentCaps>(base, `/api/instruments/${role}/capabilities`, { vendor: "keysight", connected: false });
export const connectInstrument = (base: string, role: string, args: string | ConnectArgs, backend?: string) =>
  postJSON<ConnectResult>(base, `/api/instruments/${role}/connect`,
    typeof args === "string" ? { resource: args, backend } : args);

export interface IoBackend { backend: string; label: string; available: boolean; spec?: string; error?: string }
export const ioBackends = (base: string) =>
  getJSON<{ backends: IoBackend[] }>(base, "/api/io/backends", { backends: [] });

export interface UsbInstrument { vendor: string; vendor_name: string; vid: string; pid: string; name: string; status: string }
export interface IoRecommendation { reason: string; software: string; url: string; alt?: { software: string; url: string } }
export interface IoEnvironment {
  backends: IoBackend[];
  system_visa: boolean;
  usb_drivable: boolean;
  lan_drivable: boolean;
  usb_instruments: UsbInstrument[];
  recommendations: IoRecommendation[];
  ready: boolean;
}
const EMPTY_ENV: IoEnvironment = {
  backends: [], system_visa: false, usb_drivable: false, lan_drivable: false,
  usb_instruments: [], recommendations: [], ready: false,
};
export const ioEnvironment = (base: string) => getJSON<IoEnvironment>(base, "/api/io/environment", EMPTY_ENV);

export interface AutoconnectEntry { resource: string; idn: string | null; role: string | null; vendor?: string; connected: boolean; error?: string }
export interface AutoconnectResult { connected: AutoconnectEntry[]; detected: AutoconnectEntry[] }
export const ioAutoconnect = (base: string, lan = false) =>
  postJSON<AutoconnectResult>(base, `/api/io/autoconnect${lan ? "?lan=1" : ""}`, {});

export interface IoDetails {
  connected: boolean; role: string; resource?: string | null; backend?: string;
  provenance?: string; vendor?: string; vendor_name?: string | null;
  idn?: { raw: string; vendor: string; model: string; serial: string; firmware: string } | null;
  error?: string;
}
export const ioDetails = (base: string, role: string) =>
  getJSON<IoDetails>(base, `/api/io/details/${role}`, { connected: false, role });

export interface ScpiResult { ok: boolean; query?: boolean; response?: string | null; error?: string }
export const ioScpi = (base: string, role: string, command: string, query = false) =>
  postJSON<ScpiResult>(base, "/api/io/scpi", { role, command, query });

export interface McpInfo {
  available: boolean; server_name: string; command: string; args: string[];
  url: string; tools: string[]; config_json: string; note: string;
}
export const mcpInfo = (base: string) =>
  getJSON<McpInfo>(base, "/api/mcp/info", { available: false, server_name: "", command: "", args: [], url: "", tools: [], config_json: "", note: "" });

// --- logic analyzer -------------------------------------------------------
export interface LogicCapture {
  sample_rate: number;
  channels: Record<string, number[]>;
  protocol?: string;
  mapping?: Record<string, string>;
  options?: Record<string, unknown>;
}
export type LogicFrame = Record<string, string | number | boolean | null>;
export interface LogicSource { id: string; name: string; available: boolean; path?: string | null; install?: { software: string; url: string } }

export const logicSample = (base: string, protocol: string) =>
  getJSON<LogicCapture>(base, `/api/logic/sample?protocol=${protocol}`, { sample_rate: 0, channels: {} });
export const logicSources = (base: string) =>
  getJSON<{ sources: LogicSource[] }>(base, "/api/logic/sources", { sources: [] });
export const logicDecode = (base: string, body: {
  protocol: string; sample_rate: number; channels: Record<string, number[]>;
  mapping: Record<string, string>; options: Record<string, unknown>;
}) => postJSON<{ ok: boolean; protocol?: string; count?: number; frames?: LogicFrame[]; error?: string }>(base, "/api/logic/decode", body);
export const logicCapture = (base: string, body: { driver: string; channels: number; sample_rate: number; samples: number }) =>
  postJSON<{ ok: boolean; sample_rate?: number; channels?: Record<string, number[]>; error?: string; install?: string }>(base, "/api/logic/capture", body);

// --- MCU programmer / firmware (pymcuprog) --------------------------------
export interface McuTool { product: string; serial?: string | null; manufacturer?: string | null }
export interface McuStatus { available: boolean; tools: McuTool[]; n_devices: number; install?: { software: string; url: string } }
export interface McuRead {
  ok: boolean; device?: string; memory?: string; device_id?: string; voltage?: number | null;
  bytes?: number; base_address?: number; data_b64?: string; intel_hex?: string; error?: string;
}
export const mcuStatus = (base: string) => getJSON<McuStatus>(base, "/api/mcu/status", { available: false, tools: [], n_devices: 0 });
export const mcuDevices = (base: string) => getJSON<{ devices: string[] }>(base, "/api/mcu/devices", { devices: [] });
export const mcuDevice = (base: string, name: string) => getJSON<Record<string, string | number | boolean>>(base, `/api/mcu/device/${name}`, {});
export const mcuRead = (base: string, body: { device: string; tool_serial?: string; memory?: string; max_bytes?: number }) =>
  postJSON<McuRead>(base, "/api/mcu/read", body);
export const mcuErase = (base: string, body: { device: string; tool_serial?: string; confirm: boolean }) =>
  postJSON<{ ok: boolean; error?: string; action?: string }>(base, "/api/mcu/erase", body);

// --- design tools (CubeMX .ioc, TI tools, power stage) --------------------
export interface DesignTool { id: string; name: string; kind: string; installed: boolean; path: string | null; launchable: boolean }
export interface IocPin { pin: string; signal: string; mode: string; label: string; pupd: string }
export interface IocTimer { name: string; params: Record<string, string> }
export interface IocParsed {
  ok: boolean; mcu: string; family: string; project?: string;
  pins: IocPin[]; peripherals: string[]; timers: IocTimer[]; n_keys?: number; error?: string;
}
export const toolsDetect = (base: string) => getJSON<{ tools: DesignTool[] }>(base, "/api/tools/detect", { tools: [] });
export const toolsLaunch = (base: string, id: string) =>
  postJSON<{ ok: boolean; launched?: string; path?: string; error?: string }>(base, `/api/tools/launch/${id}`, {});
export const iocParse = (base: string, text: string) =>
  postJSON<IocParsed>(base, "/api/ioc/parse", { text });
export const iocEdit = (base: string, text: string, edits: Record<string, string | null>) =>
  postJSON<{ ok: boolean; text?: string; error?: string }>(base, "/api/ioc/edit", { text, edits });
export type PowerStage = { ok: boolean; topology?: string; duty_pct?: number; inductor_uH?: number; peak_current_A?: number; input_current_A?: number; ripple_current_A?: number; output_cap_uF_for_1pct?: number; note?: string; error?: string };
export const powerStage = (base: string, topo: "buck" | "boost", p: { vin: number; vout: number; iout: number; fsw_khz: number; ripple_pct: number }) =>
  getJSON<PowerStage>(base, `/api/power/${topo}?vin=${p.vin}&vout=${p.vout}&iout=${p.iout}&fsw_khz=${p.fsw_khz}&ripple_pct=${p.ripple_pct}`, { ok: false });
export const webenchUrl = (base: string, p: { vin_min: number; vin_max: number; vout: number; iout: number }) =>
  getJSON<{ url: string }>(base, `/api/power/webench?vin_min=${p.vin_min}&vin_max=${p.vin_max}&vout=${p.vout}&iout=${p.iout}`, { url: "" });

// --- SPICE verification of the power stage --------------------------------
export interface SpiceEngine { id: string; name: string; path: string }
export interface SpiceCheck { name: string; value: number; unit: string; limit: number; pass: boolean; cmp: string }
export interface SpiceMetrics { vout_mean?: number; regulation_pct?: number; vout_ripple_mvpp?: number; il_ripple_a?: number; il_ripple_pct?: number; efficiency_pct?: number | null; load_step_dip_mv?: number | null; waveform?: { t: number[]; vout: number[] }; points?: number }
export interface SpiceVerifyResult { ok: boolean; engine?: string; topology?: string; verified?: boolean; checks?: SpiceCheck[]; metrics?: SpiceMetrics; note?: string; error?: string; install?: string }
export const spiceStatus = (base: string) => getJSON<{ engines: SpiceEngine[] }>(base, "/api/spice/status", { engines: [] });
export const spiceVerify = (base: string, body: {
  topology: string; vin: number; vout: number; iout: number; L_uH: number; Cout_uF: number;
  fsw_khz: number; esr_mohm?: number; dcr_mohm?: number; targets?: Record<string, number>; engine_id?: string;
}) => postJSON<SpiceVerifyResult>(base, "/api/spice/verify", body);

// --- native WEBENCH-class power designer + Digi-Key adapter ----------------
export interface PowerPart { mpn: string; integrated_fet: boolean; iout_max?: number | null; note: string; datasheet: string }
export interface PowerCompensation { crossover_hz: number; power_pole_hz: number; esr_zero_hz?: number | null; phase_margin_target_deg: number; type2: { Rc_ohm: number; Cc1_nF: number; Cc2_pF: number }; note: string }
export interface PowerDesign {
  ok: boolean; recommendation?: { topology: string; reason: string }; parts?: PowerPart[];
  sizing?: Record<string, number | string | boolean | null>; compensation?: PowerCompensation; error?: string;
}
export const powerDesign = (base: string, p: { vin: number; vout: number; iout: number; fsw_khz: number; ripple_pct: number; isolated?: boolean }) =>
  getJSON<PowerDesign>(base, `/api/power/design?vin=${p.vin}&vout=${p.vout}&iout=${p.iout}&fsw_khz=${p.fsw_khz}&ripple_pct=${p.ripple_pct}&isolated=${p.isolated ? "true" : "false"}`, { ok: false });

export interface LoopCheck { name: string; value: number | null; cmp: string; limit: number; unit: string; pass: boolean }
export interface LoopVerify {
  ok: boolean; engine?: string; topology?: string; stable?: boolean;
  metrics?: { crossover_hz: number | null; phase_margin_deg: number | null; gain_margin_db: number | null; gain_margin_infinite?: boolean; target_crossover_hz?: number };
  checks?: LoopCheck[]; assumptions?: Record<string, number>;
  bode?: { f_hz: number; mag_db: number; phase_deg: number }[]; note?: string; error?: string; install?: string;
}
export const loopStatus = (base: string) => getJSON<{ available: boolean; engine: string }>(base, "/api/power/loop/status", { available: false, engine: "python-control" });
export const loopVerify = (base: string, body: {
  vin: number; vout: number; iout: number; L_uH: number; Cout_uF: number; fsw_khz: number;
  esr_mohm?: number; ri_ohm?: number; vref_v?: number;
}) => postJSON<LoopVerify>(base, "/api/power/loop", body);

export interface CapBank {
  rms_current_a: number; parallel_count: number; count_for_ripple: number; count_for_capacitance: number;
  total_capacitance_uF: number; total_esr_mohm: number; esr_loss_w: number; temp_rise_c: number | null;
  ripple_voltage_mvpp: number; v_applied: number; v_derated_limit: number;
  derating_ok: boolean; ripple_current_ok: boolean; ok: boolean;
}
export interface CapBankResult { ok: boolean; topology?: string; duty_pct?: number; candidate?: Record<string, number | string>; input_cap?: CapBank; output_cap?: CapBank; note?: string; error?: string }
export const capacitorBank = (base: string, body: { topology: string; vin: number; vout: number; iout: number; fsw_khz: number; il_ripple_pp_a?: number; c_each_uF?: number; esr_each_mohm?: number; irms_each_a?: number; vrated?: number; dielectric?: string }) =>
  postJSON<CapBankResult>(base, "/api/power/capacitors", body);

export interface MagneticsDb { available: boolean; engine?: string; core_materials?: number; core_shapes?: number; core_manufacturers?: string[]; wires?: number | null; mode?: string; install?: string }
export interface MagneticDesign { core_shape: string; core_material: string; gap_mm: number | null; turns: number[]; core_loss_w: number | null; winding_loss_w: number | null; total_loss_w: number | null; inductance_uH: number | null; temperature_rise_c: number | null; score: number | null }
export interface MagneticsResult { ok: boolean; engine?: string; mode?: string; requirement?: Record<string, number>; designs?: MagneticDesign[]; note?: string; error?: string; install?: string }
export const magneticsStatus = (base: string) => getJSON<MagneticsDb>(base, "/api/power/magnetics/status", { available: false });
export const magneticsAdvise = (base: string, body: { inductance_uH: number; i_dc: number; i_ripple_pp: number; fsw_khz: number }) =>
  postJSON<MagneticsResult>(base, "/api/power/magnetics", body);

export interface DigikeyStatus { configured: boolean; connected: boolean; error?: string | null; register_url: string; note: string }
export interface DkPart { mpn: string; manufacturer?: string; description?: string; datasheet?: string; webench?: string }
export const digikeyStatus = (base: string) => getJSON<DigikeyStatus>(base, "/api/digikey/status", { configured: false, connected: false, register_url: "", note: "" });
export const digikeyConnect = (base: string, client_id: string, client_secret: string) =>
  postJSON<{ ok: boolean; connected?: boolean; error?: string }>(base, "/api/digikey/connect", { client_id, client_secret });
export const digikeySearch = (base: string, q: string) =>
  getJSON<{ ok: boolean; count?: number; parts?: DkPart[]; error?: string }>(base, `/api/digikey/search?q=${encodeURIComponent(q)}`, { ok: false });

export interface VerifyResult {
  ok: boolean;
  connected?: boolean;
  provenance?: string;
  idn?: string | null;
  reasons?: string[];
  error?: string;
}
export const verifyInstrument = (base: string, role: string) =>
  postJSON<VerifyResult>(base, `/api/instruments/${role}/verify`, {});

export const disconnectInstrument = (base: string, role: string) =>
  postJSON<{ ok: boolean; connected: boolean }>(base, `/api/instruments/${role}/disconnect`, {});

// --- scope ----------------------------------------------------------------
export interface ScopeChannelFrame {
  ch: number;
  t: number[];
  v: number[];
  meta?: { vpp?: number; points?: number };
  measure?: Record<string, number | null>;
}
export interface ScopeFrame {
  connected: boolean;
  provenance?: Provenance;
  channels?: ScopeChannelFrame[];
  error?: string;
}

export interface ScopeChannelCfg {
  ch: number;
  enabled?: boolean;
  scale?: number;
  offset?: number;
  coupling?: string;
  probe?: number;
  bwlimit?: boolean;
  invert?: boolean;
  label?: string;
  unit?: string;
}
export interface ScopeConfig {
  channels?: ScopeChannelCfg[];
  timebase_scale?: number;
  timebase_position?: number;
  timebase_reference?: string;
  trig_mode?: string;
  trig_source?: string;
  trig_level?: number;
  trig_slope?: string;
  trig_coupling?: string;
  trig_holdoff?: number;
  trig_sweep?: string;
  acq_type?: string;
  acq_count?: number;
  acq_points?: number;
  run?: "run" | "stop" | "single";
}
export const scopeConfig = (base: string, cfg: ScopeConfig) =>
  postJSON<{ ok: boolean; connected?: boolean; error?: string }>(base, "/api/scope/config", cfg);

export const scopeBringup = (base: string) =>
  postJSON<Record<string, unknown>>(base, "/api/scope/bringup", {});

export interface ScopeMeasurements {
  connected: boolean;
  ch?: number;
  measurements?: Record<string, { value: number | null; unit: string }>;
  error?: string;
}
export const scopeMeasure = (base: string, ch: number) =>
  getJSON<ScopeMeasurements>(base, `/api/scope/measure?ch=${ch}`, { connected: false });

// --- DMM ------------------------------------------------------------------
export interface DmmReading {
  connected: boolean;
  value?: number | null;
  unit?: string;
  function?: string;
  dialect?: string;
  provenance?: Provenance;
  error?: string;
}
export const dmmConfig = (base: string, cfg: { function: string; range?: string | number; nplc?: number; math?: string; autozero?: boolean }) =>
  postJSON<{ ok: boolean; connected?: boolean; unit?: string; error?: string }>(base, "/api/dmm/config", cfg);

// --- spectrum analyzer ----------------------------------------------------
export interface SaFrame {
  connected: boolean;
  freqs?: number[];
  amps?: number[];
  center?: number;
  span?: number;
  provenance?: Provenance;
  peak?: { freq: number | null; amp: number | null };
  error?: string;
}
export interface SaConfig {
  center?: number; span?: number; start?: number; stop?: number;
  rbw?: number; vbw?: number; rbw_auto?: boolean; vbw_auto?: boolean;
  ref_level?: number; atten?: number; preamp?: boolean; sweep_points?: number;
  trace_mode?: string; detector?: string; averages?: number;
}
export const saConfig = (base: string, cfg: SaConfig) =>
  postJSON<{ ok: boolean; connected?: boolean; error?: string }>(base, "/api/sa/config", cfg);

// --- generic websocket helper ---------------------------------------------
export function openWs<T>(base: string, path: string, onFrame: (f: T) => void, onState: (open: boolean) => void): WebSocket {
  const ws = new WebSocket(base.replace(/^http/, "ws") + path);
  ws.onopen = () => onState(true);
  ws.onclose = () => onState(false);
  ws.onerror = () => onState(false);
  ws.onmessage = (ev) => {
    try {
      onFrame(JSON.parse(ev.data) as T);
    } catch {
      /* ignore */
    }
  };
  return ws;
}

// --- presets --------------------------------------------------------------
export type Verdict = "ALLOW" | "REQUIRE_CONFIRM" | "BLOCK";
export const VERDICT_TONE: Record<Verdict, "verified" | "unverified" | "danger"> = {
  ALLOW: "verified",
  REQUIRE_CONFIRM: "unverified",
  BLOCK: "danger",
};
export interface PresetInfo {
  id: string; name: string; instrument: string; testing_for: string;
  requires_envelope: boolean; requires_confirm: boolean;
  suggested_envelope: { max_voltage: number; max_current: number } | null; n_steps: number;
}
export const listPresets = (base: string) => getJSON<PresetInfo[]>(base, "/api/presets", []);

export interface PresetPreview {
  ok_to_run: boolean;
  overall: Verdict;
  connected?: boolean;
  steps: { description: string; verdict: string; reasons?: string[] }[];
}
export interface PresetApplyResult {
  ok: boolean;
  provenance?: string;
  summary: string;
  rolled_back: boolean;
  connected?: boolean;
}
export interface PresetBody {
  envelope?: { max_voltage: number; max_current: number } | null;
  confirm?: boolean;
}
export const previewPreset = (base: string, id: string, body: PresetBody = {}) =>
  postJSON<PresetPreview>(base, `/api/presets/${id}/preview`, body);
export const applyPreset = (base: string, id: string, body: PresetBody = {}) =>
  postJSON<PresetApplyResult>(base, `/api/presets/${id}/apply`, body);

// --- source (PSU) ---------------------------------------------------------
export interface PsuBody {
  vset: number; iset: number; ovp: number; ocp: number; dut_max_v: number; dut_max_i: number; confirm?: boolean;
}
export interface PsuFrame {
  connected: boolean;
  provenance?: Provenance;
  vset?: number | null; iset?: number | null; vout?: number | null; iout?: number | null;
  output_on?: boolean;
  error?: string;
}
export const psuPreview = (base: string, body: PsuBody) =>
  postJSON<{ overall: Verdict; ok_to_run: boolean; connected?: boolean }>(base, "/api/psu/preview", body);
export const psuApply = (base: string, body: PsuBody) =>
  postJSON<{ ok: boolean; summary: string; rolled_back: boolean; connected?: boolean }>(base, "/api/psu/apply", body);
export const psuOff = (base: string) => postJSON<{ ok: boolean }>(base, "/api/psu/off", {});

// --- function generator (AWG) ---------------------------------------------
export interface AwgBody { func: string; freq: number; vpp: number; offset: number; dut_max_v: number; dut_max_i: number; confirm?: boolean }
export interface AwgFrame {
  connected: boolean; provenance?: Provenance; func?: string; freq?: number | null; vpp?: number | null; offset?: number | null; output_on?: boolean; error?: string;
}
export const awgPreview = (base: string, body: AwgBody) =>
  postJSON<{ overall: Verdict; ok_to_run: boolean; connected?: boolean }>(base, "/api/awg/preview", body);
export const awgApply = (base: string, body: AwgBody) =>
  postJSON<{ ok: boolean; summary: string; connected?: boolean }>(base, "/api/awg/apply", body);
export const awgOff = (base: string) => postJSON<{ ok: boolean }>(base, "/api/awg/off", {});

// --- electronic load ------------------------------------------------------
export interface EloadBody { mode: string; level: number; ocp: number; dut_max_v: number; dut_max_i: number; confirm?: boolean }
export interface EloadFrame {
  connected: boolean; provenance?: Provenance; mode?: string; level?: number | null; ocp?: number | null; vout?: number | null; iout?: number | null; input_on?: boolean; error?: string;
}
export const eloadPreview = (base: string, body: EloadBody) =>
  postJSON<{ overall: Verdict; ok_to_run: boolean; connected?: boolean }>(base, "/api/eload/preview", body);
export const eloadApply = (base: string, body: EloadBody) =>
  postJSON<{ ok: boolean; summary: string; connected?: boolean }>(base, "/api/eload/apply", body);
export const eloadOff = (base: string) => postJSON<{ ok: boolean }>(base, "/api/eload/off", {});

// --- calculators / parts / kicad ------------------------------------------
export interface CalcField { k: string; label: string; default: number }
export interface CalcMeta { id: string; name: string; fields: CalcField[] }
export interface PartResult { mpn: string; mfr: string; desc: string; category: string; package: string; price_1k: number; specs_typed?: Record<string, number | string> }

export const listCalcs = (base: string) =>
  getJSON<{ calculators: CalcMeta[] }>(base, "/api/calc", { calculators: [] }).then((r) => r.calculators);

export async function runCalc(base: string, name: string, body: Record<string, number>): Promise<{ ok: boolean; result?: unknown; error?: string }> {
  const r = await fetch(`${base}/api/calc/${name}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (r.status === 404) return { ok: false, error: "unknown calculator" };
  return (await r.json()) as { ok: boolean; result?: unknown; error?: string };
}

export async function searchParts(base: string, query: string, category?: string): Promise<{ ok: boolean; provider?: string; results?: PartResult[]; error?: string }> {
  const params = new URLSearchParams({ query });
  if (category) params.set("category", category);
  return getJSON(base, `/api/parts/search?${params}`, { ok: false });
}
export const partsStatus = (base: string) =>
  getJSON<{ categories?: string[]; providers?: Record<string, boolean> }>(base, "/api/parts/status", {});

export async function analyzeKicad(base: string, text: string): Promise<Record<string, unknown>> {
  return postJSON(base, "/api/kicad/analyze", { text });
}

// --- CAN bus offline decode -----------------------------------------------
export interface CanDecoded {
  id: number;
  name: string | null;
  signals: Record<string, { value: number; unit: string }>;
}
export const canDecode = (base: string, dbc: string, log: string) =>
  postJSON<{ ok: boolean; messages?: number; decoded?: CanDecoded[]; error?: string }>(base, "/api/can/decode", { dbc, log });

// --- RTL / HDL (Verilog / SystemVerilog / VHDL) ---------------------------
export type HdlLang = "verilog" | "systemverilog" | "vhdl";
export interface RtlTool { id: string; name: string; purpose?: string; installed: boolean; path: string | null }
export interface RtlDiagnostic { severity: string; code?: string | null; file?: string | null; line: number | null; col?: number | null; message: string }
export interface RtlFpgaFamily { id: string; name: string; boards: string; synth: boolean; pnr: boolean; available: boolean }
export interface RtlVendor { id: string; name: string; constraint: string; installed: boolean; path: string | null }
export interface RtlToolchain {
  tools: RtlTool[];
  capabilities: Record<string, boolean>;
  languages: string[];
  fpga?: { available: boolean; families: RtlFpgaFamily[] };
  vendors?: RtlVendor[];
  any: boolean;
  install: string;
  ai?: boolean;
}
export interface RtlTimingClock { clock: string; fmax_mhz: number; verdict: string | null; target_mhz: number | null }
export interface RtlTimingResult { ok: boolean; family?: string; device?: string; top?: string; routed?: boolean; stage?: string; clocks?: RtlTimingClock[]; utilization?: Record<string, { used: number; total: number; pct: number }>; met_timing?: boolean | null; log_tail?: string; error?: string; diagnostics?: RtlDiagnostic[] }
export interface RtlRegmapResult { ok: boolean; name?: string; systemverilog?: string; markdown?: string; n_registers?: number; lint?: RtlLintResult; error?: string }
export interface RtlConstraintResult { ok: boolean; format?: string; ecosystem?: string; text?: string; error?: string }
export interface RtlFpgaResult { ok: boolean; family?: string; device?: string; synthesized?: boolean; top?: string; utilization?: Record<string, number>; cells?: Record<string, number>; total_cells?: number; pnr_available?: boolean; note?: string; boards?: string; error?: string; diagnostics?: RtlDiagnostic[]; log?: string }
export interface RtlLintResult { ok: boolean; language?: string; tool?: string; diagnostics?: RtlDiagnostic[]; clean?: boolean; errors?: number; warnings?: number; error?: string; install?: string }
export interface RtlVcd { signals: string[]; time_end: number; text: string }
export interface RtlSimResult { ok: boolean; language?: string; tool?: string; compiled?: boolean; verdict?: string; stdout?: string; vcd?: RtlVcd | null; diagnostics?: RtlDiagnostic[]; error?: string; install?: string }
export interface RtlSynthResult { ok: boolean; language?: string; synthesized?: boolean; top?: string; stats?: Record<string, number>; cells?: Record<string, number>; log?: string; error?: string; install?: string; diagnostics?: RtlDiagnostic[] }
export interface RtlFormatResult { ok: boolean; language?: string; formatted?: string; error?: string; install?: string }
export interface RtlRound { lint: RtlLintResult; sim?: RtlSimResult | null; validated: boolean }
export interface RtlGenerateResult { ok: boolean; language?: string; code?: string; notes?: string; validated?: boolean; rounds?: RtlRound[]; n_rounds?: number; model?: string; error?: string; raw?: string }
export interface RtlOptimizeResult { ok: boolean; language?: string; goal?: string; accepted?: boolean; code?: string; candidate?: string; notes?: string; before?: { synth: RtlSynthResult }; after?: { synth: RtlSynthResult }; note?: string | null; error?: string }

const EMPTY_TC: RtlToolchain = { tools: [], capabilities: {}, languages: [], any: false, install: "" };
export const rtlStatus = (base: string) => getJSON<RtlToolchain>(base, "/api/rtl/status", EMPTY_TC);
export const rtlLint = (base: string, body: { source: string; language?: string; top?: string }) =>
  postJSON<RtlLintResult>(base, "/api/rtl/lint", body);
export const rtlSimulate = (base: string, body: { source: string; testbench: string; language?: string; top?: string }) =>
  postJSON<RtlSimResult>(base, "/api/rtl/simulate", body);
export const rtlSynth = (base: string, body: { source: string; language?: string; top?: string }) =>
  postJSON<RtlSynthResult>(base, "/api/rtl/synth", body);
export const rtlFpga = (base: string, body: { source: string; family: string; language?: string; top?: string }) =>
  postJSON<RtlFpgaResult>(base, "/api/rtl/fpga", body);
export const rtlTiming = (base: string, body: { source: string; family: string; device?: string; language?: string; top?: string; target_mhz?: number }) =>
  postJSON<RtlTimingResult>(base, "/api/rtl/timing", body);
export const rtlRegmap = (base: string, body: { spec: Record<string, unknown>; lint?: boolean }) =>
  postJSON<RtlRegmapResult>(base, "/api/rtl/regmap", body);
export const rtlConstraints = (base: string, body: { fmt: string; ports: Record<string, unknown>[] }) =>
  postJSON<RtlConstraintResult>(base, "/api/rtl/constraints", body);
export const rtlFormat = (base: string, body: { source: string; language?: string }) =>
  postJSON<RtlFormatResult>(base, "/api/rtl/format", body);
export const rtlGenerate = (base: string, body: { spec: string; language: string; testbench?: string; top?: string; max_rounds?: number }) =>
  postJSON<RtlGenerateResult>(base, "/api/rtl/generate", body);
export const rtlOptimize = (base: string, body: { source: string; goal: string; language?: string; testbench?: string; top?: string }) =>
  postJSON<RtlOptimizeResult>(base, "/api/rtl/optimize", body);

// --- one-click third-party software setup ----------------------------------
export interface SetupTool {
  id: string; name: string; group: string; kind: "auto" | "page";
  purpose: string; source: string; url: string; note?: string;
  approx_mb?: number; installed: boolean; path?: string | null;
  one_click: boolean; needs_winget?: boolean;
}
export interface SetupInstallStatus { state: string; progress: number; detail: string; error: string | null; finished?: boolean }
export const setupCatalog = (base: string) =>
  getJSON<{ tools: SetupTool[] }>(base, "/api/setup/catalog", { tools: [] });
export const setupInstall = (base: string, id: string) =>
  postJSON<{ ok: boolean; started?: boolean; already_running?: boolean; error?: string; url?: string }>(base, `/api/setup/install/${id}`, {});
export const setupStatus = (base: string) =>
  getJSON<{ installs: Record<string, SetupInstallStatus> }>(base, "/api/setup/status", { installs: {} });

// --- LabVIEW ----------------------------------------------------------------
export interface LvInstall { version: string; path: string; bitness: string }
export interface LvStatus { installed: boolean; installs: LvInstall[]; default: string | null; cli: string | null; cli_available: boolean; download: string }
export interface LvProject { name: string; path: string; modified: number }
export interface LvOpResult { ok: boolean; returncode?: number; log?: string; error?: string; install?: string; launched?: string }
export const lvStatus = (base: string) =>
  getJSON<LvStatus>(base, "/api/labview/status", { installed: false, installs: [], default: null, cli: null, cli_available: false, download: "" });
export const lvProjects = (base: string) =>
  getJSON<{ projects: LvProject[] }>(base, "/api/labview/projects", { projects: [] });
export const lvRunVi = (base: string, vi_path: string) =>
  postJSON<LvOpResult>(base, "/api/labview/run-vi", { vi_path });
export const lvMassCompile = (base: string, directory: string) =>
  postJSON<LvOpResult>(base, "/api/labview/mass-compile", { directory });
export const lvBuild = (base: string, project: string, build_spec?: string) =>
  postJSON<LvOpResult>(base, "/api/labview/build", { project, build_spec });
export const lvLaunch = (base: string, project?: string) =>
  postJSON<LvOpResult>(base, "/api/labview/launch", { project });
export const lvClose = (base: string) => postJSON<LvOpResult>(base, "/api/labview/close", {});

// --- Xilinx / Intel / Lattice PLD targets -----------------------------------
export interface PldFamily { name: string; part: string; board?: string | null; cpld?: boolean; open_flow?: string; note?: string }
export interface PldVendor { vendor: string; tool: string; tool_installed: boolean; tool_path?: string | null; families: Record<string, PldFamily> }
export interface VendorProjectResult { ok: boolean; vendor?: string; family?: string; part?: string; top?: string; is_cpld?: boolean; tool?: string; tool_installed?: boolean; files?: Record<string, string>; notes?: string[]; error?: string }
export const pldTargets = (base: string) =>
  getJSON<{ vendors: Record<string, PldVendor> }>(base, "/api/rtl/pld-targets", { vendors: {} });
export const vendorProject = (base: string, body: { source: string; vendor: string; family: string; part?: string; top?: string; language?: string; ports?: Record<string, unknown>[] }) =>
  postJSON<VendorProjectResult>(base, "/api/rtl/vendor-project", body);

// --- parts from URL + local list -------------------------------------------
export interface UrlPart { ok: boolean; source_url?: string; vendor?: string; mpn?: string | null; manufacturer?: string | null; name?: string; description?: string; image?: string; price?: string | number; fetched?: boolean; duplicate?: boolean; entry?: Record<string, unknown>; count?: number; error?: string; id?: number; added?: string }
export const partsFromUrl = (base: string, url: string, add = true) =>
  postJSON<UrlPart>(base, "/api/parts/from-url", { url, add });
export const partsListGet = (base: string) =>
  getJSON<{ parts: UrlPart[] }>(base, "/api/parts/list", { parts: [] });
export const partsListRemove = async (base: string, id: number) => {
  const r = await fetch(`${base}/api/parts/list/${id}`, { method: "DELETE" });
  return (await r.json()) as { ok: boolean; count: number };
};
export function partsListExport(base: string): void {
  const a = document.createElement("a");
  a.href = `${base}/api/parts/list/export`;
  a.download = "parts_list.csv";
  a.click();
}

// --- FPGA bring-up ----------------------------------------------------------
export interface JtagResult { ok: boolean; found?: boolean; devices?: { idcode: string; manufacturer?: string | null; model?: string | null }[]; usb?: string; log?: string; error?: string; install?: string }
export interface BitstreamStep { step: string; ok: boolean; log_tail: string }
export interface BitstreamResult { ok: boolean; built?: boolean; dir?: string; bitstream?: string | null; size_bytes?: number | null; fmax_mhz?: number | null; device?: string; top?: string; steps?: BitstreamStep[]; stage?: string; error?: string; install?: string }
export interface ProgramResult { ok: boolean; programmed?: boolean; log?: string; hint?: string | null; error?: string }
export interface VendorExportResult extends VendorProjectResult { dir?: string; files_written?: string[] }
export const rtlJtag = (base: string) => getJSON<JtagResult>(base, "/api/rtl/jtag", { ok: false });
export const rtlBoards = (base: string) => getJSON<{ ok: boolean; boards?: string[]; count?: number }>(base, "/api/rtl/boards", { ok: false });
export const rtlBitstream = (base: string, body: { source: string; family: string; device?: string; top?: string; language?: string; ports?: Record<string, unknown>[] }) =>
  postJSON<BitstreamResult>(base, "/api/rtl/bitstream", body);
export const rtlProgram = (base: string, body: { bitstream: string; board?: string; cable?: string }) =>
  postJSON<ProgramResult>(base, "/api/rtl/program", body);
export const rtlVendorExport = (base: string, body: { source: string; vendor: string; family: string; part?: string; top?: string; language?: string }) =>
  postJSON<VendorExportResult>(base, "/api/rtl/vendor-export", body);
export const rtlVendorLaunch = (base: string, project_dir: string, vendor?: string) =>
  postJSON<{ ok: boolean; opened?: string; launched_tool?: string | null; note?: string | null; error?: string }>(base, "/api/rtl/vendor-launch", { project_dir, vendor });

// --- LabVIEW VI Server -------------------------------------------------------
export interface LvComStatus { ok: boolean; connected?: boolean; version?: string; error?: string; hint?: string }
export interface LvViRunResult { ok: boolean; vi?: string; inputs_set?: string[]; outputs?: Record<string, unknown>; error?: string }
export interface LvTemplate { name: string; path: string }
export const lvComStatus = (base: string) => getJSON<LvComStatus>(base, "/api/labview/com-status", { ok: false });
export const lvViRun = (base: string, body: { vi_path: string; inputs?: Record<string, unknown>; outputs?: string[] }) =>
  postJSON<LvViRunResult>(base, "/api/labview/vi-run", body);
export const lvTemplates = (base: string) => getJSON<{ ok: boolean; templates: LvTemplate[]; count: number }>(base, "/api/labview/templates", { ok: false, templates: [], count: 0 });
export const lvCreateVi = (base: string, body: { save_path: string; template: string; open_in_labview?: boolean }) =>
  postJSON<{ ok: boolean; created?: string; opened?: boolean; note?: string; error?: string; available?: string[] }>(base, "/api/labview/create-vi", body);
export const lvBuilderStatus = (base: string) => getJSON<{ available: boolean; builder_vi: string; guide?: string | null }>(base, "/api/labview/builder-status", { available: false, builder_vi: "" });

// --- RTL professional workflow ---------------------------------------------
export interface DevEnvItem { id: string; name: string; purpose: string; installed: boolean; path?: string | null; install?: string | null }
export const rtlDevEnv = (base: string) =>
  getJSON<{ items: DevEnvItem[]; stack_note: string }>(base, "/api/rtl/devenv", { items: [], stack_note: "" });
export interface RtlSnippet { id: string; name: string; language: string; note: string; code: string }
export const rtlSnippets = (base: string) =>
  getJSON<{ snippets: RtlSnippet[] }>(base, "/api/rtl/snippets", { snippets: [] });
export const rtlGtkwave = (base: string, vcd: string, name: string) =>
  postJSON<{ ok: boolean; file?: string; error?: string }>(base, "/api/rtl/gtkwave", { vcd, name });
export const rtlExportProject = (base: string, body: { files: Record<string, string>; dest: string; open_in?: string }) =>
  postJSON<{ ok: boolean; dir?: string; written?: string[]; error?: string }>(base, "/api/rtl/export-project", body);
export const logicLaunchPulseview = (base: string) =>
  postJSON<{ ok: boolean; error?: string }>(base, "/api/logic/launch-pulseview", {});

// --- assistant ------------------------------------------------------------
export interface ChatEvent {
  type: "text" | "tool_use" | "tool_result" | "done" | "turn_end" | "error";
  text?: string; name?: string; provenance?: string | null; error?: string; message?: string;
}
export const getAssistantStatus = (base: string) =>
  getJSON<{ available: boolean; model: string }>(base, "/api/assistant/status", { available: false, model: "" });

export function openChat(base: string, onEvent: (e: ChatEvent) => void, onState: (open: boolean) => void): WebSocket {
  return openWs<ChatEvent>(base, "/ws/chat", onEvent, onState);
}

// --- agent bridge (Layer B) ----------------------------------------------
export interface AgentStatus {
  sdk_installed: boolean;
  claude_cli: string | null;
  api_key: boolean;
  ready: boolean;
  exposed_tools: string[];
  note: string;
}
export const agentStatus = (base: string) =>
  getJSON<AgentStatus>(base, "/api/agent/status", { sdk_installed: false, claude_cli: null, api_key: false, ready: false, exposed_tools: [], note: "" });
export const agentRun = (base: string, prompt: string) =>
  postJSON<{ ok: boolean; error?: string; events?: string[] }>(base, "/api/agent/run", { prompt });

// --- instrument screenshot -----------------------------------------------
export async function fetchScreenshot(base: string, role: string): Promise<Blob | null> {
  try {
    const r = await fetch(`${base}/api/${role}/screenshot`);
    return r.ok ? await r.blob() : null;
  } catch {
    return null;
  }
}

// --- server-side session logging ------------------------------------------
export const logStart = (base: string, role: string) => postJSON<{ ok: boolean }>(base, `/api/log/${role}/start`, {});
export const logStop = (base: string, role: string) => postJSON<{ ok: boolean }>(base, `/api/log/${role}/stop`, {});
export const logClear = (base: string, role: string) => postJSON<{ ok: boolean }>(base, `/api/log/${role}/clear`, {});
export const logStatus = (base: string, role: string) =>
  getJSON<{ active: boolean; count: number }>(base, `/api/log/${role}/status`, { active: false, count: 0 });
export function logExport(base: string, role: string): void {
  const a = document.createElement("a");
  a.href = `${base}/api/log/${role}/export`;
  a.download = `${role}_log.csv`;
  a.click();
}
