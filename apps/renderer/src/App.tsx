import { useEffect, useState } from "react";
import { AssistantDrawer } from "./components/AssistantDrawer";
import { CalculatorsPanel } from "./components/CalculatorsPanel";
import { CanTab } from "./components/CanTab";
import { ConnectionsTab } from "./components/ConnectionsTab";
import { DmmTab } from "./components/DmmTab";
import { IoWatcher } from "./components/IoWatcher";
import { KicadPanel } from "./components/KicadPanel";
import { LabviewTab } from "./components/LabviewTab";
import { LogicTab } from "./components/LogicTab";
import { SetupTab } from "./components/SetupTab";
import { PartsPanel } from "./components/PartsPanel";
import { ProgrammerTab } from "./components/ProgrammerTab";
import { ProvenanceBar } from "./components/ProvenanceBar";
import { RtlTab } from "./components/RtlTab";
import { SaTab } from "./components/SaTab";
import { ScopeTab } from "./components/ScopeTab";
import { SourcesTab } from "./components/SourcesTab";
import { Stm32Tab } from "./components/Stm32Tab";
import { SystemTab } from "./components/SystemTab";
import { WorkbenchTab } from "./components/WorkbenchTab";
import { Sidebar } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { baseUrl, getHealth, type Health } from "./lib/api";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [view, setView] = useState("workbench");

  useEffect(() => {
    let stop = false;
    let id: number | undefined;
    (async () => {
      const base = await baseUrl();
      const tick = async () => {
        const h = await getHealth(base);
        if (!stop) setHealth(h);
      };
      await tick();
      id = window.setInterval(tick, 3000);
    })();
    return () => { stop = true; if (id) clearInterval(id); };
  }, []);

  return (
    <div className="flex h-full flex-col">
      <ProvenanceBar health={health} />
      <IoWatcher />
      <div className="flex min-h-0 flex-1">
        <Sidebar active={view} onSelect={setView} />
        <main key={view} className="flex min-h-0 flex-1 animate-fade-up flex-col gap-3 overflow-y-auto p-3">
          {view === "workbench" && <WorkbenchTab />}
          {view === "scope" && <ScopeTab />}
          {view === "dmm" && <DmmTab />}
          {view === "sa" && <SaTab />}
          {view === "parts" && <PartsPanel />}
          {view === "kicad" && <KicadPanel />}
          {view === "circuit" && <CalculatorsPanel />}
          {view === "source" && <SourcesTab />}
          {view === "logic" && <LogicTab />}
          {view === "rtl" && <RtlTab />}
          {view === "labview" && <LabviewTab />}
          {view === "setup" && <SetupTab />}
          {view === "programmer" && <ProgrammerTab />}
          {view === "stm32" && <Stm32Tab />}
          {view === "can" && <CanTab />}
          {view === "connections" && <ConnectionsTab />}
          {view === "system" && <SystemTab />}
        </main>
        <AssistantDrawer />
      </div>
      <StatusBar health={health} />
    </div>
  );
}
