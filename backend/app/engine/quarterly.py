"""Latest-quarter results check: compares the most recent quarter with the same quarter a year earlier
(the like-for-like comparison, free of seasonality) and with the previous quarter.

Quarterly data on the free provider is sparse (about 4-5 quarters, sometimes with gaps), so every
comparison states which quarters it used, and missing comparisons are reported, not guessed.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from . import formulas as F
from .formulas import is_num


def _find(periods: list[dict[str, Any]], end: date, lo: int, hi: int) -> Optional[dict[str, Any]]:
    for p in reversed(periods):
        d = (end - date.fromisoformat(p["period_end"])).days
        if lo <= d <= hi:
            return p
    return None


def _margin(f: dict[str, Any], num_key: str) -> Optional[float]:
    num, rev = f.get(num_key), f.get("revenue")
    return F.pct(num, rev).value if is_num(num) and is_num(rev) else None


def quarterly_check(bundle: dict[str, Any], is_financial: bool, today: Optional[date] = None) -> dict[str, Any]:
    qs = sorted(bundle.get("quarterly") or [], key=lambda p: p["period_end"])
    qs = [q for q in qs if q["fields"].get("revenue") is not None or q["fields"].get("net_income") is not None]
    if not qs:
        return {"available": False, "reason": "The data provider has no quarterly results for this company."}
    latest = qs[-1]
    end = date.fromisoformat(latest["period_end"])
    year_ago = _find(qs[:-1], end, 350, 380)
    prev = _find(qs[:-1], end, 80, 100)
    lf = latest["fields"]
    metrics = [("revenue", "Revenue")]
    if is_financial:
        metrics.append(("net_interest_income", "Net interest income"))
    else:
        metrics += [("ebitda", "EBITDA"), ("operating_income", "Operating profit")]
    metrics += [("net_income", "Net profit"), ("eps_diluted", "EPS (diluted)")]

    rows = []
    for key, label in metrics:
        cur = lf.get(key)
        if not is_num(cur):
            continue
        ya = year_ago["fields"].get(key) if year_ago else None
        pv = prev["fields"].get(key) if prev else None
        yoy, qoq = F.growth(cur, ya), F.growth(cur, pv)
        rows.append({"key": key, "label": label, "latest": cur, "year_ago": ya, "prev": pv,
                     "yoy_pct": yoy.value, "yoy_reason": yoy.reason, "qoq_pct": qoq.value, "qoq_reason": qoq.reason,
                     "unit": "per_share" if key == "eps_diluted" else "currency"})
    margins = []
    if not is_financial:
        for key, label in (("operating_income", "Operating margin"), ("net_income", "Net margin")):
            cur = _margin(lf, key)
            ya = _margin(year_ago["fields"], key) if year_ago else None
            if cur is not None:
                margins.append({"label": label, "latest": cur, "year_ago": ya,
                                "change_pp": (cur - ya) if ya is not None else None})

    signals: list[dict[str, Any]] = []
    by = {r["key"]: r for r in rows}

    def sig(kind, severity, title, evidence):
        signals.append({"kind": kind, "severity": severity, "title": title, "evidence": evidence})

    top_key = "net_interest_income" if is_financial and "net_interest_income" in by else "revenue"
    top = by.get(top_key)
    if top and is_num(top["yoy_pct"]):
        g = top["yoy_pct"]
        if g <= -5:
            sig("negative", "high" if g <= -15 else "medium", f"{top['label']} fell year on year",
                f"{top['label']} {g:+.1f}% vs {year_ago['label']}.")
        elif g >= 15:
            sig("positive", "low", f"Strong {top['label'].lower()} growth", f"{top['label']} {g:+.1f}% vs {year_ago['label']}.")
    ni = by.get("net_income")
    if ni and is_num(ni["yoy_pct"]):
        g = ni["yoy_pct"]
        if g <= -15:
            sig("negative", "high" if g <= -30 else "medium", "Net profit fell year on year", f"Net profit {g:+.1f}% vs {year_ago['label']}.")
        elif g >= 20:
            sig("positive", "low", "Net profit grew strongly", f"Net profit {g:+.1f}% vs {year_ago['label']}.")
    elif ni and ni["latest"] < 0:
        sig("negative", "high", "Loss in the latest quarter", f"Net loss in {latest['label']}.")
    for m in margins:
        if m["change_pp"] is not None and m["change_pp"] <= -2:
            sig("negative", "medium", f"{m['label']} compressed", f"{m['label']} {m['latest']:.1f}% vs {m['year_ago']:.1f}% a year "
                f"earlier ({m['change_pp']:+.1f} pp).")
        elif m["change_pp"] is not None and m["change_pp"] >= 2:
            sig("positive", "low", f"{m['label']} expanded", f"{m['label']} {m['latest']:.1f}% vs {m['year_ago']:.1f}% "
                f"({m['change_pp']:+.1f} pp).")

    neg = [s for s in signals if s["kind"] == "negative"]
    pos = [s for s in signals if s["kind"] == "positive"]
    if year_ago is None:
        verdict = "Not enough history"
    elif any(s["severity"] == "high" for s in neg) or len(neg) >= 2:
        verdict = "Weak quarter"
    elif neg and pos:
        verdict = "Mixed quarter"
    elif neg:
        verdict = "Soft quarter"
    elif pos:
        verdict = "Strong quarter"
    else:
        verdict = "Steady quarter"
    today = today or date.today()
    return {
        "available": True, "verdict": verdict, "latest": latest["label"], "latest_end": latest["period_end"],
        "year_ago": year_ago["label"] if year_ago else None, "prev": prev["label"] if prev else None,
        "rows": rows, "margins": margins, "signals": signals,
        "age_days": (today - end).days,
        "note": None if year_ago else "The same quarter of last year is missing from the free data, so the like-for-like "
                                      "comparison is not available; quarter-on-quarter changes can be seasonal.",
        "method": "Like-for-like: latest quarter vs the same quarter one year earlier (avoids seasonality). "
                  "Quarter-on-quarter shown for momentum only.",
    }


def quarter_flags(q: dict[str, Any]) -> list[dict[str, Any]]:
    """Feed severe quarterly deterioration into the red-flag list (and therefore the risk score)."""
    out = []
    if not q.get("available"):
        return out
    for s in q["signals"]:
        if s["kind"] == "negative" and s["severity"] == "high":
            out.append({"id": f"q_{s['title'].lower().replace(' ', '_')}", "title": f"Latest quarter: {s['title'].lower()}",
                        "severity": "medium", "category": "growth", "evidence": s["evidence"], "period": q["latest"],
                        "implication": "One quarter can be noisy; check management commentary for one-offs before "
                                       "reading a trend into it.",
                        "rule": "Quarterly like-for-like decline beyond threshold"})
    return out
