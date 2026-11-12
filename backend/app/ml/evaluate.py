"""How well does the anomaly model catch distorted accounts, compared with the rule-based red flags?

There are no labelled examples of manipulated Indian accounts to test against, so the evaluation uses the
standard approach for unsupervised detectors: **inject known distortions** into real companies' features and
measure detection on companies the model has not seen.

Protocol (5-fold cross-validation over the real scanned universe):
  * fit the model on 80% of the companies;
  * score the held-out 20% as they are ("clean") and with each distortion pattern applied ("injected");
  * detection rate = share of injected copies at or above the model's "unusual" threshold (90th percentile
    of training scores); false-alarm rate = share of clean held-out companies above it;
  * ROC AUC = how well the anomaly score separates injected from clean (0.5 = chance, 1.0 = perfect);
  * the rule baseline applies the app's own red-flag thresholds to the same features.

Caveats: the distortions are designed, not observed, and "clean" companies are not verified to be clean.
The point is a fair, repeatable comparison between the model and the rules, not a fraud-detection accuracy.

Run:  .venv\\Scripts\\python -m app.ml.evaluate            (uses your latest screener scan)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
from sklearn.metrics import roc_auc_score

from . import anomaly
from .features import FEATURES

Features = dict[str, Optional[float]]


def _set(f: Features, key: str, fn: Callable[[float], float], default: float) -> None:
    f[key] = fn(f[key] if f.get(key) is not None else default)


def _profit_without_cash(f: Features) -> None:
    _set(f, "accruals_to_assets", lambda v: v + 8, 0)
    _set(f, "cash_conversion_3y", lambda v: min(v, 0.45), 1.0)


def _receivables_build_up(f: Features) -> None:
    _set(f, "receivables_vs_revenue_cagr", lambda v: v + 18, 0)


def _inventory_and_asset_bloat(f: Features) -> None:  # no rule covers these two signals
    _set(f, "inventory_days_change", lambda v: v + 40, 0)
    _set(f, "asset_vs_revenue_growth", lambda v: v + 25, 0)


def _subtle_combination(f: Features) -> None:
    """Several signals worsen at once, each staying inside its rule threshold."""
    _set(f, "cash_conversion_3y", lambda v: min(v, 0.85), 1.0)
    _set(f, "receivables_vs_revenue_cagr", lambda v: max(v, 8), 0)
    _set(f, "margin_change", lambda v: min(v, -2.5), 0)
    _set(f, "accruals_to_assets", lambda v: v + 4, 0)
    _set(f, "asset_vs_revenue_growth", lambda v: v + 10, 0)


PATTERNS: dict[str, tuple[str, Callable[[Features], None]]] = {
    "profit_without_cash": ("Profit without cash: accruals +8% of assets, cash conversion capped at 0.45x", _profit_without_cash),
    "receivables_build_up": ("Receivables build-up: receivables grow 18 pp/yr faster than revenue", _receivables_build_up),
    "inventory_and_asset_bloat": ("Inventory & asset bloat: +40 inventory days, assets grow 25 pp faster than sales (no rule covers this)", _inventory_and_asset_bloat),
    "subtle_combination": ("Subtle combination: five signals worsen, each staying inside its rule threshold", _subtle_combination),
}


def rule_flags(f: Features) -> bool:
    """The app's red-flag thresholds (engine/redflags.py) applied to the same features. Approximations: the
    cash rule also requires rising profit, and the exceptional-items rule needs 2 of 3 years."""
    v = lambda k: f.get(k)  # noqa: E731
    return any([
        v("cash_conversion_3y") is not None and v("cash_conversion_3y") < 0.8,
        v("receivables_vs_revenue_cagr") is not None and v("receivables_vs_revenue_cagr") > 10,
        v("margin_change") is not None and v("margin_change") < -3,
        v("unusual_share_of_pbt") is not None and v("unusual_share_of_pbt") > 15,
        v("share_count_change_3y") is not None and v("share_count_change_3y") > 5,
    ])


def evaluate(rows: list[dict[str, Any]], folds: int = 5, seed: int = 0, one_sided: bool = True) -> dict[str, Any]:
    rows = [r for r in rows if anomaly.usable(r.get("features"))]
    if len(rows) < anomaly.MIN_UNIVERSE + 5:
        raise ValueError(f"Need at least {anomaly.MIN_UNIVERSE + 5} usable companies; have {len(rows)}.")
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(rows))
    clean_scores: list[float] = []
    clean_model_hits = clean_rule_hits = 0
    inj: dict[str, dict[str, list]] = {k: {"scores": [], "model": [], "rules": []} for k in PATTERNS}
    for k in range(folds):
        test_idx = set(order[k::folds].tolist())
        train = [r for i, r in enumerate(rows) if i not in test_idx]
        test = [r for i, r in enumerate(rows) if i in test_idx]
        fitted = anomaly.fit(train, one_sided)
        if fitted is None:
            raise ValueError("Training fold too small.")
        threshold = float(np.percentile(fitted.train_scores, anomaly.UNUSUAL_PCT))
        clean = [r["features"] for r in test]
        s = anomaly.raw_scores(fitted, clean)
        clean_scores += s.tolist()
        clean_model_hits += int((s >= threshold).sum())
        clean_rule_hits += sum(rule_flags(f) for f in clean)
        for name, (_, apply) in PATTERNS.items():
            injected = []
            for f in clean:
                f = dict(f)
                apply(f)
                injected.append(f)
            si = anomaly.raw_scores(fitted, injected)
            inj[name]["scores"] += si.tolist()
            inj[name]["model"] += (si >= threshold).tolist()
            inj[name]["rules"] += [rule_flags(f) for f in injected]
    n = len(clean_scores)
    patterns = {}
    for name, d in inj.items():
        y = [0] * n + [1] * len(d["scores"])
        patterns[name] = {
            "description": PATTERNS[name][0],
            "roc_auc": round(float(roc_auc_score(y, clean_scores + d["scores"])), 3),
            "model_detection": round(float(np.mean(d["model"])), 3),
            "rule_detection": round(float(np.mean(d["rules"])), 3),
            "either_detection": round(float(np.mean([a or b for a, b in zip(d["model"], d["rules"])])), 3),
        }
    return {"companies": len(rows), "folds": folds, "seed": seed, "patterns": patterns, "one_sided": one_sided,
            "model_false_alarm": round(clean_model_hits / n, 3), "rule_false_alarm": round(clean_rule_hits / n, 3)}


QUALITY_FLAGS = {"profit_cash_gap", "receivables_outpacing", "exceptional_gains", "margin_decline", "dilution",
                 "negative_fcf", "losses"}


def real_world_overlap(rows: list[dict[str, Any]], one_sided: bool = True) -> dict[str, Any]:
    """On the real universe (no injection): which companies does the model flag, and do the rules agree?"""
    fitted = anomaly.fit(rows, one_sided)
    scored = [(r, anomaly.score(fitted, r["features"])) for r in rows if anomaly.usable(r.get("features"))]
    flagged = sorted([(r, s) for r, s in scored if s["level"] != "typical"], key=lambda x: -x[1]["score"])
    with_rules = [r for r, _ in flagged if QUALITY_FLAGS & set(r.get("flag_ids") or [])]
    rule_only = [r for r, s in scored if s["level"] == "typical" and QUALITY_FLAGS & set(r.get("flag_ids") or [])]
    return {
        "scored": len(scored), "model_flagged": len(flagged), "also_rule_flagged": len(with_rules),
        "rule_flagged_not_model": len(rule_only),
        "top": [{"symbol": r["symbol"], "name": r.get("name"), "percentile": s["percentile"],
                 "reasons": [x["text"] for x in s["reasons"]],
                 "rule_flags": sorted(QUALITY_FLAGS & set(r.get("flag_ids") or []))} for r, s in flagged[:8]],
    }


def report(ev: dict[str, Any], real: dict[str, Any], v1: dict[str, Any] | None = None, market: str = "IN") -> str:
    rows = "\n".join(
        f"| {p['description']} | {p['roc_auc']:.2f} | {p['model_detection']:.0%} | {p['rule_detection']:.0%} | {p['either_detection']:.0%} |"
        for p in ev["patterns"].values())
    top = "\n".join(
        f"| {t['name'] or t['symbol']} ({t['symbol']}) | {t['percentile']:.0f} | {'; '.join(t['reasons']) or '(combination, no single signal)'} | "
        f"{', '.join(t['rule_flags']) or 'none'} |" for t in real["top"])
    feats = "\n".join(f"| {v[0]} | {v[1]} | {v[4] or 'none (model only)'} |" for v in FEATURES.values())
    history = "" if v1 is None else "\n".join([
        "## Model history: v1 (two-sided) vs v2 (one-sided)", "",
        "v1 scored deviations in both directions and used plain robust scaling. On real data it flagged companies for",
        "unusually *good* signals (very strong cash conversion, one-off losses), and the extreme tails of a few",
        "companies made realistic distortions look ordinary. v2 counts only each signal's risky direction, compresses",
        "tails with log1p and puts a floor under each feature's scale. Distortions and protocol are unchanged.", "",
        "| Distortion | v1 AUC | v2 AUC | v1 detects | v2 detects |", "|---|---|---|---|---|",
        *[f"| {p['description'].split(':')[0]} | {p['roc_auc']:.2f} | {ev['patterns'][k]['roc_auc']:.2f} | "
          f"{p['model_detection']:.0%} | {ev['patterns'][k]['model_detection']:.0%} |" for k, p in v1["patterns"].items()],
        "", f"False alarms: v1 {v1['model_false_alarm']:.0%}, v2 {ev['model_false_alarm']:.0%}.", "",
        *(["v2 was designed after seeing v1's results on this Indian universe, so these numbers are optimistic; the",
            "US evaluation (`--market US`, docs/ML_EVALUATION_US.md) is the independent check."] if market == "IN" else
          ["v2 was designed on the Indian universe; this US universe played no part in it, so these results are an",
           "independent check of that design."]), "", ""])
    return f"""# ML evaluation: earnings-quality anomaly detector

Generated {date.today().isoformat()} by `python -m app.ml.evaluate --market {market}` on {ev['companies']}
non-financial {"Indian" if market == "IN" else "US"} companies from the screener scan ({ev['folds']}-fold cross-validation, seed {ev['seed']}). Re-run it after a new scan;
numbers change with the universe.

## Model

{anomaly.MODEL_CARD['algorithm']}. Each company is described by {len(FEATURES)} earnings-quality signals:

| Signal | Unit | Rule in `redflags.py` |
|---|---|---|
{feats}

## Detection of injected distortions (held-out companies)

| Distortion | ROC AUC | Model detects | Rules detect | Either detects |
|---|---|---|---|---|
{rows}

False alarms on unmodified held-out companies: **model {ev['model_false_alarm']:.0%}** (by design about 10%,
the "unusual" threshold), **rules {ev['rule_false_alarm']:.0%}**.

How to read it: ROC AUC is how well the anomaly score ranks distorted companies above normal ones
(0.5 = chance, 1.0 = perfect). "Detects" uses each method's own alarm threshold.

## Real companies (no injection)

The model marks **{real['model_flagged']} of {real['scored']}** companies unusual or highly unusual;
**{real['also_rule_flagged']}** of those also have at least one earnings-quality red flag from the rules, and
**{real['rule_flagged_not_model']}** companies have such a red flag but look typical to the model.

| Company | Percentile | Why the model flagged it | Rule-based quality flags |
|---|---|---|---|
{top}

{history}## Limitations

- Unsupervised: "unusual" means unlike its peers, not manipulated. Growth companies, restructurings and
  sector quirks also stand out, and sectors are not modelled separately.
- Injected distortions are designed scenarios; real manipulation can look different.
- Small universe (a few hundred companies at most) and Yahoo's 4-5 years of statements.
- The rule baseline is an approximation of `redflags.py` on the same features (see `rule_flags`).
"""


def main(argv: list[str] | None = None) -> int:
    from .. import db
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--market", default="IN", choices=["IN", "US"])
    ap.add_argument("--out", help="default: docs/ML_EVALUATION.md (India) or docs/ML_EVALUATION_US.md")
    args = ap.parse_args(argv)
    docs = Path(__file__).resolve().parents[3] / "docs"
    args.out = args.out or str(docs / ("ML_EVALUATION.md" if args.market == "IN" else "ML_EVALUATION_US.md"))
    rows = anomaly.universe_rows(db.scan_list(), args.market)
    try:
        ev = evaluate(rows)
    except ValueError as e:
        print(f"Cannot evaluate: {e} Run a screener scan of 100+ {args.market} companies first.", file=sys.stderr)
        return 1
    v1 = evaluate(rows, one_sided=False)
    real = real_world_overlap(rows)
    Path(args.out).write_text(report(ev, real, v1, args.market), encoding="utf-8")
    print(f"Wrote {args.out}")
    for p in ev["patterns"].values():
        print(f"  AUC {p['roc_auc']:.2f}  model {p['model_detection']:.0%}  rules {p['rule_detection']:.0%}  {p['description']}")
    print(f"  false alarms: model {ev['model_false_alarm']:.0%}, rules {ev['rule_false_alarm']:.0%}")
    print("  v1 (two-sided): " + ", ".join(f"AUC {p['roc_auc']:.2f} / {p['model_detection']:.0%}" for p in v1["patterns"].values())
          + f" | false alarms {v1['model_false_alarm']:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
