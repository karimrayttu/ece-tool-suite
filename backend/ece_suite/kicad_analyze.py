"""KiCad schematic analyzer — a pure S-expression parser + lightweight detectors.

Ports the *idea* of kicad-happy (no KiCad runtime, parse the saved file directly). This is a
starter analyzer: it extracts placed components, net labels, and a few deterministic
detectors. Deeper analysis (full net graph, datasheet cross-ref) is incremental.
"""

from __future__ import annotations

from pathlib import Path


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "()":
            tokens.append(c)
            i += 1
        elif c.isspace():
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                if text[j] == '"':
                    break
                buf.append(text[j])
                j += 1
            tokens.append('"' + "".join(buf))  # mark strings with a leading quote
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in "() \t\r\n":
                j += 1
            tokens.append(text[i:j])
            i = j
    return tokens


def parse_sexpr(text: str):
    tokens = tokenize(text)
    pos = 0

    def parse():
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        if tok == "(":
            lst = []
            while tokens[pos] != ")":
                lst.append(parse())
            pos += 1  # consume ")"
            return lst
        return tok

    out = []
    while pos < len(tokens):
        out.append(parse())
    return out[0] if len(out) == 1 else out


def _is_list(x) -> bool:
    return isinstance(x, list)


def _head(x) -> str:
    return x[0] if _is_list(x) and x and isinstance(x[0], str) else ""


def _props(symbol: list) -> dict[str, str]:
    props: dict[str, str] = {}
    for node in symbol:
        if _is_list(node) and _head(node) == "property" and len(node) >= 3:
            key = node[1].lstrip('"')
            val = node[2].lstrip('"')
            props[key] = val
    return props


def _find_all(tree, head: str) -> list:
    found = []
    if _is_list(tree):
        if _head(tree) == head:
            found.append(tree)
        for node in tree:
            found.extend(_find_all(node, head))
    return found


def analyze_text(text: str) -> dict:
    tree = parse_sexpr(text)
    components = []
    for sym in _find_all(tree, "symbol"):
        props = _props(sym)
        ref = props.get("Reference", "")
        if not ref or ref.startswith("#"):  # skip power symbols / lib defs without a real ref
            continue
        lib_id = ""
        for node in sym:
            if _is_list(node) and _head(node) == "lib_id" and len(node) >= 2:
                lib_id = node[1].lstrip('"')
        components.append({
            "ref": ref,
            "value": props.get("Value", ""),
            "lib_id": lib_id,
            "footprint": props.get("Footprint", ""),
        })

    labels = sorted({n[1].lstrip('"') for n in _find_all(tree, "label") if len(n) >= 2 and isinstance(n[1], str)})
    glabels = sorted({n[1].lstrip('"') for n in _find_all(tree, "global_label") if len(n) >= 2 and isinstance(n[1], str)})

    def _ref_prefix(c):
        return "".join(ch for ch in c["ref"] if ch.isalpha())

    counts: dict[str, int] = {}
    for c in components:
        counts[_ref_prefix(c)] = counts.get(_ref_prefix(c), 0) + 1

    regulators = [c for c in components if "regulator" in c["lib_id"].lower()]
    decoupling = [c for c in components if _ref_prefix(c) == "C" and c["value"].lower().endswith(("nf", "n"))]

    return {
        "component_count": len(components),
        "components": components,
        "ref_counts": counts,
        "nets": sorted(set(labels) | set(glabels)),
        "detectors": {
            "regulators": [c["ref"] for c in regulators],
            "decoupling_caps": len(decoupling),
            "resistors": counts.get("R", 0),
            "capacitors": counts.get("C", 0),
            "ics": counts.get("U", 0),
        },
    }


def analyze_path(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return analyze_text(p.read_text(encoding="utf-8", errors="replace"))
