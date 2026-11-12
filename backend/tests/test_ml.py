"""Earnings-quality anomaly model: features, model behaviour, evaluation and API (synthetic universe, offline)."""
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import db
from app.analysis import analyse
from app.main import app
from app.ml import anomaly, evaluate
from app.ml.features import FEATURE_NAMES, MIN_FEATURES, extract
from tests.conftest import AUTH


def universe(n=150, seed=0):
    """Plausible, mostly healthy companies: each feature drawn around a typical value."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        f = {
            "accruals_to_assets": rng.normal(-1.0, 2.5),
            "cash_conversion_3y": float(np.clip(rng.normal(1.05, 0.25), -3, 5)),
            "receivables_vs_revenue_cagr": rng.normal(0, 5),
            "margin_change": rng.normal(0, 1.8),
            "inventory_days_change": rng.normal(0, 6),
            "asset_vs_revenue_growth": rng.normal(0, 7),
            "unusual_share_of_pbt": abs(rng.normal(2, 3)),
            "share_count_change_3y": abs(rng.normal(0.3, 0.8)),
        }
        out.append({"symbol": f"SYN{i}.NS", "name": f"Synthetic {i}", "features": {k: float(v) for k, v in f.items()},
                    "flag_ids": []})
    return out


@pytest.fixture(scope="module")
def fitted():
    return anomaly.fit(universe())


# ---------------- features ----------------
def test_features_from_demo_companies():
    steady = extract(analyse("DEMO-STEADY"))
    assert set(steady) == set(FEATURE_NAMES)
    assert sum(v is not None for v in steady.values()) >= MIN_FEATURES
    assert steady["cash_conversion_3y"] > 0.9  # healthy cash generation
    lever = extract(analyse("DEMO-LEVER"))
    assert lever["receivables_vs_revenue_cagr"] > 10 and lever["share_count_change_3y"] > 5  # its known problems
    assert extract(analyse("DEMO-BANK")) is None  # financials excluded


def test_feature_formulas():
    a = analyse("DEMO-STEADY")
    f = extract(a)
    rows = {r["key"]: r["values"] for rows in a["statements"]["annual"]["rows"].values() for r in rows}
    ni, cfo, ta = rows["net_income"][-1], rows["cfo"][-1], rows["total_assets"][-1]
    assert math.isclose(f["accruals_to_assets"], (ni - cfo) / ta * 100, rel_tol=1e-9)
    assert math.isclose(f["cash_conversion_3y"], sum(rows["cfo"][-3:]) / sum(rows["net_income"][-3:]), rel_tol=1e-9)


# ---------------- model ----------------
def test_needs_a_minimum_universe():
    assert anomaly.fit(universe(anomaly.MIN_UNIVERSE - 1)) is None
    assert anomaly.fit(universe(anomaly.MIN_UNIVERSE)) is not None


def test_injected_distortion_is_flagged_with_the_right_reasons(fitted):
    odd = dict(universe(1, seed=7)[0]["features"])
    odd.update(accruals_to_assets=10.0, cash_conversion_3y=0.3)
    r = anomaly.score(fitted, odd)
    assert r["level"] in ("unusual", "highly_unusual") and r["percentile"] >= 90
    assert {x["feature"] for x in r["reasons"][:2]} == {"accruals_to_assets", "cash_conversion_3y"}
    assert "not turning into cash" in next(x["text"] for x in r["reasons"] if x["feature"] == "cash_conversion_3y")


def test_typical_company_is_typical_and_scores_are_deterministic(fitted):
    median_like = {k: float(m) for k, m in zip(FEATURE_NAMES, fitted.median)}
    r = anomaly.score(fitted, median_like)
    assert r["level"] == "typical" and r["percentile"] < 50 and r["reasons"] == []
    again = anomaly.fit(universe())
    assert anomaly.score(again, median_like)["score"] == r["score"]  # fixed random_state


def test_missing_features_are_imputed_or_refused(fitted):
    f = dict(universe(1, seed=3)[0]["features"])
    for k in FEATURE_NAMES[:3]:
        f[k] = None
    r = anomaly.score(fitted, f)
    assert r["available"] and set(r["missing"]) == set(FEATURE_NAMES[:3])
    assert all(x["feature"] not in r["missing"] for x in r["reasons"])
    sparse = {k: (None if i >= MIN_FEATURES - 1 else 0.0) for i, k in enumerate(FEATURE_NAMES)}
    assert anomaly.score(fitted, sparse)["available"] is False


def test_extreme_outlier_does_not_break_scaling(fitted):
    f = dict(universe(1, seed=5)[0]["features"])
    f["inventory_days_change"] = 1e9
    r = anomaly.score(fitted, f)
    assert r["available"] and math.isfinite(r["score"]) and r["reasons"][0]["feature"] == "inventory_days_change"


# ---------------- evaluation ----------------
def test_evaluation_on_synthetic_universe():
    ev = evaluate.evaluate(universe(200), folds=5)
    p = ev["patterns"]
    assert set(p) == set(evaluate.PATTERNS)
    assert p["profit_without_cash"]["roc_auc"] > 0.9
    # signals that no rule covers: the model adds detection the rules cannot
    assert p["inventory_and_asset_bloat"]["rule_detection"] <= ev["rule_false_alarm"] + 0.05
    assert p["inventory_and_asset_bloat"]["model_detection"] > 0.5
    assert p["subtle_combination"]["model_detection"] > p["subtle_combination"]["rule_detection"]
    assert 0.03 <= ev["model_false_alarm"] <= 0.2
    real = evaluate.real_world_overlap(universe(200))
    md = evaluate.report(ev, real)
    assert "ROC AUC" in md and "Limitations" in md


def test_rule_baseline_matches_redflag_thresholds():
    base = {k: 0.0 for k in FEATURE_NAMES} | {"cash_conversion_3y": 1.0}
    assert evaluate.rule_flags(base) is False
    assert evaluate.rule_flags(base | {"cash_conversion_3y": 0.79}) is True
    assert evaluate.rule_flags(base | {"receivables_vs_revenue_cagr": 10.5}) is True
    assert evaluate.rule_flags(base | {"share_count_change_3y": 6}) is True
    assert evaluate.rule_flags(base | {"inventory_days_change": 500}) is False  # no rule for this signal


# ---------------- API ----------------
@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers=AUTH) as c:
        yield c


def _clear_scans():
    with db.tx() as c:
        c.execute("DELETE FROM scan_results")


def test_api_without_and_with_a_scanned_universe(client):
    _clear_scans()
    r = client.get("/api/ml/anomalies").json()
    assert r["available"] is False and "screener scan" in r["reason"]
    assert client.get("/api/company/DEMO-STEADY/anomaly").json()["available"] is False

    rows = universe(60)
    rows[0]["features"].update(accruals_to_assets=12.0, cash_conversion_3y=0.2, receivables_vs_revenue_cagr=25.0)
    for r in rows:
        db.scan_put(r["symbol"], {"name": r["name"], "ml_features": r["features"], "flag_ids": ["profit_cash_gap"] if r is rows[0] else []})
    db.scan_put("BANKX.NS", {"name": "Bank X", "ml_features": None})  # financial: ignored
    try:
        r = client.get("/api/ml/anomalies").json()
        assert r["available"] and r["n"] == 60 and len(r["results"]) == 60
        assert r["results"][0]["symbol"] == rows[0]["symbol"] and r["results"][0]["level"] == "highly_unusual"
        assert r["results"][0]["rule_flags"] == ["profit_cash_gap"]
        assert [x["score"] for x in r["results"]] == sorted((x["score"] for x in r["results"]), reverse=True)

        s = client.get("/api/screener").json()
        assert s["ml"][rows[0]["symbol"]]["level"] == "highly_unusual" and "BANKX.NS" not in s["ml"]

        c = client.get("/api/company/DEMO-STEADY/anomaly").json()  # not in the universe: features computed live
        assert c["available"] and c["in_universe"] is False and c["n"] == 60
        assert client.get("/api/company/DEMO-BANK/anomaly").json()["available"] is False
    finally:
        _clear_scans()
