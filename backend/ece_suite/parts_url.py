"""Paste a distributor/manufacturer URL → auto-extract the part's info + keep a local list.

Two extraction layers, honest about what each produced:

* **URL structure** — Digi-Key / Mouser / LCSC / TI / ST / Farnell-style URLs carry the MPN
  (or product code) in a predictable path segment; parsed offline, always works.
* **Page fetch** — the page's schema.org ``Product`` JSON-LD (name, mpn, brand, description,
  image, price) with og:/<title> fallbacks. One GET per pasted link, no crawling and no
  retries, sending a User-Agent that names this tool. A distributor that declines returns an
  error and the result says ``fetched: false``, keeping the URL-derived fields. Pass
  ``fetch=False`` to stay offline. For anything past the occasional lookup, use a vendor API
  (Digi-Key or Nexar, both wired up already) rather than reading the storefront.

The local parts list lives at ``~/.ece-suite/parts_list.json`` — add / list / remove /
export CSV. Nothing external is written.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__

DATA_DIR = Path(os.environ.get("ECE_SUITE_DATA", Path.home() / ".ece-suite"))
LIST_PATH = DATA_DIR / "parts_list.json"

# Identify honestly. Pretending to be Chrome to get past a bot-wall is exactly the access the
# distributor declined to grant.
_UA = f"ece-tool-suite/{__version__} (+https://github.com/karimrayttu/ece-tool-suite)"


# --- URL-structure parsers -------------------------------------------------
def parse_url(url: str) -> dict:
    """Vendor + best MPN/product-code guess from the URL alone (no network)."""
    u = urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.")
    segs = [unquote(s) for s in u.path.split("/") if s]
    out = {"source_url": url, "vendor": host, "mpn": None, "manufacturer": None}

    def seg_after(marker: str, offset: int = 1) -> str | None:
        low = [s.lower() for s in segs]
        return segs[low.index(marker) + offset] if marker in low and len(segs) > low.index(marker) + offset else None

    if "digikey" in host:
        out["vendor"] = "Digi-Key"
        out["manufacturer"] = (seg_after("detail") or "").replace("-", " ").title() or None
        out["mpn"] = seg_after("detail", 2)
    elif "mouser" in host:
        out["vendor"] = "Mouser"
        tail = seg_after("productdetail")
        if tail:
            # forms: "<Mfr>/<MPN>" (two segs) or "<Mfr>-<MPN>" (one seg)
            nxt = seg_after("productdetail", 2)
            if nxt:
                out["manufacturer"], out["mpn"] = tail, nxt
            elif "-" in tail:
                mfr, _, mpn = tail.partition("-")
                out["manufacturer"], out["mpn"] = mfr, mpn
            else:
                out["mpn"] = tail
    elif "lcsc" in host:
        out["vendor"] = "LCSC"
        m = re.search(r"_(C\d+)\.html", u.path)
        out["mpn"] = m.group(1) if m else None          # LCSC product code; page fetch refines
    elif host.endswith("ti.com"):
        out["vendor"] = "Texas Instruments"
        out["manufacturer"] = "Texas Instruments"
        out["mpn"] = seg_after("product") or (segs[-1] if segs else None)
    elif host.endswith("st.com"):
        out["vendor"] = "STMicroelectronics"
        out["manufacturer"] = "STMicroelectronics"
        out["mpn"] = (segs[-1].split(".")[0] if segs else None)
    elif "octopart" in host:
        out["vendor"] = "Octopart"
        if len(segs) >= 2:
            # /<mpn>-<mfr>-<id>  — mpn is the leading chunk
            out["mpn"] = segs[-1].rsplit("-", 2)[0]
    elif "farnell" in host or "newark" in host or "element14" in host:
        out["vendor"] = "Farnell/Newark"
        out["mpn"] = next((s for s in reversed(segs) if re.match(r"^[A-Za-z0-9][\w.-]{3,}$", s)
                           and not s.isdigit()), None)
    elif "arrow" in host:
        out["vendor"] = "Arrow"
        out["mpn"] = segs[-1] if segs else None
    else:
        # generic: last path segment that looks like a part number
        out["mpn"] = next((s for s in reversed(segs)
                           if re.match(r"^[A-Za-z0-9][\w.+-]{3,}$", s)), None)
    if out["mpn"]:
        out["mpn"] = out["mpn"].strip().upper() if len(out["mpn"]) < 40 else out["mpn"].strip()
    return out


# --- page fetch (best effort) ---------------------------------------------
def _jsonld_products(html_text: str) -> list[dict]:
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                         html_text, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and it.get("@type") in ("Product", ["Product"]):
                out.append(it)
            elif isinstance(it, dict) and isinstance(it.get("@graph"), list):
                out += [g for g in it["@graph"] if isinstance(g, dict) and g.get("@type") == "Product"]
    return out


def fetch_page_info(url: str, timeout: float = 8.0) -> dict:
    """schema.org Product JSON-LD (+og/title fallback). Returns {} on any failure."""
    import httpx

    try:
        r = httpx.get(url, headers={"User-Agent": _UA, "Accept-Language": "en"},
                      timeout=timeout, follow_redirects=True)
        if r.status_code >= 400:
            return {}
        text = r.text[:800_000]
    except Exception:  # noqa: BLE001 - network best-effort by design
        return {}

    info: dict = {}
    for p in _jsonld_products(text):
        info["name"] = p.get("name") or info.get("name")
        info["mpn"] = p.get("mpn") or p.get("sku") or info.get("mpn")
        brand = p.get("brand")
        info["manufacturer"] = (brand.get("name") if isinstance(brand, dict) else brand) or info.get("manufacturer")
        info["description"] = p.get("description") or info.get("description")
        img = p.get("image")
        info["image"] = (img[0] if isinstance(img, list) and img else img) or info.get("image")
        offers = p.get("offers")
        if isinstance(offers, dict):
            info["price"] = offers.get("price") or info.get("price")
    if not info.get("name"):
        m = re.search(r'property="og:title"\s+content="([^"]+)"', text) or \
            re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
        if m:
            info["name"] = _html.unescape(m.group(1)).strip()[:160]
    if info:
        info["fetched"] = True
    return info


def part_from_url(url: str, fetch: bool = True) -> dict:
    if not re.match(r"^https?://", url or ""):
        return {"ok": False, "error": "not a URL"}
    base = parse_url(url)
    page = fetch_page_info(url) if fetch else {}
    merged = {**base, **{k: v for k, v in page.items() if v}}
    merged.setdefault("fetched", False)
    merged["ok"] = True
    if not merged.get("name") and merged.get("mpn"):
        merged["name"] = merged["mpn"]
    return merged


# --- local parts list ------------------------------------------------------
def _load() -> list[dict]:
    try:
        return json.loads(LIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LIST_PATH.write_text(json.dumps(items, indent=1), encoding="utf-8")


def list_parts() -> list[dict]:
    return _load()


def add_part(entry: dict) -> dict:
    items = _load()
    entry = {k: v for k, v in entry.items() if k != "ok"}
    entry["id"] = max((i.get("id", 0) for i in items), default=0) + 1
    entry["added"] = time.strftime("%Y-%m-%d %H:%M")
    # de-dupe by source_url or (mpn+vendor)
    for existing in items:
        if (entry.get("source_url") and existing.get("source_url") == entry["source_url"]) or \
           (entry.get("mpn") and existing.get("mpn") == entry.get("mpn")
                and existing.get("vendor") == entry.get("vendor")):
            return {"ok": True, "duplicate": True, "entry": existing, "count": len(items)}
    items.append(entry)
    _save(items)
    return {"ok": True, "duplicate": False, "entry": entry, "count": len(items)}


def remove_part(part_id: int) -> dict:
    items = _load()
    kept = [i for i in items if i.get("id") != part_id]
    _save(kept)
    return {"ok": True, "removed": len(items) - len(kept), "count": len(kept)}


def export_rows() -> list[list]:
    return [[i.get("mpn", ""), i.get("manufacturer", ""), i.get("name", ""),
             i.get("vendor", ""), i.get("price", ""), i.get("source_url", ""), i.get("added", "")]
            for i in _load()]
