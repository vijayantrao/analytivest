import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers=AUTH) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_search_groups_sample(client):
    r = client.get("/api/search", params={"q": "demo"}).json()
    syms = {g["primary_symbol"] for g in r["results"]}
    assert {"DEMO-STEADY", "DEMO-LEVER", "DEMO-BANK"} <= syms


def test_analysis_payload_has_provenance_and_verdicts(client):
    a = client.get("/api/company/DEMO-STEADY/analysis").json()
    assert a["is_sample"] is True and "SAMPLE" in a["source_label"]
    assert a["freshness"]["retrieved_at"] > 0
    v = a["scores"]["verdicts"]
    assert set(v) == {"business_quality", "financial_risk", "valuation"}
    assert a["scores"]["decision_label"]
    pe = a["valuation"]["multiples"]["pe"]
    assert pe["formula"] and pe["basis"] and pe["quality"] == "calculated"
    assert "not investment advice" in a["disclaimer"].lower()


def test_invalid_and_unknown_symbols(client):
    assert client.get("/api/company/bad$sym/analysis").status_code in (400, 404)
    r = client.get("/api/company/NOSUCH-XYZ/analysis")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_dcf_override_changes_value(client):
    base = client.post("/api/company/DEMO-STEADY/dcf", json={}).json()["dcf"]["result"]["value_per_share"]
    hi = client.post("/api/company/DEMO-STEADY/dcf", json={"discount": 9}).json()["dcf"]["result"]["value_per_share"]
    assert hi > base
    assert client.post("/api/company/DEMO-STEADY/dcf", json={"discount": 99}).status_code == 422


def test_watchlist_roundtrip(client):
    assert client.post("/api/watchlist", json={"symbol": "DEMO-LEVER"}).status_code == 200
    items = client.get("/api/watchlist").json()["items"]
    assert any(i["symbol"] == "DEMO-LEVER" for i in items)
    client.delete("/api/watchlist/DEMO-LEVER")
    assert not any(i["symbol"] == "DEMO-LEVER" for i in client.get("/api/watchlist").json()["items"])


def test_notes_affect_governance(client):
    r = client.put("/api/company/DEMO-STEADY/notes", json={"promoter_pledge_pct": 0, "auditor_qualification": False,
                                                           "auditor_resigned": False, "material_litigation": False,
                                                           "rpt_concern": False, "source": "test"})
    assert r.status_code == 200
    a = client.get("/api/company/DEMO-STEADY/analysis").json()
    assert a["scores"]["categories"]["governance"]["score"] is not None
    assert client.put("/api/company/DEMO-STEADY/notes", json={"promoter_pledge_pct": 140}).status_code == 422


def test_compare_limits(client):
    r = client.get("/api/compare", params={"symbols": "DEMO-STEADY,DEMO-LEVER,DEMO-BANK"}).json()
    assert len(r["rows"]) == 3
    assert client.get("/api/compare", params={"symbols": "A,B,C,D,E,F"}).status_code == 400


def test_csv_export(client):
    r = client.get("/api/company/DEMO-STEADY/export.csv")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert "SAMPLE DATA" in r.text and "Revenue" in r.text


def test_ipo_sample_and_create(client):
    items = client.get("/api/ipos").json()["items"]
    assert any(i["is_sample"] for i in items)
    a = client.get("/api/ipos/demo-precision-ipo/analysis").json()
    assert a["analysis"]["structure"]["fresh_pct"] == pytest.approx(40.0)
    body = {"company_name": "Test Co", "price_band_low": 100, "price_band_high": 105, "fresh_issue_cr": 50,
            "ofs_cr": 10, "pre_issue_shares": 5e7,
            "financials": [{"fy": "FY2025", "revenue_cr": 200, "ebitda_cr": 40, "pat_cr": 20, "net_worth_cr": 100},
                           {"fy": "FY2026", "revenue_cr": 240, "ebitda_cr": 50, "pat_cr": 26, "net_worth_cr": 126}],
            "manual_peers": [{"name": "P1", "pe": 20}, {"name": "P2", "pe": 30}]}
    new_id = client.post("/api/ipos", json=body).json()["id"]
    an = client.get(f"/api/ipos/{new_id}/analysis").json()["analysis"]
    assert len(an["scenarios"]) == 3
    bad = dict(body, price_band_low=120)
    assert client.post("/api/ipos", json=bad).status_code == 422
    assert client.delete("/api/ipos/demo-precision-ipo").status_code == 400
    client.delete(f"/api/ipos/{new_id}")


def test_methodology_is_inspectable(client):
    m = client.get("/api/methodology").json()
    assert "composite_weights" in m["scoring"] and m["principles"]
