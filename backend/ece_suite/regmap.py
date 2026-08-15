"""Register-map generator: spec -> synthesizable SystemVerilog register block + Markdown docs.

A digital engineer's bread-and-butter deliverable is a register map and its documentation kept
in lock-step. This module takes a compact spec (registers, offsets, access, reset, bit fields)
and emits BOTH a synthesizable SystemVerilog register file (simple read/write bus, per-field
hardware ports) and a Markdown datasheet — from the same source of truth, so they can't drift.

The generated RTL is meant to be fed straight into :mod:`rtl` (it is lint-clean SystemVerilog),
which is how we prove it's real rather than plausible: the generator dog-foods the toolchain.
"""

from __future__ import annotations

import re


class RegmapError(ValueError):
    pass


def parse_bits(spec: str | int) -> tuple[int, int]:
    """'7:0' -> (7, 0); '3' -> (3, 3). Returns (msb, lsb)."""
    s = str(spec).strip()
    if ":" in s:
        hi, lo = s.split(":", 1)
        msb, lsb = int(hi), int(lo)
    else:
        msb = lsb = int(s)
    if msb < lsb or lsb < 0:
        raise RegmapError(f"bad bit range {spec!r}")
    return msb, lsb


def _norm_access(a: str | None) -> str:
    a = (a or "rw").strip().lower()
    return a if a in ("rw", "ro", "wo") else "rw"


def _validate(spec: dict) -> dict:
    """Normalize + validate a register-map spec; raises RegmapError on a real problem."""
    dw = int(spec.get("data_width", 32))
    if dw not in (8, 16, 32, 64):
        raise RegmapError("data_width must be 8, 16, 32, or 64")
    regs = spec.get("registers") or []
    if not regs:
        raise RegmapError("no registers in spec")
    seen_off: dict[int, str] = {}
    out_regs = []
    for r in regs:
        name = str(r.get("name", "")).strip()
        if not re.match(r"^[A-Za-z_]\w*$", name):
            raise RegmapError(f"invalid register name {name!r}")
        off = int(r.get("offset", 0))
        if off % (dw // 8):
            raise RegmapError(f"{name}: offset {off} not aligned to {dw // 8} bytes")
        if off in seen_off:
            raise RegmapError(f"{name}: offset {off} collides with {seen_off[off]}")
        seen_off[off] = name
        used = 0
        fields = []
        for f in r.get("fields") or []:
            fname = str(f.get("name", "")).strip()
            if not re.match(r"^[A-Za-z_]\w*$", fname):
                raise RegmapError(f"{name}: invalid field name {fname!r}")
            msb, lsb = parse_bits(f.get("bits", "0"))
            if msb >= dw:
                raise RegmapError(f"{name}.{fname}: bit {msb} exceeds data_width {dw}")
            mask = ((1 << (msb - lsb + 1)) - 1) << lsb
            if used & mask:
                raise RegmapError(f"{name}.{fname}: bits {msb}:{lsb} overlap another field")
            used |= mask
            fields.append({"name": fname, "msb": msb, "lsb": lsb, "width": msb - lsb + 1,
                           "access": _norm_access(f.get("access", r.get("access", "rw"))),
                           "reset": int(f.get("reset", 0)) & ((1 << (msb - lsb + 1)) - 1),
                           "description": str(f.get("description", "")).strip()})
        if not fields:  # whole-word register
            fields.append({"name": "VALUE", "msb": dw - 1, "lsb": 0, "width": dw,
                           "access": _norm_access(r.get("access", "rw")),
                           "reset": int(r.get("reset", 0)) & ((1 << dw) - 1), "description": ""})
        out_regs.append({"name": name, "offset": off, "description": str(r.get("description", "")).strip(),
                         "fields": fields})
    return {"name": str(spec.get("name", "regs")).strip() or "regs",
            "data_width": dw, "addr_width": int(spec.get("addr_width", 8)), "registers": out_regs}


def _sv(spec: dict) -> str:
    name, dw, aw = spec["name"], spec["data_width"], spec["addr_width"]
    hw_ports, storage, out_assigns, resets = [], [], [], []
    write_cases, read_cases = [], []
    has_writable = False
    for r in spec["registers"]:
        wlines, rparts = [], []
        for f in r["fields"]:
            sig = f"{r['name'].lower()}_{f['name'].lower()}"
            width = f"[{f['width'] - 1}:0] " if f["width"] > 1 else ""
            sel = f"[{f['msb']}:{f['lsb']}]" if f["width"] > 1 else f"[{f['lsb']}]"
            if f["access"] in ("rw", "wo"):
                has_writable = True
                hw_ports.append(f"  output logic {width}{sig}")
                storage.append(f"  logic {width}{sig}_q;")
                out_assigns.append(f"  assign {sig} = {sig}_q;")
                resets.append(f"      {sig}_q <= {f['width']}'h{f['reset']:X};")
                wlines.append(f"          {sig}_q <= wdata{sel};")
                rparts.append((f["lsb"], f"{sig}_q"))
            else:  # ro: value driven by hardware into the read mux
                hw_ports.append(f"  input  logic {width}{sig}")
                rparts.append((f["lsb"], sig))
        if wlines:
            write_cases.append(f"        {aw}'h{r['offset']:X}: begin\n" + "\n".join(wlines) + "\n        end")
        assign = " | ".join(f"(DATA_W'({src}) << {lsb})" if lsb else f"DATA_W'({src})" for lsb, src in rparts)
        read_cases.append(f"        {aw}'h{r['offset']:X}: rdata = {assign};")

    fixed_ports = [
        "  input  logic              clk",
        "  input  logic              rst_n",
        "  input  logic [ADDR_W-1:0] addr",
        "  input  logic              sel",
        "  input  logic              write",
        "  input  logic [DATA_W-1:0] wdata",
        "  output logic [DATA_W-1:0] rdata",
    ]
    ports = ",\n".join(fixed_ports + hw_ports)

    if has_writable:
        write_proc = f"""  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
{chr(10).join(resets)}
    end else if (sel && write) begin
      case (addr)
{chr(10).join(write_cases)}
        default: ; // no writable register at this address
      endcase
    end
  end
"""
        # register maps rarely use every wdata bit; consume the leftovers so lint stays clean
        unused = "  wire _unused = &{1'b0, wdata};\n"
    else:  # all-read-only map: consume the write-side inputs so lint stays clean
        write_proc = ""
        unused = "  wire _unused = &{1'b0, clk, rst_n, sel, write, wdata};\n"

    return f"""// Auto-generated register block for '{name}' — {dw}-bit data, {aw}-bit address.
// Simple synchronous register bus: assert sel + write to write; rdata is combinational.
module {name}_regs #(
  parameter int ADDR_W = {aw},
  parameter int DATA_W = {dw}
) (
{ports}
);
{chr(10).join(storage)}
{chr(10).join(out_assigns)}

{write_proc}  always_comb begin
    rdata = '0;
    case (addr)
{chr(10).join(read_cases)}
      default: rdata = '0;
    endcase
  end
{unused}endmodule
"""


def _markdown(spec: dict) -> str:
    name, dw = spec["name"], spec["data_width"]
    lines = [f"# `{name}` register map", "",
             f"- Data width: **{dw} bits**", f"- Address width: **{spec['addr_width']} bits**",
             f"- Registers: **{len(spec['registers'])}**", "",
             "| Offset | Name | Access | Reset | Description |",
             "|---|---|---|---|---|"]
    for r in spec["registers"]:
        acc = "/".join(sorted({f["access"] for f in r["fields"]}))
        reset = sum(f["reset"] << f["lsb"] for f in r["fields"])
        lines.append(f"| 0x{r['offset']:02X} | `{r['name']}` | {acc} | 0x{reset:X} | {r['description']} |")
    for r in spec["registers"]:
        lines += ["", f"## `{r['name']}` — 0x{r['offset']:02X}",
                  r["description"] or "", "",
                  "| Bits | Field | Access | Reset | Description |", "|---|---|---|---|---|"]
        for f in sorted(r["fields"], key=lambda x: -x["msb"]):
            bits = f"{f['msb']}:{f['lsb']}" if f["width"] > 1 else f"{f['lsb']}"
            lines.append(f"| {bits} | `{f['name']}` | {f['access']} | 0x{f['reset']:X} | {f['description']} |")
    return "\n".join(lines) + "\n"


def generate(spec: dict, lint: bool = True) -> dict:
    """Generate SystemVerilog + Markdown from a register-map spec, and (by default) lint the RTL."""
    try:
        norm = _validate(spec)
    except RegmapError as e:
        return {"ok": False, "error": str(e)}
    sv = _sv(norm)
    md = _markdown(norm)
    result = {"ok": True, "name": norm["name"], "systemverilog": sv, "markdown": md,
              "n_registers": len(norm["registers"])}
    if lint:
        from . import rtl
        lr = rtl.lint(sv, "systemverilog", top=f"{norm['name']}_regs")
        result["lint"] = lr
    return result
