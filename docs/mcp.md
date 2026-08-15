# Driving the bench from an agent client

The suite can act as an [MCP](https://modelcontextprotocol.io) server, so Claude Desktop,
Claude Code, Cursor or any other MCP client can read from whatever instruments the app has
connected.

## How it is wired

`ece_suite.mcp_server` is a stdio server that opens no instruments of its own. It calls the
running app's localhost API, so the app keeps sole ownership of the hardware: one connection,
one lock, the same safety gates. Start the app first, then point the client at the server.

## Setup

1. Launch the app and leave it running. The sidecar listens on `127.0.0.1:8848`, or the next
   free port if that one is taken.
2. Open the Connections tab, find the *AI control (MCP server)* card, and press Copy. That
   gives you a config block with your interpreter path already filled in, which is the part
   people most often get wrong. It looks like this:

```json
{
  "mcpServers": {
    "ece-tool-suite": {
      "command": "<path-to-your-clone>\\backend\\.venv\\Scripts\\python.exe",
      "args": ["-m", "ece_suite.mcp_server"],
      "env": { "ECE_SUITE_URL": "http://127.0.0.1:8848" }
    }
  }
}
```

   From a packaged install the interpreter is `backend\runtime\python.exe` under the app's
   resources directory instead. On macOS or Linux it is `backend/.venv/bin/python`.

3. Restart the client.

If the app is not running, the tools return an error saying so rather than trying to open the
instruments themselves.

## Tools

| Tool | What it does |
|---|---|
| `list_instruments` | Connected instruments with vendor, model and provenance tag |
| `io_environment` | What is plugged in, and whether the VISA layer can drive it |
| `autoconnect(lan)` | Discover and bind instruments to roles (USB, plus LAN with `lan`) |
| `scope_measure(ch)` | Full measurement set for one oscilloscope channel |
| `dmm_read` | One meter reading: value, unit, function |
| `spectrum_peak` | Peak marker frequency and amplitude |
| `scpi(role, command, write)` | Raw SCPI query or command to a connected instrument |
| `list_calculators`, `run_calculator(name, params)` | The design calculators |
| `decode_logic(...)` | Decode captured digital channels as SPI, I²C or UART |

Every result carries its provenance tag. A reading from an instrument that has not passed the
verify gate arrives labelled `UNVERIFIED_HW`, and the client sees that label.

## What this path can and cannot do

`scpi(..., write=True)` is a raw passthrough. It goes around the safety engine entirely, which
means an output-enable or a level command will energize your DUT, exactly as a vendor's
interactive IO utility would. Reads and measurements are safe. Every command lands in the
audit log either way.

For sourcing with the protection-before-enable interlock, use the app's Sources tab rather
than raw SCPI.

The separate in-process agent bridge (System tab) is a different thing: it exposes only the
read-only tool surface, and no tool that can energize a DUT is reachable from it at all.
`backend/tests/test_contract.py` asserts that the autonomous surface stays a subset of the
chatbox surface, so the two cannot drift apart without a test failing.
