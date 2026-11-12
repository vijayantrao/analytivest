"""Earnings-quality anomaly detector: an Isolation Forest over the features in `features.py`.

Unsupervised: there are no labelled "manipulated accounts" to learn from, so the model learns what is normal
across the scanned universe and scores how hard a company is to fit into that picture. It complements the
rule-based red flags (which check one signal at a time against a fixed threshold) by catching unusual
*combinations* of signals, each of which may sit below its rule threshold.

Pipeline (v2, "one-sided"; v1 "two-sided" is kept for the evaluation's comparison)
  1. Robust z-score per feature: (x - median) / max(1.4826 * MAD, floor), the floor being a minimum meaningful
     unit per feature (SCALE_FLOOR).
  2. Only the risky direction counts (RISK_SIGN): z is oriented so that positive = warning, values on the safe
     side are set to 0, and log1p compresses extreme tails so one wild value cannot drown out several
     moderate warnings. (v1 used both directions, clipped to +/-8, and flagged companies for unusually good
     signals.) Missing values are set to the median (0); companies with fewer than MIN_FEATURES known values
     are not scored.
  3. IsolationForest(n_estimators=300, random_state=42). Anomaly score = -score_samples (higher = stranger).
  4. Percentile of the score within the training universe: top 10% = "unusual", top 3% = "highly unusual".
  5. Explanation by occlusion: each known feature is reset to the peer median and the company re-scored; the
     drop in anomaly score is that feature's contribution. These are model-based attributions, not just
     "the biggest z-score".
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from .features import FEATURE_NAMES, FEATURES, MIN_FEATURES, RISK_SIGN, SCALE_FLOOR

MIN_UNIVERSE = 30
UNUSUAL_PCT, HIGHLY_UNUSUAL_PCT = 90.0, 97.0
Z_CLIP = 8.0  # v1 only
N_ESTIMATORS, SEED = 300, 42
SIGN = np.array([RISK_SIGN[k] for k in FEATURE_NAMES], dtype=float)
FLOOR = np.array([SCALE_FLOOR[k] for k in FEATURE_NAMES], dtype=float)


@dataclass
class Fitted:
    model: IsolationForest
    median: np.ndarray
    scale: np.ndarray
    train_scores: np.ndarray  # sorted
    symbols: list[str]
    n: int
    one_sided: bool = True

    def percentile(self, s: float) -> float:
        return float(np.searchsorted(self.train_scores, s, side="right") / len(self.train_scores) * 100)


def _matrix(feature_dicts: list[dict[str, Optional[float]]]) -> np.ndarray:
    return np.array([[np.nan if d.get(k) is None else float(d[k]) for k in FEATURE_NAMES] for d in feature_dicts],
                    dtype=float)


def _oriented_z(X: np.ndarray, median: np.ndarray, scale: np.ndarray, one_sided: bool) -> np.ndarray:
    Z = (X - median) / scale
    return Z * SIGN if one_sided else Z


def _scale(X: np.ndarray, median: np.ndarray, scale: np.ndarray, one_sided: bool = True) -> np.ndarray:
    Z = _oriented_z(X, median, scale, one_sided)
    Z = np.log1p(np.clip(Z, 0.0, 1e6)) if one_sided else np.clip(Z, -Z_CLIP, Z_CLIP)
    return np.where(np.isnan(Z), 0.0, Z)  # missing -> peer median


def usable(features: Optional[dict[str, Optional[float]]]) -> bool:
    return bool(features) and sum(v is not None for v in features.values()) >= MIN_FEATURES


def fit(rows: list[dict[str, Any]], one_sided: bool = True) -> Optional[Fitted]:
    """rows: [{"symbol": ..., "features": {...}}]. Returns None when too few companies can be used.
    one_sided=False reproduces v1 (both directions, no scale floor) for the evaluation."""
    rows = [r for r in rows if usable(r.get("features"))]
    if len(rows) < MIN_UNIVERSE:
        return None
    X = _matrix([r["features"] for r in rows])
    median = np.nanmedian(X, axis=0)
    mad = np.nanmedian(np.abs(X - median), axis=0) * 1.4826
    std = np.nanstd(X, axis=0)
    if one_sided:
        scale = np.maximum(np.where(np.isnan(mad), 0.0, mad), FLOOR)
    else:
        scale = np.where(mad > 1e-9, mad, np.where(std > 1e-9, std, 1.0))
    median = np.where(np.isnan(median), 0.0, median)
    Z = _scale(X, median, scale, one_sided)
    model = IsolationForest(n_estimators=N_ESTIMATORS, random_state=SEED).fit(Z)
    return Fitted(model, median, scale, np.sort(-model.score_samples(Z)), [r["symbol"] for r in rows], len(rows),
                  one_sided)


def _fmt(v: float, unit: str) -> str:
    if unit == "x":
        return f"{v:.2f}x"
    if unit in ("pp", "days"):
        return f"{v:+.1f} {unit}"
    return f"{v:.1f}%" if unit == "%" else f"{v:.1f} {unit}"


def _describe(name: str, value: float, median: float) -> str:
    label, unit, high_means, low_means, _ = FEATURES[name]
    why = f"higher than peers: {high_means}" if value > median else f"lower than peers: {low_means}"
    return f"{label} {_fmt(value, unit)} vs peer median {_fmt(median, unit)} ({why})"


def raw_scores(fitted: Fitted, feature_dicts: list[dict[str, Optional[float]]]) -> np.ndarray:
    """Anomaly scores only (no explanations), in one batch: used by the evaluation."""
    return -fitted.model.score_samples(_scale(_matrix(feature_dicts), fitted.median, fitted.scale, fitted.one_sided))


def score(fitted: Fitted, features: dict[str, Optional[float]]) -> dict[str, Any]:
    if not usable(features):
        return {"available": False, "reason": f"Fewer than {MIN_FEATURES} of the {len(FEATURE_NAMES)} features "
                                              "could be computed from the available statements."}
    x = _matrix([features])
    z = _scale(x, fitted.median, fitted.scale, fitted.one_sided)
    oz = _oriented_z(x, fitted.median, fitted.scale, fitted.one_sided)  # for explanations: + = risky (v2)
    s = float(-fitted.model.score_samples(z)[0])
    pct = fitted.percentile(s)
    known = [j for j, k in enumerate(FEATURE_NAMES) if features.get(k) is not None]
    occluded = np.repeat(z, len(known), axis=0)
    for row, j in enumerate(known):
        occluded[row, j] = 0.0
    drops = s - (-fitted.model.score_samples(occluded))
    contributions = sorted(((float(d), j) for d, j in zip(drops, known)), reverse=True)
    reasons = []
    for d, j in contributions:
        zj = float(oz[0, j])
        if d <= 0.005 or (zj < 1.5 if fitted.one_sided else abs(zj) < 1.5):
            continue
        k = FEATURE_NAMES[j]
        reasons.append({"feature": k, "label": FEATURES[k][0], "value": features[k], "peer_median": float(fitted.median[j]),
                        "z": round(zj, 2), "contribution": round(d, 4),
                        "text": _describe(k, float(features[k]), float(fitted.median[j]))})
        if len(reasons) == 3:
            break
    level = "highly_unusual" if pct >= HIGHLY_UNUSUAL_PCT else "unusual" if pct >= UNUSUAL_PCT else "typical"
    return {"available": True, "score": round(s, 4), "percentile": round(pct, 1), "level": level,
            "reasons": reasons, "missing": [k for k in FEATURE_NAMES if features.get(k) is None],
            "features": {k: features.get(k) for k in FEATURE_NAMES},
            "peer_median": {k: float(m) for k, m in zip(FEATURE_NAMES, fitted.median)}}


# ---------------- universe from screener scans (cached per scan state) ----------------
# One model per market: a US company is only ever compared with US companies, an Indian one with Indian ones.
_cache: dict[str, tuple[str, Optional[Fitted]]] = {}
_cache_lock = threading.Lock()


def universe_rows(scan_rows: list[dict[str, Any]], market: str = "IN") -> list[dict[str, Any]]:
    from ..screener import market_of
    return [{"symbol": r["symbol"], "name": r["summary"].get("name"), "features": r["summary"].get("ml_features"),
             "flag_ids": r["summary"].get("flag_ids", [])}
            for r in scan_rows if r["summary"].get("ml_features") and market_of(r) == market]


def fitted_for(scan_rows: list[dict[str, Any]], market: str = "IN") -> tuple[Optional[Fitted], list[dict[str, Any]]]:
    rows = universe_rows(scan_rows, market)
    key = hashlib.sha1(json.dumps([[r["symbol"], r["features"]] for r in rows], sort_keys=True).encode()).hexdigest()
    with _cache_lock:
        if market not in _cache or _cache[market][0] != key:
            _cache[market] = (key, fit(rows))
        return _cache[market][1], rows


MODEL_CARD = {
    "name": "Earnings-quality anomaly detector",
    "algorithm": f"scikit-learn IsolationForest ({N_ESTIMATORS} trees, random_state={SEED}) on robust z-scores of the "
                 "risky direction of each signal, log-compressed",
    "trained_on": "the companies of the same market (India or US) in your screener scans, banks and other financials "
                  "excluded",
    "features": [{"name": k, "label": v[0], "unit": v[1], "rule": v[4]} for k, v in FEATURES.items()],
    "levels": f"top {100 - UNUSUAL_PCT:.0f}% of the universe = unusual, top {100 - HIGHLY_UNUSUAL_PCT:.0f}% = highly unusual",
    "limits": "Unsupervised: 'unusual' means unlike its peers, not 'manipulated'. Small universes and Yahoo's 4-5 years "
              "of data limit accuracy; sector differences are not modelled. Use it to decide what to look into, "
              "alongside the rule-based red flags.",
}
