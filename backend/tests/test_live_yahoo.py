"""Integration tests against the real Yahoo Finance endpoints. Run with: pytest --live"""
import pytest

pytestmark = pytest.mark.live


def test_yahoo_fundamentals_shape():
    from app.providers.yahoo import YahooProvider
    b = YahooProvider().fundamentals("TCS.NS")
    assert b["profile"]["exchange"] == "NSE" and b["profile"]["currency"] == "INR"
    assert len(b["annual"]) >= 3
    latest = b["annual"][-1]["fields"]
    for k in ("revenue", "net_income", "total_assets", "equity", "cfo"):
        assert k in latest
    assert b["quote"]["price"] and b["quote"]["delayed"] is True
    assert len(b["_prices"]) > 1000


def test_yahoo_search_groups_nse_bse():
    from app.providers import registry
    r = registry.search("hdfc bank")
    hdfc = next(g for g in r["results"] if "HDFC Bank" in g["name"])
    exch = {l["exchange"] for l in hdfc["listings"]}
    assert "NSE" in exch and hdfc["primary_symbol"].endswith(".NS")


def test_bank_bonus_issue_eps_is_consistent():
    """HDFC Bank's 1:1 bonus (Aug 2025): historical EPS must be on the post-bonus basis."""
    from app.providers import registry
    b = registry.get_bundle("HDFCBANK.NS", force=True)
    eps = [p["fields"].get("eps_diluted") for p in b["annual"]]
    eps = [e for e in eps if e]
    assert max(eps) / min(eps) < 1.5  # no 2x jump from mixing bases


def test_usd_reporter_converted_to_inr():
    """Infosys reports to Yahoo in USD but trades in INR: multiples must be computed in one currency."""
    from app.analysis import analyse
    a = analyse("INFY.NS", force=True)
    assert a["profile"]["financial_currency"] == "INR" and a["profile"].get("reported_currency") == "USD"
    pe = a["valuation"]["multiples"]["pe"]["value"]
    assert pe is not None and 5 < pe < 80
    pb_recon = next(r for r in a["valuation"]["reconciliation"] if r["metric"] == "P/B")
    assert abs(pb_recon["diff_pct"]) < 15
