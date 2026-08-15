"""One-click third-party setup: catalog shape, host allowlist, safe extraction, install
state machine (offline via monkeypatched download), and endpoint contracts."""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ece_suite import main as _main
from ece_suite import setup_tools as ST


# --- catalog --------------------------------------------------------------
def test_catalog_shape_and_ids_unique():
    cat = ST.catalog()
    ids = [e["id"] for e in cat]
    assert len(ids) == len(set(ids))
    for e in cat:
        assert {"id", "name", "group", "kind", "purpose", "source", "url",
                "installed", "one_click"} <= set(e)
        assert e["kind"] in ("auto", "page")
        assert e["one_click"] == (e["kind"] == "auto")
        assert e["url"].startswith("https://")


def test_auto_entries_use_official_channels_only():
    for e in ST._catalog():
        if e["kind"] != "auto":
            continue
        r = e["recipe"]
        if r["type"].startswith("github-"):
            assert r["repo"] in ("YosysHQ/oss-cad-suite-build", "ghdl/ghdl",
                                 "chipsalliance/verible")
        elif r["type"] == "winget":
            assert r["package"] in ("ADI.LTspice", "KiCad.KiCad")
        else:
            pytest.fail(f"unknown recipe type {r['type']!r}")


# --- guardrails -----------------------------------------------------------
def test_host_allowlist_refuses_non_official():
    with pytest.raises(RuntimeError, match="non-official host"):
        ST._check_host("https://evil.example.com/payload.zip")
    ST._check_host("https://api.github.com/repos/x/y/releases/latest")  # no raise


def test_safe_extract_rejects_traversal(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape.txt", "nope")
    with pytest.raises(RuntimeError, match="escapes target"):
        ST._safe_extract(bad, tmp_path / "out")


def test_safe_extract_normal_zip(tmp_path):
    ok = tmp_path / "ok.zip"
    with zipfile.ZipFile(ok, "w") as z:
        z.writestr("dir/file.txt", "content")
    ST._safe_extract(ok, tmp_path / "out")
    assert (tmp_path / "out" / "dir" / "file.txt").read_text() == "content"


# --- install state machine (offline) --------------------------------------
def _fake_verible_zip(dest: Path) -> None:
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr("verible-x/verible-verilog-format.exe", b"MZfake")
        z.writestr("verible-x/verible-verilog-lint.exe", b"MZfake")


def test_github_zip_recipe_installs_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(ST, "suite_root", lambda: tmp_path / "suite")
    monkeypatch.setattr(ST, "_github_asset", lambda repo, pat: ("https://github.com/fake.zip", 0))

    def fake_download(tool_id, url, dest, hint=0):
        _fake_verible_zip(Path(dest))
        ST._set(tool_id, progress=100)
    monkeypatch.setattr(ST, "_download", fake_download)

    out = ST._install_github_zip("verible", {"repo": "chipsalliance/verible",
                                             "asset": "win64", "target": "bin-exes"})
    assert (tmp_path / "suite" / "bin" / "verible-verilog-format.exe").exists()
    assert out.endswith("bin")


def test_run_install_error_path_is_honest(monkeypatch):
    # a recipe that blows up must land in state=error with the message, never crash
    entry = {"id": "verible", "kind": "auto",
             "recipe": {"type": "github-zip", "repo": "chipsalliance/verible",
                        "asset": "win64", "target": "bin-exes"}}
    monkeypatch.setattr(ST, "_install_github_zip",
                        lambda tid, r: (_ for _ in ()).throw(RuntimeError("boom")))
    ST._run_install("verible", entry)
    st = ST.status()["verible"]
    assert st["state"] == "error" and "boom" in st["error"]


def test_start_install_rejects_unknown_and_page_kinds():
    assert ST.start_install("no-such-tool")["ok"] is False
    r = ST.start_install("keysight-iolibs")
    assert r["ok"] is False and "url" in r  # page-kind: hand back the official page


def test_start_install_runs_thread_to_completion(monkeypatch):
    done = {}

    def fake_run(tool_id, entry):
        done["ran"] = (tool_id, entry["id"])
        ST._set(tool_id, state="done", finished=True)
    monkeypatch.setattr(ST, "_run_install", fake_run)
    r = ST.start_install("verible")
    assert r["ok"] and r.get("started")
    for _ in range(50):
        if ST.status().get("verible", {}).get("finished"):
            break
        time.sleep(0.05)
    assert done["ran"][0] == "verible"


# --- endpoints ------------------------------------------------------------
def test_setup_endpoints_contract():
    c = TestClient(_main.app)
    cat = c.get("/api/setup/catalog").json()
    assert "tools" in cat and any(t["id"] == "oss-cad-suite" for t in cat["tools"])
    st = c.get("/api/setup/status").json()
    assert "installs" in st
    bad = c.post("/api/setup/install/nope").json()
    assert bad["ok"] is False
