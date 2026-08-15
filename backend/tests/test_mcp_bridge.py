"""Layer B bridge: only AUTONOMOUS (read-only) tools are exposed; runs gate on readiness."""

from ece_suite.main import registry
from ece_suite.mcp_bridge import (
    autonomous_tool_specs,
    build_mcp_server,
    run_agent_task,
    sdk_installed,
    status,
)


def test_autonomous_specs_exclude_source_control():
    names = {s["name"] for s in autonomous_tool_specs(registry)}
    assert "scope_capture" in names and "dmm_measure_vdc" in names
    assert "psu_apply_preset" not in names  # SOURCE_CONTROL is never exposed to the agent


def test_status_shape_and_not_ready_here():
    st = status(registry)
    for k in ("sdk_installed", "claude_cli", "api_key", "ready", "exposed_tools"):
        assert k in st
    assert isinstance(st["exposed_tools"], list)
    # no claude CLI / key in this environment
    assert st["ready"] is False


def test_build_mcp_server_when_sdk_present():
    if sdk_installed():
        server = build_mcp_server(registry)
        assert server is not None


async def test_run_blocked_when_not_ready():
    if not status(registry)["ready"]:
        r = await run_agent_task(registry, "measure CH1 Vpp")
        assert r["ok"] is False and "not ready" in r["error"]
