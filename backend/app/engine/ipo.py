"""IPO evaluation from figures the user enters from the RHP/DRHP (or the sample IPO).

Units: amounts in ₹ crore (as RHPs present them), prices in ₹ per share, share counts absolute.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from . import formulas as F
from .formulas import is_num

CR = 1e7


def _n(x: Any) -> Optional[float]:
    try:
        return float(x) if x is not None and x != "" and is_num(float(x)) else None
    except (TypeError, ValueError):
        return None


def _label_score(s: Optional[float], risk: bool = False) -> Optional[str]:
    if s is None:
        return None
    if risk:
        return "Low" if s < 25 else "Moderate" if s < 45 else "Elevated" if s < 65 else "High"
    return "Strong" if s >= 75 else "Good" if s >= 60 else "Average" if s >= 45 else "Weak" if s >= 30 else "Poor"


def _assess(items: list[tuple[str, Optional[float], list[tuple[float, float]], float, str]], risk: bool = False) -> dict[str, Any]:
    """items: (label, input, points, weight, display)."""
    acc = w_av = w_all = 0.0
    rows = []
    for label, x, pts, w, disp in items:
        w_all += w
        s = F.lerp_score(x, pts) if x is not None else None
        if s is not None:
            acc += s * w
            w_av += w
        rows.append({"label": label, "input": x, "display": disp, "score": s, "weight": w})
    score = acc / w_av if w_av else None
    completeness = w_av / w_all if w_all else 0
    if completeness < 0.4:
        score = None
    return {"score": score, "label": _label_score(score, risk) or "Insufficient evidence", "completeness": completeness,
            "items": rows, "higher_is_riskier": risk}


def analyse_ipo(p: dict[str, Any], peers: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[str] = []
    lo, hi = _n(p.get("price_band_low")), _n(p.get("price_band_high"))
    price = hi or lo
    fresh_cr, ofs_cr = _n(p.get("fresh_issue_cr")) or 0.0, _n(p.get("ofs_cr")) or 0.0
    issue_cr = fresh_cr + ofs_cr
    pre_shares = _n(p.get("pre_issue_shares"))
    fin = sorted(p.get("financials") or [], key=lambda r: r.get("fy", ""))
    latest = fin[-1] if fin else {}

    structure: dict[str, Any] = {"issue_size_cr": issue_cr, "fresh_issue_cr": fresh_cr, "ofs_cr": ofs_cr,
                                 "fresh_pct": fresh_cr / issue_cr * 100 if issue_cr else None,
                                 "ofs_pct": ofs_cr / issue_cr * 100 if issue_cr else None,
                                 "explanation": "Fresh issue money goes to the company (new shares, dilutes existing "
                                                "holders). Offer-for-sale money goes to the selling shareholders, "
                                                "not the company."}
    if not price or not pre_shares:
        return {"error": "Price band and pre-issue share count are required to value the IPO.", "structure": structure}

    fresh_shares = fresh_cr * CR / price
    post_shares = _n(p.get("post_issue_shares")) or (pre_shares + fresh_shares)
    if _n(p.get("post_issue_shares")):
        implied = pre_shares + fresh_shares
        if abs(implied / post_shares - 1) > 0.02:
            warnings.append(f"Entered post-issue shares differ {abs(implied/post_shares-1)*100:.1f}% from pre-issue + "
                            "fresh-issue shares at the upper band (check the RHP, e.g. pre-IPO placement or employee quota).")
    mcap_cr = post_shares * price / CR
    mcap_lo_cr = (pre_shares + fresh_cr * CR / lo) * lo / CR if lo else None
    structure.update({"price_used": price, "price_band": [lo, hi], "fresh_shares": fresh_shares,
                      "ofs_shares": ofs_cr * CR / price, "pre_issue_shares": pre_shares, "post_issue_shares": post_shares,
                      "dilution_pct": fresh_shares / pre_shares * 100,
                      "post_issue_mcap_cr": mcap_cr, "post_issue_mcap_cr_lower_band": mcap_lo_cr,
                      "lot_size": _n(p.get("lot_size")),
                      "min_investment": (_n(p.get("lot_size")) or 0) * price if p.get("lot_size") else None})

    # Financial history metrics
    hist = []
    for i, r in enumerate(fin):
        rev, ebitda, pat, nw = (_n(r.get(k)) for k in ("revenue_cr", "ebitda_cr", "pat_cr", "net_worth_cr"))
        debt, cfo, capex = (_n(r.get(k)) for k in ("borrowings_cr", "cfo_cr", "capex_cr"))
        prev = fin[i - 1] if i else None
        hist.append({
            "fy": r.get("fy"), "revenue_cr": rev, "ebitda_cr": ebitda, "pat_cr": pat, "net_worth_cr": nw,
            "borrowings_cr": debt, "cfo_cr": cfo, "capex_cr": capex,
            "revenue_growth": F.growth(rev, _n(prev.get("revenue_cr"))).value if prev else None,
            "pat_growth": F.growth(pat, _n(prev.get("pat_cr"))).value if prev else None,
            "ebitda_margin": F.pct(ebitda, rev).value, "pat_margin": F.pct(pat, rev).value,
            "ronw": F.pct(pat, nw).value, "debt_to_equity": F.ratio(debt, nw).value,
            "cfo_to_pat": F.ratio(cfo, pat).value,
            "fcf_cr": (cfo - capex) if (cfo is not None and capex is not None) else None,
        })
    yrs = len(fin) - 1
    rev_cagr = F.cagr(_n(fin[0].get("revenue_cr")), _n(latest.get("revenue_cr")), yrs).value if yrs >= 1 else None
    pat_cagr = F.cagr(_n(fin[0].get("pat_cr")), _n(latest.get("pat_cr")), yrs).value if yrs >= 1 else None

    pat, ebitda, rev = _n(latest.get("pat_cr")), _n(latest.get("ebitda_cr")), _n(latest.get("revenue_cr"))
    nw, debt = _n(latest.get("net_worth_cr")), _n(latest.get("borrowings_cr"))
    cash = _n(p.get("cash_cr")) or 0.0
    post_nw = (nw + fresh_cr) if nw is not None else None
    ev_post = mcap_cr + (debt or 0) - cash - fresh_cr
    val = {
        "eps_pre": (pat * CR / pre_shares) if pat is not None else None,
        "eps_post": (pat * CR / post_shares) if pat is not None else None,
        "pe_post": F.ratio(mcap_cr, pat, name="P/E").value,
        "pe_pre": F.ratio(pre_shares * price / CR, pat, name="P/E").value,
        "pb_post": F.ratio(mcap_cr, post_nw, name="P/B").value,
        "ev_ebitda": F.ratio(ev_post, ebitda, name="EV/EBITDA").value,
        "ps": F.ratio(mcap_cr, rev, name="P/S").value,
        "ev_post_cr": ev_post,
        "post_issue_net_worth_cr": post_nw,
        "notes": ["P/E (post-issue) = post-issue market cap ÷ latest-FY PAT, the comparable basis for listed peers.",
                  "P/E (pre-issue) uses pre-issue shares, which is how some RHPs present it; it flatters the multiple.",
                  "Post-issue net worth ≈ latest net worth + fresh issue (issue expenses ignored).",
                  "EV assumes fresh-issue proceeds are held as cash until deployed."],
    }

    # Peers: from listed symbols (provider ratios) + manual entries
    allp = list(peers) + [dict(m, source="user-entered") for m in (p.get("manual_peers") or [])]
    def med(k):
        vals = [x.get(k) for x in allp if is_num(x.get(k)) and x.get(k) > 0]
        return F.median(vals), F.percentile(vals, 25), F.percentile(vals, 75), len(vals)
    pe_med, pe_p25, pe_p75, n_pe = med("pe")
    ev_med, _, _, n_ev = med("ev_ebitda")
    pb_med, _, _, n_pb = med("pb")
    roe_med, _, _, _ = med("roe")
    peer_cmp = {"peers": allp, "pe_median": pe_med, "pe_p25": pe_p25, "pe_p75": pe_p75, "n_pe": n_pe,
                "ev_ebitda_median": ev_med, "pb_median": pb_med, "roe_median": roe_med,
                "pe_premium_pct": (val["pe_post"] / pe_med - 1) * 100 if (val["pe_post"] and pe_med) else None,
                "ev_ebitda_premium_pct": (val["ev_ebitda"] / ev_med - 1) * 100 if (val["ev_ebitda"] and ev_med) else None}

    # Scenarios
    scenarios = []
    so = p.get("scenario_overrides") or {}
    g_hist = pat_cagr if pat_cagr is not None else (rev_cagr if rev_cagr is not None else 0.0)
    if pat is not None and pat > 0 and pe_med and n_pe >= 2:
        defs = [
            ("Conservative", max(0.0, min(g_hist, 25.0)) * 0.5, (pe_p25 or pe_med) * 0.85,
             "half of historical PAT growth (capped at 25%); peer 25th-percentile P/E less a 15% new-listing discount"),
            ("Base case", max(0.0, min(g_hist, 25.0)) * 0.8, pe_med * 0.95,
             "80% of historical PAT growth (capped at 25%); peer median P/E less a 5% discount"),
            ("Optimistic", max(0.0, min(g_hist, 35.0)), pe_p75 or pe_med,
             "historical PAT growth continues (capped at 35%); peer 75th-percentile P/E"),
        ]
        for name, g, mult, why in defs:
            o = so.get(name.lower().split()[0], {})
            g = _n(o.get("growth")) if _n(o.get("growth")) is not None else g
            mult = _n(o.get("pe")) if _n(o.get("pe")) is not None else mult
            fwd_pat = pat * (1 + g / 100)
            v = fwd_pat * CR * mult / post_shares
            scenarios.append({"name": name, "pat_growth_pct": g, "pe_multiple": mult, "forward_pat_cr": fwd_pat,
                              "value_per_share": v, "vs_issue_price_pct": (v / price - 1) * 100, "assumptions": why})
    else:
        warnings.append("Scenarios need positive PAT and at least 2 peer P/E multiples (listed peers or manual entries).")

    # Assessments
    conc = _n(p.get("top_customer_concentration_pct"))
    margins = [h["ebitda_margin"] for h in hist if h["ebitda_margin"] is not None]
    margin_trend = (margins[-1] - margins[0]) if len(margins) >= 2 else None
    business = _assess([
        ("Revenue CAGR", rev_cagr, [(-5, 0), (0, 20), (10, 55), (20, 80), (30, 100)], 30, "%"),
        ("PAT margin (latest)", hist[-1]["pat_margin"] if hist else None, [(0, 0), (4, 30), (8, 55), (12, 75), (20, 100)], 20, "%"),
        ("RoNW (latest)", hist[-1]["ronw"] if hist else None, [(0, 0), (8, 30), (12, 50), (18, 75), (25, 100)], 25, "%"),
        ("EBITDA-margin change over the period", margin_trend, [(-5, 0), (-2, 30), (0, 55), (2, 75), (5, 100)], 10, "pp"),
        ("Customer concentration (top customers %)", conc, [(10, 100), (30, 70), (50, 40), (75, 10)], 15, "%"),
    ])
    cfo_pat = [h["cfo_to_pat"] for h in hist if h["cfo_to_pat"] is not None]
    fcfs = [h["fcf_cr"] for h in hist if h["fcf_cr"] is not None]
    post_de = F.ratio(debt, post_nw).value if post_nw else None
    financial = _assess([
        ("Debt / equity (post-issue)", post_de, [(0, 100), (0.3, 85), (0.6, 65), (1.0, 45), (2.0, 15)], 30, "×"),
        ("Avg CFO / PAT", sum(cfo_pat) / len(cfo_pat) if cfo_pat else None, [(0, 0), (0.5, 25), (0.8, 55), (1.0, 80), (1.2, 100)], 35, "×"),
        ("Share of years with positive FCF", sum(1 for x in fcfs if x > 0) / len(fcfs) if fcfs else None,
         [(0, 0), (0.34, 35), (0.67, 65), (1, 100)], 20, "share"),
        ("PAT CAGR", pat_cagr, [(-10, 0), (0, 25), (10, 55), (20, 80), (30, 100)], 15, "%"),
    ])
    base = next((s for s in scenarios if s["name"] == "Base case"), None)
    valuation = _assess([
        ("P/E premium vs peer median", peer_cmp["pe_premium_pct"], [(-40, 95), (-20, 75), (0, 55), (20, 35), (50, 10), (100, 0)], 40, "%"),
        ("EV/EBITDA premium vs peer median", peer_cmp["ev_ebitda_premium_pct"], [(-40, 95), (-20, 75), (0, 55), (20, 35), (50, 10)], 25, "%"),
        ("Base-case value vs upper band", base["vs_issue_price_pct"] if base else None, [(-40, 0), (-15, 25), (0, 50), (15, 75), (40, 100)], 35, "%"),
    ])
    contingent = _n(p.get("contingent_liabilities_cr"))
    pre_p, post_p = _n(p.get("promoter_pre_pct")), _n(p.get("promoter_post_pct"))
    n_risk = len(p.get("risk_factors") or [])
    governance = _assess([
        ("Contingent liabilities as % of net worth", F.pct(contingent, nw).value if contingent is not None else None,
         [(0, 0), (5, 15), (15, 40), (30, 70), (60, 100)], 35, "%"),
        ("Litigation disclosed (user notes)", 1.0 if (p.get("litigation_notes") or "").strip() else (0.0 if "litigation_notes" in p else None),
         [(0, 10), (1, 50)], 25, "flag"),
        ("Post-issue promoter holding", post_p, [(30, 70), (50, 35), (70, 15), (75, 10)], 25, "%"),
        ("Risk factors entered", float(n_risk) if p.get("risk_factors") is not None else None, [(0, 20), (5, 40), (15, 60)], 15, "count"),
    ], risk=True)
    gcp = sum(_n(u.get("amount_cr")) or 0 for u in (p.get("use_of_proceeds") or [])
              if "general corporate" in (u.get("purpose") or "").lower())
    sub = p.get("subscription") or {}
    gmp = p.get("gmp") or {}
    ipo_risk = _assess([
        ("OFS share of issue", structure["ofs_pct"], [(0, 5), (30, 30), (50, 50), (75, 75), (100, 90)], 30, "%"),
        ("Promoter stake sold in IPO (pp)", (pre_p - post_p) if (pre_p is not None and post_p is not None) else None,
         [(0, 5), (5, 25), (15, 55), (25, 80)], 20, "pp"),
        ("General corporate purposes as % of fresh issue", (gcp / fresh_cr * 100) if fresh_cr else None,
         [(0, 5), (10, 20), (25, 60), (35, 90)], 15, "%"),
        ("P/E premium vs peers", peer_cmp["pe_premium_pct"], [(-30, 5), (0, 30), (30, 60), (80, 90)], 20, "%"),
        ("Subscription frenzy (overall ×)", _n(sub.get("total")), [(1, 10), (20, 30), (50, 55), (150, 75)], 15, "×"),
    ], risk=True)

    # Lock-ins (approximate; SEBI ICDR rules as of 2022+)
    lockins = []
    ld = p.get("listing_date")
    try:
        allot = date.fromisoformat(ld) - timedelta(days=1) if ld else None
    except ValueError:
        allot = None
    if allot:
        lockins = [
            {"who": "Anchor investors (50%)", "date": (allot + timedelta(days=30)).isoformat()},
            {"who": "Anchor investors (remaining 50%)", "date": (allot + timedelta(days=90)).isoformat()},
            {"who": "Pre-IPO non-promoter shareholders / promoter excess holding", "date": (allot + timedelta(days=182)).isoformat()},
            {"who": "Promoters' minimum contribution (20% of post-issue capital)", "date": (allot + timedelta(days=548)).isoformat()},
        ]
    for k in ("anchor_lockin_50_date", "anchor_lockin_100_date"):
        if p.get(k):
            lockins.insert(0, {"who": "From RHP/allotment notice: " + k.replace("_", " "), "date": p[k], "user_entered": True})

    if ofs_cr > fresh_cr:
        warnings.append("Most of the issue is an offer-for-sale: the majority of the money goes to selling shareholders, "
                        "not into the business.")
    if fresh_cr and gcp / fresh_cr > 0.25:
        warnings.append("General corporate purposes exceed 25% of the fresh issue (SEBI's cap is 25% of gross proceeds). "
                        "Check the RHP's objects of the issue.")
    if _n(sub.get("total")) or _n(gmp.get("value")):
        warnings.append("Subscription levels and grey-market premium reflect short-term demand, not business value. "
                        "They are not reasons to invest.")
    if conc is not None and conc > 50:
        warnings.append(f"High customer concentration ({conc:.0f}%): losing a key customer would hurt revenue materially.")

    return {
        "structure": structure, "history": hist, "rev_cagr": rev_cagr, "pat_cagr": pat_cagr,
        "cagr_period": f"{fin[0].get('fy')} → {latest.get('fy')} ({yrs} yrs)" if yrs >= 1 else None,
        "valuation": val, "peers": peer_cmp, "scenarios": scenarios,
        "assessments": {"business_quality": business, "financial_strength": financial, "valuation_attractiveness": valuation,
                        "governance_disclosure_risk": governance, "ipo_specific_risk": ipo_risk},
        "use_of_proceeds": p.get("use_of_proceeds") or [], "gcp_cr": gcp,
        "subscription": sub, "gmp": {**gmp, "label": "UNOFFICIAL and speculative: grey-market quotes are unregulated "
                                                    "and not a measure of value."} if gmp else None,
        "lockins": lockins,
        "lockin_note": "Approximate dates from SEBI ICDR lock-in periods counted from an estimated allotment date "
                       "(listing − 1 day). Confirm against the RHP and basis-of-allotment document.",
        "warnings": warnings,
        "risk_factors": p.get("risk_factors") or [],
    }
