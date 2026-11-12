"""Earnings-quality features for the anomaly model, computed from one company's analysis.

Each feature is a classic accounting warning sign. Several match a rule in `engine/redflags.py` exactly
(so the model can be compared with the rules on equal terms); the others have no rule and are where the
model can add something. Banks and other financials are excluded: their accounts (loans, deposits) do
not fit these definitions.
"""
from __future__ import annotations

import math
from typing import Any, Optional

# name -> (label, unit, what a HIGH value means, what a LOW value means, rule threshold in redflags.py or None)
FEATURES: dict[str, tuple[str, str, str, str, Optional[str]]] = {
    "accruals_to_assets": ("Accruals (profit not backed by cash)", "% of assets",
                           "a larger share of profit is accounting accruals rather than cash",
                           "profit is more than backed by cash", None),
    "cash_conversion_3y": ("Cash conversion (3y)", "x",
                           "operating cash exceeds reported profit", "reported profit is not turning into cash",
                           "below the sector threshold (0.7-0.8x) while profit rises"),
    "receivables_vs_revenue_cagr": ("Receivables growth minus revenue growth (3y)", "pp",
                                    "customers are paying more slowly, or sales are booked ahead of cash",
                                    "collections are improving", "> 10 pp"),
    "margin_change": ("Operating margin vs prior 3-year average", "pp",
                      "margins have jumped (check whether it is sustainable)", "margins have fallen", "< -3 pp"),
    "inventory_days_change": ("Change in inventory days (1y)", "days",
                              "stock is piling up relative to sales", "stock is being run down", None),
    "asset_vs_revenue_growth": ("Asset growth minus revenue growth (1y)", "pp",
                                "the balance sheet is growing faster than the business",
                                "sales are growing much faster than assets", None),
    "unusual_share_of_pbt": ("Exceptional items share of profit before tax", "%",
                             "more of the profit comes from one-off items", "one-off losses are reducing profit",
                             "> 15% (in 2 of 3 years)"),
    "share_count_change_3y": ("Share count change (3y)", "%",
                              "existing shareholders are being diluted", "the company is buying back shares", "> 5%"),
}
FEATURE_NAMES = list(FEATURES)
# Direction in which a value is an earnings-quality warning (+1: high is risky, -1: low is risky). The model only
# counts deviations in that direction, so companies are not flagged for unusually *good* signals.
RISK_SIGN = {"accruals_to_assets": 1, "cash_conversion_3y": -1, "receivables_vs_revenue_cagr": 1, "margin_change": -1,
             "inventory_days_change": 1, "asset_vs_revenue_growth": 1, "unusual_share_of_pbt": 1, "share_count_change_3y": 1}
# Smallest spread that counts as one unit of "unusual" (in each feature's unit), so a feature on which almost every
# company sits at the same value (e.g. share count change of 0%) does not turn tiny differences into huge z-scores.
SCALE_FLOOR = {"accruals_to_assets": 1.0, "cash_conversion_3y": 0.1, "receivables_vs_revenue_cagr": 2.0, "margin_change": 1.0,
               "inventory_days_change": 5.0, "asset_vs_revenue_growth": 3.0, "unusual_share_of_pbt": 2.0,
               "share_count_change_3y": 1.0}
MIN_FEATURES = 5  # a company needs at least this many known features to be scored


def _num(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _series(a: dict[str, Any], key: str) -> list[Optional[float]]:
    return [_num((p or {}).get("value")) for p in a["metrics"]["annual"]["series"].get(key, [])]


def _statement(a: dict[str, Any], key: str) -> list[Optional[float]]:
    for rows in a["statements"]["annual"]["rows"].values():
        for r in rows:
            if r["key"] == key:
                return [_num(v) for v in r["values"]]
    return []


def _cagr(first: Optional[float], last: Optional[float], years: int) -> Optional[float]:
    if first is None or last is None or first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def _growth(prev: Optional[float], cur: Optional[float]) -> Optional[float]:
    if prev is None or cur is None or prev <= 0:
        return None
    return (cur / prev - 1) * 100


def extract(a: dict[str, Any]) -> Optional[dict[str, Optional[float]]]:
    """Feature values for the latest fiscal year (None for financials). Missing values stay None:
    the model imputes the peer median for them, and too many missing values exclude the company."""
    if a["metrics"].get("is_financial") or len(a["metrics"]["annual"]["labels"]) < 2:
        return None
    ni, cfo = _series(a, "net_income"), _series(a, "cfo")
    assets, rec, rev = _statement(a, "total_assets"), _statement(a, "receivables"), _statement(a, "revenue")
    om, inv_days = _series(a, "operating_margin"), _series(a, "inventory_days")
    shares = _statement(a, "shares_outstanding")
    f: dict[str, Optional[float]] = {k: None for k in FEATURE_NAMES}

    if ni and cfo and assets and None not in (ni[-1], cfo[-1], assets[-1]) and assets[-1] > 0:
        f["accruals_to_assets"] = (ni[-1] - cfo[-1]) / assets[-1] * 100
    n3, c3 = ni[-3:], cfo[-3:]
    if len(n3) == 3 and len(c3) == 3 and None not in n3 + c3 and sum(n3) > 0:
        f["cash_conversion_3y"] = max(-3.0, min(5.0, sum(c3) / sum(n3)))  # bounded: tiny profits explode the ratio
    if len(rec) >= 4 and len(rev) >= 4:
        rg, sg = _cagr(rec[-4], rec[-1], 3), _cagr(rev[-4], rev[-1], 3)
        if rg is not None and sg is not None:
            f["receivables_vs_revenue_cagr"] = rg - sg
    known_om = [x for x in om if x is not None]
    if om and om[-1] is not None and len(known_om) >= 2:
        prior = [x for x in om[-4:-1] if x is not None]
        if prior:
            f["margin_change"] = om[-1] - sum(prior) / len(prior)
    if len(inv_days) >= 2 and None not in inv_days[-2:]:
        f["inventory_days_change"] = inv_days[-1] - inv_days[-2]
    if len(assets) >= 2 and len(rev) >= 2:
        ag, rg1 = _growth(assets[-2], assets[-1]), _growth(rev[-2], rev[-1])
        if ag is not None and rg1 is not None:
            f["asset_vs_revenue_growth"] = ag - rg1
    un = _series(a, "unusual_share_of_pbt")
    if un and un[-1] is not None:
        f["unusual_share_of_pbt"] = un[-1]
    if len(shares) >= 4 and shares[-4] and shares[-1] is not None:
        f["share_count_change_3y"] = _growth(shares[-4], shares[-1])
    return f
