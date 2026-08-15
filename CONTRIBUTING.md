# Contributing

This is a personal project that grew large enough to be worth publishing. Issues and pull
requests are welcome. The notes below are what I would want to know before touching the code.

## Getting a working checkout

```powershell
git clone https://github.com/karimrayttu/ece-tool-suite.git
cd ece-tool-suite
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
npm test
```

`scripts/setup.sh` is the POSIX equivalent. You need CPython 3.12 or newer and Node 18 or
newer. The setup script installs the optional extras by default; pass `-Minimal` / `--minimal`
if you only want the core and the test dependencies.

No instrument is required to develop. The test suite drives simulated transports, and every
feature that shells out to a vendor tool (Yosys, Icarus, LTspice, LabVIEWCLI, CubeMX) detects
whether the tool is present and skips its tests when it is not. A clean checkout on a machine
with none of those installed should still give you a green run with a pile of skips.

## Layout

| Path | What lives there |
|---|---|
| `backend/ece_suite/` | FastAPI sidecar. One module per feature area. |
| `backend/ece_suite/instruments/` | Transports, SCPI, vendor dialects, capability profiles, sim models. |
| `backend/tests/` | pytest suite. |
| `apps/renderer/src/components/` | One React component per tab, named after the tab. |
| `apps/desktop/` | Electron main process, preload, sidecar lifecycle. |
| `docs/tutorial/` | Seven chapters covering the code, with screenshots. |

`backend/ece_suite/main.py` holds the whole HTTP and WebSocket surface. It is long. Splitting
it into routers is on the list, but the tests import symbols from it directly, so that change
has to happen in one piece rather than incrementally.

## Rules that are not style preferences

Three things in this codebase exist to stop it from lying about hardware. Changes that weaken
them will not be merged.

**Provenance cannot be raised silently.** A `Reading` or `Waveform` cannot be constructed
without a tag, and `provenance.py` only allows trust to go down. If you find yourself wanting
to hand-write `VERIFIED_HW`, the answer is to run the verify gate, not to relabel the data.

**Protective limits go on before the output goes on.** `PresetRunner` sets OVP/OCP, reads them
back, and only then enables. If any step fails it forces the output off and rolls back. New
sourcing paths route through it rather than writing `:OUTP ON` themselves.

**The autonomous agent surface is a subset of the chatbox surface.** `test_contract.py`
asserts this. Tools that can energize a DUT are not reachable from the agent bridge at all,
and that is a structural property, not a prompt instruction.

## Adding an instrument

Most models need a capability profile and a few command overrides, not a new driver.

1. Add the vendor's SCPI differences to `instruments/vendors.py`.
2. Describe what the model can actually do in `instruments/capabilities.py`. The UI reads
   this and hides controls the instrument does not have, so an over-generous profile shows
   users buttons that will error.
3. Add a sim model under `instruments/sim/` if you want tests without the hardware.
4. Add tests to `test_vendors_multivendor.py`.

If you have the instrument on your bench, say so in the PR and paste the `*IDN?` string. If
you do not, say that too. A profile written from the programming manual alone is still useful;
it just needs to be labelled as untested so someone with the box can confirm it.

## Tests

```powershell
npm test                                        # whole suite, quiet
npm run lint                                    # ruff, and CI fails on a finding
node scripts/python.js -m pytest -v -k safety   # one area, verbose
```

New behaviour needs a test. Bug fixes need a test that fails before the fix. Tests that need
an external tool use `pytest.mark.skipif` with a reason string, following the pattern already
in `test_rtl.py`.

## Style

Python targets 3.12 with `from __future__ import annotations` at the top of each module, and
sticks to the standard library plus what is already in `pyproject.toml`. Lines wrap at 100 by
convention, and `ruff` enforces the rest; its config in `backend/pyproject.toml` says why each
disabled rule is disabled. Docstrings explain why a piece of hardware behaves the way it does;
they do not restate the code.

TypeScript is strict. Components are function components with hooks, one per file, and shared
primitives live in `components/ui/`. Tailwind classes only, no separate stylesheets.

Commit messages describe the change in the imperative: `Add Siglent SDS1000X-E scope profile`,
not `updated files`.

## What I am unlikely to merge

- Anything that adds a required cloud service or telemetry.
- A rewrite of a working subsystem for stylistic reasons.
- New dependencies with no clear job. The backend has seven required packages and I would
  like to keep it near that.
- Simulator code in the runtime path. The sim transports are for tests. If the shipped app can
  instantiate one, the provenance tags stop meaning anything.
