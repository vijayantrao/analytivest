"""Regression tests for bugs found in the November 2026 code review. Each test fails on the old behaviour."""
import time

import pytest
from fastapi.testclient import TestClient

from app import alerts, config, db, screener
from app.analysis import analyse
from app.engine import valuation as V
from app.engine.metrics import compute_metrics
from app.engine.narrative import build_narrative
from app.main import app
from app.markets import MARKETS, large_amount, money
from app.ml import anomaly
from app.normalize import prefer_continuing_operations
from app.providers import registry
from tests.conftest import AUTH
from tests.test_ml import universe


@pytest.fixture
def client():
    with TestClient(app, headers=AUTH) as c:
        yield c


# ---------------- 1. "Replace" import must not wipe the portfolio when nothing can be matched ----------------
def test_replace_import_keeps_holdings_when_nothing_matches(client):
    client.delete("/api/portfolio")
    client.post("/api/portfolio", json={"symbol": "DEMO-STEADY", "quantity": 10, "avg_cost": 100})
    client.post("/api/portfolio", json={"symbol": "DEMO-LEVER", "quantity": 5})
    r = client.post("/api/portfolio/import?mode=replace",
                    files={"file": ("h.csv", b"Stock Name,Quantity\nSome Unknown Company,10\n")})
    assert r.status_code == 422 and "existing holdings were kept" in r.json()["detail"]
    assert {h["symbol"] for h in client.get("/api/portfolio").json()["holdings"]} == {"DEMO-STEADY", "DEMO-LEVER"}


def test_replace_import_swaps_holdings_when_rows_match(client):
    client.delete("/api/portfolio")
    client.post("/api/portfolio", json={"symbol": "DEMO-LEVER", "quantity": 5})
    csv = b"Symbol,Stock Name,Quantity,Avg Cost\nDEMO-STEADY,,7,120\n,Some Unknown Company,3,10\n"
    r = client.post("/api/portfolio/import?mode=replace", files={"file": ("h.csv", csv)}).json()
    assert [a["symbol"] for a in r["added"]] == ["DEMO-STEADY"] and len(r["unresolved"]) == 1
    h = client.get("/api/portfolio").json()["holdings"]
    assert [(x["symbol"], x["quantity"], x["avg_cost"]) for x in h] == [("DEMO-STEADY", 7.0, 120.0)]
    client.delete("/api/portfolio")


def test_holdings_replace_is_atomic():
    db.holdings_clear()
    db.holding_put("DEMO-STEADY", "Steady", 1, None, "t")
    with pytest.raises(Exception):  # second row violates NOT NULL quantity: nothing may change
        db.holdings_replace([("DEMO-LEVER", "Lever", 2, None, "t"), ("DEMO-BANK", "Bank", None, None, "t")])
    assert [h["symbol"] for h in db.holdings_list()] == ["DEMO-STEADY"]
    db.holdings_clear()


# ---------------- 2. A scan interrupted by a restart must not block new scans ----------------
def test_interrupted_jobs_are_cleared_at_startup(monkeypatch):
    db.conn()
    now = time.time()
    db.job_put("scan-dead", "scan", "running", 5, 50, "analysing X", now - 3 * 86400)
    db.job_put("alerts-dead", "alerts", "running", 1, 4, "checking X", now - 2 * 3600)
    db.job_put("alerts-live", "alerts", "running", 1, 4, "checking Y", now - 60)  # e.g. the command-line checker
    with TestClient(app, headers=AUTH) as c:  # startup runs here
        dead = db.job_get("scan-dead")
        assert dead["status"] == "error" and "Interrupted" in dead["message"] and "5 of 50" in dead["message"]
        assert db.job_get("alerts-dead")["status"] == "error"
        assert db.job_get("alerts-live")["status"] == "running"
        monkeypatch.setattr(config, "OFFLINE", False)
        monkeypatch.setattr(screener, "start", lambda *a, **k: "scan-new")
        r = c.post("/api/screener/scan", json={"size": 50})
        assert r.status_code == 200 and r.json()["job_id"] == "scan-new"
    db.job_put("alerts-live", "alerts", "done", 4, 4, "done", now - 60, now)


# ---------------- 3. Screener ML scores: batched, and cached per scan state ----------------
def test_batch_scores_equal_one_by_one_and_are_cached(monkeypatch):
    rows = universe(60)
    rows[3]["features"]["cash_conversion_3y"] = None  # a company with a missing feature
    scan_rows = [{"symbol": r["symbol"], "summary": {"name": r["name"], "ml_features": r["features"], "market": "IN"}}
                 for r in rows]
    fitted, scores = anomaly.scores_for(scan_rows, "IN")
    assert len(scores) == 60
    for r in rows[:12]:
        assert anomaly.score(fitted, r["features"]) == scores[r["symbol"]]

    calls = []
    real = anomaly.score_many
    monkeypatch.setattr(anomaly, "score_many", lambda *a, **k: calls.append(1) or real(*a, **k))
    anomaly.scores_for(scan_rows, "IN")
    assert calls == []  # unchanged scan: served from the cache
    scan_rows[0]["summary"]["ml_features"] = dict(rows[0]["features"], accruals_to_assets=25.0)
    _, changed = anomaly.scores_for(scan_rows, "IN")
    assert calls == [1] and changed[rows[0]["symbol"]] != scores[rows[0]["symbol"]]


# ---------------- 4. Text uses each company's own currency ----------------
def test_money_helpers():
    assert money(356.27, "USD") == "$356.27" and money(1234.5, "INR") == "₹1,234.50"
    assert money(12, "CHF") == "CHF 12.00" and money(305.33, None, 0) == "₹305"
    assert large_amount(9e9, "USD") == "$9.0 billion" and large_amount(4.5e8, "USD") == "$450 million"
    assert large_amount(8.2e11, "INR") == "₹82,000 Cr"


def test_price_alerts_use_the_holding_currency():
    us = alerts.diff({"price": 300.0, "name": "Apple Inc."}, {"price": 356.27, "name": "Apple Inc.", "currency": "USD"})
    assert us[0]["message"].startswith("$300.00") and "₹" not in us[0]["message"]
    india = alerts.diff({"price": 3000.0, "name": "TCS"}, {"price": 3300.0, "name": "TCS", "currency": "INR"})
    assert india[0]["message"].startswith("₹3,000.00")
    below = alerts.diff({"price": 110.0}, {"price": 95.0, "fv_low": 100.0, "currency": "USD", "symbol": "X"})
    assert any(a["kind"] == "below_fair_range" and "$95.00" in a["message"] and "$100.00" in a["message"] for a in below)


def test_narrative_dcf_note_and_discontinued_note_follow_the_currency():
    a = analyse("DEMO-STEADY", include_peers=False)
    text = lambda cur: " ".join(q["a"] for q in build_narrative(  # noqa: E731
        "X", a["metrics"], a["valuation"], a["scores"], a["flags"], cur)["sections"][0]["qa"])
    assert "₹" in text("INR") and "$" not in text("INR")
    assert "$" in text("USD") and "₹" not in text("USD")

    bundle = registry.get_bundle("DEMO-STEADY")
    metrics = compute_metrics(bundle, MARKETS["US"].statutory_tax_rate)
    us_note = V.dcf_analysis(bundle, metrics, MARKETS["US"])["assumption_notes"]["discount"]
    assert "US 10-year Treasury" in us_note and "Indian" not in us_note
    assert "Indian 10-year government bond" in V.dcf_analysis(bundle, metrics, MARKETS["IN"])["assumption_notes"]["discount"]

    p = [{"period_end": "2025-12-31", "label": "FY2025",
          "fields": {"net_income": 9e9, "net_income_continuing": 2e9, "shares_basic_avg": 1e9}}]
    prefer_continuing_operations(p, "USD")
    assert "$9.0 billion" in p[0]["notes"][0] and "Cr" not in p[0]["notes"][0]
