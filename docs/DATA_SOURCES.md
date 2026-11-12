# Data sources — evaluation and choice

Constraint from the owner: **personal use only, no paid APIs.**

## Evaluated options

| Source | Coverage (India) | Cost | Access / licensing | Decision |
|---|---|---|---|---|
| **Yahoo Finance via `yfinance`** | NSE (`.NS`) + BSE (`.BO`) quotes (delayed), ~4–5 yrs annual P&L/BS/CF, ~4–5 quarters, full daily price history, dividends, splits/bonus, industry screener | Free | Unofficial client of Yahoo's public endpoints. Yahoo's terms allow **personal, non-commercial use**. Informal rate limits (HTTP 429). | **Primary provider.** Verified working from this machine (TCS.NS, HDFCBANK.NS, RELIANCE.NS) on 2026-10-19. |
| Sample provider (built-in) | 3 fictional companies + 1 fictional IPO | Free | Synthetic; labelled `SAMPLE / DEMO` everywhere | **Fallback** for offline use and tests. Never mixed with real companies. |
| NSE website JSON endpoints | Quotes, announcements, shareholding, IPOs | Free | The site's terms restrict automated access. It also depends on cookie handshakes meant for browsers. | **Not used.** The app links to NSE pages for manual reading instead. |
| BSE website APIs | Similar to NSE | Free | Same concerns | **Not used**; links only. |
| Screener.in / Tickertape / Trendlyne | Excellent 10-yr Indian fundamentals | Free tier / paid | Scraping is against their terms. Paid APIs are excluded. | **Not used.** Links only. (Possible future feature: import your own Screener Excel export, which their terms allow you to download.) |
| SEBI (sebi.gov.in) DRHP/RHP PDFs | Authoritative IPO documents | Free | Public documents | **Used manually**: the IPO module takes figures you read from the RHP. Automated PDF parsing is too unreliable for financial figures. |
| SEC EDGAR XBRL API | US fundamentals, 10+ yrs | Free | Official API; needs a User-Agent | Not needed for the India MVP. It is the natural second provider when US support is added (the market registry already has a `US` entry; Yahoo covers US quotes meanwhile). |
| RBI DBIE | Macro / banking-sector series | Free | Public | Not integrated in the MVP. Bank-specific ratios like GNPA and CAR are company-level and would come from filings. |
| Alpha Vantage / FMP / Twelve Data / EODHD | Limited or no Indian fundamentals on free tiers | Free tiers heavily limited | API keys | Rejected: Indian fundamentals are weak on free tiers and the owner excluded paid plans. |

## What free data cannot provide (shown as "Not available" — never guessed)

- Promoter **pledging**, quarterly **shareholding pattern** history, FII/DII split
- Auditor qualifications or resignations, related-party transactions, contingent liabilities, litigation
- Segment and geographic revenue
- Bank asset-quality metrics (GNPA, NNPA, PCR) and capital adequacy (CAR/CET1)
- More than ~5 years of statements
- Live IPO calendar, subscription, and GMP

For governance items you can **enter facts yourself** on the company's *Management & shareholding* tab, citing the
filing you read. They are stored locally, labelled "User-entered", and feed the governance score.

## Provenance rules applied in code

Every metric carries: `value`, `period`, `currency/unit`, `source` (e.g. `Yahoo Finance (yfinance)`), `retrieved_at`,
`method` (formula text for derived values), and `quality` ∈ {`reported`, `calculated`, `provider_estimate`,
`user_entered`, `sample`, `missing`, `not_meaningful`}.

- **Reported**: the figure as delivered by the provider from company statements.
- **Calculated**: derived by this app; the formula is shown.
- **Provider-estimate**: e.g. analyst consensus EPS from Yahoo. Used **only** for forward P/E and always labelled.
- Quotes are labelled **delayed** with the exchange timestamp. Anything older than its freshness window shows a STALE badge.
