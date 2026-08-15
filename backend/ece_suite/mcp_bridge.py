"""Layer B — Claude Code + MCP agentic bridge.

Exposes the app's tools to a Claude agent through an in-process MCP server, but ONLY the
AUTONOMOUS surface — which excludes every SOURCE_CONTROL and confirm-required tool. So the
autonomous agent can read instruments and run analyses, but it physically cannot energize a
DUT or fire a safety-gated preset.

Live agent runs require the `claude` CLI (the Agent SDK's transport) and an API key; the
bridge reports readiness and refuses to run until both are present.
"""

from __future__ import annotations

import json
import os
import shutil

from .registry import Surface, ToolRegistry

MCP_SERVER_NAME = "ece-suite"


def autonomous_tool_specs(registry: ToolRegistry) -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema or {}}
        for s in registry.list_for(Surface.AUTONOMOUS)
    ]


def sdk_installed() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def status(registry: ToolRegistry) -> dict:
    cli = shutil.which("claude")
    key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    sdk = sdk_installed()
    return {
        "sdk_installed": sdk,
        "claude_cli": cli,
        "api_key": key,
        "ready": bool(sdk and cli and key),
        "exposed_tools": [s["name"] for s in autonomous_tool_specs(registry)],
        "note": "Agent runs use the AUTONOMOUS (read-only) surface; source/energize tools are never exposed.",
    }


def _make_tool(registry: ToolRegistry, name: str, description: str, schema: dict, tool):
    @tool(name, description, schema)
    async def _handler(args):  # noqa: ANN001
        try:
            result = registry.call(name, dict(args or {}), surface=Surface.AUTONOMOUS)
            text = json.dumps(result)
        except Exception as e:  # noqa: BLE001
            text = f"ERROR: {e}"
        return {"content": [{"type": "text", "text": text}]}

    return _handler


def build_mcp_server(registry: ToolRegistry):
    """Build an in-process SDK MCP server exposing the AUTONOMOUS tools. Requires the SDK."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    tools = [
        _make_tool(registry, s["name"], s["description"], s["input_schema"], tool)
        for s in autonomous_tool_specs(registry)
    ]
    return create_sdk_mcp_server(name=MCP_SERVER_NAME, version="0.0.0", tools=tools)


async def run_agent_task(registry: ToolRegistry, prompt: str, max_turns: int = 4) -> dict:
    st = status(registry)
    if not st["ready"]:
        missing = [k for k in ("sdk_installed", "claude_cli", "api_key") if not st[k]]
        return {"ok": False, "error": f"agent bridge not ready (missing: {', '.join(missing)})", "status": st}

    from claude_agent_sdk import ClaudeAgentOptions, query

    server = build_mcp_server(registry)
    allowed = [f"mcp__{MCP_SERVER_NAME}__{s['name']}" for s in autonomous_tool_specs(registry)]
    options = ClaudeAgentOptions(
        mcp_servers={MCP_SERVER_NAME: server},
        allowed_tools=allowed,
        max_turns=max_turns,
    )
    events: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        events.append(str(msg))
    return {"ok": True, "events": events}
