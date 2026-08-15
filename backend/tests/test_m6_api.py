from fastapi.testclient import TestClient

from ece_suite.main import app
from tests.test_kicad import FIXTURE

client = TestClient(app)


def test_calc_list_and_run():
    assert client.get("/api/calc").json()["calculators"]
    r = client.post("/api/calc/divider", json={"vin": 5.0, "vout": 3.3}).json()
    assert r["ok"] and abs(r["result"]["vout_actual"] - 3.3) < 0.05


def test_calc_unknown_404_and_bad_args():
    assert client.post("/api/calc/nope", json={}).status_code == 404
    r = client.post("/api/calc/microstrip", json={"w": 0.3}).json()  # missing h, er
    assert r["ok"] is False


def test_parts_search_endpoint():
    r = client.get("/api/parts/search", params={"query": "mosfet"}).json()
    assert r["ok"] and r["provider"] == "offline"


def test_kicad_analyze_endpoint():
    r = client.post("/api/kicad/analyze", json={"text": FIXTURE}).json()
    assert r["ok"] and r["component_count"] == 3
