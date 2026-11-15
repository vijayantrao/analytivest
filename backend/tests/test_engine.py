import copy

import pytest

from app.engine import valuation as V
from app.engine.ipo import analyse_ipo
from app.engine.metrics import cagr_metric, compute_metrics, ttm_from_quarters
from app.engine.redflags import compute_flags
from app.engine.scoring import load_config, score_category, score_company
from app.markets import MARKETS
from app.normalize import adjust_periods_for_splits, normalize_bundle
from app.providers.sample import SAMPLE_IPO, SampleProvider

IN = MARKETS["IN"]


def _period(end, label, **fields):
    return {"period_end": end, "label": label, "fields": fields}


# ---------------- split / bonus normalisation ----------------
def test_split_adjusts_unadjusted_period():
    periods = [_period("2023-03-31", "FY2023", net_income=1000.0, eps_basic=10.0, eps_diluted=10.0,
                       shares_basic_avg=100.0, shares_outstanding=100.0),
               _period("2024-03-31", "FY2024", net_income=1200.0, eps_basic=6.0, eps_diluted=6.0,
                       shares_basic_avg=200.0, shares_outstanding=200.0)]
    adjust_periods_for_splits(periods, [["2023-09-01", 2.0]], current_shares=200.0)
    f = periods[0]["fields"]
    assert f["shares_basic_avg"] == 200 and f["eps_basic"] == pytest.approx(5.0)
    assert periods[1]["fields"]["eps_basic"] == 6.0  # after the split: untouched
    # EPS growth is now like-for-like: 5 -> 6 (+20%), not 10 -> 6 (-40%)


def test_split_handles_provider_mixing_adjusted_and_unadjusted_fields():
    # Provider already restated basic shares/EPS but not diluted ones (seen in real data).
    periods = [_period("2023-03-31", "FY2023", net_income=1000.0, eps_basic=5.0, eps_diluted=10.0,
                       shares_basic_avg=200.0, shares_diluted_avg=100.0),
               _period("2024-03-31", "FY2024", net_income=1200.0, eps_basic=6.0, eps_diluted=6.0,
                       shares_basic_avg=200.0, shares_diluted_avg=200.0)]
    adjust_periods_for_splits(periods, [["2023-09-01", 2.0]], current_shares=200.0)
    f = periods[0]["fields"]
    assert f["shares_basic_avg"] == 200 and f["shares_diluted_avg"] == 200
    assert f["eps_basic"] == pytest.approx(5.0) and f["eps_diluted"] == pytest.approx(5.0)


def test_already_adjusted_history_is_left_alone():
    periods = [_period("2023-03-31", "FY2023", net_income=1000.0, eps_basic=5.0, shares_basic_avg=200.0),
               _period("2024-03-31", "FY2024", net_income=1200.0, eps_basic=6.0, shares_basic_avg=200.0)]
    adjust_periods_for_splits(periods, [["2023-09-01", 2.0]], current_shares=200.0)
    assert periods[0]["fields"]["eps_basic"] == 5.0 and periods[0]["fields"]["shares_basic_avg"] == 200


def test_fiscal_year_change_detected_and_growth_not_compared():
    b = {"annual": [_period("2022-03-31", "FY2022", revenue=100.0, net_income=10.0, equity=50.0),
                    _period("2022-12-31", "FY2022b", revenue=80.0, net_income=8.0, equity=55.0)],
         "quarterly": [], "splits": [], "quote": {}, "profile": {}}
    nb = normalize_bundle(b)
    assert any(w["check"] == "fiscal_year_change" for w in nb["data_quality"])
    m = compute_metrics(nb, 25.17)
    assert m["annual"]["series"]["revenue_growth"][1]["value"] is None


# ---------------- metrics ----------------
def _sample(sym):
    b = SampleProvider().fundamentals(sym)
    b.pop("_prices")
    return normalize_bundle(b)


def test_sample_metrics_match_hand_calculation():
    b = _sample("DEMO-STEADY")
    m = compute_metrics(b, IN.statutory_tax_rate)
    L = m["latest"]
    # FY2026: revenue 6800 cr, PBT 1300, tax 328 -> PAT 972 cr
    assert L["net_margin"]["value"] == pytest.approx(972 / 6800 * 100)
    # ROE on average equity (3900 + 4370) / 2
    assert L["roe"]["value"] == pytest.approx(972 / ((3900 + 4370) / 2) * 100)
    # Revenue CAGR FY2023 -> FY2026 (3 years): (6800/4950)^(1/3) - 1, period ~3.0 yrs
    g = m["growth"]["revenue_cagr_3y"]
    assert g["value"] == pytest.approx(((6800 / 4950) ** (1 / 3.0) - 1) * 100, rel=1e-3)
    assert "FY2023" in g["period"] and "FY2026" in g["period"]
    # FCF = CFO - capex
    assert L["fcf"]["value"] == pytest.approx((1050 - 270) * 1e7)
    # Net debt = debt - cash (net cash here)
    assert L["net_debt"]["value"] == pytest.approx((110 - 820) * 1e7)
    assert L["debt_to_equity"]["value"] == pytest.approx(110 / 4370)


def test_cagr_base_effect_detected():
    b = _sample("DEMO-LEVER")
    g = cagr_metric(b["annual"], "eps", 3, eps=True)
    assert g["value"] is not None and g["base_effect"] is True


def test_cagr_needs_enough_periods():
    b = _sample("DEMO-STEADY")
    g = cagr_metric(b["annual"], "revenue", 10)
    assert g["value"] is None and "needs 11" in g["reason"]


def test_ttm_requires_consecutive_quarters():
    q = [_period("2025-06-30", "Q1", revenue=1.0), _period("2025-09-30", "Q2", revenue=1.0),
         _period("2026-03-31", "Q4", revenue=1.0), _period("2026-06-30", "Q5", revenue=1.0)]
    assert ttm_from_quarters(q, "revenue")["value"] is None
    q[2] = _period("2025-12-31", "Q3", revenue=1.0)
    q = sorted(q, key=lambda p: p["period_end"])
    q[-1] = _period("2026-03-31", "Q4", revenue=1.0)
    assert ttm_from_quarters(q, "revenue")["value"] == 4.0


def test_bank_hides_industrial_ratios():
    m = compute_metrics(_sample("DEMO-BANK"), IN.statutory_tax_rate)
    assert m["is_financial"]
    for k in ("debt_to_equity", "interest_coverage", "fcf", "operating_margin"):
        assert m["latest"][k]["value"] is None and m["latest"][k]["status"] == "not_meaningful"
    assert m["latest"]["nim_proxy"]["value"] is not None


# ---------------- valuation ----------------
def test_dcf_known_example():
    # FCF 100; year 1 grows 10%; year 2 fades to 5%; TV at 5% with r = 10%.
    # PV1 = 110/1.1 = 100; FCF2 = 115.5, PV2 = 95.4545; TV = 115.5*1.05/0.05 = 2425.5, PV = 2004.5455
    r = V.dcf(100, growth=10, years=1, fade_years=1, discount=10, terminal=5, net_debt=200, shares=100)
    assert r["enterprise_value"] == pytest.approx(2200.0)
    assert r["value_per_share"] == pytest.approx(20.0)


def test_dcf_rejects_terminal_above_discount():
    r = V.dcf(100, growth=10, years=5, fade_years=5, discount=6, terminal=6, net_debt=0, shares=1)
    assert r["value_per_share"] is None


def test_dcf_not_applicable_for_negative_fcf_and_banks():
    for sym in ("DEMO-LEVER", "DEMO-BANK"):
        b = _sample(sym)
        m = compute_metrics(b, IN.statutory_tax_rate)
        assert V.dcf_analysis(b, m, IN)["applicable"] is False


def test_fair_value_range_labels():
    est = [{"value_per_share": 90}, {"value_per_share": 110}]
    assert V.fair_value_range(100, est)["label"] == "Within estimated fair-value range"
    assert V.fair_value_range(150, est)["label"] == "Potentially overvalued"
    assert V.fair_value_range(50, est)["label"] == "Potentially undervalued"
    assert V.fair_value_range(100, est[:1])["label"] == "Cannot reliably assess"


def test_price_lookup_does_not_use_stale_prices():
    prices = [["2024-01-01", 10, 10, 0], ["2024-03-28", 12, 12, 0]]
    assert V.price_on_or_before(prices, "2024-03-31") == 12
    assert V.price_on_or_before(prices, "2024-03-10") is None  # gap > 10 days


# ---------------- scoring ----------------
def test_missing_inputs_are_excluded_not_zero():
    rules = [{"key": "a", "label": "A", "weight": 50, "points": [[0, 0], [10, 100]]},
             {"key": "b", "label": "B", "weight": 50, "points": [[0, 0], [10, 100]]}]
    out = score_category(rules, {"a": {"value": 10}, "b": {"value": None, "reason": "n/a"}}, 0.4)
    assert out["score"] == 100  # not 50
    assert out["completeness"] == 0.5
    out = score_category(rules, {"a": {"value": None}, "b": {"value": None}}, 0.4)
    assert out["score"] is None and not out["sufficient"]


def _full(sym, notes=None):
    b = _sample(sym)
    m = compute_metrics(b, IN.statutory_tax_rate)
    val = V.multiples(b, m)
    val["comps"] = V.comps_valuation(m, [], val["shares"], None)
    val["fair_value"] = {"label": "Cannot reliably assess"}
    cfg = load_config()
    flags = compute_flags(b, m, val, notes, cfg["profiles"]["default"])
    return b, m, val, flags, score_company(b, m, val, flags, [], notes, cfg)


def test_quality_company_scores_better_than_leveraged_one():
    *_, steady = _full("DEMO-STEADY")
    *_, lever = _full("DEMO-LEVER")
    assert steady["verdicts"]["business_quality"]["score"] > lever["verdicts"]["business_quality"]["score"]
    assert steady["verdicts"]["financial_risk"]["score"] < lever["verdicts"]["financial_risk"]["score"]
    assert lever["decision_label"] == "Elevated financial risk"


def test_red_flags_fire_on_leveraged_sample():
    _, _, _, flags, _ = _full("DEMO-LEVER")
    ids = {f["id"] for f in flags}
    assert {"negative_fcf", "profit_cash_gap", "exceptional_gains", "receivables_outpacing", "dilution"} <= ids
    for f in flags:
        assert f["evidence"] and f["period"] and f["implication"] and f["severity"] in ("high", "medium", "low")


def test_user_entered_governance_feeds_score_and_flags():
    _, _, _, _, s0 = _full("DEMO-STEADY")
    assert s0["categories"]["governance"]["score"] is None  # insufficient without user input
    notes = {"promoter_holding_pct": 55, "promoter_pledge_pct": 60, "auditor_qualification": True,
             "auditor_resigned": False, "material_litigation": False, "rpt_concern": False}
    _, _, _, flags, s1 = _full("DEMO-STEADY", notes)
    assert s1["categories"]["governance"]["score"] is not None
    assert {"pledge", "auditor"} <= {f["id"] for f in flags}


# ---------------- IPO ----------------
def test_ipo_structure_and_valuation_maths():
    p = copy.deepcopy(SAMPLE_IPO["payload"])
    r = analyse_ipo(p, [])
    s = r["structure"]
    px = p["price_band_high"]
    fresh_shares = 400e7 / px
    assert s["fresh_shares"] == pytest.approx(fresh_shares)
    assert s["post_issue_shares"] == pytest.approx(10.5e7 + fresh_shares)
    assert s["fresh_pct"] == pytest.approx(40.0) and s["ofs_pct"] == pytest.approx(60.0)
    mcap_cr = (10.5e7 + fresh_shares) * px / 1e7
    assert s["post_issue_mcap_cr"] == pytest.approx(mcap_cr)
    assert r["valuation"]["pe_post"] == pytest.approx(mcap_cr / 151)
    assert len(r["scenarios"]) == 3
    cons, base, opt = r["scenarios"]
    assert cons["value_per_share"] < base["value_per_share"] < opt["value_per_share"]
    assert any("offer-for-sale" in w for w in r["warnings"])
    assert any("not reasons to invest" in w for w in r["warnings"])


def test_ipo_requires_core_inputs():
    r = analyse_ipo({"price_band_high": 100}, [])
    assert "error" in r


def test_peer_outliers_are_excluded_not_averaged():
    peers = [{"name": "A", "ev_ebitda": 12.0, "pe": 20.0}, {"name": "B", "ev_ebitda": 1048.7, "pe": 22.0},
             {"name": "C", "ev_ebitda": 15.0, "pe": 25.0}, {"name": "D", "ev_ebitda": 14.0, "pe": 120.0},
             {"name": "E", "ev_ebitda": 13.0, "pe": -5.0}]
    out = V.sanitize_peers(peers)
    b = next(p for p in out if p["name"] == "B")
    assert b["ev_ebitda"] is None and "implausible" in b["excluded"]["ev_ebitda"]
    d = next(p for p in out if p["name"] == "D")
    assert d["pe"] is None and "outlier" in d["excluded"]["pe"]
    assert next(p for p in out if p["name"] == "E")["pe"] is None  # negative P/E (loss) is not a multiple
    assert peers[1]["ev_ebitda"] == 1048.7  # input not mutated


def test_foreign_currency_statements_are_converted():
    from app.normalize import convert_currency
    b = {"profile": {"currency": "INR", "financial_currency": "USD"},
         "fx": {"pair": "USDINR=X", "rates": [["2025-03-28", 85.0], ["2026-03-31", 90.0]]},
         "annual": [_period("2025-03-31", "FY2025", net_income=100.0, eps_diluted=1.0, shares_basic_avg=100.0),
                    _period("2026-03-31", "FY2026", net_income=110.0, eps_diluted=1.1, shares_basic_avg=100.0)],
         "quarterly": []}
    w = convert_currency(b)
    f0, f1 = b["annual"][0]["fields"], b["annual"][1]["fields"]
    assert f0["net_income"] == pytest.approx(8500) and f1["eps_diluted"] == pytest.approx(99.0)
    assert f1["shares_basic_avg"] == 100.0  # share counts are not currency amounts
    assert b["profile"]["financial_currency"] == "INR" and b["profile"]["reported_currency"] == "USD"
    assert any(x["check"] == "currency_converted" for x in w)


def test_currency_mismatch_without_fx_blocks_multiples():
    from app.normalize import convert_currency
    b = {"profile": {"currency": "INR", "financial_currency": "USD"}, "fx": {"rates": []},
         "annual": [_period("2026-03-31", "FY2026", net_income=110.0, revenue=500.0, equity=300.0)], "quarterly": [],
         "quote": {"price": 100.0, "shares_outstanding": 10.0}}
    w = convert_currency(b)
    assert b["fx_unconverted"] and w[0]["severity"] == "high"
    m = compute_metrics(b, 25.17)
    out = V.multiples(b, m)["multiples"]
    assert out["pe"]["value"] is None and out["pb"]["value"] is None


def test_discontinued_operations_gain_does_not_inflate_profit():
    from app.normalize import prefer_continuing_operations
    periods = [_period("2026-03-31", "FY2026", net_income=82390e7, net_income_continuing=-1632e7, pbt=-1623e7,
                       shares_basic_avg=368e7, eps_basic=-0.61, eps_diluted=-0.61)]
    w = prefer_continuing_operations(periods)
    f = periods[0]["fields"]
    assert f["net_income"] == -1632e7 and f["net_income_total"] == 82390e7
    assert f["eps_basic"] == pytest.approx(-1632 / 368)
    assert w and w[0]["check"] == "discontinued_operations"
    # Small differences (rounding, minority items) leave reported profit untouched
    p2 = [_period("2026-03-31", "FY2026", net_income=100.0, net_income_continuing=97.0)]
    assert not prefer_continuing_operations(p2) and p2[0]["fields"]["net_income"] == 100.0


# ---------------- valuation bias fixes ----------------
def test_same_family_methods_count_once():
    # Three peer multiples share one peer set: they must not outvote one DCF. Peer median 150 vs DCF 90.
    est = [{"value_per_share": 90, "family": "cash_flow"},
           {"value_per_share": 140, "family": "peers"}, {"value_per_share": 150, "family": "peers"},
           {"value_per_share": 400, "family": "peers"}]
    fv = V.fair_value_range(100, est)
    assert fv["n_families"] == 2 and fv["n_methods"] == 4
    assert (fv["low"], fv["high"]) == (90, 150)  # min–max of family medians, not IQR of 4 raw values
    assert fv["label"] == "Within estimated fair-value range"
    # One family alone is not two independent views, however many methods it has.
    assert V.fair_value_range(100, est[1:])["label"] == "Cannot reliably assess"


def test_wacc_blends_equity_and_after_tax_debt():
    w = V.wacc(market_cap=800, debt=200, cost_of_equity=12.0, cost_of_debt=9.0, tax_rate=25.0)
    assert abs(w["value"] - (0.8 * 12 + 0.2 * 9 * 0.75)) < 1e-9
    assert V.wacc(None, 200, 12.0, 9.0, 25.0)["value"] == 12.0  # no market cap: fall back to cost of equity


def test_own_history_pe_needs_two_years():
    metrics = {"latest": {"eps": {"value": 10.0}}}
    hist = {"pe_stats": {"median": 25.0, "n_weeks": 200, "from": "2021-01-01", "to": "2025-01-01"}}
    out = V.own_history_pe(hist, metrics)
    assert out["value_per_share"] == 250.0 and out["family"] == "history"
    hist["pe_stats"]["n_weeks"] = 50
    assert V.own_history_pe(hist, metrics) is None
    assert V.own_history_pe({"pe_stats": {"median": 25.0, "n_weeks": 200}}, {"latest": {"eps": {"value": -1.0}}}) is None


def test_us_interest_added_back_to_fcf_not_india():
    from app.markets import MARKETS
    metrics = {"annual": {"series": {"fcf": [{"value": 100.0}], "revenue": [{"value": 1000.0}]}},
               "latest": {"effective_tax_rate": {"value": 20.0}}}
    bundle = {"annual": [{"fields": {"interest_expense": {"value": 50.0}}}]}
    us, _, t = V._fcff_series(bundle, metrics, MARKETS["US"])
    assert t == 20.0 and abs(us[0] - 140.0) < 1e-9  # 100 + 50 × (1 − 20%)
    india, _, _ = V._fcff_series(bundle, metrics, MARKETS["IN"])
    assert india[0] == 100.0
