# ML evaluation: earnings-quality anomaly detector

Generated 2026-11-12 by `python -m app.ml.evaluate --market IN` on 147
non-financial Indian companies from the screener scan (5-fold cross-validation, seed 0). Re-run it after a new scan;
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
| Profit without cash: accruals +8% of assets, cash conversion capped at 0.45x | 0.79 | 26% | 100% | 100% |
| Receivables build-up: receivables grow 18 pp/yr faster than revenue | 0.63 | 18% | 84% | 85% |
| Inventory & asset bloat: +40 inventory days, assets grow 25 pp faster than sales (no rule covers this) | 0.80 | 35% | 46% | 54% |
| Subtle combination: five signals worsen, each staying inside its rule threshold | 0.83 | 32% | 46% | 52% |

False alarms on unmodified held-out companies: **model 14%** (by design about 10%,
the "unusual" threshold), **rules 46%**.

How to read it: ROC AUC is how well the anomaly score ranks distorted companies above normal ones
(0.5 = chance, 1.0 = perfect). "Detects" uses each method's own alarm threshold.

## Real companies (no injection)

The model marks **15 of 147** companies unusual or highly unusual;
**14** of those also have at least one earnings-quality red flag from the rules, and
**60** companies have such a red flag but look typical to the model.

| Company | Percentile | Why the model flagged it | Rule-based quality flags |
|---|---|---|---|
| Godrej Properties Limited (GODREJPROP.NS) | 100 | Change in inventory days (1y) +3045.4 days vs peer median +0.6 days (higher than peers: stock is piling up relative to sales); Operating margin vs prior 3-year average -11.8 pp vs peer median +1.0 pp (lower than peers: margins have fallen); Exceptional items share of profit before tax 92.2% vs peer median -0.3% (higher than peers: more of the profit comes from one-off items) | dilution, exceptional_gains, margin_decline, negative_fcf, profit_cash_gap |
| Lloyds Metals and Energy Limited (LLOYDSME.NS) | 99 | Receivables growth minus revenue growth (3y) +221.1 pp vs peer median +1.3 pp (higher than peers: customers are paying more slowly, or sales are booked ahead of cash); Asset growth minus revenue growth (1y) +213.5 pp vs peer median +2.1 pp (higher than peers: the balance sheet is growing faster than the business); Change in inventory days (1y) +178.8 days vs peer median +0.6 days (higher than peers: stock is piling up relative to sales) | dilution, negative_fcf, receivables_outpacing |
| Vodafone Idea Limited (IDEA.NS) | 99 | Share count change (3y) 122.6% vs peer median 0.0% (higher than peers: existing shareholders are being diluted); Exceptional items share of profit before tax 169.8% vs peer median -0.3% (higher than peers: more of the profit comes from one-off items); Accruals (profit not backed by cash) 7.9 % of assets vs peer median -2.6 % of assets (higher than peers: a larger share of profit is accounting accruals rather than cash) | dilution |
| Adani Enterprises Limited (ADANIENT.NS) | 98 | Exceptional items share of profit before tax 68.5% vs peer median -0.3% (higher than peers: more of the profit comes from one-off items); Share count change (3y) 9.9% vs peer median 0.0% (higher than peers: existing shareholders are being diluted); Change in inventory days (1y) +34.4 days vs peer median +0.6 days (higher than peers: stock is piling up relative to sales) | dilution, exceptional_gains, negative_fcf |
| Meesho Limited (MEESHO.NS) | 97 | Receivables growth minus revenue growth (3y) +119.2 pp vs peer median +1.3 pp (higher than peers: customers are paying more slowly, or sales are booked ahead of cash); Accruals (profit not backed by cash) 31.8 % of assets vs peer median -2.6 % of assets (higher than peers: a larger share of profit is accounting accruals rather than cash) | losses, receivables_outpacing |
| Grasim Industries Limited (GRASIM.NS) | 97 | Cash conversion (3y) -3.00x vs peer median 1.27x (lower than peers: reported profit is not turning into cash); Share count change (3y) 2.6% vs peer median 0.0% (higher than peers: existing shareholders are being diluted) | negative_fcf |
| Suzlon Energy Limited (SUZLON.NS) | 96 | Receivables growth minus revenue growth (3y) +33.6 pp vs peer median +1.3 pp (higher than peers: customers are paying more slowly, or sales are booked ahead of cash); Share count change (3y) 10.0% vs peer median 0.0% (higher than peers: existing shareholders are being diluted); Cash conversion (3y) 0.40x vs peer median 1.27x (lower than peers: reported profit is not turning into cash) | dilution, profit_cash_gap, receivables_outpacing |
| Ather Energy Limited (ATHERENERG.NS) | 95 | Receivables growth minus revenue growth (3y) +63.3 pp vs peer median +1.3 pp (higher than peers: customers are paying more slowly, or sales are booked ahead of cash); Asset growth minus revenue growth (1y) +62.0 pp vs peer median +2.1 pp (higher than peers: the balance sheet is growing faster than the business); Share count change (3y) 2.7% vs peer median 0.0% (higher than peers: existing shareholders are being diluted) | losses, negative_fcf, receivables_outpacing |

## Model history: v1 (two-sided) vs v2 (one-sided)

v1 scored deviations in both directions and used plain robust scaling. On real data it flagged companies for
unusually *good* signals (very strong cash conversion, one-off losses), and the extreme tails of a few
companies made realistic distortions look ordinary. v2 counts only each signal's risky direction, compresses
tails with log1p and puts a floor under each feature's scale. Distortions and protocol are unchanged.

| Distortion | v1 AUC | v2 AUC | v1 detects | v2 detects |
|---|---|---|---|---|
| Profit without cash | 0.60 | 0.79 | 10% | 26% |
| Receivables build-up | 0.55 | 0.63 | 13% | 18% |
| Inventory & asset bloat | 0.70 | 0.80 | 18% | 35% |
| Subtle combination | 0.54 | 0.83 | 8% | 32% |

False alarms: v1 11%, v2 14%.

v2 was designed after seeing v1's results on this Indian universe, so these numbers are optimistic; the
US evaluation (`--market US`, docs/ML_EVALUATION_US.md) is the independent check.

## Limitations

- Unsupervised: "unusual" means unlike its peers, not manipulated. Growth companies, restructurings and
  sector quirks also stand out, and sectors are not modelled separately.
- Injected distortions are designed scenarios; real manipulation can look different.
- Small universe (a few hundred companies at most) and Yahoo's 4-5 years of statements.
- The rule baseline is an approximation of `redflags.py` on the same features (see `rule_flags`).
