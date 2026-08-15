import { Bot, ChevronLeft, ChevronRight, Send, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  baseUrl,
  getAssistantStatus,
  openChat,
  PROVENANCE_TONE,
  type ChatEvent,
  type Provenance,
} from "../lib/api";
import { cn } from "../lib/utils";
import { Badge } from "./ui/badge";

type ToolChip = { name: string; provenance?: string | null; error?: string };
type ChatMsg = { role: "user" | "assistant" | "error"; text: string; tools: ToolChip[] };

export function AssistantDrawer() {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [model, setModel] = useState("");
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("ece.assistant.collapsed") === "1",
  );

  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let stop = false;
    (async () => {
      const base = await baseUrl();
      const st = await getAssistantStatus(base);
      if (stop) return;
      setAvailable(st.available);
      setModel(st.model);
      wsRef.current = openChat(base, onEvent, (o) => !stop && setConnected(o));
    })();
    return () => {
      stop = true;
      wsRef.current?.close();
    };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  function onEvent(e: ChatEvent) {
    setMessages((prev) => {
      const next = prev.map((m) => ({ ...m, tools: [...m.tools] }));
      const last = next[next.length - 1];
      if (e.type === "text" && last?.role === "assistant") {
        last.text += e.text ?? "";
      } else if (e.type === "tool_use" && last?.role === "assistant") {
        last.tools.push({ name: e.name ?? "tool" });
      } else if (e.type === "tool_result" && last?.role === "assistant") {
        for (let i = last.tools.length - 1; i >= 0; i--) {
          if (last.tools[i].name === e.name && last.tools[i].provenance === undefined && !last.tools[i].error) {
            last.tools[i] = { ...last.tools[i], provenance: e.provenance ?? null, error: e.error };
            break;
          }
        }
      } else if (e.type === "error") {
        next.push({ role: "error", text: e.message ?? "error", tools: [] });
      }
      return next;
    });
    if (e.type === "turn_end" || e.type === "error") setStreaming(false);
  }

  function send() {
    const msg = input.trim();
    if (!msg || streaming || !available) return;
    setMessages((p) => [
      ...p,
      { role: "user", text: msg, tools: [] },
      { role: "assistant", text: "", tools: [] },
    ]);
    setInput("");
    setStreaming(true);
    wsRef.current?.send(JSON.stringify({ message: msg }));
  }

  const placeholder =
    available === null ? "connecting…" : available ? "Ask the assistant…" : "Assistant disabled (no API key)";

  useEffect(() => {
    localStorage.setItem("ece.assistant.collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  // Collapsed, the drawer is a 36px rail. On a 1280-wide laptop that 300px back is the
  // difference between a readable waveform and a cramped one, so it is worth a click.
  if (collapsed) {
    return (
      <aside className="flex w-9 shrink-0 flex-col items-center border-l border-line bg-panel2 py-2.5">
        <button
          onClick={() => setCollapsed(false)}
          title="Show assistant"
          aria-label="Show assistant"
          className="rounded-md p-1.5 text-muted hover:bg-line hover:text-ink"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <Bot className="mt-2 h-4 w-4 text-muted" />
      </aside>
    );
  }

  return (
    <aside className="flex w-[336px] shrink-0 flex-col border-l border-line bg-panel2">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2.5">
        <Bot className="h-4 w-4 text-accent" />
        <span className="text-sm font-semibold">Assistant</span>
        <span className={cn("text-[11px]", connected ? "text-verified" : "text-muted")}>●</span>
        <span className="ml-auto font-mono text-[11px] text-muted">{model || "Claude"}</span>
        <button
          onClick={() => setCollapsed(true)}
          title="Hide assistant"
          aria-label="Hide assistant"
          className="-mr-1 rounded-md p-1 text-muted hover:bg-line hover:text-ink"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {available === false && (
        <div className="m-3 flex items-start gap-2 rounded-lg border border-sim/40 bg-panel px-3 py-2 text-xs text-sim">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            Set <code className="font-mono">ANTHROPIC_API_KEY</code> in the backend environment to
            enable the assistant, then restart the sidecar.
          </span>
        </div>
      )}

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && (
          <div className="text-xs text-muted">
            Ask about the bench — e.g. “measure CH1 Vpp” or “what does the I²C preset configure?”.
            Tool results are provenance-tagged; the assistant cannot energize the DUT on its own.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={cn("flex flex-col gap-1", m.role === "user" ? "items-end" : "items-start")}>
            <div
              className={cn(
                "max-w-[92%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm",
                m.role === "user"
                  ? "bg-accent/15 text-ink"
                  : m.role === "error"
                    ? "border border-danger/40 text-danger"
                    : "bg-panel text-ink",
              )}
            >
              {m.text || (m.role === "assistant" && streaming ? "…" : "")}
            </div>
            {m.tools.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {m.tools.map((t, j) => (
                  <Badge
                    key={j}
                    tone={t.error ? "danger" : t.provenance ? PROVENANCE_TONE[t.provenance as Provenance] : "muted"}
                  >
                    {t.name}
                    {t.provenance ? ` · ${t.provenance}` : t.error ? " · blocked" : " …"}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 border-t border-line p-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
          disabled={!available}
          placeholder={placeholder}
          className="flex-1 rounded-lg border border-line bg-panel px-3 py-2 text-sm text-ink placeholder:text-muted/60 disabled:cursor-not-allowed"
        />
        <button
          onClick={send}
          disabled={!available || streaming || !input.trim()}
          className={cn(
            "grid h-9 w-9 shrink-0 place-items-center rounded-lg",
            !available || streaming || !input.trim()
              ? "cursor-not-allowed bg-line text-muted"
              : "bg-accent text-bg hover:opacity-90",
          )}
        >
          <Send className="h-4 w-4" />
        </button>
      </div>
    </aside>
  );
}
