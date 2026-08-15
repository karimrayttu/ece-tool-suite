import {
  Activity,
  Binary,
  Cable,
  CircuitBoard,
  Cpu,
  Download,
  FileCode,
  Gauge,
  GitBranch,
  HardDriveDownload,
  LayoutDashboard,
  PlugZap,
  RadioTower,
  Server,
  Workflow,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";

interface NavItem {
  key: string;
  label: string;
  icon: LucideIcon;
}

const GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Instruments",
    items: [
      { key: "workbench", label: "Workbench", icon: LayoutDashboard },
      { key: "scope", label: "Oscilloscope", icon: Activity },
      { key: "dmm", label: "Multimeter", icon: Gauge },
      { key: "sa", label: "Spectrum", icon: RadioTower },
      { key: "source", label: "Sources", icon: Zap },
    ],
  },
  {
    title: "Design",
    items: [
      { key: "parts", label: "Parts", icon: Cpu },
      { key: "kicad", label: "KiCad", icon: CircuitBoard },
      { key: "stm32", label: "STM32 & Tools", icon: Cpu },
      { key: "circuit", label: "Calculators", icon: Workflow },
      { key: "logic", label: "Logic Analyzer", icon: Binary },
      { key: "rtl", label: "RTL / HDL", icon: FileCode },
      { key: "labview", label: "LabVIEW", icon: GitBranch },
      { key: "programmer", label: "Programmer", icon: HardDriveDownload },
      { key: "can", label: "CAN bus", icon: Cable },
    ],
  },
  {
    title: "Workspace",
    items: [
      { key: "connections", label: "Connections", icon: PlugZap },
      { key: "setup", label: "Software Setup", icon: Download },
      { key: "system", label: "System", icon: Server },
    ],
  },
];

export function Sidebar({ active = "scope", onSelect }: { active?: string; onSelect?: (k: string) => void }) {
  return (
    <nav className="flex w-[220px] shrink-0 flex-col gap-4 overflow-y-auto border-r border-line bg-panel2 px-3 py-4">
      {GROUPS.map((group) => (
        <div key={group.title} className="flex flex-col gap-1">
          <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-widest text-muted/80">
            {group.title}
          </div>
          {group.items.map(({ key, label, icon: Icon }) => {
            const on = key === active;
            return (
              <button
                key={key}
                onClick={() => onSelect?.(key)}
                className={cn(
                  "group relative flex items-center gap-3 rounded-lg border px-3 py-2 text-left text-[13px] font-medium transition-all",
                  on
                    ? "border-line bg-panel text-ink shadow-panel"
                    : "border-transparent text-muted hover:bg-panel/60 hover:text-ink",
                )}
              >
                {on && (
                  <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-accent shadow-glow-cyan" />
                )}
                <Icon
                  className={cn(
                    "h-[18px] w-[18px] transition-colors",
                    on ? "text-accent drop-shadow-[0_0_4px_rgba(45,212,234,0.6)]" : "text-muted group-hover:text-ink",
                  )}
                  strokeWidth={2}
                />
                {label}
                {on && (
                  <span className="ml-auto h-[5px] w-[5px] rounded-full bg-accent shadow-glow-cyan" aria-hidden />
                )}
              </button>
            );
          })}
        </div>
      ))}
      <div className="mt-auto px-3 pt-2 text-[11px] leading-relaxed text-muted/70">
        Hardware-first · lab-truth gated
      </div>
    </nav>
  );
}
