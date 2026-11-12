"""Rule-based APPLY / BORDERLINE / SKIP suggestion for an IPO.

It answers one narrow question: judged on the business, its finances, the price asked relative to
listed peers, and governance/issue risks, does this IPO look worth applying to for a long-term holder?
It deliberately ignores subscription levels and grey-market premium (listing-day speculation), and it
knows nothing about the user's finances, so it is a screen to inform a decision, not advice.

Every rule that fires is reported, so the suggestion can always be traced back to its reasons.
"""
from __future__ import annotations

from typing import Any, Optional

from .formulas import is_num

# Weights of the five IPO assessments in the decision score (risk assessments are inverted).
WEIGHTS = {"business_quality": 0.30, "financial_strength": 0.25, "valuation_attractiveness": 0.30, "risk": 0.15}
APPLY_MIN_SCORE = 62.0
APPLY_MIN_VALUATION = 55.0
APPLY_MIN_BASE_UPSIDE = 10.0  # % margin of safety vs upper band in the base-case scenario
SKIP_MAX_SCORE = 45.0
APPLY_MAX_SERIOUS = 1  # serious issue-structure / concentration concerns tolerated for an APPLY


def _s(a: dict[str, Any], k: str) -> Optional[float]:
    v = (a.get(k) or {}).get("score")
    return float(v) if is_num(v) else None


def decide(analysis: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if analysis.get("error"):
        return _insufficient([analysis["error"]])
    A = analysis["assessments"]
    hist = analysis.get("history") or []
    s = analysis["structure"]
    peers = analysis.get("peers") or {}
    scen = {x["name"]: x for x in analysis.get("scenarios") or []}
    base = scen.get("Base case")

    missing = []
    if not hist or not is_num(hist[-1].get("pat_cr")) or not is_num(hist[-1].get("revenue_cr")):
        missing.append("restated financials (revenue and profit for at least the latest fiscal year)")
    if missing:
        return _insufficient(missing)

    latest = hist[-1]
    for_, against, breakers, conditions = [], [], [], []
    serious: list[str] = []  # concerns that individually do not force SKIP but together rule out APPLY

    bq, fs, va = _s(A, "business_quality"), _s(A, "financial_strength"), _s(A, "valuation_attractiveness")
    gov, ipo_risk = _s(A, "governance_disclosure_risk"), _s(A, "ipo_specific_risk")
    risk_vals = [v for v in (gov, ipo_risk) if v is not None]
    risk_ok = 100 - sum(risk_vals) / len(risk_vals) if risk_vals else None
    parts = {"business_quality": bq, "financial_strength": fs, "valuation_attractiveness": va, "risk": risk_ok}
    w_av = sum(WEIGHTS[k] for k, v in parts.items() if v is not None)
    score = sum(WEIGHTS[k] * v for k, v in parts.items() if v is not None) / w_av if w_av else None

    # ---- deal-breakers (any one forces SKIP) ----
    pat = latest.get("pat_cr")
    if pat is not None and pat <= 0:
        breakers.append(f"Loss-making in the latest year (PAT ₹{pat:,.0f} Cr): the price is not supported by earnings.")
    cfo_neg = sum(1 for h in hist[-3:] if is_num(h.get("cfo_cr")) and h["cfo_cr"] < 0)
    if cfo_neg >= 2:
        breakers.append(f"Operating cash flow was negative in {cfo_neg} of the last {len(hist[-3:])} years.")
    prem = peers.get("pe_premium_pct")
    if is_num(prem) and prem > 60:
        breakers.append(f"Priced at a {prem:.0f}% P/E premium to the listed-peer median.")
    if base and base["vs_issue_price_pct"] < -15:
        breakers.append(f"Even the base-case scenario values the share {abs(base['vs_issue_price_pct']):.0f}% below the upper band.")
    if gov is not None and gov >= 65:
        breakers.append("Governance and disclosure risk is high (litigation, contingent liabilities or low promoter commitment).")
    nw = latest.get("net_worth_cr")
    cont = payload.get("contingent_liabilities_cr")
    if is_num(cont) and is_num(nw) and nw > 0 and cont / nw > 0.5:
        breakers.append(f"Contingent liabilities are {cont / nw * 100:.0f}% of net worth.")

    # ---- evidence for / against ----
    def judge(v, label, good, bad):
        if v is None:
            return
        if v >= good:
            for_.append(f"{label} scores {v:.0f}/100.")
        elif v < bad:
            against.append(f"{label} scores only {v:.0f}/100.")
    judge(bq, "Business quality", 65, 45)
    judge(fs, "Financial strength", 65, 45)
    judge(va, "Valuation attractiveness", 60, 45)
    pe_post = analysis["valuation"].get("pe_post")
    if is_num(prem) and is_num(pe_post):
        msg = (f"P/E of {pe_post:.1f}× (post-issue) is {abs(prem):.0f}% {'below' if prem < 0 else 'above'} the "
               f"listed-peer median of {peers['pe_median']:.1f}×.")
        (for_ if prem <= 0 else against).append(msg)
    if base:
        (for_ if base["vs_issue_price_pct"] >= APPLY_MIN_BASE_UPSIDE else against).append(
            f"Base-case value ₹{base['value_per_share']:,.0f} is {base['vs_issue_price_pct']:+.0f}% vs the upper band "
            f"₹{s['price_band'][1]:,.0f}.")
    if is_num(s.get("ofs_pct")) and s["ofs_pct"] >= 50:
        against.append(f"{s['ofs_pct']:.0f}% of the issue is an offer for sale: that money goes to selling shareholders, not the business.")
        serious.append("offer-for-sale heavy")
    elif is_num(s.get("fresh_pct")) and s["fresh_pct"] >= 70:
        for_.append(f"{s['fresh_pct']:.0f}% of the issue is fresh capital going into the company.")
    pre, post = payload.get("promoter_pre_pct"), payload.get("promoter_post_pct")
    if is_num(post) and post < 35:
        against.append(f"Promoters will hold only {post:.0f}% after the issue.")
        serious.append("low promoter holding")
    if is_num(pre) and is_num(post) and pre - post > 20:
        against.append(f"Promoters are reducing their stake by {pre - post:.0f} percentage points in this issue.")
        serious.append("large promoter stake sale")
    conc = payload.get("top_customer_concentration_pct")
    if is_num(conc) and conc > 50:
        against.append(f"Top customers account for {conc:.0f}% of revenue (concentration risk).")
        serious.append("customer concentration")
    gcp = analysis.get("gcp_cr") or 0
    fresh = s.get("fresh_issue_cr") or 0
    if fresh and gcp / fresh > 0.25:
        against.append("General corporate purposes exceed 25% of the fresh issue, so the use of funds is vague.")
        serious.append("vague use of funds")
    g = analysis.get("rev_cagr")
    if is_num(g):
        if g >= 15:
            for_.append(f"Revenue grew {g:.1f}% a year ({analysis.get('cagr_period')}).")
        elif g < 5:
            against.append(f"Revenue grew only {g:.1f}% a year ({analysis.get('cagr_period')}).")

    no_peers = not is_num(peers.get("pe_median"))
    if no_peers:
        against.append("No peer multiples were available, so the price cannot be judged against listed companies.")

    # ---- the suggestion ----
    if breakers:
        verdict = "SKIP"
    elif score is None:
        return _insufficient(["assessment scores"])
    elif (score >= APPLY_MIN_SCORE and (va or 0) >= APPLY_MIN_VALUATION and base
          and base["vs_issue_price_pct"] >= APPLY_MIN_BASE_UPSIDE and not no_peers and len(serious) <= APPLY_MAX_SERIOUS):
        verdict = "APPLY"
    elif score < SKIP_MAX_SCORE:
        verdict = "SKIP"
    else:
        verdict = "BORDERLINE"

    # Price at which the base case would offer a 10% margin of safety
    entry_price = None
    if base and base.get("value_per_share"):
        entry_price = base["value_per_share"] / (1 + APPLY_MIN_BASE_UPSIDE / 100)
        if verdict != "APPLY":
            if entry_price < s["price_band"][1]:
                conditions.append(f"A price at or below about ₹{entry_price:,.0f} (vs the ₹{s['price_band'][1]:,.0f} upper band) "
                                  "would give the base case a 10% margin of safety. Consider watching the stock after "
                                  "listing instead of applying.")
        if verdict == "BORDERLINE" and len(serious) > APPLY_MAX_SERIOUS:
            conditions.append(f"Several structural concerns together ({', '.join(serious)}) keep this from an APPLY even "
                              "though the overall score is reasonable.")
        if verdict == "BORDERLINE":
            conditions.append("Apply only if you are comfortable with the risks listed and plan to hold for several years; "
                              "otherwise waiting for one or two quarters of listed results costs little.")
    if no_peers:
        conditions.append("Add listed peers (symbols or multiples from the RHP's ‘Basis for Offer Price’ table) to judge valuation.")

    labels = {"APPLY": "Lean towards APPLYING", "BORDERLINE": "BORDERLINE: apply only with conviction",
              "SKIP": "Lean towards SKIPPING"}
    return {
        "verdict": verdict,
        "label": labels[verdict],
        "score": score,
        "components": parts,
        "reasons_for": for_,
        "reasons_against": against,
        "deal_breakers": breakers,
        "conditions": conditions,
        "fair_entry_price": entry_price,
        "serious_concerns": serious,
        "rules": {
            "apply": f"decision score ≥ {APPLY_MIN_SCORE:.0f}, valuation ≥ {APPLY_MIN_VALUATION:.0f}, base-case value ≥ "
                     f"{APPLY_MIN_BASE_UPSIDE:.0f}% above the upper band, peer multiples available, at most "
                     f"{APPLY_MAX_SERIOUS} serious structural concern, and no deal-breaker",
            "skip": f"any deal-breaker, or decision score < {SKIP_MAX_SCORE:.0f}",
            "weights": "business quality 30%, financial strength 25%, valuation 30%, governance & IPO risk 15%",
        },
        "horizon_note": "Judged for long-term holding on fundamentals and price. Listing-day gains are not predicted: "
                        "subscription levels and GMP are excluded on purpose.",
        "disclaimer": "An algorithmic screen of the figures in the offer document, not personalised advice. It does not "
                      "know your goals, income, or other investments, and it cannot see risks the document does not "
                      "quantify. Read the RHP's risk factors before deciding.",
    }


def _insufficient(missing: list[str]) -> dict[str, Any]:
    return {"verdict": "INSUFFICIENT", "label": "Not enough data to suggest", "score": None, "reasons_for": [],
            "reasons_against": [], "deal_breakers": [], "missing": missing,
            "conditions": [f"Provide: {m}." for m in missing],
            "disclaimer": "No suggestion is made without the core figures."}
