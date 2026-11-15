"""Yahoo Finance adapter (via the open-source ``yfinance`` client).

Licensing: Yahoo's public endpoints are for personal, non-commercial use. This app is
single-user and personal. Calls are throttled and cached to stay polite.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .. import config
from ..markets import MARKETS, exchange_display, market_code_or_none, market_for_symbol
from .base import ProviderError

log = logging.getLogger("stockiq.yahoo")

# Candidate Yahoo row labels for each canonical field, in priority order.
INCOME_MAP: dict[str, list[str]] = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "cost_of_revenue": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "operating_expense": ["Operating Expense"],
    "ebitda": ["EBITDA"],
    "depreciation": ["Reconciled Depreciation", "Depreciation And Amortization In Income Statement",
                     "Depreciation Amortization Depletion Income Statement"],
    "operating_income": ["Operating Income"],
    "ebit": ["EBIT"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "interest_income": ["Interest Income", "Interest Income Non Operating"],
    "net_interest_income": ["Net Interest Income"],
    "unusual_items": ["Total Unusual Items", "Total Unusual Items Excluding Goodwill"],
    "pbt": ["Pretax Income"],
    "tax": ["Tax Provision"],
    "minority_interest_pl": ["Minority Interests"],
    "net_income": ["Net Income Common Stockholders", "Net Income",
                   "Net Income From Continuing Operation Net Minority Interest"],
    "net_income_continuing": ["Net Income From Continuing Operation Net Minority Interest"],
    "net_income_discontinued": ["Net Income Discontinuous Operations"],
    "eps_basic": ["Basic EPS"],
    "eps_diluted": ["Diluted EPS"],
    "shares_basic_avg": ["Basic Average Shares"],
    "shares_diluted_avg": ["Diluted Average Shares"],
}
BALANCE_MAP: dict[str, list[str]] = {
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets"],
    "cash": ["Cash And Cash Equivalents", "Cash Financial"],
    "short_term_investments": ["Other Short Term Investments"],
    "receivables": ["Accounts Receivable", "Receivables"],
    "inventory": ["Inventory"],
    "net_ppe": ["Net PPE"],
    "goodwill_intangibles": ["Goodwill And Other Intangible Assets"],
    "net_loans": ["Net Loan"],
    "total_liabilities": ["Total Liabilities Net Minority Interest"],
    "current_liabilities": ["Current Liabilities"],
    "payables": ["Accounts Payable", "Payables"],
    "total_debt": ["Total Debt"],
    "current_debt": ["Current Debt And Capital Lease Obligation", "Current Debt"],
    "long_term_debt": ["Long Term Debt And Capital Lease Obligation", "Long Term Debt"],
    "lease_liabilities": ["Capital Lease Obligations"],
    "equity": ["Stockholders Equity", "Common Stock Equity"],
    "minority_interest": ["Minority Interest"],
    "shares_outstanding": ["Ordinary Shares Number", "Share Issued"],
}
CASHFLOW_MAP: dict[str, list[str]] = {
    "cfo": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "cfi": ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities"],
    "cff": ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities"],
    "capex": ["Capital Expenditure", "Purchase Of PPE"],
    "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "buybacks": ["Repurchase Of Capital Stock", "Common Stock Payments"],
    "share_issuance": ["Issuance Of Capital Stock", "Common Stock Issuance"],
    "change_receivables": ["Change In Receivables"],
    "acquisitions": ["Purchase Of Business"],
}
# Stored as positive outflows (Yahoo reports them as negatives).
ABS_FIELDS = {"capex", "dividends_paid", "buybacks", "acquisitions", "interest_expense"}

_call_lock = threading.Lock()
_last_call = [0.0]


def _throttle() -> None:
    with _call_lock:
        wait = config.MIN_SECONDS_BETWEEN_PROVIDER_CALLS - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()


def _num(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _frame_to_periods(df, mapping: dict[str, list[str]], quarterly: bool) -> dict[str, dict[str, float]]:
    """{period_end_iso: {field: value}} from a yfinance statement frame (rows=items, cols=dates)."""
    out: dict[str, dict[str, float]] = {}
    if df is None or getattr(df, "empty", True):
        return out
    index = set(df.index)
    for col in df.columns:
        end = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)[:10]
        fields: dict[str, float] = {}
        for field, candidates in mapping.items():
            for label in candidates:
                if label in index:
                    v = _num(df.at[label, col])
                    if v is not None:
                        fields[field] = abs(v) if field in ABS_FIELDS else v
                        break
        if fields:
            out[end] = fields
    return out


def _label(period_end: str, quarterly: bool) -> str:
    d = datetime.strptime(period_end, "%Y-%m-%d")
    return f"Q {d.strftime('%b-%Y')}" if quarterly else f"FY{d.year}"


def _merge(*maps: dict[str, dict[str, float]], quarterly: bool) -> list[dict[str, Any]]:
    ends = sorted({e for m in maps for e in m})
    periods = []
    for e in ends:
        fields: dict[str, float] = {}
        for m in maps:
            fields.update(m.get(e, {}))
        periods.append({"period_end": e, "label": _label(e, quarterly), "fields": fields})
    return periods


def _ts(dt) -> str:
    return dt.strftime("%Y-%m-%d")


def _screener_industry(industry: str) -> Optional[str]:
    """Map a quote-summary industry ("Banks - Regional") to the screener's spelling ("Banks—Regional")."""
    import re
    try:
        from yfinance.const import EQUITY_SCREENER_EQ_MAP
    except Exception:
        return industry
    valid = EQUITY_SCREENER_EQ_MAP.get("industry", {})
    names = [n for v in valid.values() for n in v] if isinstance(valid, dict) else list(valid)
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    lookup = {norm(n): n for n in names}
    return lookup.get(norm(industry))


class YahooProvider:
    name = "yahoo"
    source_label = "Yahoo Finance (via yfinance)"

    def __init__(self) -> None:
        import yfinance  # noqa: F401  (fail fast if not installed)

    def supports(self, symbol: str) -> bool:
        return not symbol.upper().startswith("DEMO")

    # ---------------- search ----------------
    def search(self, query: str) -> list[dict[str, Any]]:
        import yfinance as yf
        _throttle()
        try:
            res = yf.Search(query, max_results=15, news_count=0, enable_fuzzy_query=True)
            quotes = res.quotes or []
        except Exception as e:  # network / parse
            raise ProviderError(f"Yahoo search failed: {e}") from e
        out = []
        for q in quotes:
            if q.get("quoteType") != "EQUITY":
                continue
            sym = q.get("symbol")
            if not sym or market_code_or_none(sym) is None:
                continue  # listings on unsupported exchanges are not offered
            out.append({
                "symbol": sym,
                "name": q.get("longname") or q.get("shortname") or sym,
                "exchange": exchange_display(q.get("exchange")) or q.get("exchDisp"),
                "exchange_code": q.get("exchange"),
                "market": market_for_symbol(sym).code,
                "sector": q.get("sector"),
                "industry": q.get("industry"),
                "provider": self.name,
            })
        return out

    # ---------------- fundamentals ----------------
    def fundamentals(self, symbol: str) -> dict[str, Any]:
        import yfinance as yf
        t = yf.Ticker(symbol)
        try:
            _throttle()
            info = t.info or {}
        except Exception as e:
            raise ProviderError(f"Yahoo quote/profile request failed: {e}") from e
        if not info or (info.get("quoteType") is None and info.get("regularMarketPrice") is None):
            raise ProviderError(f"Symbol {symbol} not found on Yahoo Finance", retryable=False, not_found=True)

        frames = {}
        for attr in ("income_stmt", "balance_sheet", "cashflow", "quarterly_income_stmt",
                     "quarterly_balance_sheet", "quarterly_cashflow"):
            try:
                _throttle()
                frames[attr] = getattr(t, attr)
            except Exception as e:  # keep going; partial data is handled downstream
                log.warning("Yahoo %s for %s failed: %s", attr, symbol, e)
                frames[attr] = None

        annual = _merge(
            _frame_to_periods(frames["income_stmt"], INCOME_MAP, False),
            _frame_to_periods(frames["balance_sheet"], BALANCE_MAP, False),
            _frame_to_periods(frames["cashflow"], CASHFLOW_MAP, False), quarterly=False)
        quarterly = _merge(
            _frame_to_periods(frames["quarterly_income_stmt"], INCOME_MAP, True),
            _frame_to_periods(frames["quarterly_balance_sheet"], BALANCE_MAP, True),
            _frame_to_periods(frames["quarterly_cashflow"], CASHFLOW_MAP, True), quarterly=True)

        # Full price history with corporate actions (one request gives prices, dividends and splits).
        try:
            _throttle()
            hist = t.history(period="max", auto_adjust=False, actions=True)
        except Exception as e:
            log.warning("Yahoo history for %s failed: %s", symbol, e)
            hist = None
        dividends, splits, prices = [], [], []
        if hist is not None and not hist.empty:
            for idx, row in hist.iterrows():
                d = _ts(idx)
                if _num(row.get("Dividends")):
                    dividends.append([d, float(row["Dividends"])])
                if _num(row.get("Stock Splits")):
                    splits.append([d, float(row["Stock Splits"])])
                c = _num(row.get("Close"))
                if c is not None:
                    prices.append([d, round(c, 4), round(_num(row.get("Adj Close")) or c, 4),
                                   int(_num(row.get("Volume")) or 0)])

        news = []
        try:
            for n in (t.news or [])[:12]:
                c = n.get("content", n)
                link = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link")
                news.append({"title": c.get("title"), "publisher": (c.get("provider") or {}).get("displayName")
                             if isinstance(c.get("provider"), dict) else c.get("publisher"),
                             "link": link, "published_at": c.get("pubDate") or c.get("providerPublishTime")})
        except Exception:
            pass

        mkt = market_for_symbol(symbol)
        fin_cur = info.get("financialCurrency")
        quote_cur = info.get("currency")
        fx = None
        if fin_cur and quote_cur and fin_cur != quote_cur:
            fx = self._fx_series(fin_cur, quote_cur)
        price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        prev = _num(info.get("regularMarketPreviousClose")) or _num(info.get("previousClose"))
        mtime = info.get("regularMarketTime")
        delay = info.get("exchangeDataDelayedBy")
        bundle = {
            "symbol": symbol.upper(),
            "provider": self.name,
            "source_label": self.source_label,
            "is_sample": False,
            "retrieved_at": time.time(),
            "profile": {
                "name": info.get("longName") or info.get("shortName") or symbol,
                "symbol": symbol.upper(),
                "exchange": exchange_display(info.get("exchange")) or info.get("fullExchangeName"),
                "market": mkt.code,
                "currency": info.get("currency") or mkt.currency,
                "financial_currency": info.get("financialCurrency") or info.get("currency") or mkt.currency,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "summary": info.get("longBusinessSummary"),
                "website": info.get("website"),
                "ir_website": info.get("irWebsite"),
                "employees": info.get("fullTimeEmployees"),
                "fiscal_year_end": info.get("lastFiscalYearEnd"),
            },
            "quote": {
                "price": price,
                "previous_close": prev,
                "change": (price - prev) if (price is not None and prev) else None,
                "change_pct": ((price / prev - 1) * 100) if (price is not None and prev) else None,
                "market_time": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else None,
                "delayed": True,
                "delay_minutes": delay,
                "shares_outstanding": _num(info.get("sharesOutstanding")) or _num(info.get("impliedSharesOutstanding")),
                "week52_high": _num(info.get("fiftyTwoWeekHigh")),
                "week52_low": _num(info.get("fiftyTwoWeekLow")),
                "currency": info.get("currency") or mkt.currency,
                "market_state": info.get("marketState"),
            },
            "provider_stats": {k: _num(info.get(k)) for k in (
                "marketCap", "enterpriseValue", "trailingPE", "priceToBook", "priceToSalesTrailing12Months",
                "enterpriseToEbitda", "trailingEps", "bookValue", "returnOnEquity", "returnOnAssets",
                "debtToEquity", "profitMargins", "operatingMargins", "revenueGrowth", "earningsGrowth",
                "totalDebt", "totalCash", "ebitda", "totalRevenue", "netIncomeToCommon", "beta",
                "payoutRatio", "dividendRate", "currentRatio", "quickRatio", "freeCashflow", "operatingCashflow")},
            "analyst": {
                "forward_eps": _num(info.get("forwardEps")) or _num(info.get("epsForward")),
                "n_analysts": info.get("numberOfAnalystOpinions"),
            },
            "annual": annual,
            "quarterly": quarterly,
            "dividends": dividends,
            "splits": splits,
            "holders": {
                "insiders_pct": (_num(info.get("heldPercentInsiders")) or 0) * 100 if info.get("heldPercentInsiders") is not None else None,
                "institutions_pct": (_num(info.get("heldPercentInstitutions")) or 0) * 100 if info.get("heldPercentInstitutions") is not None else None,
            },
            "news": [n for n in news if n.get("title")],
            "fx": fx,
            "_prices": prices,
        }
        return bundle

    def _fx_series(self, from_cur: str, to_cur: str) -> Optional[dict[str, Any]]:
        """Daily FX closes (e.g. USDINR=X) used to restate statements into the quote currency."""
        import yfinance as yf
        pair = f"{from_cur}{to_cur}=X"
        try:
            _throttle()
            h = yf.Ticker(pair).history(period="max", auto_adjust=False)
        except Exception as e:
            log.warning("FX %s failed: %s", pair, e)
            return {"pair": pair, "from": from_cur, "to": to_cur, "rates": [], "error": str(e)}
        rates = [[_ts(i), round(float(r["Close"]), 6)] for i, r in h.iterrows() if _num(r.get("Close"))]
        return {"pair": pair, "from": from_cur, "to": to_cur, "rates": rates,
                "source": "Yahoo Finance FX (daily close)"}

    def prices(self, symbol: str) -> dict[str, Any]:
        b = self.fundamentals(symbol)
        return {"prices": b["_prices"]}

    def quote(self, symbol: str) -> dict[str, Any]:
        """Lightweight quote refresh (one request)."""
        import yfinance as yf
        _throttle()
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as e:
            raise ProviderError(f"Yahoo quote request failed: {e}") from e
        price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
        if price is None:
            raise ProviderError("Yahoo returned no price", retryable=True)
        prev = _num(info.get("regularMarketPreviousClose")) or _num(info.get("previousClose"))
        mtime = info.get("regularMarketTime")
        return {
            "price": price, "previous_close": prev,
            "change": (price - prev) if prev else None,
            "change_pct": ((price / prev - 1) * 100) if prev else None,
            "market_time": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else None,
            "delayed": True, "delay_minutes": info.get("exchangeDataDelayedBy"),
            "shares_outstanding": _num(info.get("sharesOutstanding")) or _num(info.get("impliedSharesOutstanding")),
            "week52_high": _num(info.get("fiftyTwoWeekHigh")), "week52_low": _num(info.get("fiftyTwoWeekLow")),
            "currency": info.get("currency"), "market_state": info.get("marketState"),
        }

    # ---------------- peers ----------------
    def peers(self, symbol: str, industry: str | None, region: str) -> list[dict[str, Any]]:
        if not industry:
            return []
        import yfinance as yf
        from yfinance import EquityQuery
        screener_industry = _screener_industry(industry)
        if not screener_industry:
            raise ProviderError(f"Industry '{industry}' is not supported by the Yahoo screener", retryable=False)
        _throttle()
        try:
            q = EquityQuery("and", [EquityQuery("eq", ["region", region]),
                                    EquityQuery("eq", ["industry", screener_industry])])
            res = yf.screen(q, sortField="intradaymarketcap", sortAsc=False, size=40)
        except Exception as e:
            raise ProviderError(f"Yahoo screener failed: {e}") from e
        seen: dict[str, dict[str, Any]] = {}
        preferred = MARKETS["IN"].exchanges if region == "in" else {}
        for x in res.get("quotes", []):
            name = x.get("longName") or x.get("shortName") or x.get("symbol")
            key = (name or "").strip().lower()
            row = {
                "symbol": x.get("symbol"), "name": name,
                "exchange": exchange_display(x.get("exchange")),
                "market_cap": _num(x.get("marketCap")), "price": _num(x.get("regularMarketPrice")),
                "pe": _num(x.get("trailingPE")), "pb": _num(x.get("priceToBook")),
                "eps_ttm": _num(x.get("epsTrailingTwelveMonths")),
                "dividend_yield": _num(x.get("dividendYield")),
                "currency": x.get("currency"),
            }
            # Collapse NSE/BSE duplicates of the same company, preferring NSE.
            if key in seen:
                if region == "in" and x.get("exchange") == "NSI":
                    seen[key] = row
                continue
            seen[key] = row
        _ = preferred
        return list(seen.values())

    def peer_details(self, symbol: str) -> dict[str, Any]:
        """Provider-reported ratios for one peer (used in the peer table)."""
        import yfinance as yf
        _throttle()
        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as e:
            raise ProviderError(f"Yahoo peer info failed: {e}") from e
        g = lambda k: _num(info.get(k))  # noqa: E731
        roe = g("returnOnEquity")
        return {
            "symbol": symbol, "name": info.get("longName") or info.get("shortName"),
            "market_cap": g("marketCap"), "price": g("currentPrice") or g("regularMarketPrice"),
            "pe": g("trailingPE"), "pb": g("priceToBook"), "ps": g("priceToSalesTrailing12Months"),
            "ev_ebitda": g("enterpriseToEbitda"),
            "roe": roe * 100 if roe is not None else None,
            "net_margin": (g("profitMargins") or 0) * 100 if g("profitMargins") is not None else None,
            "operating_margin": (g("operatingMargins") or 0) * 100 if g("operatingMargins") is not None else None,
            "revenue_growth": (g("revenueGrowth") or 0) * 100 if g("revenueGrowth") is not None else None,
            "debt_to_equity": (g("debtToEquity") / 100) if g("debtToEquity") is not None else None,
            "dividend_yield": g("dividendYield"),
            "eps_ttm": g("trailingEps"),
            "currency": info.get("currency"),
        }
