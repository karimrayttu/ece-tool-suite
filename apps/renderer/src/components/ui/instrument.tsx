// Hardware-instrument primitives for the rack-edition UI: rotary knobs, LEDs, inset
// CRT-style screens and LED segment meters. Pure SVG/CSS — no external assets — styled
// after pro plugin hardware (tick-ring knobs, phosphor glows, chassis wells).
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../../lib/utils";

// --- Knob ------------------------------------------------------------------
// 270° rotary: track arc from 135° to 405°, neon value arc with glow, dark cap with a
// white indicator. Drag vertically (shift = fine), double-click resets, wheel nudges.
export interface KnobProps {
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  label?: string;
  unit?: string;
  size?: "sm" | "md" | "lg";
  color?: string;          // css colour for the value arc + readout
  defaultValue?: number;
  step?: number;
  format?: (v: number) => string;
  disabled?: boolean;
}

const SIZES = { sm: 44, md: 60, lg: 76 };

function polar(cx: number, cy: number, r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
}

function arcPath(cx: number, cy: number, r: number, startDeg: number, endDeg: number) {
  const s = polar(cx, cy, r, startDeg);
  const e = polar(cx, cy, r, endDeg);
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${s.x.toFixed(2)} ${s.y.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${e.x.toFixed(2)} ${e.y.toFixed(2)}`;
}

export function Knob({
  value, min, max, onChange, label, unit, size = "md", color = "#4f9dff",
  defaultValue, step, format, disabled, ticks = 11, showScale = false,
}: KnobProps & { ticks?: number; showScale?: boolean }) {
  const px = SIZES[size];
  const r = px / 2 - 6;
  const cx = px / 2, cy = px / 2;
  const START = -135, END = 135; // degrees, 0 = up
  const frac = max > min ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0;
  const angle = START + frac * (END - START);
  const drag = useRef<{ y: number; v: number } | null>(null);

  const clamp = useCallback((v: number) => {
    let x = Math.min(max, Math.max(min, v));
    if (step) x = Math.round(x / step) * step;
    return x;
  }, [min, max, step]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (disabled) return;
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { y: e.clientY, v: value };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const range = max - min;
    const px150 = e.shiftKey ? 600 : 150; // pixels for full sweep; shift = fine
    const dv = ((drag.current.y - e.clientY) / px150) * range;
    onChange(clamp(drag.current.v + dv));
  };
  const onPointerUp = () => { drag.current = null; };
  const onWheel = (e: React.WheelEvent) => {
    if (disabled) return;
    const range = max - min;
    const dv = (e.deltaY < 0 ? 1 : -1) * (e.shiftKey ? range / 200 : range / 40);
    onChange(clamp(value + dv));
  };
  const onDoubleClick = () => { if (defaultValue !== undefined && !disabled) onChange(clamp(defaultValue)); };

  const shown = format ? format(value) : `${Number(value.toPrecision(4))}${unit ? ` ${unit}` : ""}`;
  const ind = polar(cx, cy, r - 4, angle);

  return (
    <div className={cn("flex select-none flex-col items-center gap-1", disabled && "opacity-40")}>
      <svg
        width={px} height={px} viewBox={`0 0 ${px} ${px}`}
        className={cn("touch-none", !disabled && "cursor-ns-resize")}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove}
        onPointerUp={onPointerUp} onWheel={onWheel} onDoubleClick={onDoubleClick}
        role="slider" aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} aria-label={label}
      >
        <defs>
          <radialGradient id="knobCap" cx="38%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#2a323e" />
            <stop offset="55%" stopColor="#1a202a" />
            <stop offset="100%" stopColor="#0e1218" />
          </radialGradient>
        </defs>
        {/* tick ring: radial marks, majors longer than minors */}
        {Array.from({ length: ticks }, (_, i) => {
          const a = START + (i / (ticks - 1)) * (END - START);
          const major = i % 2 === 0;
          const o = polar(cx, cy, r + 1.5, a);
          const n = polar(cx, cy, r - (major ? 3 : 1.2), a);
          const active = a <= angle + 0.01;
          return (
            <line key={i} x1={n.x} y1={n.y} x2={o.x} y2={o.y}
              stroke={active ? color : "#39424f"} strokeWidth={major ? 1.4 : 0.9}
              strokeLinecap="round" opacity={active ? 0.9 : major ? 0.75 : 0.55} />
          );
        })}
        {/* value arc with glow (inside the ticks) */}
        {frac > 0.004 && (
          <path d={arcPath(cx, cy, r - 4.5, START, angle)} stroke={color} strokeWidth={2.4}
            fill="none" strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 3px ${color}) drop-shadow(0 0 8px ${color}55)` }} />
        )}
        {/* matte cap */}
        <circle cx={cx} cy={cy} r={r - 8} fill="url(#knobCap)" stroke="#323b48" strokeWidth={1} />
        <ellipse cx={cx - r * 0.12} cy={cy - r * 0.28} rx={r * 0.42} ry={r * 0.3}
          fill="rgba(255,255,255,0.06)" />
        {/* indicator */}
        <line x1={cx + (ind.x - cx) * 0.4} y1={cy + (ind.y - cy) * 0.4} x2={cx + (ind.x - cx) * 0.82} y2={cy + (ind.y - cy) * 0.82}
          stroke="#eef3f9" strokeWidth={2.2} strokeLinecap="round" />
      </svg>
      {showScale && (
        <div className="-mt-1 flex w-full justify-between px-0.5 font-mono text-[8.5px] text-muted/80">
          <span>{format ? format(min) : min}</span>
          <span>{format ? format(max) : max}</span>
        </div>
      )}
      {label && <span className="module-label !text-[9px] leading-none">{label}</span>}
      {/* bordered value chip: reads as a machined readout rather than floating text */}
      <span className="rounded-[3px] border border-line bg-panel2 px-1.5 py-[3px] font-mono text-[10.5px] leading-none tracking-wide shadow-[inset_0_1px_2px_rgba(0,0,0,0.45)]"
        style={{ color }}>{shown}</span>
    </div>
  );
}

// --- LED -------------------------------------------------------------------
const LED_COLORS: Record<string, { on: string; glow: string }> = {
  cyan: { on: "#4f9dff", glow: "0 0 6px rgba(79,157,255,.8), 0 0 14px rgba(79,157,255,.35)" },
  green: { on: "#34d399", glow: "0 0 6px rgba(52,211,153,.8), 0 0 14px rgba(52,211,153,.35)" },
  amber: { on: "#fbbf24", glow: "0 0 6px rgba(251,191,36,.8), 0 0 14px rgba(251,191,36,.35)" },
  red: { on: "#fb7185", glow: "0 0 6px rgba(251,113,133,.8), 0 0 14px rgba(251,113,133,.35)" },
  violet: { on: "#a78bfa", glow: "0 0 6px rgba(167,139,250,.8), 0 0 14px rgba(167,139,250,.35)" },
};

export function Led({ on = true, color = "cyan", breathe = false, className }: {
  on?: boolean; color?: keyof typeof LED_COLORS; breathe?: boolean; className?: string;
}) {
  const c = LED_COLORS[color] ?? LED_COLORS.cyan;
  return (
    <span
      className={cn("inline-block h-[7px] w-[7px] shrink-0 rounded-full", breathe && on && "animate-led-breathe", className)}
      style={on ? { background: c.on, boxShadow: c.glow } : { background: "#242b35", boxShadow: "inset 0 1px 2px rgba(0,0,0,.6)" }}
    />
  );
}

// --- Screen ----------------------------------------------------------------
// Inset CRT-style display well: glare + scanlines via .crt-screen (index.css).
export function Screen({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cn("crt-screen", className)}>{children}</div>;
}

// --- Analog VU meter --------------------------------------------------------
// Cream-faced needle meter (tube-compressor style): arc scale with red overload zone,
// spring-damped needle via CSS transition. value is 0..1 of full scale.
export function VuMeter({ value, label = "VU", legend, width = 190, className }: {
  value: number; label?: string; legend?: string; width?: number; className?: string;
}) {
  const h = width * 0.56;
  const cx = width / 2, cy = h * 0.92, R = width * 0.40;
  const START = -48, END = 48;                       // needle sweep degrees
  const v = Math.min(1, Math.max(0, value));
  const angle = START + v * (END - START);
  const scaleArc = arcPath(cx, cy, R, START, END);
  const redArc = arcPath(cx, cy, R, START + 0.78 * (END - START), END);
  return (
    <div className={cn("inline-flex flex-col items-center gap-1", className)}>
      <div className="rounded-lg border border-[#2c333e] bg-[#181d24] p-1.5 shadow-well">
        <svg width={width} height={h} viewBox={`0 0 ${width} ${h}`} className="rounded-md"
          style={{ background: "linear-gradient(180deg,#efe8d8 0%,#e6dcc6 70%,#ded2b8 100%)" }}>
          {/* scale */}
          <path d={scaleArc} stroke="#3a3630" strokeWidth={1.6} fill="none" />
          <path d={redArc} stroke="#b3372e" strokeWidth={3} fill="none" />
          {Array.from({ length: 11 }, (_, i) => {
            const a = START + (i / 10) * (END - START);
            const o = polar(cx, cy, R + 5, a);
            const n = polar(cx, cy, R - (i % 5 === 0 ? 4 : 1), a);
            return <line key={i} x1={n.x} y1={n.y} x2={o.x} y2={o.y}
              stroke={a > START + 0.78 * (END - START) ? "#b3372e" : "#3a3630"} strokeWidth={i % 5 === 0 ? 1.4 : 0.9} />;
          })}
          <text x={cx} y={h * 0.62} textAnchor="middle" fontFamily="Georgia, serif"
            fontSize={h * 0.2} fontWeight={600} fill="#37332c">{label}</text>
          {/* needle: spring-ish ease via transition on the rotation group */}
          <g style={{ transition: "transform 380ms cubic-bezier(.2,1.4,.4,1)", transform: `rotate(${angle}deg)`, transformOrigin: `${cx}px ${cy}px` }}>
            <line x1={cx} y1={cy} x2={cx} y2={cy - (R - 4)} stroke="#1c1a17" strokeWidth={1.8} />
          </g>
          <circle cx={cx} cy={cy} r={4.5} fill="#23201c" />
          {/* glass glare */}
          <rect x={0} y={0} width={width} height={h * 0.4} fill="url(#vuGlare)" opacity={0.5} />
          <defs>
            <linearGradient id="vuGlare" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ffffff" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
            </linearGradient>
          </defs>
        </svg>
      </div>
      {legend && <span className="module-label !text-[9px]">{legend}</span>}
    </div>
  );
}

// --- Fader ------------------------------------------------------------------
// Vertical slider with a groove track, orange value line and a grip handle (KOSMA-style).
export function Fader({ value, min, max, onChange, label, height = 120, disabled, format }: {
  value: number; min: number; max: number; onChange: (v: number) => void;
  label?: string; height?: number; disabled?: boolean; format?: (v: number) => string;
}) {
  const frac = max > min ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0;
  const drag = useRef<{ y: number; v: number } | null>(null);
  const onPointerDown = (e: React.PointerEvent) => {
    if (disabled) return;
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { y: e.clientY, v: value };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const dv = ((drag.current.y - e.clientY) / height) * (max - min) * (e.shiftKey ? 0.25 : 1);
    onChange(Math.min(max, Math.max(min, drag.current.v + dv)));
  };
  return (
    <div className={cn("flex select-none flex-col items-center gap-1", disabled && "opacity-40")}>
      <div
        className={cn("relative w-[26px] touch-none rounded-full border border-[#272e38] bg-[#0c1015] shadow-well", !disabled && "cursor-ns-resize")}
        style={{ height }}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove}
        onPointerUp={() => { drag.current = null; }}
        role="slider" aria-valuemin={min} aria-valuemax={max} aria-valuenow={value} aria-label={label}
      >
        {/* orange value line */}
        <div className="absolute left-1/2 w-[3px] -translate-x-1/2 rounded-full bg-[#f97316]"
          style={{ bottom: 6, height: Math.max(0, (height - 12) * frac), boxShadow: "0 0 6px rgba(249,115,22,.6)" }} />
        {/* grip */}
        <div className="absolute left-1/2 h-[16px] w-[22px] -translate-x-1/2 rounded-[5px] border border-[#39424f] bg-gradient-to-b from-[#2a323e] to-[#151a22]"
          style={{ bottom: 6 + (height - 12 - 16) * frac, boxShadow: "0 2px 5px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.08)" }}>
          <div className="mx-auto mt-[6px] h-[2px] w-[12px] rounded bg-[#f97316]" />
        </div>
      </div>
      {label && <span className="module-label !text-[9px]">{label}</span>}
      <span className="font-mono text-[10.5px] text-ink/80">{format ? format(value) : Number(value.toPrecision(3))}</span>
    </div>
  );
}

// --- Pill button + rocker toggle -------------------------------------------
export function Pill({ on, onClick, children, className, disabled }: {
  on?: boolean; onClick?: () => void; children: React.ReactNode; className?: string; disabled?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled}
      className={cn(
        "rounded-full border px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] transition-all",
        on
          ? "border-ink/30 bg-ink/10 text-ink shadow-[inset_0_1px_3px_rgba(0,0,0,.5)]"
          : "border-[#2c343f] bg-gradient-to-b from-[#232a34] to-[#161b22] text-muted shadow-[0_2px_5px_rgba(0,0,0,.4),inset_0_1px_0_rgba(255,255,255,.06)] hover:text-ink",
        className,
      )}>
      {children}
    </button>
  );
}

export function Rocker({ value, options, onChange, label }: {
  value: string; options: [string, string]; onChange: (v: string) => void; label?: string;
}) {
  const right = value === options[1];
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider">
        <span className={right ? "text-muted" : "text-ink"}>{options[0]}</span>
        <button onClick={() => onChange(right ? options[0] : options[1])}
          className="relative h-[14px] w-[26px] rounded-full border border-[#323b48] bg-[#0d1117] shadow-well">
          <span className="absolute top-1/2 h-[9px] w-[9px] -translate-y-1/2 rounded-full bg-ink/85 transition-all"
            style={{ left: right ? 14 : 3, boxShadow: "0 0 4px rgba(231,236,243,.5)" }} />
        </button>
        <span className={right ? "text-ink" : "text-muted"}>{options[1]}</span>
      </div>
      {label && <span className="module-label !text-[9px]">{label}</span>}
    </div>
  );
}

// --- Segment meter ---------------------------------------------------------
// LED bar: green → amber → red segments with a decaying peak-hold tick.
export function SegMeter({ value, segments = 24, className }: {
  value: number; segments?: number; className?: string;
}) {
  const [peak, setPeak] = useState(0);
  const peakRef = useRef(0);
  useEffect(() => {
    if (value >= peakRef.current) {
      peakRef.current = value;
      setPeak(value);
      return;
    }
    const t = setInterval(() => {
      peakRef.current = Math.max(value, peakRef.current - 0.012);
      setPeak(peakRef.current);
    }, 50);
    return () => clearInterval(t);
  }, [value]);
  const lit = Math.round(Math.min(1, Math.max(0, value)) * segments);
  const peakSeg = Math.round(Math.min(1, Math.max(0, peak)) * segments);
  return (
    <div className={cn("flex items-end gap-[2px]", className)}>
      {Array.from({ length: segments }, (_, i) => {
        const frac = i / segments;
        const color = frac < 0.6 ? "#34d399" : frac < 0.85 ? "#fbbf24" : "#fb7185";
        const isOn = i < lit;
        const isPeak = i === peakSeg - 1 && peakSeg > lit;
        return (
          <span key={i} className="h-[10px] w-[3px] rounded-[1px]"
            style={{
              background: isOn || isPeak ? color : "#1c222c",
              boxShadow: isOn ? `0 0 4px ${color}88` : undefined,
              opacity: isPeak && !isOn ? 0.9 : 1,
            }} />
        );
      })}
    </div>
  );
}
