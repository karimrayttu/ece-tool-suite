"""GenAI-assisted RTL: design, validate, and optimize SystemVerilog — gated by the toolchain.

This is the "AI writes hardware, the tools grade it" loop. A large language model proposes
RTL, but the verdict is never the model's to give: every candidate is run through
:mod:`rtl` (Verilator/Icarus lint, and — when a testbench is supplied — a real Icarus
simulation), and only a tool-clean result is returned as validated. If lint errors or a
simulation mismatch come back, the diagnostics are fed to the model for another round.

That closes the exact gap the ai-ee-guardrails discipline warns about: an LLM will happily
emit confident, plausible, *wrong* RTL. Here it cannot pass unless the compiler and the
simulator agree. The Anthropic client is injectable so the loop is unit-testable offline.
"""

from __future__ import annotations

import os
import re
from typing import Any

from . import rtl

DEFAULT_MODEL = os.environ.get("ECE_SUITE_MODEL", "claude-sonnet-4-6")

_DESIGN_SYSTEM = (
    "You are a senior digital-design engineer writing synthesizable RTL for FPGA/ASIC. "
    "Rules: (1) Output the module as ONE fenced code block tagged with the language "
    "(```systemverilog / ```verilog / ```vhdl). (2) Synthesizable constructs only — no delays "
    "except in a testbench, no unsynthesizable system tasks in the DUT. (3) For SystemVerilog "
    "use always_ff/always_comb, explicit reset, and named ports. (4) Keep exactly one top "
    "module unless asked otherwise. After the code block, add 2-4 lines on key design choices. "
    "You will be given the compiler/linter/simulator output for your code — when it reports "
    "errors, FIX them and return the corrected full module. NEVER include or repeat a provided "
    "testbench in your code block — it is compiled separately and duplicating it breaks the "
    "build. Never claim a design passes; the toolchain decides."
)

_OPTIMIZE_SYSTEM = (
    "You are optimizing existing RTL. Preserve the module's external behavior and port list "
    "EXACTLY — the same testbench must still pass. Optimize for the stated goal (area, timing, "
    "power, or readability). Output the full revised module as ONE fenced code block tagged "
    "with the language, then 2-4 lines explaining what you changed and why it is behavior-"
    "preserving. The change is only accepted if the simulator still passes and the linter is "
    "clean; do not claim otherwise."
)

_CODE_RE = re.compile(r"```(?:systemverilog|verilog|sv|vhdl|vhd)?\s*\n(.*?)```", re.S | re.I)


def available(client: Any = None, api_key: str | None = None) -> bool:
    return client is not None or bool(api_key or os.environ.get("ANTHROPIC_API_KEY"))


def _extract_code(text: str) -> str | None:
    blocks = _CODE_RE.findall(text or "")
    if not blocks:
        return None
    # the intended module is the longest fenced block
    return max(blocks, key=len).strip()


def _notes(text: str) -> str:
    """Everything outside code fences — the model's rationale."""
    return _CODE_RE.sub("", text or "").strip()


def _strip_tb_modules(code: str, testbench: str | None) -> str:
    """Remove any module the model duplicated from the provided testbench.

    Models sometimes echo the given testbench inside their code block; compiling it alongside
    the real testbench then fails on duplicate definitions. Verilog modules don't nest, so a
    non-greedy module..endmodule cut per testbench module name is safe.
    """
    if not testbench:
        return code
    out = code
    for name in rtl.module_names(testbench):
        out = re.sub(rf"\bmodule\s+{re.escape(name)}\b.*?\bendmodule\b", "", out, flags=re.S)
    return out.strip()


def _client(client: Any, api_key: str | None) -> Any:
    if client is not None:
        return client
    from anthropic import AsyncAnthropic  # lazy: only the live path needs the SDK

    return AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))


def _text_of(resp: Any) -> str:
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text" or hasattr(block, "text"):
            parts.append(getattr(block, "text", ""))
    return "".join(parts)


def _validate(code: str, language: str, testbench: str | None, top: str | None) -> dict:
    """Run the ground-truth gate: lint always, simulate when a testbench is present."""
    lint = rtl.lint(code, language, top=top)
    result = {"lint": lint}
    ok = bool(lint.get("ok")) and lint.get("errors", 1) == 0
    if testbench:
        sim = rtl.simulate(code, testbench, language, top=top)
        result["sim"] = sim
        ok = ok and sim.get("ok") and sim.get("compiled") and sim.get("verdict") in ("pass", "ran")
        # if the tb prints an explicit pass, require it
        if sim.get("verdict") == "fail":
            ok = False
    result["validated"] = bool(ok)
    return result


def _diag_feedback(v: dict) -> str:
    """Turn a validation result into a corrective prompt for the model."""
    lines: list[str] = []
    lint = v.get("lint", {})
    for d in lint.get("diagnostics", [])[:20]:
        loc = f"line {d['line']}" + (f":{d['col']}" if d.get("col") else "")
        lines.append(f"[{d['severity']}] {loc}: {d['message']}")
    sim = v.get("sim", {})
    if sim:
        if not sim.get("compiled"):
            lines.append("Simulation did not compile.")
        elif sim.get("verdict") == "fail":
            lines.append("Testbench reported a FAILURE / mismatch:")
        if sim.get("stdout"):
            lines.append("Simulator output:\n" + sim["stdout"][:1500])
    body = "\n".join(lines) or "Unknown validation failure."
    return ("The toolchain reported problems with your RTL. Fix them and return the full "
            "corrected module in a single fenced code block.\n\n" + body)


async def generate(spec: str, language: str = "systemverilog", *, testbench: str | None = None,
                   top: str | None = None, max_rounds: int = 3, client: Any = None,
                   api_key: str | None = None, model: str | None = None,
                   max_tokens: int = 3000) -> dict:
    """Design RTL from a natural-language spec, iterating until the toolchain is clean.

    Returns the final code, per-round validation, and whether it ended validated. When a
    testbench is supplied the loop also requires a passing simulation, not just a clean lint.
    """
    if not available(client, api_key):
        return {"ok": False, "error": "No ANTHROPIC_API_KEY configured — set it to enable AI RTL."}
    lang = rtl._norm_lang(language, spec)
    cli = _client(client, api_key)
    mdl = model or DEFAULT_MODEL
    tb_note = ("\n\nA testbench WILL be run against your module; make the ports match this "
               f"testbench:\n```\n{testbench}\n```") if testbench else ""
    messages = [{"role": "user", "content": f"Design in {lang}:\n\n{spec}{tb_note}"}]

    rounds: list[dict] = []
    code: str | None = None
    notes = ""
    for _ in range(max(1, max_rounds)):
        resp = await cli.messages.create(model=mdl, max_tokens=max_tokens,
                                         system=_DESIGN_SYSTEM, messages=messages)
        text = _text_of(resp)
        extracted = _extract_code(text)
        if extracted:
            code = _strip_tb_modules(extracted, testbench)
        notes = _notes(text) or notes
        if not code:
            return {"ok": False, "error": "model returned no code block", "raw": text}
        v = _validate(code, lang, testbench, top)
        rounds.append({"lint": v["lint"], "sim": v.get("sim"), "validated": v["validated"]})
        if v["validated"]:
            break
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": _diag_feedback(v)}]

    return {"ok": True, "language": lang, "code": code, "notes": notes,
            "validated": rounds[-1]["validated"] if rounds else False,
            "rounds": rounds, "n_rounds": len(rounds), "model": mdl}


async def optimize(source: str, goal: str = "area", language: str | None = None, *,
                   testbench: str | None = None, top: str | None = None, client: Any = None,
                   api_key: str | None = None, model: str | None = None,
                   max_tokens: int = 3000) -> dict:
    """Optimize existing RTL for a goal, keeping behavior — accepted only if it still validates.

    If a testbench is provided and the optimized RTL fails simulation, the ORIGINAL source is
    kept and ``accepted=False`` is returned (never trade correctness for a smaller cell count).
    """
    if not available(client, api_key):
        return {"ok": False, "error": "No ANTHROPIC_API_KEY configured — set it to enable AI RTL."}
    lang = rtl._norm_lang(language, source)
    cli = _client(client, api_key)
    mdl = model or DEFAULT_MODEL

    baseline = _validate(source, lang, testbench, top)
    before_synth = rtl.synthesize(source, lang, top=top) if lang != "vhdl" else {"ok": False}
    tb_note = (f"\n\nThis testbench must still pass:\n```\n{testbench}\n```") if testbench else ""
    prompt = (f"Optimize this {lang} module for {goal}. Keep behavior and ports identical."
              f"{tb_note}\n\n```{lang}\n{source}\n```")
    resp = await cli.messages.create(model=mdl, max_tokens=max_tokens,
                                     system=_OPTIMIZE_SYSTEM, messages=[{"role": "user", "content": prompt}])
    text = _text_of(resp)
    code = _extract_code(text)
    if code:
        code = _strip_tb_modules(code, testbench)
    if not code:
        return {"ok": False, "error": "model returned no code block", "raw": text}

    after = _validate(code, lang, testbench, top)
    after_synth = rtl.synthesize(code, lang, top=top) if lang != "vhdl" else {"ok": False}
    accepted = bool(after["validated"])
    return {
        "ok": True, "language": lang, "goal": goal, "accepted": accepted,
        "code": code if accepted else source, "candidate": code,
        "notes": _notes(text),
        "before": {"validation": baseline, "synth": before_synth},
        "after": {"validation": after, "synth": after_synth},
        "model": mdl,
        "note": None if accepted else "Optimized RTL did not validate; keeping the original.",
    }
