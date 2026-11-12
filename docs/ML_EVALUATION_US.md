# ML evaluation: earnings-quality anomaly detector

Generated 2026-11-12 by `python -m app.ml.evaluate --market US` on 157
non-financial US companies from the screener scan (5-fold cross-validation, seed 0). Re-run it after a new scan;
numbers change with the universe.

## Model

scikit-learn IsolationForest (300 trees, random_state=42) on robust z-scores of the risky direction of each signal, log-compressed. Each company is described by 8 earnings-quality signals:

| Signal | Unit | Rule in `redflags.py` |
|---|---|---|
| Accruals (profit not backed by cash) | % of assets | none (model only) |
| Cash conversion (3y) | x | below the sector threshold (0.7-0.8x) while profit rises |
| Receivables growth minus revenue growth (3y) | pp | > 10 pp |
| Operating margin vs prior 3-year average | pp | < -3 pp |
| Change in inventory days (1y) | days | none (model only) |
| Asset growth minus revenue growth (1y) | pp | none (model only) |
| Exceptional items share of profit before tax | % | > 15% (in 2 of 3 years) |
| Share count change (3y) | % | > 5% |

## Detection of injected distortions (held-out companies)

| Distortion | ROC AUC | Model detects | Rules detect | Either detects |
|---|---|---|---|---|
| Profit without cash: accruals +8% of assets, cash conversion capped at 0.45x | 0.88 | 57% | 100% | 100% |
| Receivables build-up: receivables grow 18 pp/yr faster than revenue | 0.74 | 28% | 92% | 92% |
| Inventory & asset bloat: +40 inventory days, assets grow 25 pp faster than sales (no rule covers this) | 0.90 | 61% | 42% | 68% |
| Subtle combination: five signals worsen, each staying inside its rule threshold | 0.89 | 54% | 42% | 62% |

False alarms on unmodified held-out companies: **model 12%** (by design about 10%,
the "unusual" threshold), **rules 42%**.

How to read it: ROC AUC is how well the anomaly score ranks distorted companies above normal ones
(0.5 = chance, 1.0 = perfect). "Detects" uses each method's own alarm threshold.

## Real companies (no injection)

The model marks **16 of 157** companies unusual or highly unusual;
**14** of those also have at least one earnings-quality red flag from the rules, and
**49** companies have such a red flag but look typical to the model.

| Company | Percentile | Why the model flagged it | Rule-based quality flags |
|---|---|---|---|
| Synopsys, Inc. (SNPS) | 100 | Asset growth minus revenue growth (1y) +253.7 pp vs peer median +0.1 pp (higher than peers: the balance sheet is growing faster than the business); Exceptional items share of profit before tax 43.0% vs peer median -0.3% (higher than peers: more of the profit comes from one-off items); Share count change (3y) 22.1% vs peer median -1.6% (higher than peers: existing shareholders are being diluted) | dilution, margin_decline, receivables_outpacing |
| Western Digital Corporation (WDC) | 99 | Accruals (profit not backed by cash) 38.6 % of assets vs peer median -3.7 % of assets (higher than peers: a larger share of profit is accounting accruals rather than cash); Cash conversion (3y) 0.53x vs peer median 1.49x (lower than peers: reported profit is not turning into cash); Exceptional items share of profit before tax 58.6% vs peer median -0.3% (higher than peers: more of the profit comes from one-off items) | dilution, profit_cash_gap |
| Moderna, Inc. (MRNA) | 99 | Operating margin vs prior 3-year average -114.5 pp vs peer median +1.8 pp (lower than peers: margins have fallen); Change in inventory days (1y) +35.2 days vs peer median +0.9 days (higher than peers: stock is piling up relative to sales); Asset growth minus revenue growth (1y) +27.2 pp vs peer median +0.1 pp (higher than peers: the balance sheet is growing faster than the business) | losses, margin_decline, negative_fcf |
| The Boeing Company (BA) | 98 | Exceptional items share of profit before tax 368.0% vs peer median -0.3% (higher than peers: more of the profit comes from one-off items); Share count change (3y) 31.3% vs peer median -1.6% (higher than peers: existing shareholders are being diluted) | dilution, negative_fcf |
| PDD Holdings Inc. (PDD) | 98 | Receivables growth minus revenue growth (3y) +56.5 pp vs peer median +1.7 pp (higher than peers: customers are paying more slowly, or sales are booked ahead of cash); Share count change (3y) 7.9% vs peer median -1.6% (higher than peers: existing shareholders are being diluted); Asset growth minus revenue growth (1y) +15.8 pp vs peer median +0.1 pp (higher than peers: the balance sheet is growing faster than the business) | dilution, margin_decline, receivables_outpacing |
| Newmont Corporation (NEM) | 97 | Share count change (3y) 37.3% vs peer median -1.6% (higher than peers: existing shareholders are being diluted); Change in inventory days (1y) +23.5 days vs peer median +0.9 days (higher than peers: stock is piling up relative to sales); Receivables growth minus revenue growth (3y) +18.9 pp vs peer median +1.7 pp (higher than peers: customers are paying more slowly, or sales are booked ahead of cash) | dilution, receivables_outpacing |
| NVIDIA Corporation (NVDA) | 96 | Asset growth minus revenue growth (1y) +19.8 pp vs peer median +0.1 pp (higher than peers: the balance sheet is growing faster than the business); Accruals (profit not backed by cash) 8.4 % of assets vs peer median -3.7 % of assets (higher than peers: a larger share of profit is accounting accruals rather than cash); Receivables growth minus revenue growth (3y) +15.8 pp vs peer median +1.7 pp (higher than peers: customers are paying more slowly, or sales are booked ahead of cash) | receivables_outpacing |
| QUALCOMM Incorporated (QCOM) | 96 | Change in inventory days (1y) +35.3 days vs peer median +0.9 days (higher than peers: stock is piling up relative to sales); Accruals (profit not backed by cash) 4.1 % of assets vs peer median -3.7 % of assets (higher than peers: a larger share of profit is accounting accruals rather than cash); Operating margin vs prior 3-year average -5.9 pp vs peer median +1.8 pp (lower than peers: margins have fallen) | margin_decline |

## Model history: v1 (two-sided) vs v2 (one-sided)

v1 scored deviations in both directions and used plain robust scaling. On real data it flagged companies for
unusually *good* signals (very strong cash conversion, one-off losses), and the extreme tails of a few
companies made realistic distortions look ordinary. v2 counts only each signal's risky direction, compresses
tails with log1p and puts a floor under each feature's scale. Distortions and protocol are unchanged.

| Distortion | v1 AUC | v2 AUC | v1 detects | v2 detects |
|---|---|---|---|---|
| Profit without cash | 0.76 | 0.88 | 18% | 57% |
| Receivables build-up | 0.64 | 0.74 | 14% | 28% |
| Inventory & asset bloat | 0.84 | 0.90 | 33% | 61% |
| Subtle combination | 0.64 | 0.89 | 10% | 54% |

False alarms: v1 10%, v2 12%.

v2 was designed on the Indian universe; this US universe played no part in it, so these results are an
independent check of that design.

## Limitations

- Unsupervised: "unusual" means unlike its peers, not manipulated. Growth companies, restructurings and
  sector quirks also stand out, and sectors are not modelled separately.
- Injected distortions are designed scenarios; real manipulation can look different.
- Small universe (a few hundred companies at most) and Yahoo's 4-5 years of statements.
- The rule baseline is an approximation of `redflags.py` on the same features (see `rule_flags`).
