"""Regression tests for the scoring fixes: which companies get the bank model, governance parity across markets,
inputs counted once, short fiscal years, ROIC with missing debt, and unsupported exchanges."""
import copy

import pytest

from app.engine import valuation as V
from app.engine.metrics import cagr_metric, compute_metrics, compute_series, financial_kind
from app.engine.redflags import compute_flags
from app.engine.scoring import INDIA_ONLY_INPUTS, load_config, score_company
from app.markets import UnsupportedMarket, market_for_symbol
from app.providers import registry
from app.providers.sample import SampleProvider


# ---------------- which companies are lenders ----------------
@pytest.mark.parametrize("industry,fields,expected", [
    ("Banks - Regional", None, "lender"),
    ("Mortgage Finance", None, "lender"),
    ("Capital Markets", None, "lender"),  # broker-dealers: balance sheets of client money
    ("Insurance - Life", None, "insurer"),
    ("Insurance - Property & Casualty", None, "insurer"),
    ("Insurance Brokers", None, None),  # fee business, standard model
    ("Financial Data & Stock Exchanges", None, None),
    ("Credit Services", {"net_loans": 890, "total_assets": 1000}, "lender"),  # an NBFC
    ("Credit Services", {"revenue": 100, "net_interest_income": -2, "total_assets": 1000}, None),  # Visa-like
    ("Credit Services", None, "lender"),  # no balance-sheet data: keep the conservative default
    # An Indian NBFC as Yahoo reports it: no loan book, negative "net interest income", but 84% of assets borrowed.
    ("Credit Services", {"revenue": 100, "net_interest_income": -39, "total_debt": 840, "total_assets": 1000}, "lender"),
    ("Credit Services", {"revenue": 100, "net_interest_income": -2, "total_debt": 380, "total_assets": 1000}, None),
    ("Asset Management", {"revenue": 100, "net_interest_income": 1, "total_debt": 600, "total_assets": 1000}, None),
    ("Asset Management", {"revenue": 100, "net_interest_income": 0.5}, None),  # a fund manager
    ("Asset Management", {"net_loans": 600, "total_assets": 1000}, "lender"),  # a lender filed as asset manager
    ("Asset Management", None, None),
    ("Software - Application", {"net_loans": 900, "total_assets": 1000}, None),
])
def test_financial_kind(industry, fields, expected):
    assert financial_kind({"sector": "Financial Services", "industry": industry}, fields) == expected


def _bundle(sym, industry=None):
    b = SampleProvider().fundamentals(sym)
    if industry:
        b = copy.deepcopy(b)
        b["profile"]["industry"] = industry
    return b


def _score(b, market="IN", notes=None):
    from app.markets import MARKETS
    m = compute_metrics(b, MARKETS[market].statutory_tax_rate)
    val = V.multiples(b, m)
    val["comps"] = V.comps_valuation(m, [], val["shares"], None)
    val["fair_value"] = {"label": "Cannot reliably assess"}
    cfg = load_config()
    flags = compute_flags(b, m, val, notes, cfg["profiles"]["default"])
    return m, score_company(b, m, val, flags, [], notes, cfg, market=market)


def test_insurer_uses_revenue_growth_and_skips_bank_only_categories():
    m, s = _score(_bundle("DEMO-BANK", "Insurance - Life"))
    assert m["financial_kind"] == "insurer" and s["model"] == "financial"
    growth_keys = {it["key"] for it in s["categories"]["growth"]["items"]}
    assert "revenue_cagr" in growth_keys and not {"nii_cagr", "loans_cagr"} & growth_keys
    for cat in ("asset_quality", "cash_flow", "balance_sheet"):  # balance sheet: life insurers only
        assert s["categories"][cat].get("not_applicable"), cat


def test_bank_still_gets_the_bank_model():
    m, s = _score(_bundle("DEMO-BANK"))
    assert m["financial_kind"] == "lender"
    assert {"nii_cagr", "loans_cagr"} <= {it["key"] for it in s["categories"]["growth"]["items"]}


# ---------------- governance and double counting ----------------
def test_governance_needs_entered_facts_in_both_markets():
    assert {"pledge_pct", "insider_holding"} <= INDIA_ONLY_INPUTS
    for market in ("IN", "US"):
        _, s = _score(_bundle("DEMO-STEADY"), market=market)
        assert s["categories"]["governance"]["score"] is None, market  # provider data alone is not enough
        _, s = _score(_bundle("DEMO-STEADY"), market=market,
                      notes={"auditor_qualification": False, "auditor_resigned": False,
                             "material_litigation": False, "rpt_concern": False})
        assert s["categories"]["governance"]["score"] is not None, market


def test_each_input_counts_once_in_the_composite():
    cfg = load_config()
    for model, cats in cfg["categories"].items():
        keys = [r["key"] for name, rules in cats.items() if name in cfg["composite_weights"][model] for r in rules]
        assert len(keys) == len(set(keys)), (model, sorted(k for k in keys if keys.count(k) > 1))


# ---------------- short fiscal years and ROIC ----------------
def _periods(short_index=None):
    ps = []
    for i, (end, rev) in enumerate([("2022-03-31", 1000), ("2022-12-31", 750), ("2023-12-31", 1000),
                                    ("2024-12-31", 1100)]):
        p = {"period_end": end, "label": f"FY{end[:4]}", "fields": {"revenue": rev, "net_income": rev / 10,
                                                                     "eps_diluted": rev / 100}}
        if i == short_index:
            p["non_standard_length_days"] = 275
        ps.append(p)
    return ps


def test_growth_is_not_measured_against_a_short_year():
    S = compute_series(_periods(short_index=1), statutory_tax=25)["series"]
    growth = [c["value"] for c in S["revenue_growth"]]
    assert growth[1] is None  # the short year itself
    assert growth[2] is None  # the full year after it: was +33% from 750 → 1000
    assert abs(growth[3] - 10.0) < 1e-9  # two normal years compare as usual


def test_cagr_refuses_a_short_start_or_end_year():
    ps = _periods(short_index=1)
    out = cagr_metric(ps[1:], "revenue", 2)  # starts at the 9-month year
    assert out["value"] is None and "12-month" in out["reason"]
    assert cagr_metric(_periods(), "revenue", 3)["value"] is not None


def test_roic_is_missing_when_debt_is_missing():
    ps = [{"period_end": f"{y}-03-31", "label": f"FY{y}",
           "fields": {"revenue": 1000, "ebit": 200, "pbt": 180, "tax": 45, "equity": 800, "cash": 100,
                      "total_debt": 300}} for y in (2024, 2025)]
    S = compute_series(ps, statutory_tax=25)["series"]
    assert S["roic"][-1]["value"] is not None
    del ps[-1]["fields"]["total_debt"]
    cell = compute_series(ps, statutory_tax=25)["series"]["roic"][-1]
    assert cell["value"] is None and "total debt" in cell["reason"]  # not computed as if debt were zero


# ---------------- markets ----------------
@pytest.mark.parametrize("sym", ["7203.T", "VOD.L", "0700.HK", "SAP.DE"])
def test_unsupported_exchanges_are_rejected(sym):
    with pytest.raises(UnsupportedMarket):
        market_for_symbol(sym)
    with pytest.raises(ValueError):
        registry.validate_symbol(sym)


@pytest.mark.parametrize("sym,code", [("TCS.NS", "IN"), ("500325.BO", "IN"), ("AAPL", "US"), ("BRK-B", "US"),
                                      ("DEMO-STEADY", "IN")])
def test_supported_symbols(sym, code):
    assert market_for_symbol(sym).code == code and registry.validate_symbol(sym) == sym
