"""In-app Claude assistant (Layer A).

A streaming agent loop on the Anthropic SDK, wired to the shared tool registry. Every tool
result it receives carries its provenance tag, so the model is structurally prevented from
presenting a simulated reading as a real one. The model may *see* source-control tools (to
guide the user) but cannot self-confirm an energize — the registry refuses that.

The Anthropic client is injectable so the loop is testable without a live API call.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from .registry import Surface, ToolRegistry

DEFAULT_MODEL = os.environ.get("ECE_SUITE_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = (
    "You are the in-app assistant for an electrical engineer's bench tool suite "
    "(oscilloscope, DMM, spectrum analyzer, power supply). You can call tools to read "
    "instruments and run analyses.\n\n"
    "CRITICAL — PROVENANCE: every tool result includes a `_provenance` field that is one of "
    "SIMULATED, UNVERIFIED_HW, or VERIFIED_HW. You MUST relay this honestly. If a value is "
    "SIMULATED, say so plainly — it is NOT a real measurement, there is no hardware "
    "connected. Never present a simulated or unverified value as a confirmed measurement.\n\n"
    "SAFETY: you may describe source/load (power-supply) presets, but you cannot energize "
    "anything yourself — those require the user to confirm in the UI. If a tool returns a "
    "'requires explicit human confirmation' error, tell the user to use the preset's confirm "
    "control; do not retry.\n\n"
    "Be concise and quantitative, like a good lab partner."
)


def build_tool_defs(registry: ToolRegistry, surface: Surface) -> list[dict]:
    """Anthropic tool definitions from the registry's surface projection."""
    defs = []
    for spec in registry.list_for(surface):
        defs.append({
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema or {"type": "object", "properties": {}},
        })
    return defs


class Assistant:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        client: Any = None,
        surface: Surface = Surface.CHATBOX,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        max_tokens: int = 2048,
        max_hops: int = 8,
    ):
        self.registry = registry
        self.surface = surface
        self.model = model
        self.max_tokens = max_tokens
        self.max_hops = max_hops
        self._client = client
        self._api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY")

    def available(self) -> bool:
        return self._client is not None or bool(self._api_key)

    def _ensure_client(self) -> Any:
        if self._client is None:
            from anthropic import AsyncAnthropic  # lazy: only needed for the real path

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def run(self, user_message: str, history: list[dict] | None = None) -> AsyncIterator[dict]:
        """Stream events: {type:text|tool_use|tool_result|done|error, ...}."""
        if not self.available():
            yield {"type": "error", "message":
                   "No ANTHROPIC_API_KEY configured. Set it (or the assistant extra) to enable chat."}
            return

        client = self._ensure_client()
        tools = build_tool_defs(self.registry, self.surface)
        messages: list[dict] = list(history or []) + [{"role": "user", "content": user_message}]

        for _ in range(self.max_hops):
            async with client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            ) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if getattr(delta, "type", None) == "text_delta":
                            yield {"type": "text", "text": delta.text}
                final = await stream.get_final_message()

            messages.append({"role": "assistant", "content": final.content})
            tool_uses = [b for b in final.content if getattr(b, "type", None) == "tool_use"]

            if final.stop_reason == "tool_use" and tool_uses:
                tool_results = []
                for tu in tool_uses:
                    yield {"type": "tool_use", "name": tu.name, "input": dict(tu.input or {})}
                    try:
                        result = self.registry.call(tu.name, dict(tu.input or {}), surface=self.surface)
                        yield {"type": "tool_result", "name": tu.name, "provenance": result.get("_provenance")}
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result),
                        })
                    except Exception as e:  # noqa: BLE001 - surface tool errors back to the model
                        yield {"type": "tool_result", "name": tu.name, "provenance": None, "error": str(e)}
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": tu.id,
                            "content": f"ERROR: {e}", "is_error": True,
                        })
                messages.append({"role": "user", "content": tool_results})
                continue

            yield {"type": "done", "stop_reason": final.stop_reason}
            return

        yield {"type": "done", "stop_reason": "max_hops_reached"}
