# Analytivest: stock & IPO research for Indian markets

A personal, locally-run research tool for NSE/BSE-listed companies and IPOs. It works with free data only and reports
**three separate verdicts** rather than a buy/sell score:

| Verdict | Question |
|---|---|
| **Business quality** | Is the company fundamentally strong? |
| **Financial risk** | How vulnerable is it to debt, cash-flow problems or deterioration? |
| **Valuation** | Is today's price reasonable relative to fundamentals? |

Every number shows its period, source, formula and type (reported / calculated / provider-estimate / user-entered).
Missing data is never treated as zero, and every scoring rule can be inspected on the Methodology page.

> Research and decision support only. Not investment advice, not a recommendation, no guarantee of returns.
> Quotes are delayed. Verify figures against company filings.

---

## Quick start (Windows)

Requirements: **Python 3.12+** (tested on 3.14) via the `py` launcher, and **Node.js 20+** (tested on 24).

```powershell
.\start.ps1
```

On first run this creates `backend\.venv`, installs the Python packages, builds the frontend, and then serves everything at
**http://127.0.0.1:8000** (the server binds to localhost only).

Manual steps, if you prefer:

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
cd ..\frontend
npm install
npm run build
cd ..\backend
.\.venv\Scripts\python run.py
```

**Development mode** (hot reload): run `.\.venv\Scripts\python run.py --reload` in `backend`, and `npm run dev` in
`frontend`, then open http://localhost:5173. Vite proxies `/api` to the backend.

No API keys are needed. Optional settings are documented in [`.env.example`](.env.example); copy it to `.env` to change them.

## Tests

```powershell
cd backend
.\.venv\Scripts\python -m pytest            # 116 offline tests (formulas, scoring, valuation, IPO, imports, portfolio, alerts, security, backup, ML, API)
.\.venv\Scripts\python -m pytest --live     # + 4 integration tests against real Yahoo Finance data
cd ..\frontend
npm run build                               # type-checks (tsc) and builds the UI
```

Offline tests use the fictional sample provider and a throwaway database. The end-to-end user journeys (search, company
tabs, DCF editing, watchlist, IPO, compare, mobile layout, light/dark theme) were exercised in a browser during development.

## Using it

- **Search** by name or symbol (`TCS`, `HDFC Bank`, `RELIANCE.NS`). Numeric BSE codes such as `500325` are not
  supported by the provider; use `RELIANCE.BO` for the BSE listing.
  NSE and BSE listings of the same company are grouped, with NSE used by default.
- **Company page tabs:** Overview · Financials · Growth & profitability · Debt & balance sheet · Cash flow · Valuation
  (editable DCF with sensitivity) · Management & shareholding (enter pledge/auditor/litigation facts yourself) · Peers ·
  Risks & red flags · News & disclosures · Analysis (rule-based narrative and full score breakdown).
- **IPOs:** add an IPO from the RHP figures (*IPOs → New IPO from RHP*). A fictional sample IPO is included.
- **Compare:** up to five companies side by side. **Watchlist** and **saved snapshots** are stored locally.
- **Export:** CSV from the company header; **PDF** uses the browser's print dialog (*Save as PDF*) with a print stylesheet.
- **Offline demo:** `DEMO-STEADY`, `DEMO-LEVER`, `DEMO-BANK` are fictional companies, always labelled SAMPLE DATA.

## Project structure

```
stockiq/
├── start.ps1                 one-command start (Windows)
├── .env.example              optional settings (no secrets needed)
├── docs/
│   ├── ARCHITECTURE.md       architecture, data flow, schema, API, caching, failure modes, security
│   ├── DATA_SOURCES.md       provider evaluation, licensing, what free data cannot provide
│   ├── METHODOLOGY.md        normalisation, formulas, valuation, scoring, red flags, IPO maths
│   └── UX_DESIGN.md          personas, IA, wireframes, design system, accessibility
├── backend/
│   ├── run.py                starts uvicorn on 127.0.0.1:8000 (serves API + built frontend)
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py           FastAPI routes, validation, rate limiting, SPA hosting
│   │   ├── analysis.py       orchestration: data → metrics → valuation → flags → scores → narrative
│   │   ├── normalize.py      FX conversion, split/bonus adjustment, continuing ops, validation
│   │   ├── markets.py        market registry (IN, US); add markets here
│   │   ├── db.py             SQLite: cache, watchlist, notes, saved analyses, IPOs, portfolio, alerts
│   │   ├── backup.py         backup / restore / weekly automatic backups
│   │   ├── config.py, glossary.py
│   │   ├── providers/        base.py (contract), yahoo.py, sample.py, registry.py (cache + fallback)
│   │   ├── engine/           formulas, metrics, valuation, redflags, scoring (+ scoring_config.json), ipo, narrative
│   │   └── ml/               earnings-quality anomaly model: features, IsolationForest, evaluation
│   └── tests/                unit, API and live integration tests
└── frontend/                 React 19 + TypeScript + Vite + Tailwind v4 + Recharts + TanStack Query
    └── src/{components,lib,pages}
```

## Database

SQLite at `%LOCALAPPDATA%\Analytivest\stockiq.db` (outside OneDrive, which would upload it and can corrupt a live
database), created automatically on first start. A database at the old location (`backend/data`) is moved there
automatically; change the folder with `STOCKIQ_DATA_DIR`. The schema is in `backend/app/db.py`, with a
`schema_version` table for future migrations. To reset, stop the server and delete the file; the sample IPO is recreated
on start. Raw provider responses are cached with a `_schema` marker, so changes to field mappings trigger an automatic
re-fetch.

## Data provider configuration

The provider chain is set by `STOCKIQ_PROVIDERS` (default `yahoo,sample`). `STOCKIQ_OFFLINE=1` disables network calls.
To add a provider, implement the `Provider` protocol in `backend/app/providers/base.py` (returning the canonical bundle),
then register it in `providers/registry.py`. To add a market, add an entry to `markets.py`. See `docs/DATA_SOURCES.md` for
why Yahoo was chosen and which sources were rejected (exchange websites and Screener.in are linked, not scraped).

## Data, backups & security

Open **Data & security** (gear icon in the header):

- **Backups:** *Download backup* saves one readable JSON file with everything you entered or imported (portfolio,
  watchlist, notes, imports, IPOs, saved snapshots, alerts). Market data is left out because it downloads again.
  A weekly automatic backup goes to `%LOCALAPPDATA%\Analytivest\backups` (last 8 kept).
- **Where backups go:** *Keep local only* (default), or *This computer + Google Drive*, which also copies each
  backup to `My Drive\Analytivest Backups`. This uses the free **Google Drive for desktop** app: install it and sign
  in, and Analytivest finds the "My Drive" folder (usually `G:\My Drive`) automatically. Analytivest never handles
  your Google password or tokens; Google's app does the upload. If Drive is not running, the local backup is still
  written and the page shows that the Drive copy failed.
- **Encrypted Google Drive copies** (on by default when you pick Google Drive): AES-256-GCM with a key derived from
  your password by scrypt, so Google, or anyone who gets into your Google account, sees only scrambled data. The
  password is saved on this PC protected by Windows (DPAPI, tied to your Windows account) so weekly backups run
  unattended; it is never included in backups. Restoring an encrypted copy on another PC asks for the password.
  **If you lose the password, the Google Drive copies cannot be opened**; the copies on this PC stay unencrypted.
- **Without the desktop app:** *Download encrypted backup* saves a password-encrypted file (using your saved
  password, or one you type for that file). Drag it into drive.google.com in the browser; restore it later with
  *Restore from a file* (it asks for the password when it isn't saved on this PC). *Download unencrypted* is for
  copies you keep on this computer only.
- **Restore** from a downloaded file or from the list (local or Google Drive copies). A safety backup of the current data is saved first, so a
  restore can be undone.
- **Protection:** the app answers only to `127.0.0.1`/`localhost`, refuses requests from other websites and requires
  a secret key that changes on every start, so a malicious page open in your browser cannot read or change your
  data. Pages use a strict Content-Security-Policy, and uploaded Office/ZIP files are checked for zip bombs before
  unpacking. Details: `docs/ARCHITECTURE.md` section 9.

## Deployment

The app is designed to run on your own computer: `start.ps1`, or `run.py` behind any process manager. It binds to
`127.0.0.1` and has no login. **Do not expose it to the internet as-is.** Publishing it would require authentication,
a licensed data provider (Yahoo's terms are personal-use only), PostgreSQL and a review of the security notes in
`docs/ARCHITECTURE.md` §9.

## Implemented features

- Company search with autocomplete, duplicate-listing grouping and keyboard navigation
- Normalised statements (4–5 annual years, ~5 quarters) with provenance, adjusted for FX, splits/bonus issues and discontinued operations
- Roughly 45 metrics with guards for negative/zero denominators, missing periods, fiscal-year changes and base effects
- Separate scoring model for banks/financials; sector profiles for leverage tolerance
- Three verdicts, a composite score, data completeness, confidence and positive/negative factors
- Valuation: multiples, historical P/E band, FY-end multiples, editable DCF with sensitivity, peer comparables (with outlier screening), DDM, justified P/B, fair-value range, reconciliation with provider figures, total shareholder return
- Automated red flags with evidence, severity, period, implication and rule
- User-entered governance facts (pledge, auditor, litigation, related-party transactions) feeding scores
- IPO module: issue structure, fresh vs OFS, dilution, implied multiples vs peers, three scenarios, five assessments, lock-in dates, GMP/subscription shown only as unofficial context
- **Upload RHP/DRHP** (IPOs → Upload RHP/DRHP): accepts PDF (text or scanned, with offline OCR), DOCX, HTML, TXT, RTF,
  XLSX, EPUB/XPS, images, ZIP and legacy binaries. It extracts the price band, issue structure, shares, promoter holding,
  restated financials (any of ₹ crore/million/lakh), objects of the issue, the peer table and risk factors. Each figure
  shows its page and source text for review, and the app then suggests **Apply / Borderline / Skip** with its reasons,
  deal-breakers and a margin-of-safety price (`backend/app/ingest/`, `backend/app/engine/ipo_decision.py`).
  Try it offline with the fictional sample RHP button.
- Rule-based narrative answering the ten guiding questions
- Compare (≤5), watchlist, saved snapshots, CSV export, print-to-PDF
- **10-year history import** (Financials tab): upload the Excel file from Screener.in's free "Export to Excel". Imported
  years replace the provider's for the same dates; the provider still fills fields the export lacks (capex, current
  assets/liabilities) and newer years (`backend/app/ingest/screener_import.py`).
- **Annual report upload** (Management & shareholding tab): any format; extracts auditor opinion (qualified/clean,
  emphasis of matter), promoter holding and pledges, contingent liabilities, related-party and litigation pointers, and
  for banks GNPA, NNPA, CAR and PCR, each with page evidence, to review and apply (`ingest/annual_report.py`).
- **Bank data entry**: GNPA, NNPA, capital adequacy and provision coverage feed a real asset-quality score and bank red flags.
- **Quarterly results check**: latest quarter vs the same quarter last year (and vs the previous quarter), with a
  verdict (strong/steady/mixed/soft/weak); severe declines feed the red flags (`engine/quarterly.py`).
- **Portfolio** (`/portfolio`): import Zerodha/Groww/any CSV or Excel holdings; value, P&L, weights, sector allocation,
  weighted quality, and warnings for concentration, high risk, overvaluation and weak quarters.
- **Alerts** (`/alerts` + header bell): daily check (default 18:30 while the app runs, or via Windows Task Scheduler with
  `.venv\Scripts\python -m app.alerts`) for new/cleared red flags, verdict and valuation changes, 10-point score moves,
  new quarterly results and 8%+ price moves; browser notifications while the app is open (`app/alerts.py`).
- **Earnings-quality anomaly detector (machine learning)**: a scikit-learn Isolation Forest trained on the screener
  universe flags companies whose accounting signals (accruals, cash conversion, receivables vs sales, margins,
  inventory, balance-sheet growth, one-off gains, dilution) are unlike their peers, with per-company explanations
  from occlusion attributions. Shown on the *Risks* tab and as an *ML check* column / *Unusual accounts (ML)* preset in
  the screener. It complements the rule-based flags; `python -m app.ml.evaluate` measures both on injected
  distortions with cross-validation and writes [`docs/ML_EVALUATION.md`](docs/ML_EVALUATION.md) (`app/ml/`).
- **Stock screener** (`/screener`): background scan of the top 50–500 Indian companies by market cap, then presets
  (quality at a fair price, undervalued, low-risk dividend payers, red-flag watch) and filters (`app/screener.py`).
- **Data & security** (`/settings`): backups (download, weekly automatic, optional Google Drive copy, restore with a
  safety copy), data location
  and security status
- Dark/light/system theme, responsive layouts, keyboard support, chart table views, glossary tooltips, loading/empty/error states, stale-data banners

## Known limitations

- **Data depth:** Yahoo provides about 4–5 fiscal years, so 5- and 10-year CAGRs are unavailable unless you import a
  Screener.in export. Quarterly data often has gaps, and TTM is then taken from the provider (labelled).
- **Screener.in import format:** the parser follows the export's documented "Data Sheet" row labels and is tested on a
  synthetic file in that layout, not yet on a real export. If an import fails or looks wrong, share the file and it can
  be adjusted.
- **Document readers (RHP, annual report):** pattern-based, tested on synthetic documents; real reports vary, so always
  check the page evidence before saving.
- **Alerts** only run while the app is running unless you add the Task Scheduler job; browser notifications need the
  app open in a tab. **Screener scans** take about 5 s per company on a cold cache (top 100 ≈ 8 minutes).
- **Data accuracy:** Yahoo is unofficial and sometimes inconsistent (e.g. HDFC Bank's balance-sheet equity disagrees with
  its own book value per share). The app flags such gaps, but cannot fix them without a second source.
- **Not available from free sources:** shareholding history and FII/DII split, segment/geographic revenue, live IPO
  calendars, subscription and GMP. Pledges, auditor remarks, contingent liabilities and bank NPA/CAR come from documents
  you upload or figures you enter.
- **Not implemented:** SEC EDGAR provider for US, news beyond what Yahoo returns (often none for Indian stocks),
  server-generated PDFs.
- **Speed:** a company's first load takes about 10–40 seconds (statements, prices and peer ratios); later loads come from the cache.
- **FX conversion** uses period-end rates for flows (an approximation), so growth includes currency effects.
- **Windows long paths:** in very deep folders, `curl_cffi` (used by yfinance) may fail to load. yfinance then falls back
  to plain requests, which works but is more likely to be rate-limited, and the OCR engine fails to load. The current
  `Documents\Analytivest` location is short enough (OCR verified working there).
- **Local backups are not encrypted** (only the Google Drive copies are). They contain your portfolio in plain JSON;
  keep downloaded backups in folders only you can access.
- **Sector models:** there is one financial-sector model; insurers and NBFC sub-types are not separately calibrated.
