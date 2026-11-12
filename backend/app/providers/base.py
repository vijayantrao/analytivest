"""Provider contract and the canonical (provider-agnostic) data model.

A provider returns a ``bundle`` dict with this shape (JSON-serialisable so it can be cached):

{
  "symbol": "TCS.NS", "provider": "yahoo", "source_label": "Yahoo Finance (yfinance)",
  "is_sample": false, "retrieved_at": <epoch>,
  "profile": {name, symbol, exchange, market, currency, financial_currency, sector, industry,
              summary, website, employees, ir_website},
  "quote": {price, previous_close, change, change_pct, market_time, delayed, shares_outstanding,
            week52_high, week52_low, currency},
  "provider_stats": {...provider-reported ratios, used only for reconciliation / peers / fallbacks},
  "analyst": {forward_eps, n_analysts},
  "annual": [Period...], "quarterly": [Period...],     # sorted oldest -> newest
  "dividends": [[iso_date, amount], ...], "splits": [[iso_date, ratio], ...],
  "holders": {insiders_pct, institutions_pct, institutions_count},
  "news": [{title, publisher, link, published_at}],
}

Period = {"period_end": "2026-03-31", "label": "FY2026" | "Q Jun-2026", "fields": {canonical_field: value}}
Values are in the reporting currency, absolute units (not crores). Missing values are omitted.
"""
from __future__ import annotations

from typing import Any, Protocol


class ProviderError(Exception):
    """Provider failed (network, rate limit, bad payload)."""

    def __init__(self, message: str, *, retryable: bool = True, not_found: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.not_found = not_found


class Provider(Protocol):
    name: str
    source_label: str

    def supports(self, symbol: str) -> bool: ...

    def search(self, query: str) -> list[dict[str, Any]]: ...

    def fundamentals(self, symbol: str) -> dict[str, Any]: ...

    def prices(self, symbol: str) -> dict[str, Any]: ...

    def peers(self, symbol: str, industry: str | None, region: str) -> list[dict[str, Any]]: ...


# Canonical statement fields: key -> (statement, label, kind)
# kind: "flow" (summed over a period) or "stock" (balance at period end) or "per_share"
CANONICAL_FIELDS: dict[str, tuple[str, str, str]] = {
    # Income statement
    "revenue": ("income", "Revenue", "flow"),
    "cost_of_revenue": ("income", "Cost of revenue", "flow"),
    "gross_profit": ("income", "Gross profit", "flow"),
    "operating_expense": ("income", "Operating expenses", "flow"),
    "ebitda": ("income", "EBITDA", "flow"),
    "depreciation": ("income", "Depreciation & amortisation", "flow"),
    "operating_income": ("income", "Operating income", "flow"),
    "ebit": ("income", "EBIT", "flow"),
    "interest_expense": ("income", "Interest expense", "flow"),
    "interest_income": ("income", "Interest income", "flow"),
    "net_interest_income": ("income", "Net interest income", "flow"),
    "unusual_items": ("income", "Exceptional / unusual items", "flow"),
    "pbt": ("income", "Profit before tax", "flow"),
    "tax": ("income", "Tax expense", "flow"),
    "minority_interest_pl": ("income", "Minority interest (P&L)", "flow"),
    "net_income": ("income", "Net profit (to shareholders)", "flow"),
    "net_income_total": ("income", "Net profit incl. discontinued operations", "flow"),
    "net_income_continuing": ("income", "Net profit from continuing operations", "flow"),
    "net_income_discontinued": ("income", "Profit from discontinued operations", "flow"),
    "eps_basic": ("income", "EPS – basic", "per_share"),
    "eps_diluted": ("income", "EPS – diluted", "per_share"),
    "shares_basic_avg": ("income", "Basic weighted avg. shares", "shares"),
    "shares_diluted_avg": ("income", "Diluted weighted avg. shares", "shares"),
    # Balance sheet
    "total_assets": ("balance", "Total assets", "stock"),
    "current_assets": ("balance", "Current assets", "stock"),
    "cash": ("balance", "Cash & cash equivalents", "stock"),
    "short_term_investments": ("balance", "Short-term investments", "stock"),
    "receivables": ("balance", "Trade receivables", "stock"),
    "inventory": ("balance", "Inventory", "stock"),
    "net_ppe": ("balance", "Net fixed assets (PP&E)", "stock"),
    "goodwill_intangibles": ("balance", "Goodwill & intangibles", "stock"),
    "net_loans": ("balance", "Net loans (advances)", "stock"),
    "total_liabilities": ("balance", "Total liabilities", "stock"),
    "current_liabilities": ("balance", "Current liabilities", "stock"),
    "payables": ("balance", "Trade payables", "stock"),
    "total_debt": ("balance", "Total borrowings (incl. leases)", "stock"),
    "current_debt": ("balance", "Short-term borrowings (incl. leases)", "stock"),
    "long_term_debt": ("balance", "Long-term borrowings (incl. leases)", "stock"),
    "lease_liabilities": ("balance", "Lease liabilities", "stock"),
    "equity": ("balance", "Shareholders' equity", "stock"),
    "minority_interest": ("balance", "Minority interest", "stock"),
    "shares_outstanding": ("balance", "Shares outstanding (period end)", "shares"),
    # Cash flow
    "cfo": ("cashflow", "Cash flow from operations", "flow"),
    "cfi": ("cashflow", "Cash flow from investing", "flow"),
    "cff": ("cashflow", "Cash flow from financing", "flow"),
    "capex": ("cashflow", "Capital expenditure", "flow"),
    "dividends_paid": ("cashflow", "Dividends paid", "flow"),
    "buybacks": ("cashflow", "Share buybacks", "flow"),
    "share_issuance": ("cashflow", "Shares issued", "flow"),
    "change_receivables": ("cashflow", "Change in receivables", "flow"),
    "acquisitions": ("cashflow", "Acquisitions of businesses", "flow"),
}
