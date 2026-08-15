import pytest

from ece_suite.parts import NexarProvider, search, search_offline, status


def test_offline_search_finds_regulator():
    r = search("3.3", category="regulator")
    assert r["provider"] == "offline"
    assert any("AMS1117" in p["mpn"] for p in r["results"])


def test_search_by_category_only():
    res = search_offline("", category="mosfet")
    assert res and all(p["category"] == "mosfet" for p in res)


def test_status_shape():
    s = status()
    assert s["offline_catalog"] > 0
    assert "nexar" in s["providers"]


def test_nexar_unconfigured_raises():
    np = NexarProvider()
    if not np.available():  # no keys in this environment
        with pytest.raises(RuntimeError):
            np.search("STM32")
