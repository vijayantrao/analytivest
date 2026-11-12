"""Sample provider: FICTIONAL demo companies with synthetic numbers.

These exist so the app works offline and so tests are deterministic. They are not
real companies, and every payload carries ``is_sample: true``; the UI shows a
SAMPLE DATA banner wherever they appear. They are never mixed with real data.
"""
from __future__ import annotations

import math
import random
import time
from datetime import date, timedelta
from typing import Any

from .base import ProviderError

CR = 1e7  # 1 crore in rupees

# Figures below are in ₹ crore (synthetic). FY ends 31 March.
_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

_COMPANIES: dict[str, dict[str, Any]] = {
    "DEMO-STEADY": {
        "name": "Demo Steady Consumer Ltd (SAMPLE)",
        "sector": "Consumer Defensive", "industry": "Packaged Foods",
        "summary": "Fictional sample company: a steadily growing consumer-goods maker with low debt. "
                   "All figures are synthetic and exist only to demonstrate the app.",
        "price": 820.0, "shares": 50.0,  # crore shares
        "annual": {
            "revenue":      [4000, 4400, 4950, 5500, 6100, 6800],
            "cost_of_revenue": [2280, 2490, 2790, 3080, 3390, 3770],
            "ebitda":       [800, 900, 1030, 1160, 1300, 1460],
            "depreciation": [120, 130, 140, 155, 170, 185],
            "interest_expense": [20, 18, 16, 15, 14, 12],
            "pbt":          [690, 780, 900, 1020, 1150, 1300],
            "tax":          [175, 197, 227, 257, 290, 328],
            "total_assets": [3600, 3950, 4400, 4900, 5450, 6100],
            "current_assets": [1700, 1850, 2050, 2300, 2550, 2850],
            "cash":         [400, 450, 520, 600, 700, 820],
            "receivables":  [330, 360, 400, 440, 490, 540],
            "inventory":    [520, 560, 620, 680, 740, 810],
            "current_liabilities": [900, 980, 1080, 1180, 1290, 1420],
            "total_debt":   [180, 160, 150, 140, 130, 110],
            "equity":       [2500, 2770, 3100, 3480, 3900, 4370],
            "cfo":          [560, 640, 720, 830, 930, 1050],
            "capex":        [170, 180, 200, 220, 240, 270],
            "dividends_paid": [250, 290, 330, 380, 430, 490],
            "shares_outstanding": [50, 50, 50, 50, 50, 50],
        },
        "dividend_per_share": [5.0, 5.8, 6.6, 7.6, 8.6, 9.8],
    },
    "DEMO-LEVER": {
        "name": "Demo Leveraged Infra Ltd (SAMPLE)",
        "sector": "Industrials", "industry": "Engineering & Construction",
        "summary": "Fictional sample company: a fast-growing infrastructure contractor funded with rising debt and "
                   "equity issues, with weak cash conversion. Synthetic data for demonstration only.",
        "price": 210.0, "shares": 60.0,
        "annual": {
            "revenue":      [3000, 3600, 3300, 4200, 5000, 5600],
            "cost_of_revenue": [2400, 2900, 2700, 3450, 4120, 4650],
            "ebitda":       [420, 500, 380, 560, 640, 690],
            "depreciation": [90, 100, 110, 125, 140, 160],
            "interest_expense": [170, 210, 240, 290, 340, 380],
            "unusual_items": [0, 0, 0, 60, 85, 110],
            "pbt":          [160, 190, 30, 205, 245, 260],
            "tax":          [40, 48, 8, 52, 62, 66],
            "total_assets": [5200, 6100, 6700, 7800, 9100, 10400],
            "current_assets": [2600, 3100, 3300, 3900, 4600, 5300],
            "cash":         [150, 140, 110, 160, 120, 130],
            "receivables":  [700, 900, 1000, 1450, 1900, 2400],
            "inventory":    [450, 520, 560, 640, 720, 800],
            "current_liabilities": [2300, 2700, 3000, 3500, 4100, 4700],
            "total_debt":   [1800, 2200, 2650, 3200, 3900, 4500],
            "equity":       [1900, 2050, 2080, 2400, 2700, 3000],
            "cfo":          [150, 60, -120, 40, -60, -30],
            "capex":        [300, 380, 260, 420, 450, 500],
            "dividends_paid": [20, 20, 0, 0, 0, 0],
            "share_issuance": [0, 0, 0, 180, 120, 100],
            "shares_outstanding": [48, 48, 48, 53, 57, 60],
        },
        "dividend_per_share": [0.4, 0.4, 0, 0, 0, 0],
    },
    "DEMO-BANK": {
        "name": "Demo Finance Bank Ltd (SAMPLE)",
        "sector": "Financial Services", "industry": "Banks - Regional",
        "summary": "Fictional sample private-sector bank used to demonstrate the financial-sector scoring model. "
                   "Synthetic data only.",
        "price": 980.0, "shares": 150.0,
        "annual": {
            "revenue":      [14000, 15600, 18200, 21800, 25000, 28000],
            "interest_income": [24000, 26500, 31000, 37500, 43000, 48500],
            "interest_expense": [12500, 13600, 16100, 20000, 23000, 26000],
            "net_interest_income": [11500, 12900, 14900, 17500, 20000, 22500],
            "pbt":          [5200, 6100, 7600, 9300, 10900, 12300],
            "tax":          [1310, 1535, 1915, 2340, 2745, 3100],
            "total_assets": [450000, 505000, 575000, 660000, 750000, 840000],
            "cash":         [30000, 33000, 36000, 41000, 45000, 50000],
            "net_loans":    [290000, 330000, 382000, 445000, 510000, 575000],
            "total_debt":   [45000, 52000, 60000, 72000, 80000, 88000],
            "equity":       [52000, 57000, 63000, 70000, 78500, 88000],
            "cfo":          [9000, -4000, 12000, 6000, -2000, 15000],
            "capex":        [600, 650, 720, 800, 900, 1000],
            "dividends_paid": [600, 750, 900, 1050, 1200, 1350],
            "shares_outstanding": [150, 150, 150, 150, 150, 150],
        },
        "dividend_per_share": [4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
    },
}


def _period_fields(c: dict[str, Any], i: int) -> dict[str, float]:
    a = c["annual"]
    f: dict[str, float] = {}
    for k, series in a.items():
        v = series[i]
        f[k] = v * (CR if k != "shares_outstanding" else CR)
    # Derived "reported" lines consistent with the synthetic inputs
    if "cost_of_revenue" in a:
        f["gross_profit"] = (a["revenue"][i] - a["cost_of_revenue"][i]) * CR
    # Same convention as Yahoo: EBIT = PBT + interest (so it includes other income and exceptional items);
    # operating income = EBITDA − D&A.
    f["ebit"] = (a["pbt"][i] + a["interest_expense"][i]) * CR
    if "ebitda" in a:
        f["operating_income"] = (a["ebitda"][i] - a["depreciation"][i]) * CR
    ni = (a["pbt"][i] - a["tax"][i])
    f["net_income"] = ni * CR
    shares = a["shares_outstanding"][i] * CR
    f["eps_basic"] = f["net_income"] / shares
    f["eps_diluted"] = f["eps_basic"]
    f["shares_basic_avg"] = shares
    f["shares_diluted_avg"] = shares
    if "total_assets" in a and "equity" in a:
        f["total_liabilities"] = (a["total_assets"][i] - a["equity"][i]) * CR
    if "cfo" in a and "capex" in a:
        f["cfi"] = -(a["capex"][i] * 1.1) * CR
        f["cff"] = (-a.get("dividends_paid", [0] * 6)[i] + a.get("share_issuance", [0] * 6)[i]) * CR
    return f


def _prices(symbol: str, end_price: float, years: int = 6) -> list[list[Any]]:
    rng = random.Random(symbol)
    end = date(2026, 10, 16)
    start = end - timedelta(days=365 * years)
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    # Random walk, then rescale so the last close equals end_price.
    logp = [0.0]
    for _ in days[1:]:
        logp.append(logp[-1] + rng.gauss(0.0004, 0.016))
    scale = math.log(end_price) - logp[-1]
    out = []
    for d, lp in zip(days, logp):
        p = round(math.exp(lp + scale), 2)
        out.append([d.isoformat(), p, p, rng.randint(200_000, 2_000_000)])
    return out


class SampleProvider:
    name = "sample"
    source_label = "SAMPLE DATA (fictional, synthetic)"

    def supports(self, symbol: str) -> bool:
        return symbol.upper() in _COMPANIES

    def search(self, query: str) -> list[dict[str, Any]]:
        q = query.strip().lower()
        out = []
        for sym, c in _COMPANIES.items():
            if q in sym.lower() or q in c["name"].lower() or q in ("demo", "sample"):
                out.append({"symbol": sym, "name": c["name"], "exchange": "SAMPLE", "exchange_code": "SAMPLE",
                            "market": "IN", "sector": c["sector"], "industry": c["industry"],
                            "provider": self.name, "is_sample": True})
        return out

    def fundamentals(self, symbol: str) -> dict[str, Any]:
        sym = symbol.upper()
        if sym not in _COMPANIES:
            raise ProviderError(f"{symbol} is not a sample company", retryable=False, not_found=True)
        c = _COMPANIES[sym]
        annual = [{"period_end": f"{y}-03-31", "label": f"FY{y}", "fields": _period_fields(c, i)}
                  for i, y in enumerate(_YEARS)]
        price = c["price"]
        prices = _prices(sym, price)
        prev = prices[-2][1]
        dividends = [[f"{y}-07-15", dps] for y, dps in zip(_YEARS, c["dividend_per_share"]) if dps > 0]
        return {
            "symbol": sym, "provider": self.name, "source_label": self.source_label, "is_sample": True,
            "retrieved_at": time.time(),
            "profile": {"name": c["name"], "symbol": sym, "exchange": "SAMPLE", "market": "IN", "currency": "INR",
                        "financial_currency": "INR", "sector": c["sector"], "industry": c["industry"],
                        "summary": c["summary"], "website": None, "ir_website": None, "employees": None},
            "quote": {"price": price, "previous_close": prev, "change": price - prev,
                      "change_pct": (price / prev - 1) * 100, "market_time": "2026-10-16T10:00:00+00:00",
                      "delayed": True, "delay_minutes": None, "shares_outstanding": c["shares"] * CR,
                      "week52_high": max(p[1] for p in prices[-252:]), "week52_low": min(p[1] for p in prices[-252:]),
                      "currency": "INR", "market_state": "CLOSED"},
            "provider_stats": {},
            "analyst": {"forward_eps": None, "n_analysts": None},
            "annual": annual, "quarterly": [],
            "dividends": dividends, "splits": [],
            "holders": {"insiders_pct": None, "institutions_pct": None},
            "news": [],
            "_prices": prices,
        }

    def prices(self, symbol: str) -> dict[str, Any]:
        return {"prices": self.fundamentals(symbol)["_prices"]}

    def peers(self, symbol: str, industry: str | None, region: str) -> list[dict[str, Any]]:
        return []


SAMPLE_IPO = {
    "id": "demo-precision-ipo",
    "name": "Demo Precision Components Ltd (SAMPLE IPO)",
    "status": "sample",
    "is_sample": True,
    "payload": {
        "company_name": "Demo Precision Components Ltd (SAMPLE IPO)",
        "sector": "Industrials", "industry": "Auto Parts",
        "business_summary": "Fictional auto-component maker used to demonstrate the IPO workflow. All numbers are synthetic.",
        "exchange": "NSE, BSE", "status": "sample",
        "price_band_low": 415, "price_band_high": 436, "lot_size": 52, "face_value": 2,
        "fresh_issue_cr": 400, "ofs_cr": 600,
        "pre_issue_shares": 10.5e7,
        "promoter_pre_pct": 88.0, "promoter_post_pct": 64.0,
        "open_date": "2026-11-03", "close_date": "2026-11-05", "listing_date": "2026-11-10",
        "anchor_lockin_50_date": "2026-12-05", "anchor_lockin_100_date": "2027-02-03",
        "use_of_proceeds": [
            {"purpose": "Repayment of borrowings", "amount_cr": 180},
            {"purpose": "Capex for new plant", "amount_cr": 140},
            {"purpose": "General corporate purposes", "amount_cr": 80},
        ],
        "financials": [
            {"fy": "FY2024", "revenue_cr": 1450, "ebitda_cr": 218, "pat_cr": 96, "net_worth_cr": 620,
             "borrowings_cr": 410, "cfo_cr": 120, "capex_cr": 95},
            {"fy": "FY2025", "revenue_cr": 1720, "ebitda_cr": 265, "pat_cr": 124, "net_worth_cr": 735,
             "borrowings_cr": 455, "cfo_cr": 104, "capex_cr": 130},
            {"fy": "FY2026", "revenue_cr": 2010, "ebitda_cr": 318, "pat_cr": 151, "net_worth_cr": 880,
             "borrowings_cr": 520, "cfo_cr": 146, "capex_cr": 160},
        ],
        "cash_cr": 60,
        "top_customer_concentration_pct": 58.0,
        "contingent_liabilities_cr": 45,
        "litigation_notes": "Synthetic example: 3 tax disputes and 1 civil suit against the promoter (sample text).",
        "risk_factors": [
            "Top 5 customers contribute 58% of revenue (sample).",
            "Dependence on the domestic passenger-vehicle cycle (sample).",
            "Raw-material (steel, aluminium) price volatility (sample).",
        ],
        "subscription": {"qib": 85.2, "nii": 42.1, "retail": 9.6, "total": 38.4, "as_of": "Sample data"},
        "gmp": {"value": 95, "as_of": "Sample data", "source": "Unofficial (sample)"},
        "peers": ["DEMO-STEADY"],
        "manual_peers": [
            {"name": "Listed Peer A (sample)", "pe": 32.0, "ev_ebitda": 17.0, "pb": 5.1, "roe": 16.0},
            {"name": "Listed Peer B (sample)", "pe": 26.0, "ev_ebitda": 14.5, "pb": 3.9, "roe": 14.0},
            {"name": "Listed Peer C (sample)", "pe": 41.0, "ev_ebitda": 22.0, "pb": 7.2, "roe": 19.0},
        ],
        "source_note": "SAMPLE: fictional RHP figures for demonstration.",
    },
}
