# Methodology: formulas, normalisation and scoring

The live, authoritative version of every threshold and weight is
`backend/app/engine/scoring_config.json`. The app's **Methodology** page renders it directly. This
document explains the reasoning.

## 1. Data normalisation (before any metric is computed)

Run on every read (`backend/app/normalize.py`), in this order:

1. **Currency alignment.** Some Indian companies (e.g. Infosys) report to the provider in USD while
   trading in INR. Each period is converted at the provider's daily FX close on the period end. Flows
   are therefore translated at closing rather than average rates, which is noted as an approximation.
   If no FX rate is available, valuation multiples are blocked rather than computed across currencies.
2. **Split / bonus adjustment.** The provider restates history inconsistently, sometimes per field.
   Share counts are put on today's basis by walking backwards from the newest period: each field is
   either raw or raw × the later split factor, whichever is closer in log terms to the next period's
   normalised count. Each EPS field is then either raw or raw ÷ factor, whichever matches
   net profit ÷ adjusted shares within 15% (otherwise the computed value is used and noted).
3. **Continuing operations.** When total net profit differs by more than 10% from profit from continuing
   operations (demergers, business sales), ratios and valuation use continuing profit. Total profit is
   kept and the period is annotated.
4. **Validation.** Balance-sheet identity (±3%), negative revenue, EPS vs profit/shares consistency, and
   non-12-month periods (fiscal-year changes). Year-on-year comparisons across a non-standard period are
   suppressed.

## 2. Core formulas (`backend/app/engine/formulas.py`, `metrics.py`)

| Metric | Formula | Guard |
|---|---|---|
| YoY growth | (Xₜ / Xₜ₋₁ − 1) × 100 | blank if Xₜ₋₁ ≤ 0 |
| CAGR | ((End / Start)^(1/years) − 1) × 100; years from actual period-end dates | blank if Start or End ≤ 0; **base-effect** flag if Start < ½ the period median (excluded from scoring) |
| Net / operating / EBITDA margin | X / Revenue × 100 | revenue must be > 0 |
| ROE | Net profit / average equity × 100 | blank if average equity ≤ 0; closing equity used (and noted) if the prior year is missing |
| ROCE | EBIT / average (Total assets − Current liabilities) × 100 | |
| ROIC | EBIT × (1 − t) / average (Equity + Debt − Cash) × 100; t = effective rate if 5–45%, else 25.17% statutory | |
| Debt-to-equity | Total borrowings (incl. leases) / Equity | blank if equity ≤ 0 |
| Net debt | Total debt − (Cash + short-term investments) | negative = net cash |
| Net debt / EBITDA | Net debt / EBITDA | blank if EBITDA ≤ 0 |
| Interest coverage | EBIT / interest expense | "no material interest" when interest ≈ 0 (treated as strong) |
| Current / quick ratio | CA / CL; (CA − Inventory) / CL | |
| Receivable / inventory days | Receivables / Revenue × 365; Inventory / COGS × 365 | |
| Free cash flow | CFO − Capex | |
| Cash conversion | CFO / Net profit (and 3-yr cumulative for scoring) | |
| Payout ratio | Dividends paid / Net profit | |
| TTM | Sum of the latest 4 quarters | only if the quarters are consecutive (80–100 days apart) |

For banks, NBFCs and insurers, industrial ratios (margins, D/E, coverage, FCF, ROCE…) are marked
**not meaningful** and replaced by NII growth, loan growth, ROA, an NII/average-assets NIM proxy and
equity/assets. Asset quality (GNPA) and capital adequacy (CAR) are listed as unavailable, not estimated.

## 3. Valuation (`backend/app/engine/valuation.py`)

- **Market cap** = price × current shares; **EV** = market cap + debt + minority interest − cash & ST investments.
- **P/E (latest FY)** = market cap / FY net profit. **P/E (TTM)** from 4 consecutive quarters, else the provider's figure (labelled).
  **Forward P/E** only when ≥3 analysts contribute (labelled *estimate*).
- **Historical P/E band:** weekly price ÷ EPS of the latest fiscal year published ≥60 days earlier (no look-ahead).
- **DCF:** base FCF = average of the last 3 years' FCF (must be positive); stage-1 growth = 3-yr revenue CAGR clipped
  to 2–18%; linear fade to terminal growth (5%) over 5 years; discount 12% (≈7% G-sec + equity risk premium).
  Equity = EV − net debt − minority interest. A 5×5 sensitivity grid (discount × terminal growth) and growth
  sensitivity are always shown. All assumptions are editable. Not applied to lenders or when FCF ≤ 0.
- **Comparables:** peer median P/E × EPS; peer median EV/EBITDA × EBITDA − net debt; for lenders peer median P/B × BVPS.
  Requires ≥3 valid peers. Provider peer ratios are screened first: values outside plausibility bounds
  (e.g. EV/EBITDA > 150×) or more than 4× from the median of the others are excluded and shown as “excl.”.
- **Dividend discount model:** D₀ × (1+g)/(kₑ − g); only with dividends in ≥3 of the last 4 years; excluded from the
  range when payout < 30%.
- **Justified P/B:** (ROE − g)/(kₑ − g) × BVPS; used in the range for financial companies.
- **Fair-value range:** IQR of method values when ≥4 methods, else min–max; needs ≥2 methods, otherwise
  “Cannot reliably assess”. Label: below the range = *Potentially undervalued*, above = *Potentially overvalued*.
- **Reconciliation:** market cap, P/B, EV and EV/EBITDA are compared with the provider's own figures. Gaps >10% are
  flagged. Gaps >20% on like-for-like checks (market cap, P/B) cap confidence at Medium and add a caveat. Provider
  values that are implausible on their face are ignored.

## 4. Scoring (`backend/app/engine/scoring.py`)

Each category is a weighted set of inputs. Each input is scored 0–100 by **piecewise-linear interpolation** between
configured points, then:

```
category score = Σ(score_i × weight_i) / Σ(weight_i over AVAILABLE inputs)
completeness  = Σ(weight of available inputs) / Σ(all weights)
```

A missing input is excluded (never scored as zero). A category with completeness < 40% is reported as
**insufficient data**.

**Three verdicts**

| Verdict | Construction |
|---|---|
| Business quality (0–100) | Growth 30 · Profitability 40 · Cash flow 20 · Governance 10 (financials: growth 30 · profitability 45 · asset quality 15 · governance 10). Requires growth and profitability. |
| Financial risk (0–100, higher = riskier) | 0.7 × (100 − resilience) + red-flag points (high 10, medium 4, low 1; capped at 30). Resilience = balance sheet 60 / cash flow 40 (financials: capital 50 / asset quality 50). |
| Valuation | Label from the fair-value range; attractiveness score from upside to the range midpoint, P/E vs peers, P/E percentile in own history, FCF yield and PEG. |

**Composite** (configurable; standard weights) = growth 20, profitability 20, balance sheet 15, cash flow 15,
valuation 15, governance 10, industry 5.

**Sector profiles** scale leverage thresholds: *capital-intensive* industries (utilities, infrastructure, telecom,
steel…) tolerate 1.5× the leverage; *asset-light* ones (IT services, software) 0.8×.

**Confidence** = 100 − 0.6 × (100 − completeness), less 15 for <4 years of data, 10 for stale data, 5 per reconciliation
flag (max 10, +10 if a gap is >20%), and 5 when valuation methods disagree widely; capped at Medium on a major discrepancy.

**Decision-support label:** *Insufficient evidence* (completeness < 50% or no quality score) → *Elevated financial risk*
(risk ≥ 55) → *Strong fundamentals* (quality ≥ 70, risk < 35, valuation not stretched) → *Fundamentally sound, valuation
needs scrutiny* (good quality, unattractive valuation) → otherwise *Mixed financial picture*.

## 5. Red flags (`backend/app/engine/redflags.py`)

Each flag carries evidence, severity, period, implication and the rule that fired: losses, negative equity, persistent
negative FCF, profit rising while CFO lags (3-yr cumulative CFO/PAT < 0.8 and < 0.5 for high), operating-margin decline
> 3 pp vs the prior 3-yr average, leverage and coverage thresholds (by sector profile), current ratio < 1, receivables
CAGR exceeding revenue CAGR by >10 pp, exceptional items >15% of PBT in 2 of 3 years, ROE falling two years running,
share-count growth >5% in 3 years, sharp latest-year deterioration, valuation >1.75× peer P/E, and user-entered
governance facts (pledge, auditor, litigation, related-party transactions). Lenders get lender-specific checks.
Flags are signals for further reading, never findings of wrongdoing.

## 6. IPO analysis (`backend/app/engine/ipo.py`)

Fresh-issue shares = fresh issue ÷ upper band; post-issue shares = pre-issue + fresh; post-issue market cap at the upper
band; P/E on post-issue shares (comparable basis) and pre-issue shares (as some RHPs quote it); post-issue net worth =
net worth + fresh issue; EV assumes proceeds are held as cash. Scenarios: next-year PAT × P/E ÷ post-issue shares, with
(conservative) half of historical PAT growth and peer 25th-percentile P/E less 15%, (base) 80% of growth and peer median
less 5%, (optimistic) full growth and the peer 75th percentile. Five assessments are kept separate; subscription and GMP
only ever raise *risk*, never attractiveness. Lock-in dates follow SEBI ICDR periods (anchor 30/90 days, pre-IPO holders
6 months, promoters' minimum contribution 18 months) counted from an estimated allotment date. Confirm them against the
offer document.
