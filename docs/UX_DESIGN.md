# Analytivest — UX & UI design

## 1. Personas & primary journeys

| Persona | Need | Key journey |
|---|---|---|
| **Learner** (new retail investor) | "Is this company OK? What do these terms mean?" | Search → dashboard → three verdicts in plain English → tap a term for its definition |
| **Analyst-minded owner** (the primary user) | Evidence, formulas, sources, the ability to change assumptions | Search → dashboard → Valuation tab → edit DCF assumptions → Risks tab → export CSV/PDF |
| **IPO evaluator** | "Is this IPO priced sensibly against listed peers?" | IPO list → new IPO from RHP figures → structure (fresh vs OFS) → scenarios → risks |
| **Comparer** | Choose between 2–5 companies | Compare page → add symbols → side-by-side verdicts and ratios |

## 2. Information architecture

```
Analytivest
├── Home (search hero · watchlist · recent · IPOs · data status)
├── Company /c/:symbol
│   ├── Overview          (verdicts, price, key trends, positives, risks, freshness)
│   ├── Financials        (P&L / balance sheet / cash flow tables, annual + quarterly)
│   ├── Growth & profit   (revenue/profit, margins, EPS, ROE/ROCE)
│   ├── Debt & balance    (debt vs cash, leverage, liquidity, working capital)
│   ├── Cash flow         (CFO vs PAT, FCF, capex, dividends/buybacks)
│   ├── Valuation         (multiples, history, DCF editor + sensitivity, comps, DDM, fair-value range)
│   ├── Shareholding      (holders, user-entered governance facts)
│   ├── Peers             (industry peers via screener, medians)
│   ├── Risks & flags     (automated warnings with evidence)
│   ├── News & filings    (provider news + official disclosure links)
│   └── Analysis          (rule-based narrative, score breakdown, data quality)
├── IPOs /ipo  → /ipo/:id  (analysis) · /ipo/new (RHP entry form)
├── Compare /compare?s=A,B,C
├── Watchlist & saved analyses /watchlist
├── Methodology /methodology (live scoring rules + formulas)
└── Glossary /glossary
```

## 3. Navigation

- **Desktop / tablet:** a slim top bar holds the logo, the global search (press `/` from anywhere), the main links (IPOs, Compare, Watchlist, Methodology) and the theme toggle. Company pages add a sticky header (name, symbol, exchange, price) and a horizontal, scrollable tab bar.
- **Mobile:** the top bar collapses to logo, search icon and a menu button; company tabs become a scrollable pill row.
- Tabs are real routes (`/c/TCS.NS/valuation`), so back/forward and deep links work.

## 4. Low-fidelity wireframes

**Home**
```
┌──────────────────────────────────────────────────────────────┐
│ ◆ Analytivest   [ / Search company, symbol or IPO…      ]  ◐   │
├──────────────────────────────────────────────────────────────┤
│        Research Indian stocks & IPOs with evidence           │
│   [ Search: e.g. "TCS", "HDFC Bank", "RELIANCE.NS"     ]     │
│   Try: TCS · HDFCBANK · RELIANCE · DEMO sample               │
├───────────────────────────┬──────────────────────────────────┤
│ Watchlist                 │ IPOs (your RHP entries + sample) │
│ TCS.NS  ₹… ▲0.4%  BQ 78  │ DEMO Precision … Base: ₹…        │
├───────────────────────────┴──────────────────────────────────┤
│ Data status: Yahoo ✓ (delayed) · cache 12 items · disclaimer │
└──────────────────────────────────────────────────────────────┘
```

**Company overview**
```
┌──────────────────────────────────────────────────────────────┐
│ Tata Consultancy Services  TCS.NS · NSE · IT Services  [☆]   │
│ ₹2,476.20  ▲0.32%  delayed · 19 Oct 15:30 IST   Mcap ₹8.96L Cr│
│ [Overview][Financials][Growth][Debt][Cash flow][Valuation]…  │
├───────────────────┬───────────────────┬──────────────────────┤
│ BUSINESS QUALITY  │ FINANCIAL RISK    │ VALUATION            │
│ 81/100 Strong     │ Low  (18/100)     │ Within fair range    │
│ why ▸             │ why ▸             │ ├──■───●──┤ ₹2.1–2.9k │
├───────────────────┴───────────────────┴──────────────────────┤
│ Summary label: "Strong fundamentals"  Confidence: Medium     │
├──────────────────────────────┬───────────────────────────────┤
│ Price chart [1Y 3Y 5Y 10Y]   │ Revenue & profit (annual)     │
├──────────────────────────────┼───────────────────────────────┤
│ + Positives (evidence)       │ − Risks / red flags           │
├──────────────────────────────┴───────────────────────────────┤
│ Data: Yahoo Finance · FY2026 · retrieved 19 Oct 11:20 · ✓    │
└──────────────────────────────────────────────────────────────┘
```

**Valuation tab**
```
Multiples table (value · basis · period · source)  |  Historical P/E band chart
Fair-value range: [DCF ▬▬] [Comps ▬▬] [DDM ▬] vs ● price
DCF editor: discount = WACC [~11%] g1 [10%] years [5] terminal g [5%] base FCF [3y avg]
Sensitivity grid (WACC × terminal growth) · assumptions · limitations
```

**IPO analysis**
```
Issue: price band · lot · size ▸ Fresh ₹X (Y%) | OFS ₹Z (W%)  [stacked bar]
Post-issue mcap · implied P/E · EV/EBITDA · P/B · peer medians
Five assessments (Business · Financial · Valuation · Governance · IPO-specific)
Scenarios: Conservative | Base | Optimistic (assumptions shown) vs issue price
Risks from RHP · Subscription · GMP (UNOFFICIAL, speculative) · lock-in dates
```

## 5. Visual design system

- **Tone:** quiet, dense where needed, never flashy. Surfaces carry the hierarchy; colour is reserved for meaning.
- **Colour tokens** (CSS variables, light/dark): `--bg`, `--surface`, `--surface-2`, `--border`, `--text`,
  `--text-muted`, `--accent` (blue), `--pos` (green), `--neg` (red), `--warn` (amber), plus a chart palette.
  Green/red appear **only** on directional values and verdicts, always paired with an icon (▲▼, ✓, !) and a text label.
- **Type:** Inter (variable) for UI; tabular figures (`font-variant-numeric: tabular-nums`) for all numbers.
  Scale: 12 / 13 / 14 / 16 / 20 / 24 / 32.
- **Spacing:** 4-pt grid; cards 16–20 px padding; 12 px radius; 1 px borders over heavy shadows.
- **Number formatting (India):** ₹ with Indian grouping (₹1,23,456), large values in **₹ Cr** / **₹ L Cr**;
  percentages to 1 dp; ratios to 2 dp; "—" plus a reason tooltip for missing; "n/m" for not meaningful.

## 6. Component library

`SearchBox` (combobox, grouped NSE/BSE results) · `VerdictCard` · `ScoreBar` · `FairValueRange` ·
`MetricTile` (value, period, provenance popover) · `ProvenanceBadge` · `FreshnessBadge` · `Term` (inline glossary
tooltip) · `ChartCard` (title, period selector, legend, data-table toggle) · `DataTable` (sticky first column,
horizontal scroll) · `FlagItem` (severity chip + evidence) · `Tabs` · `Skeleton` · `EmptyState` · `ErrorState`
(message + Retry) · `Disclaimer` · `ThemeToggle`.

## 7. Responsive layouts

| Breakpoint | Layout |
|---|---|
| ≥1280 desktop | 12-col grid; verdicts 3-up; charts 2-up |
| 768–1279 tablet | Verdicts 3-up (compact); charts 1-up; tables scroll horizontally |
| <768 mobile | Single column; verdicts stacked; tab pills scroll; tables show the first column sticky |

## 8. Interaction specification

- **Search:** debounced 250 ms; ↑/↓ to move, Enter to open, Esc to close. NSE and BSE listings of the same company
  appear under one company row with exchange chips, and NSE is the default.
- **Charts:** hover/focus tooltips with exact values and periods; period selectors (1Y/3Y/5Y/10Y/Max, disabled
  when data is not available); a "Table" toggle on every chart exposes the underlying numbers.
- **Provenance:** clicking any metric's ⓘ shows the source, period, retrieval time, formula and quality.
- **DCF editor:** changes are debounced and recomputed server-side; a "Reset" control restores the defaults.
- **Loading:** skeletons shaped like the final layout. **Errors:** plain-language cause + Retry. **Empty:** explains why (e.g. "Yahoo does not provide quarterly cash flow for this company").
- **Watchlist:** a star toggle with optimistic update.

## 9. Accessibility & usability

- WCAG 2.1 AA contrast for text in both themes; focus rings always visible; every control reachable by keyboard.
- Charts have text alternatives (data-table toggle) and never rely on colour alone (line styles and markers differ, and legends sit next to their series).
- `prefers-reduced-motion` disables transitions. Semantic landmarks (`header`, `nav`, `main`) and ARIA tabs.
- Jargon: every metric label is a `Term` with a short definition plus "Learn more" linking to the glossary.
- A persistent footer disclaimer, and verdicts phrased as evidence ("Potentially overvalued"), never instructions ("Sell").
