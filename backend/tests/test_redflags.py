"""Every red-flag rule: it fires on evidence past its threshold, and stays quiet just inside it.

Inputs are built directly (no provider), so each test changes one number and checks one rule.
"""
import pytest

from app.engine.redflags import compute_flags

THRESHOLDS = {"de_medium": 1.0, "de_high": 2.0, "nd_ebitda_medium": 3.0, "nd_ebitda_high": 4.0,
              "cash_conversion_warn": 0.8}
LABELS = ["FY2022", "FY2023", "FY2024", "FY2025"]


def build(series=None, latest=None, fields=None, fin=False, kind=None, growth=None):
    """Metrics and bundle for four healthy years; override only what a test is about."""
    base = {"net_income": [100, 110, 120, 130], "fcf": [50, 60, 70, 80], "cfo": [120, 130, 140, 150],
            "operating_margin": [20, 20, 20, 20], "roe": [18, 18, 18, 18], "unusual_share_of_pbt": [0, 0, 0, 0]}
    base.update(series or {})
    lat = {"debt_to_equity": 0.3, "net_debt_to_ebitda": 0.5, "interest_coverage": 12, "current_ratio": 1.6,
           "revenue_growth": 10, "net_income_growth": 8}
    lat.update(latest or {})
    flds = [{"equity": 500, "revenue": 1000 * (1.1 ** i), "receivables": 100 * (1.1 ** i),
             "shares_outstanding": 100} for i in range(4)]
    for k, vals in (fields or {}).items():
        for i, v in enumerate(vals):
            flds[i][k] = v
    metrics = {"annual": {"labels": LABELS, "series": {k: [{"value": v} for v in vs] for k, vs in base.items()}},
               "latest": {k: {"value": v} for k, v in lat.items()},
               "growth": growth or {"eps_cagr_3y": {"value": 10}}, "is_financial": fin,
               "financial_kind": kind if fin else None}
    return {"annual": [{"fields": f} for f in flds]}, metrics


def ids(bundle, metrics, valuation=None, notes=None):
    return {f["id"] for f in compute_flags(bundle, metrics, valuation or {}, notes, THRESHOLDS)}


def test_healthy_company_has_no_flags():
    assert ids(*build()) == set()


def test_losses():
    assert "losses" in ids(*build(series={"net_income": [100, 110, -5, -20]}))


def test_negative_equity():
    assert "negative_equity" in ids(*build(fields={"equity": [500, 400, 100, -10]}))


def test_margin_decline():
    assert "margin_decline" in ids(*build(series={"operating_margin": [20, 20, 20, 16.5]}))
    assert "margin_decline" not in ids(*build(series={"operating_margin": [20, 20, 20, 17.5]}))  # only 2.5 pp


@pytest.mark.parametrize("de,severity", [(1.5, "medium"), (2.5, "high")])
def test_high_leverage(de, severity):
    b, m = build(latest={"debt_to_equity": de})
    f = next(f for f in compute_flags(b, m, {}, None, THRESHOLDS) if f["id"] == "high_leverage")
    assert f["severity"] == severity


def test_high_net_debt_ebitda():
    assert "high_net_debt_ebitda" in ids(*build(latest={"net_debt_to_ebitda": 3.5}))
    assert "high_net_debt_ebitda" not in ids(*build(latest={"net_debt_to_ebitda": 2.9}))


def test_weak_coverage():
    assert "weak_coverage" in ids(*build(latest={"interest_coverage": 2.0}))


def test_low_liquidity():
    assert "low_liquidity" in ids(*build(latest={"current_ratio": 0.8}))


def test_declining_returns():
    assert "declining_returns" in ids(*build(series={"roe": [25, 24, 20, 15]}))
    assert "declining_returns" not in ids(*build(series={"roe": [20, 19, 18, 17]}))  # only 2 pp


def test_sudden_deterioration():
    assert "sudden_deterioration" in ids(*build(latest={"revenue_growth": -20}))
    assert "sudden_deterioration" in ids(*build(latest={"net_income_growth": -40}))


def test_valuation_vs_peers_and_absolute():
    val = {"multiples": {"pe": {"value": 40}}, "comps": {"medians": {"pe": {"value": 20}}}}
    assert "valuation_vs_peers" in ids(*build(), valuation=val)
    val = {"multiples": {"pe": {"value": 70}}}
    assert "valuation_absolute" in ids(*build(), valuation=val)
    b, m = build(growth={"eps_cagr_3y": {"value": 25}})
    assert "valuation_absolute" not in ids(b, m, valuation=val)  # high P/E backed by growth


def test_user_entered_litigation_and_rpt():
    notes = {"material_litigation": True, "rpt_concern": True}
    assert {"litigation", "rpt"} <= ids(*build(), notes=notes)


def lender(**latest):
    return build(latest={"roa": 1.5, "loan_growth": 12, "equity_to_assets": 10, **latest}, fin=True, kind="lender")


def test_lender_rules():
    assert ids(*lender()) == set()
    assert "low_roa" in ids(*lender(roa=0.4))
    assert "rapid_loan_growth" in ids(*lender(loan_growth=35))
    assert "thin_equity" in ids(*lender(equity_to_assets=5))


def test_industrial_rules_do_not_apply_to_lenders():
    b, m = lender(debt_to_equity=8, current_ratio=0.2)
    assert not {"high_leverage", "low_liquidity"} & ids(b, m)


def test_insurers_skip_lender_thresholds():
    # A life insurer's ROA and equity ÷ assets are low by design; they must not be flagged as weak lending.
    b, m = build(latest={"roa": 0.4, "equity_to_assets": 4}, fin=True, kind="insurer")
    assert not {"low_roa", "thin_equity"} & ids(b, m)
