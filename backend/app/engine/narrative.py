"""Deterministic, rule-based write-up of the analysis (no LLM, no paid API).

Every sentence is generated from computed numbers so it can be traced back to a metric.
"""
from __future__ import annotations

from typing import Any, Optional

from ..markets import money
from .formulas import is_num


def _p(x: Optional[float], d: int = 1) -> str:
    return "n/a" if not is_num(x) else f"{x:.{d}f}%"


def _x(x: Optional[float], d: int = 2) -> str:
    return "n/a" if not is_num(x) else f"{x:.{d}f}×"


def _v(d: Any) -> Optional[float]:
    if isinstance(d, dict):
        d = d.get("value")
    return d if is_num(d) else None


def build_narrative(name: str, metrics: dict[str, Any], val: dict[str, Any], scores: dict[str, Any],
                    flags: list[dict[str, Any]], currency: str | None = None) -> dict[str, Any]:
    L, G = metrics["latest"], metrics["growth"]
    fin = metrics["is_financial"]
    lbl = metrics["annual"]["labels"]
    last = lbl[-1] if lbl else "the latest year"
    V = scores["verdicts"]
    sections = []

    # Answers to the ten guiding questions
    def cagr_pick(base):
        for k in (f"{base}_3y", f"{base}_max"):
            if _v(G.get(k)) is not None:
                return _v(G[k]), G[k]["period"]
        return None, None

    rc, rp = cagr_pick("revenue_cagr")
    ec, ep = cagr_pick("eps_cagr")
    q = []
    bq = V["business_quality"]
    q.append({"q": "Is this company financially healthy?",
              "a": f"Business quality is rated {bq['label'].lower()}"
                   + (f" ({bq['score']:.0f}/100)" if bq["score"] is not None else "")
                   + f" and financial risk is {V['financial_risk']['label'].lower()}"
                   + (f" ({V['financial_risk']['score']:.0f}/100, higher = riskier)." if V['financial_risk']['score'] is not None else ".")})
    if fin:
        nc, npd = cagr_pick("nii_cagr")
        q.append({"q": "Is its business growing consistently?",
                  "a": f"Net interest income grew {_p(nc)} a year ({npd or 'period n/a'}); loan growth in {last} was "
                       f"{_p(_v(L.get('loan_growth')))}."})
    else:
        cons = metrics["revenue_consistency"]
        q.append({"q": "Is its business growing consistently?",
                  "a": f"Revenue grew {_p(rc)} a year ({rp or 'period n/a'})."
                       + (f" Revenue fell in {cons['declines']} of {cons['n']} years; yearly growth varied by "
                          f"±{cons['stdev']:.1f} pp." if cons.get("stdev") is not None else " Too few years to judge consistency.")})
    ni_g = _v(L.get("net_income_growth"))
    q.append({"q": "Is it profitable, and are profits improving?",
              "a": f"Net margin was {_p(_v(L.get('net_margin')))} in {last}, with ROE of {_p(_v(L.get('roe')))}. "
                   f"Net profit changed {_p(ni_g)} year on year; EPS compounded at {_p(ec)} ({ep or 'n/a'})."
                   + (" Profit grew faster than revenue, so margins expanded." if (is_num(ec) and is_num(rc) and ec > rc + 2) else
                      " Profit grew slower than revenue: margins compressed, or the share count rose." if (is_num(ec) and is_num(rc) and ec < rc - 2) else "")})
    if fin:
        inp = scores.get("inputs", {})
        car, gnpa, nnpa = (_v(inp.get(k)) for k in ("car", "gnpa", "nnpa"))
        bank_bits = []
        if car is not None:
            bank_bits.append(f"capital adequacy {_p(car, 2)}")
        if gnpa is not None:
            bank_bits.append(f"gross NPA {_p(gnpa, 2)}")
        if nnpa is not None:
            bank_bits.append(f"net NPA {_p(nnpa, 2)}")
        q.append({"q": "Is its debt manageable?",
                  "a": "For lenders, borrowing is the business model, so debt-to-equity is not used. "
                       + (f"From the figures you entered: {', '.join(bank_bits)}. " if bank_bits else
                          "Capital adequacy and NPAs are not in the free data; enter them on the Management & "
                          "shareholding tab. ")
                       + f"Equity was {_p(_v(L.get('equity_to_assets')))} of assets (a crude leverage proxy)."})
    else:
        nd = _v(L.get("net_debt"))
        q.append({"q": "Is its debt manageable?",
                  "a": ("The company has net cash (more cash than debt). " if is_num(nd) and nd < 0 else "")
                       + f"Debt-to-equity {_x(_v(L.get('debt_to_equity')))}, net debt/EBITDA "
                         f"{_x(_v(L.get('net_debt_to_ebitda')), 1)}, interest coverage "
                         f"{_x(_v(L.get('interest_coverage')), 1) if _v(L.get('interest_coverage')) else 'not meaningful (no material interest)'}."})
    fv = val.get("fair_value") or {}
    m = val.get("multiples") or {}
    q.append({"q": "Is the stock reasonably valued?",
              "a": f"{fv.get('label', 'Cannot reliably assess')}. P/E {_x(_v(m.get('pe')), 1)}, P/B {_x(_v(m.get('pb')), 1)}"
                   + ("" if fin else f", EV/EBITDA {_x(_v(m.get('ev_ebitda')), 1)}")
                   + (f". Estimated range {money(fv['low'], currency, 0)}–{money(fv['high'], currency, 0)} from {fv['n_methods']} methods"
                      f"{' (wide: methods disagree)' if fv.get('wide') else ''}." if fv.get("low") else ".")})
    hi = [f for f in flags if f["severity"] == "high"]
    q.append({"q": "What are the major risks and warning signs?",
              "a": (f"{len(flags)} automated warning(s), {len(hi)} high severity: "
                    + "; ".join(f["title"].lower() for f in flags[:4]) + ".") if flags else
                   "No automated red flags were triggered by the available data. That is not proof of absence; "
                   "governance items need checking in filings."})
    pos = [p["label"] for p in scores["positives"][:3]]
    neg = [n["label"] for n in scores["negatives"][:3]]
    q.append({"q": "What would make it attractive or unattractive?",
              "a": ("Strengths: " + "; ".join(pos) + ". " if pos else "")
                   + ("Weaknesses: " + "; ".join(neg) + "." if neg else "")})
    missing = [it["label"] for c in scores["categories"].values() for it in c.get("items", [])
               if it["score"] is None][:6]
    q.append({"q": "What important information is missing or uncertain?",
              "a": f"Data completeness is {scores['data_completeness']:.0f}% and confidence is "
                   f"{scores['confidence']['label'].lower()}. Not available: " + "; ".join(missing) + "." if missing else
                   f"Data completeness is {scores['data_completeness']:.0f}%."})
    price = _v(m.get("price"))
    cond = []
    if fv.get("low") and price:
        cond.append(f"a price nearer the low end of the estimated range (≈{money(fv['low'], currency, 0)}, "
                    f"{(fv['low'] / price - 1) * 100:+.0f}% from today)")
    if not fin and is_num(_v(L.get("debt_to_equity"))) and _v(L.get("debt_to_equity")) > 1:
        cond.append("debt reduction to below 1× equity")
    if any(f["id"] in ("profit_cash_gap", "negative_fcf") for f in flags):
        cond.append("operating cash flow that consistently matches reported profit")
    if any(f["id"] == "margin_decline" for f in flags):
        cond.append("stabilising margins")
    q.append({"q": "What would make the investment more attractive?",
              "a": ("Conditions that would improve the risk/reward: " + "; ".join(cond) + ".") if cond else
                   "Key watch-points: sustained growth at current margins and valuation staying within its historical band."})

    summary = (f"{name}: {scores['decision_label']}. Business quality {bq['label'].lower()}, financial risk "
               f"{V['financial_risk']['label'].lower()}, valuation: {V['valuation']['label'].lower()}. "
               f"Confidence {scores['confidence']['label'].lower()}.")
    sections.append({"title": "Answers to key questions", "qa": q})
    return {"summary": summary, "sections": sections,
            "method": "Generated by fixed rules from the computed metrics (no language model). Every statement maps "
                      "to a number on the other tabs.",
            "disclaimer": "Research and decision support only, not investment advice or a recommendation to buy or "
                          "sell. Algorithmic signals can be wrong; verify against company filings."}
