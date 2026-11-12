"""Provider-agnostic normalisation and validation of a fundamentals bundle.

- Adjusts per-share figures for splits/bonus issues when a period was reported pre-split.
- Detects non-12-month (fiscal-year change) periods.
- Runs accounting sanity checks and records data-quality warnings (never silently "fixes" numbers).
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from .engine.formulas import is_num


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def split_factor_after(period_end: str, splits: list[list[Any]]) -> float:
    """Cumulative split/bonus factor for corporate actions dated after ``period_end``.

    Yahoo encodes a 1:1 bonus as 2.0 and a 1→5 split as 5.0.
    """
    f = 1.0
    end = _d(period_end)
    for d, ratio in splits:
        if _d(d) > end and is_num(ratio) and ratio > 0:
            f *= ratio
    return f


SHARE_FIELDS = ("shares_basic_avg", "shares_diluted_avg", "shares_outstanding")
EPS_FIELDS = ("eps_basic", "eps_diluted")


def _logdist(a: float, b: float) -> float:
    return abs(math.log(a / b))


def adjust_periods_for_splits(periods: list[dict[str, Any]], splits: list[list[Any]],
                              current_shares: float | None) -> None:
    """Put every period's share counts and EPS on today's share basis. Mutates periods in place.

    Providers restate history for splits/bonus issues inconsistently, sometimes per field within
    the same period. So each field is decided independently:

    * Share counts: walking from the newest period backwards, each share field is either the raw
      value or raw × (split factor after that period), whichever is closer (log distance) to the
      already-normalised share count of the next-newer period. A split of factor ≥2 is a jump of
      ≥0.69 in log terms, while organic issuance is usually much smaller.
    * EPS: each EPS field becomes raw or raw ÷ factor, whichever is closer to net profit ÷
      normalised weighted shares. If neither is within 15%, the computed value is used and noted.
    """
    ref = current_shares if is_num(current_shares) and current_shares > 0 else None
    for p in reversed(periods):
        p.setdefault("notes", [])
        f = p["fields"]
        factor = split_factor_after(p["period_end"], splits)
        if abs(factor - 1.0) < 1e-9:
            nxt = f.get("shares_basic_avg") or f.get("shares_outstanding") or f.get("shares_diluted_avg")
            ref = nxt if is_num(nxt) and nxt > 0 else ref
            continue
        changed = []
        if ref is not None:
            for k in SHARE_FIELDS:
                v = f.get(k)
                if is_num(v) and v > 0 and _logdist(v * factor, ref) < _logdist(v, ref):
                    f[k] = v * factor
                    changed.append(k)
        basic = f.get("shares_basic_avg") or f.get("shares_outstanding")
        ni = f.get("net_income")
        if is_num(basic) and basic > 0 and is_num(ni) and abs(ni) > 0:
            implied = ni / basic
            for k in EPS_FIELDS:
                e = f.get(k)
                if not is_num(e) or e == 0:
                    continue
                cands = [(e, False), (e / factor, True)]
                best, adj = min(cands, key=lambda c: abs(c[0] / implied - 1) if implied else 0)
                if abs(best / implied - 1) <= 0.15:
                    f[k] = best
                    if adj:
                        changed.append(k)
                else:
                    f[k] = implied
                    changed.append(k)
                    p["notes"].append(f"{k.replace('_', ' ')} replaced by net profit ÷ adjusted shares: the reported "
                                      "figure was inconsistent with both bases.")
        elif ref is None:
            p["notes"].append(f"Split/bonus factor {factor:g} after this period; share data unavailable, "
                              "per-share values not adjusted.")
        if changed:
            p["split_adjusted_by"] = factor
            p["notes"].append(f"Adjusted for a later split/bonus (factor {factor:g}): {', '.join(sorted(set(changed)))}.")
        nxt = f.get("shares_basic_avg") or f.get("shares_outstanding") or f.get("shares_diluted_avg")
        ref = nxt if is_num(nxt) and nxt > 0 else ref


def prefer_continuing_operations(periods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use profit from continuing operations when it differs materially from total profit.

    A demerger or business sale can book a large one-off gain in discontinued operations
    (e.g. a reported ₹82,000 Cr profit on a pre-tax loss); valuing the remaining business on
    that figure would be badly misleading. Total profit is kept as ``net_income_total``.
    EPS is recomputed from continuing profit and (split-adjusted) weighted shares.
    """
    warnings = []
    for p in periods:
        f = p["fields"]
        ni, nic = f.get("net_income"), f.get("net_income_continuing")
        if not (is_num(ni) and is_num(nic)):
            continue
        if abs(ni - nic) <= 0.10 * max(abs(ni), abs(nic), 1.0):
            continue
        f["net_income_total"] = ni
        f["net_income"] = nic
        for k, sk in (("eps_basic", "shares_basic_avg"), ("eps_diluted", "shares_diluted_avg")):
            sh = f.get(sk) or f.get("shares_basic_avg")
            if is_num(sh) and sh > 0:
                f[k] = nic / sh
        p.setdefault("notes", []).append(
            "Net profit and EPS use continuing operations; total profit including discontinued operations was "
            f"{ni / 1e7:,.0f} Cr (currency of statements).")
        warnings.append({"period": p["label"], "check": "discontinued_operations", "severity": "medium",
                         "message": "Reported net profit includes a large discontinued-operations item (e.g. a demerger or "
                                    "business sale). Ratios and valuation use profit from continuing operations instead."})
    return warnings


def validate_periods(periods: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    prev_end = None
    for p in periods:
        f = p["fields"]
        lbl = p["label"]
        ta, tl, eq, mi = f.get("total_assets"), f.get("total_liabilities"), f.get("equity"), f.get("minority_interest") or 0
        if all(is_num(x) for x in (ta, tl, eq)) and ta > 0:
            gap = abs(ta - (tl + eq + mi)) / ta
            if gap > 0.03:
                warnings.append({"period": lbl, "check": "balance_sheet_identity", "severity": "low",
                                 "message": f"Assets differ from liabilities + equity by {gap*100:.1f}% "
                                            "(possibly other equity items or provider classification)."})
        if is_num(f.get("revenue")) and f["revenue"] < 0:
            warnings.append({"period": lbl, "check": "negative_revenue", "severity": "high",
                             "message": "Reported revenue is negative; growth and margin metrics are unreliable."})
        ni, eps = f.get("net_income"), f.get("eps_basic")
        sh = f.get("shares_basic_avg")
        if all(is_num(x) for x in (ni, eps, sh)) and sh > 0 and abs(ni) > 0:
            implied = ni / sh
            if abs(eps) > 0 and abs(implied / eps - 1) > 0.15:
                warnings.append({"period": lbl, "check": "eps_consistency", "severity": "low",
                                 "message": "Reported EPS differs >15% from net profit ÷ weighted shares; "
                                            "EPS may be on a different basis (e.g. continuing operations)."})
        if prev_end and kind == "annual":
            days = (_d(p["period_end"]) - _d(prev_end)).days
            if not 330 <= days <= 400:
                p["non_standard_length_days"] = days
                warnings.append({"period": lbl, "check": "fiscal_year_change", "severity": "medium",
                                 "message": f"This period is {days} days after the previous one (fiscal-year change "
                                            "or missing year); year-on-year comparisons across it are not like-for-like."})
        prev_end = p["period_end"]
    return warnings


NON_MONETARY = {"shares_basic_avg", "shares_diluted_avg", "shares_outstanding"}


def needs_fx(bundle: dict[str, Any]) -> bool:
    p = bundle.get("profile") or {}
    return bool(p.get("financial_currency") and p.get("currency") and p["financial_currency"] != p["currency"])


def _rate_on(rates: list[list[Any]], d: str) -> float | None:
    import bisect
    dates = [r[0] for r in rates]
    i = bisect.bisect_right(dates, d) - 1
    if i < 0 or (_d(d) - _d(rates[i][0])).days > 10:
        return None
    return float(rates[i][1])


def convert_currency(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Restate statements reported in another currency (e.g. Infosys reports in USD, trades in INR)
    into the quote currency, using the FX close at each period end. Flows are thereby translated at
    closing rather than average rates, an approximation that is recorded as a data-quality note."""
    warnings: list[dict[str, Any]] = []
    if not needs_fx(bundle):
        return warnings
    p = bundle["profile"]
    fx = bundle.get("fx") or {}
    rates = fx.get("rates") or []
    if not rates:
        bundle["fx_unconverted"] = True
        warnings.append({"period": "all", "check": "currency_mismatch", "severity": "high",
                         "message": f"Statements are in {p['financial_currency']} but the price is in {p['currency']} and "
                                    "no exchange rate was available, so valuation multiples are not meaningful."})
        return warnings
    for key in ("annual", "quarterly"):
        for per in bundle.get(key) or []:
            r = _rate_on(rates, per["period_end"])
            if r is None:
                per["fields"] = {k: v for k, v in per["fields"].items() if k in NON_MONETARY}
                per.setdefault("notes", []).append("No FX rate for this date; monetary values dropped.")
                continue
            per["fields"] = {k: (v * r if k not in NON_MONETARY and is_num(v) else v) for k, v in per["fields"].items()}
            per.setdefault("notes", []).append(f"Converted from {p['financial_currency']} at {r:.4f} ({fx.get('pair')}).")
    p["reported_currency"] = p["financial_currency"]
    p["financial_currency"] = p["currency"]
    warnings.append({"period": "all", "check": "currency_converted", "severity": "low",
                     "message": f"The company reports in {p['reported_currency']}; figures were converted to {p['currency']} "
                                f"at each period-end {fx.get('pair')} rate. Growth rates therefore include currency "
                                "movements, and flows use closing rather than average rates."})
    return warnings


def normalize_bundle(bundle: dict[str, Any], imported: dict[str, Any] | None = None) -> dict[str, Any]:
    fx_warnings = convert_currency(bundle)
    if imported:
        # User-imported history (already in the quote currency) merges after FX conversion of provider data.
        from .ingest.screener_import import merge_import
        merge_import(bundle, imported)
    splits = bundle.get("splits") or []
    shares_now = (bundle.get("quote") or {}).get("shares_outstanding")
    for key in ("annual", "quarterly"):
        bundle[key] = sorted(bundle.get(key) or [], key=lambda p: p["period_end"])
        adjust_periods_for_splits(bundle[key], splits, shares_now)
    disc_warnings = []
    for key in ("annual", "quarterly"):
        disc_warnings += prefer_continuing_operations(bundle[key])
    # Drop annual periods that carry almost nothing (Yahoo sometimes returns a stub oldest column).
    bundle["annual"] = [p for p in bundle["annual"] if len(p["fields"]) >= 3]
    bundle["data_quality"] = fx_warnings + disc_warnings + (validate_periods(bundle["annual"], "annual")
                              + validate_periods(bundle["quarterly"], "quarterly"))
    return bundle
