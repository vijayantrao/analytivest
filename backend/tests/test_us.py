"""US market support: screener per market, ML model per market, US portfolio tickers, FX for rupee totals."""
import pytest
from fastapi.testclient import TestClient

from app import db, screener
from app.main import app
from app.portfolio import resolve_symbol
from app.providers import registry
from app.providers.base import ProviderError
from tests.conftest import AUTH
from tests.test_ml import universe


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers=AUTH) as c:
        yield c


def _clear_scans():
    with db.tx() as c:
        c.execute("DELETE FROM scan_results")


def test_scan_tags_market_and_results_are_split(monkeypatch, client):
    _clear_scans()
    calls = []

    def fake_universe(size, market="IN"):
        calls.append(market)
        return [{"symbol": "DEMO-STEADY", "name": "Demo"}]
    monkeypatch.setattr(screener, "universe", fake_universe)
    screener.run_scan("scan-us-test", 1, include_peers=False, market="US")
    assert calls == ["US"]
    assert "United States" in db.job_get("scan-us-test")["message"]
    # stored rows carry their market; old rows without one fall back to the symbol's market
    db.scan_put("AAPL", {"name": "Apple"})
    db.scan_put("TCS.NS", {"name": "TCS"})
    try:
        us = {r["symbol"] for r in client.get("/api/screener?market=US").json()["results"]}
        india = {r["symbol"] for r in client.get("/api/screener?market=IN").json()["results"]}
        assert "AAPL" in us and "TCS.NS" in india and "AAPL" not in india and "TCS.NS" not in us
        assert client.get("/api/screener?market=UK").status_code == 422
    finally:
        _clear_scans()


def test_ml_model_is_per_market(client):
    _clear_scans()
    for r in universe(40):  # an Indian universe only
        db.scan_put(r["symbol"], {"name": r["name"], "ml_features": r["features"], "market": "IN"})
    try:
        assert client.get("/api/ml/anomalies?market=IN").json()["available"] is True
        us = client.get("/api/ml/anomalies?market=US").json()
        assert us["available"] is False
        # a US company is never scored against Indian peers
        r = client.get("/api/company/AAPL/anomaly").json()
        assert r["available"] is False and r["market"] == "US" and "United States" in r["reason"]
        for i, row in enumerate(universe(40, seed=9)):
            db.scan_put(f"US{i}", {"name": f"US {i}", "ml_features": row["features"], "market": "US"})
        us = client.get("/api/ml/anomalies?market=US").json()
        assert us["available"] and us["n"] == 40 and all(x["symbol"].startswith("US") for x in us["results"])
    finally:
        _clear_scans()


def test_us_portfolio_tickers():
    assert resolve_symbol({"symbol_hint": "AAPL"}, None, "US") == ("AAPL", None)
    assert resolve_symbol({"symbol_hint": "brk.b"}, None, "US") == ("BRK-B", None)
    assert resolve_symbol({"symbol_hint": "TCS"}, None, "IN") == ("TCS.NS", None)  # Indian default unchanged
    found = {"results": [{"market": "IN", "primary_symbol": "INFY.NS", "name": "Infosys"},
                         {"market": "US", "primary_symbol": "INFY", "name": "Infosys ADR"}]}
    assert resolve_symbol({"name": "Infosys"}, lambda q: found, "US")[0] == "INFY"
    assert resolve_symbol({"name": "Infosys"}, lambda q: found, "IN")[0] == "INFY.NS"


def test_us_portfolio_import(client):
    client.delete("/api/portfolio")
    csv = b"Symbol,Quantity,Average Price\nAAPL,3,150.5\nMSFT,2,300\n"
    r = client.post("/api/portfolio/import?mode=replace&market=US", files={"file": ("us.csv", csv)}).json()
    assert {x["symbol"] for x in r["added"]} == {"AAPL", "MSFT"}
    assert client.post("/api/portfolio/import?market=XX", files={"file": ("us.csv", csv)}).status_code == 422
    client.delete("/api/portfolio")


def test_fx_rate_uses_cache_and_fails_cleanly(client):
    with db.tx() as c:
        c.execute("DELETE FROM cache WHERE key LIKE 'fx:%'")
    with pytest.raises(ProviderError):  # offline, nothing cached
        registry.fx_rate("USDINR")
    assert client.get("/api/fx?pair=USDINR").status_code == 503
    assert client.get("/api/fx?pair=usd").status_code == 422
    db.cache_put("fx:USDINR", "fx", {"pair": "USDINR", "rate": 94.0, "as_of": "2026-11-12", "source": "test"}, "yahoo")
    r = client.get("/api/fx?pair=USDINR").json()
    assert r["rate"] == 94.0 and r["served_from"] == "cache"


# ---------------- per-market alert schedule ----------------
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from app import alerts  # noqa: E402
from app.engine.scoring import load_config, score_company  # noqa: E402
from tests.test_engine import _full  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def test_us_check_time_follows_new_york_daylight_saving():
    assert alerts.us_auto_time(datetime(2026, 1, 15, 12, 0, tzinfo=IST)) == "03:00"  # EST: 16:30 = 03:00 IST
    assert alerts.us_auto_time(datetime(2026, 7, 15, 12, 0, tzinfo=IST)) == "02:00"  # EDT: 16:30 = 02:00 IST


def test_due_markets():
    cfg = {"enabled": True, "time": "18:30", "time_us": "02:30"}
    both = {"IN": ["TCS.NS"], "US": ["AAPL"]}
    morning, evening = datetime(2026, 11, 14, 9, 0), datetime(2026, 11, 14, 19, 0)
    none = {"IN": None, "US": None}
    assert alerts.due_markets(morning, cfg, none, both) == ["US"]  # US closed overnight; India still open
    assert alerts.due_markets(evening, cfg, none, both) == ["IN", "US"]
    ran = {"IN": datetime(2026, 11, 14, 18, 45).timestamp(), "US": datetime(2026, 11, 14, 3, 0).timestamp()}
    assert alerts.due_markets(evening, cfg, ran, both) == []  # each runs once a day
    yesterday = {"IN": datetime(2026, 11, 13, 18, 45).timestamp(), "US": datetime(2026, 11, 13, 3, 0).timestamp()}
    assert alerts.due_markets(evening, cfg, yesterday, both) == ["IN", "US"]
    assert alerts.due_markets(evening, cfg, none, {"IN": ["TCS.NS"], "US": []}) == ["IN"]  # nothing US tracked
    assert alerts.due_markets(evening, {**cfg, "enabled": False}, none, both) == []


def test_tracked_symbols_split_by_market_and_settings_api(client):
    client.delete("/api/portfolio")
    client.post("/api/portfolio", json={"symbol": "DEMO-STEADY", "quantity": 1})
    db.holding_put("AAPL", "Apple", 2, 150, "test")
    try:
        assert "AAPL" in alerts.tracked_symbols("US") and "AAPL" not in alerts.tracked_symbols("IN")
        assert "DEMO-STEADY" in alerts.tracked_symbols("IN")
        assert client.put("/api/alerts/settings", json={"enabled": True, "time": "18:30", "time_us": "25:00"}).status_code == 422
        assert client.put("/api/alerts/settings", json={"enabled": True, "time": "18:30", "time_us": "02:15"}).status_code == 200
        s = client.get("/api/alerts").json()["schedule"]
        assert s["times"] == {"IN": "18:30", "US": "02:15"} and s["tracked"]["US"] >= 1
        assert client.put("/api/alerts/settings", json={"enabled": True, "time": "18:30", "time_us": None}).status_code == 200
        assert client.get("/api/alerts").json()["schedule"]["times"]["US"] == alerts.us_auto_time()
    finally:
        client.delete("/api/portfolio")


def test_run_checks_records_last_run_per_market():
    db.setting_put("alerts_last_run_IN", 1.0)
    db.setting_put("alerts_last_run_US", 1.0)
    alerts.run_checks(symbols=[], market="US")
    assert db.setting_get("alerts_last_run_US") > 1.0 and db.setting_get("alerts_last_run_IN") == 1.0


# ---------------- India-only scoring inputs ----------------
def test_us_governance_ignores_indian_only_inputs():
    b, m, val, flags, india = _full("DEMO-STEADY")
    us = score_company(b, m, val, flags, [], None, load_config(), market="US")
    keys = lambda s: {i["key"] for i in s["categories"]["governance"]["items"]}  # noqa: E731
    assert "pledge_pct" in keys(india) and "pledge_pct" not in keys(us)
    assert us["categories"]["governance"]["completeness"] > india["categories"]["governance"]["completeness"]
    assert us["data_completeness"] >= india["data_completeness"]


def test_us_bank_asset_quality_not_applicable():
    b, m, val, flags, india = _full("DEMO-BANK")
    us = score_company(b, m, val, flags, [], None, load_config(), market="US")
    assert india["categories"]["asset_quality"].get("not_applicable") is not True
    assert us["categories"]["asset_quality"]["not_applicable"] is True and "Indian" in us["categories"]["asset_quality"]["note"]
    assert us["data_completeness"] > india["data_completeness"]  # no longer counted as missing
