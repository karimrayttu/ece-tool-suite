"""The standalone MCP server exposes the bench as tools, and the app hands out its config."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from ece_suite import main as _main

# ece_suite.mcp_server imports the `mcp` package at module level, and that lives in the
# `assistant` extra. Skip the file rather than failing collection, so a core-only install
# still gives a clean run.
pytest.importorskip("mcp", reason="MCP server needs the `assistant` extra")

from ece_suite import mcp_server  # noqa: E402 - must follow the importorskip above


def test_mcp_server_tool_surface():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert {"list_instruments", "autoconnect", "scope_measure", "dmm_read", "scpi",
            "run_calculator", "list_calculators", "io_environment", "decode_logic"} <= names


def test_mcp_info_endpoint_gives_client_config():
    client = TestClient(_main.app)
    info = client.get("/api/mcp/info").json()
    assert info["available"] is True
    assert info["server_name"] == "ece-tool-suite"
    assert info["args"] == ["-m", "ece_suite.mcp_server"]
    cfg = json.loads(info["config_json"])
    assert "ece-tool-suite" in cfg["mcpServers"]
    assert cfg["mcpServers"]["ece-tool-suite"]["args"] == ["-m", "ece_suite.mcp_server"]


def test_dmm_read_endpoint_honest_when_disconnected():
    client = TestClient(_main.app)
    _main.manager.disconnect("dmm")
    assert client.get("/api/dmm/read").json()["connected"] is False
