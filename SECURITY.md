# Security

## Reporting

Use GitHub's private vulnerability reporting on the
[Security tab](https://github.com/karimrayttu/ece-tool-suite/security/advisories/new).
Please do not open a public issue for anything exploitable.

This is a one-person project, so expect a first reply within a week rather than within a day.

## What the app exposes

The Python sidecar binds `127.0.0.1` only, on port 8848 with fallback to the next free port.
It has no authentication, because anything that can reach the port is already running as you
on your machine. Two consequences worth knowing:

- Do not put the sidecar behind a reverse proxy or bind it to `0.0.0.0`. There is no
  authorization layer to put in front of, and the API can enable a power supply output.
- Any local process can talk to it. On a shared or multi-user machine, treat a running
  instance the way you would treat an unlocked instrument front panel.

The Electron shell generates a per-launch nonce that `/health` echoes back, so it will not
adopt a sidecar it did not start.

## Secrets

API keys are read from environment variables (`ANTHROPIC_API_KEY`, `NEXAR_CLIENT_ID` and
`NEXAR_CLIENT_SECRET`, `DIGIKEY_CLIENT_ID` and `DIGIKEY_CLIENT_SECRET`) and are never written
to disk by the app. Digi-Key credentials entered in the UI stay in backend process memory for
the lifetime of that process.

The audit log at `~/.ece-suite/audit.log.jsonl` records every instrument operation, including
raw SCPI. It does not record credentials, but it does record what you did to your hardware, so
scrub it before attaching it to an issue.

## The safety gates are not a security boundary

The `SafetyInvariantEngine` and `PresetRunner` stop the *application* from energizing a DUT
outside its declared envelope. They are not a defence against a hostile local process, and
they are not a substitute for the instrument's own OVP/OCP settings. The MCP server's
`scpi(..., write=True)` tool is a documented raw passthrough that bypasses them entirely, in
the same way a vendor's interactive IO utility does.

If you are relying on software to keep voltage off something, set the limit on the
instrument's front panel too.

## Supported versions

Fixes go onto `main`. There are no maintained release branches yet.
