"""The Yahoo adapter, tested offline against a fake ``yfinance`` module.

The live tests (``--live``) prove the adapter still matches Yahoo's real responses; these prove the parsing logic
(statement frames, sign conventions, prices and corporate actions, quotes, search filtering, peers) on every CI run
without the network.
"""
import sys
import types

import pandas as pd
import pytest

from app.providers import yahoo as Y
from app.providers.base import ProviderError

INFO = {
    "quoteType": "EQUITY", "longName": "Fake Industries Ltd", "exchange": "NSI", "currency": "INR",
    "financialCurrency": "INR", "sector": "Industrials", "industry": "Specialty Industrial Machinery",
    "currentPrice": 110.0, "regularMarketPreviousClose": 100.0, "regularMarketTime": 1_700_000_000,
    "sharesOutstanding": 1_000_000, "fiftyTwoWeekHigh": 130.0, "fiftyTwoWeekLow": 80.0,
    "heldPercentInsiders": 0.52, "heldPercentInstitutions": 0.30, "marketCap": 1.1e8, "trailingPE": float("nan"),
    "forwardEps": 9.5, "numberOfAnalystOpinions": 4,
}


def _frame(rows: dict[str, list[float]], dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=pd.to_datetime(dates)).T


ANNUAL = ["2025-03-31", "2024-03-31"]
QUARTER = ["2025-03-31", "2024-12-31"]


class FakeTicker:
    def __init__(self, symbol: str, info=None, fail_statements=False):
        self.symbol = symbol
        self.info = INFO if info is None else info
        self._fail = fail_statements
        self.news = [{"content": {"title": "Fake wins order", "canonicalUrl": {"url": "https://example.com/a"},
                                  "provider": {"displayName": "Wire"}, "pubDate": "2025-05-01"}},
                     {"content": {"title": None}}]

    def _stmt(self, df):
        if self._fail:
            raise RuntimeError("Yahoo hiccup")
        return df

    @property
    def income_stmt(self):
        return self._stmt(_frame({"Total Revenue": [1000.0, 900.0], "Net Income": [120.0, 100.0],
                                  "Interest Expense": [-15.0, -12.0], "Diluted EPS": [12.0, 10.0]}, ANNUAL))

    @property
    def balance_sheet(self):
        return _frame({"Total Assets": [2000.0, 1800.0], "Total Debt": [300.0, float("nan")],
                       "Stockholders Equity": [900.0, 800.0]}, ANNUAL)

    @property
    def cashflow(self):
        return _frame({"Operating Cash Flow": [150.0, 130.0], "Capital Expenditure": [-60.0, -50.0],
                       "Cash Dividends Paid": [-20.0, -18.0]}, ANNUAL)

    @property
    def quarterly_income_stmt(self):
        return _frame({"Total Revenue": [260.0, 250.0]}, QUARTER)

    quarterly_balance_sheet = None
    quarterly_cashflow = None

    def history(self, **_):
        idx = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
        return pd.DataFrame({"Close": [100.0, float("nan"), 104.0], "Adj Close": [99.0, None, 103.5],
                             "Volume": [10, 20, 30], "Dividends": [0.0, 0.0, 2.5],
                             "Stock Splits": [0.0, 0.0, 0.0]}, index=idx)


class FakeEquityQuery:
    def __init__(self, op, operands):
        self.op, self.operands = op, operands


@pytest.fixture
def fake_yf(monkeypatch):
    mod = types.ModuleType("yfinance")
    mod.Ticker = FakeTicker
    mod.EquityQuery = FakeEquityQuery
    mod.screen_calls = []

    def screen(q, **kw):
        mod.screen_calls.append((q, kw))
        return {"quotes": [
            {"symbol": "PEER.BO", "longName": "Peer Co", "exchange": "BSE", "marketCap": 5e9, "trailingPE": 20},
            {"symbol": "PEER.NS", "longName": "Peer Co", "exchange": "NSI", "marketCap": 5e9, "trailingPE": 21},
            {"symbol": "OTHER.NS", "longName": "Other Co", "exchange": "NSI", "marketCap": 3e9, "priceToBook": 2},
        ]}
    mod.screen = screen

    class Search:
        def __init__(self, query, **_):
            self.quotes = [
                {"symbol": "FAKE.NS", "quoteType": "EQUITY", "longname": "Fake Industries", "exchange": "NSI"},
                {"symbol": "7203.T", "quoteType": "EQUITY", "shortname": "Toyota", "exchange": "JPX"},
                {"symbol": "FAKEETF.NS", "quoteType": "ETF", "shortname": "Fake ETF"},
                {"symbol": "AAPL", "quoteType": "EQUITY", "shortname": "Apple", "exchange": "NMS"},
            ]
    mod.Search = Search
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    monkeypatch.setattr(Y, "_throttle", lambda: None)
    monkeypatch.setattr(Y, "_screener_industry", lambda ind: ind)
    return mod


def test_num_rejects_nan_inf_and_text():
    assert Y._num("3.5") == 3.5
    for bad in (None, float("nan"), float("inf"), "n/a", object()):
        assert Y._num(bad) is None


def test_fundamentals_parses_statements_and_signs(fake_yf):
    b = Y.YahooProvider().fundamentals("FAKE.NS")
    assert [p["label"] for p in b["annual"]] == ["FY2024", "FY2025"]  # oldest first
    latest = b["annual"][-1]["fields"]
    assert latest["revenue"] == 1000.0 and latest["net_income"] == 120.0
    # Outflows are stored as positive numbers whatever sign Yahoo uses.
    assert latest["capex"] == 60.0 and latest["dividends_paid"] == 20.0 and latest["interest_expense"] == 15.0
    # A NaN cell is missing, never zero.
    assert "total_debt" not in b["annual"][0]["fields"]
    assert [p["label"] for p in b["quarterly"]] == ["Q Dec-2024", "Q Mar-2025"]


def test_fundamentals_quote_profile_and_actions(fake_yf):
    b = Y.YahooProvider().fundamentals("fake.ns")
    assert b["symbol"] == "FAKE.NS" and b["profile"]["market"] == "IN" and b["profile"]["exchange"] == "NSE"
    q = b["quote"]
    assert q["price"] == 110.0 and q["change"] == 10.0 and abs(q["change_pct"] - 10.0) < 1e-9
    assert q["market_time"].startswith("2023-11-14")
    assert b["holders"] == {"insiders_pct": 52.0, "institutions_pct": 30.0}
    assert b["provider_stats"]["trailingPE"] is None  # NaN from Yahoo becomes missing
    assert b["dividends"] == [["2025-01-06", 2.5]] and b["splits"] == []
    assert [p[0] for p in b["_prices"]] == ["2025-01-02", "2025-01-06"]  # the NaN close is skipped
    assert b["_prices"][0][2] == 99.0
    assert [n["title"] for n in b["news"]] == ["Fake wins order"]  # untitled items dropped
    assert b["news"][0]["link"] == "https://example.com/a"


def test_fundamentals_keeps_going_when_a_statement_fails(fake_yf, monkeypatch):
    monkeypatch.setattr(fake_yf, "Ticker", lambda s: FakeTicker(s, fail_statements=True))
    b = Y.YahooProvider().fundamentals("FAKE.NS")
    assert "revenue" not in b["annual"][-1]["fields"]  # income statement failed ...
    assert b["annual"][-1]["fields"]["total_assets"] == 2000.0  # ... the balance sheet still arrived


def test_unknown_symbol_is_not_found(fake_yf, monkeypatch):
    monkeypatch.setattr(fake_yf, "Ticker", lambda s: FakeTicker(s, info={}))
    with pytest.raises(ProviderError) as e:
        Y.YahooProvider().fundamentals("NOPE.NS")
    assert e.value.not_found


def test_quote_requires_a_price(fake_yf, monkeypatch):
    q = Y.YahooProvider().quote("FAKE.NS")
    assert q["price"] == 110.0 and q["week52_low"] == 80.0
    monkeypatch.setattr(fake_yf, "Ticker", lambda s: FakeTicker(s, info={"currency": "INR"}))
    with pytest.raises(ProviderError):
        Y.YahooProvider().quote("FAKE.NS")


def test_search_keeps_supported_equities_only(fake_yf):
    res = Y.YahooProvider().search("fake")
    assert [r["symbol"] for r in res] == ["FAKE.NS", "AAPL"]  # Tokyo listing and the ETF are dropped
    assert [r["market"] for r in res] == ["IN", "US"]


def test_peers_collapse_nse_bse_duplicates(fake_yf):
    rows = Y.YahooProvider().peers("FAKE.NS", "Specialty Industrial Machinery", "in")
    assert [r["symbol"] for r in rows] == ["PEER.NS", "OTHER.NS"]  # NSE listing preferred over BSE
    q, kw = fake_yf.screen_calls[0]
    assert kw["sortField"] == "intradaymarketcap" and q.op == "and"
    assert Y.YahooProvider().peers("FAKE.NS", None, "in") == []


def test_peer_details_converts_units(fake_yf, monkeypatch):
    info = {"longName": "Peer", "returnOnEquity": 0.18, "profitMargins": 0.1, "debtToEquity": 45.0,
            "currentPrice": 50.0}
    monkeypatch.setattr(fake_yf, "Ticker", lambda s: FakeTicker(s, info=info))
    d = Y.YahooProvider().peer_details("PEER.NS")
    assert abs(d["roe"] - 18.0) < 1e-9 and abs(d["net_margin"] - 10.0) < 1e-9
    assert d["debt_to_equity"] == 0.45 and d["operating_margin"] is None  # Yahoo gives D/E in percent


def test_fx_series(fake_yf):
    fx = Y.YahooProvider()._fx_series("USD", "INR")
    assert fx["pair"] == "USDINR=X" and fx["rates"] == [["2025-01-02", 100.0], ["2025-01-06", 104.0]]
