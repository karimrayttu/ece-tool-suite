"""Digi-Key V3/V4 API adapter — the only public route to TI WEBENCH-backed data.

WEBENCH itself is TI's proprietary cloud tool (no offline build, no public API). Digi-Key,
however, hosts a WEBENCH Design Center and exposes product data through its developer API, and
provides per-part WEBENCH launch links. This adapter does the OAuth2 client-credentials flow
with YOUR free Digi-Key developer app, searches parts, and builds WEBENCH launch URLs.

Nothing works until credentials are provided (via the Connect card or the env vars
DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET). Secrets are held in memory for the session and are
never written to the repo.
"""

from __future__ import annotations

import os
import time

import httpx

_API = os.environ.get("DIGIKEY_API_BASE", "https://api.digikey.com")
_state: dict = {
    "client_id": os.environ.get("DIGIKEY_CLIENT_ID", ""),
    "client_secret": os.environ.get("DIGIKEY_CLIENT_SECRET", ""),
    "token": None,
    "token_exp": 0.0,
}


def configured() -> bool:
    return bool(_state["client_id"] and _state["client_secret"])


def _get_token() -> str | None:
    if not configured():
        return None
    if _state["token"] and time.monotonic() < _state["token_exp"] - 30:
        return _state["token"]
    try:
        r = httpx.post(f"{_API}/v1/oauth2/token", data={
            "client_id": _state["client_id"], "client_secret": _state["client_secret"],
            "grant_type": "client_credentials"}, timeout=15)
        r.raise_for_status()
        j = r.json()
        _state["token"] = j["access_token"]
        _state["token_exp"] = time.monotonic() + float(j.get("expires_in", 600))
        return _state["token"]
    except Exception:  # noqa: BLE001
        return None


def status() -> dict:
    ok = False
    err = None
    if configured():
        tok = _get_token()
        ok = bool(tok)
        if not ok:
            err = "credentials present but token request failed (check the client id/secret)"
    return {
        "configured": configured(), "connected": ok, "error": err, "api_base": _API,
        "register_url": "https://developer.digikey.com/",
        "note": "WEBENCH is TI's cloud tool with no public API; Digi-Key's developer API is the "
                "supported route to WEBENCH-backed part data + per-part WEBENCH launch links. "
                "Register a free app at developer.digikey.com, then Connect with the OAuth client id/secret.",
    }


def connect(client_id: str, client_secret: str) -> dict:
    _state["client_id"] = client_id.strip()
    _state["client_secret"] = client_secret.strip()
    _state["token"] = None
    tok = _get_token()
    if not tok:
        return {"ok": False, "error": "could not get an OAuth token — check the client id/secret and that the app is a Client-Credentials (Product Information) app."}
    return {"ok": True, "connected": True}


def webench_launch(mpn: str) -> str:
    """Digi-Key's per-part WEBENCH launch link."""
    return f"https://webench.ti.com/webench5/power/launch_wb.cgi?part={mpn}&fromdisty=digikey"


def search_parts(keywords: str, limit: int = 10) -> dict:
    tok = _get_token()
    if not tok:
        return {"ok": False, "error": "not connected — add Digi-Key developer credentials first",
                "register_url": "https://developer.digikey.com/"}
    try:
        r = httpx.post(f"{_API}/products/v4/search/keyword",
                       headers={"Authorization": f"Bearer {tok}", "X-DIGIKEY-Client-Id": _state["client_id"],
                                "X-DIGIKEY-Locale-Site": "US", "X-DIGIKEY-Locale-Language": "en",
                                "X-DIGIKEY-Locale-Currency": "USD", "Content-Type": "application/json"},
                       json={"Keywords": keywords, "Limit": max(1, min(limit, 50))}, timeout=20)
        r.raise_for_status()
        j = r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    parts = []
    for p in (j.get("Products") or [])[:limit]:
        mpn = p.get("ManufacturerProductNumber") or p.get("ManufacturerPartNumber") or ""
        parts.append({
            "mpn": mpn,
            "manufacturer": (p.get("Manufacturer") or {}).get("Name") if isinstance(p.get("Manufacturer"), dict) else p.get("Manufacturer"),
            "description": (p.get("Description") or {}).get("ProductDescription") if isinstance(p.get("Description"), dict) else p.get("ProductDescription"),
            "datasheet": p.get("DatasheetUrl"),
            "webench": webench_launch(mpn) if mpn else None,
        })
    return {"ok": True, "count": len(parts), "parts": parts}
