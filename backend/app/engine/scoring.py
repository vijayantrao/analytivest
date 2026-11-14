"""Transparent scoring: category scores -> three verdicts + composite, completeness, confidence.

Rules:
- Missing inputs are *excluded* (their weight is dropped and completeness falls); never scored as zero.
- A category with completeness below ``min_category_completeness`` is reported as insufficient data.
- Every sub-score records its input, the thresholds used and the points awarded.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from . import formulas as F
from .formulas import is_num

CONFIG_PATH = Path(__file__).with_name("scoring_config.json")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def select_profile(cfg: dict[str, Any], profile: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    sector, industry = profile.get("sector") or "", profile.get("industry") or ""
    for name, p in cfg["profiles"].items():
        if name == "default":
            continue
        if sector in p.get("match_sectors", []) or industry in p.get("match_industries", []):
            return name, {**cfg["profiles"]["default"], **p}
    return "default", cfg["profiles"]["default"]


def _v(x: Any) -> Optional[float]:
    if isinstance(x, dict):
        x = x.get("value")
    return float(x) if is_num(x) else None


def _series(metrics: dict[str, Any], key: str) -> list[Optional[float]]:
    return [c["value"] for c in metrics["annual"]["series"].get(key, [])]


def _avg_last(vals: list[Optional[float]], n: int = 3) -> tuple[Optional[float], int]:
    v = [x for x in vals[-n:] if is_num(x)]
    return (sum(v) / len(v), len(v)) if v else (None, 0)


def _growth_pick(metrics: dict[str, Any], base: str) -> tuple[Optional[float], Optional[str]]:
    """3-yr CAGR, else the longest available; a CAGR distorted by a depressed base year is skipped
    (and if every option is distorted, the result is treated as missing rather than scored)."""
    g = metrics["growth"]
    for k in (f"{base}_3y", f"{base}_max"):
        if _v(g.get(k)) is not None and not g[k].get("base_effect"):
            return _v(g[k]), g[k].get("period")
    return None, None


def build_inputs(bundle: dict[str, Any], metrics: dict[str, Any], val: dict[str, Any], peers: list[dict[str, Any]],
                 notes: Optional[dict[str, Any]], profile_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """All scoring inputs: key -> {value, display, basis} (value None = missing, with reason)."""
    I: dict[str, dict[str, Any]] = {}
    labels = metrics["annual"]["labels"]

    def put(key, value, basis="", reason=None, unit=""):
        I[key] = {"value": value if is_num(value) else None, "basis": basis, "unit": unit,
                  "reason": reason if not is_num(value) else None}

    last = labels[-1] if labels else ""
    span3 = f"{labels[-3]}–{last}" if len(labels) >= 3 else (f"{labels[0]}–{last}" if labels else "")

    v, p = _growth_pick(metrics, "revenue_cagr"); put("revenue_cagr", v, p or "", "CAGR not computable", "%")
    v, p = _growth_pick(metrics, "eps_cagr"); put("eps_cagr", v, p or "", "EPS CAGR not computable (needs positive start/end EPS)", "%")
    v, p = _growth_pick(metrics, "nii_cagr"); put("nii_cagr", v, p or "", "NII not reported", "%")
    v, p = _growth_pick(metrics, "loans_cagr"); put("loans_cagr", v, p or "", "loan book not reported", "%")
    rc = metrics["revenue_consistency"]
    put("revenue_growth_stdev", rc.get("stdev"), f"{rc.get('n')} yearly growth rates", "needs ≥3 yearly growth rates", "pp")
    put("revenue_decline_years", rc.get("declines"), f"of {rc.get('n')} years", "needs ≥3 yearly growth rates", "years")
    ng = [x for x in _series(metrics, "net_income_growth") if is_num(x)]
    put("net_income_decline_years", sum(1 for x in ng if x < 0) if len(ng) >= 3 else None, f"of {len(ng)} years",
        "needs ≥3 yearly profit growth rates", "years")
    put("revenue_growth_latest", metrics["latest"].get("revenue_growth", {}).get("value"), last,
        metrics["latest"].get("revenue_growth", {}).get("reason"), "%")

    for key, src in (("roe_avg3", "roe"), ("roce_avg3", "roce"), ("roa_avg3", "roa"), ("fcf_margin_avg3", "fcf_margin")):
        a, n = _avg_last(_series(metrics, src))
        put(key, a, f"{n}-yr average to {last}", f"{src.upper()} not computable", "%")
    om = _series(metrics, "operating_margin")
    put("operating_margin_latest", om[-1] if om else None, last, "operating margin not available", "%")
    if len(om) >= 4 and all(is_num(x) for x in om[-4:]):
        put("operating_margin_trend", om[-1] - sum(om[-4:-1]) / 3, f"{last} vs prior 3-yr avg", unit="pp")
    else:
        put("operating_margin_trend", None, reason="needs 4 years of operating margin")
    put("nim_proxy", metrics["latest"].get("nim_proxy", {}).get("value"), last, "NII or assets missing", "%")
    put("equity_to_assets", metrics["latest"].get("equity_to_assets", {}).get("value"), last, "equity or assets missing", "%")
    # Bank asset quality and capital: not in free data, so read from user-entered facts
    # (typed in, or extracted from an uploaded annual report / results document and confirmed).
    nb = notes or {}
    for key, field, what in (("gnpa", "gnpa_pct", "Gross NPA"), ("nnpa", "nnpa_pct", "Net NPA"),
                             ("car", "car_pct", "capital adequacy (CAR)"), ("pcr", "pcr_pct", "provision coverage (PCR)")):
        put(key, nb.get(field), f"user-entered{', ' + nb['bank_as_of'] if nb.get('bank_as_of') else ''}",
            f"{what} is not available from the free provider; enter it on the Management & shareholding tab", "%")

    tol = profile_cfg.get("leverage_tolerance", 1.0)
    L = metrics["latest"]
    de = _v(L.get("debt_to_equity"))
    put("debt_to_equity", de / tol if de is not None else None, f"{last}; raw {de:.2f}×" if de is not None else last,
        L.get("debt_to_equity", {}).get("reason"), "×")
    nde = _v(L.get("net_debt_to_ebitda"))
    put("net_debt_to_ebitda", nde / tol if nde is not None else None, f"{last}; raw {nde:.2f}×" if nde is not None else last,
        L.get("net_debt_to_ebitda", {}).get("reason"), "×")
    ic = L.get("interest_coverage", {})
    if ic.get("value") is None and ic.get("status") == "not_meaningful" and "no material interest" in (ic.get("reason") or ""):
        put("interest_coverage", 100.0, f"{last}: no material interest expense (treated as very strong)", unit="×")
    else:
        put("interest_coverage", ic.get("value"), last, ic.get("reason"), "×")
    put("current_ratio", _v(L.get("current_ratio")), last, L.get("current_ratio", {}).get("reason"), "×")

    cfo, ni = _series(metrics, "cfo")[-3:], _series(metrics, "net_income")[-3:]
    if cfo and len(cfo) == len(ni) and all(is_num(x) for x in cfo + ni) and sum(ni) > 0:
        put("cash_conversion_3y", sum(cfo) / sum(ni), span3, unit="×")
    else:
        put("cash_conversion_3y", None, reason="needs 3 years of CFO and positive cumulative profit")
    fcf = [x for x in _series(metrics, "fcf")[-3:] if is_num(x)]
    put("fcf_positive_share", (sum(1 for x in fcf if x > 0) / len(fcf)) if len(fcf) >= 2 else None, span3,
        "needs ≥2 years of FCF", "share")
    rec = [p["fields"].get("receivables") for p in bundle.get("annual", [])]
    rev = [p["fields"].get("revenue") for p in bundle.get("annual", [])]
    if len(rec) >= 4 and all(is_num(x) and x > 0 for x in rec[-4:] + rev[-4:]):
        gap = (((rec[-1] / rec[-4]) ** (1 / 3) - 1) - ((rev[-1] / rev[-4]) ** (1 / 3) - 1)) * 100
        put("receivables_vs_sales_gap", gap, f"{labels[-4]}–{last}", unit="pp")
    else:
        put("receivables_vs_sales_gap", None, reason="needs 4 years of receivables and revenue")

    # Valuation inputs
    fv = val.get("fair_value") or {}
    put("upside_to_fair_mid", fv.get("upside_to_mid_pct"), f"{fv.get('n_methods', 0)} methods",
        fv.get("reason") or "fair-value range not available", "%")
    mult = val.get("multiples", {})
    med = (val.get("comps") or {}).get("medians", {})
    pe = _v(mult.get("pe"))
    pe_med = _v(med.get("pe"))
    put("pe_vs_peers", pe / pe_med if (pe and pe_med and pe > 0 and pe_med > 0) else None,
        f"P/E {pe:.1f}× vs median {pe_med:.1f}×" if (pe and pe_med) else "", "peer or own P/E not available", "×")
    pb, pb_med = _v(mult.get("pb")), _v(med.get("pb"))
    put("pb_vs_peers", pb / pb_med if (pb and pb_med and pb > 0 and pb_med > 0) else None,
        f"P/B {pb:.2f}× vs median {pb_med:.2f}×" if (pb and pb_med) else "", "peer or own P/B not available", "×")
    jpb = (val.get("justified_pb") or {}).get("justified_pb")
    put("pb_vs_justified", pb / jpb if (pb and jpb and jpb > 0) else None,
        f"P/B {pb:.2f}× vs justified {jpb:.2f}×" if (pb and jpb) else "", "justified P/B not applicable", "×")
    hist = (val.get("history") or {}).get("pe_band") or []
    if pe and pe > 0 and len(hist) >= 20:
        below = sum(1 for h in hist if h["pe"] <= pe)
        put("pe_history_percentile", below / len(hist) * 100, f"vs {len(hist)} weekly observations", unit="pctile")
    else:
        put("pe_history_percentile", None, reason="needs ≥20 weeks of positive-EPS P/E history")
    put("fcf_yield", _v(mult.get("fcf_yield")), last, (mult.get("fcf_yield") or {}).get("reason"), "%")
    put("peg", _v(mult.get("peg")), (mult.get("peg") or {}).get("basis", ""), (mult.get("peg") or {}).get("reason"), "×")

    # Governance
    sc = [p["fields"].get("shares_outstanding") for p in bundle.get("annual", [])]
    if len(sc) >= 4 and is_num(sc[-1]) and is_num(sc[-4]) and sc[-4] > 0:
        put("dilution_3y", max(0.0, (sc[-1] / sc[-4] - 1) * 100), f"{labels[-4]}–{last}, split-adjusted", unit="%")
    else:
        put("dilution_3y", None, reason="needs 4 years of share counts")
    n = notes or {}
    holders = bundle.get("holders") or {}
    promoter = n.get("promoter_holding_pct") if is_num(n.get("promoter_holding_pct")) else holders.get("insiders_pct")
    put("insider_holding", promoter, "user-entered promoter holding" if is_num(n.get("promoter_holding_pct"))
        else "provider 'insiders' % (for Indian companies, approximates the promoter group)", "not reported", "%")
    put("pledge_pct", n.get("promoter_pledge_pct"), "user-entered", "not available from free data; enter it from the "
        "shareholding pattern on the exchange website", "%")
    if "auditor_qualification" in n or "auditor_resigned" in n:
        put("auditor_clean", 0.0 if (n.get("auditor_qualification") or n.get("auditor_resigned")) else 1.0, "user-entered")
    else:
        put("auditor_clean", None, reason="not available from free data; enter it from the annual report")
    if "material_litigation" in n or "rpt_concern" in n:
        issues = int(bool(n.get("material_litigation"))) + int(bool(n.get("rpt_concern")))
        put("litigation_rpt_clean", {0: 1.0, 1: 0.5, 2: 0.0}[issues], "user-entered")
    else:
        put("litigation_rpt_clean", None, reason="not available from free data; enter it from the annual report")

    # Industry position (needs peers)
    mcap = val.get("market_cap")
    pm = [p.get("market_cap") for p in peers if is_num(p.get("market_cap"))]
    if mcap and len(pm) >= 3:
        smaller = sum(1 for x in pm if x < mcap)
        put("mcap_rank_pct", smaller / len(pm) * 100, f"vs {len(pm)} peers", unit="pctile")
    else:
        put("mcap_rank_pct", None, reason="needs ≥3 peers with market cap")
    nm_ = _v(L.get("net_margin"))
    pnm = F.median([p.get("net_margin") for p in peers if is_num(p.get("net_margin"))])
    put("net_margin_vs_peers", (nm_ - pnm) if (nm_ is not None and pnm is not None and len(peers) >= 3) else None,
        f"{nm_:.1f}% vs median {pnm:.1f}%" if (nm_ is not None and pnm is not None) else "", "needs ≥3 peers", "pp")
    rg = _v(L.get("revenue_growth"))
    prg = F.median([p.get("revenue_growth") for p in peers if is_num(p.get("revenue_growth"))])
    put("growth_vs_peers", (rg - prg) if (rg is not None and prg is not None and len(peers) >= 3) else None,
        "latest FY vs peers' latest reported growth", "needs ≥3 peers", "pp")
    roe = _v(L.get("roe"))
    proe = F.median([p.get("roe") for p in peers if is_num(p.get("roe"))])
    put("roe_vs_peers", (roe - proe) if (roe is not None and proe is not None and len(peers) >= 3) else None,
        f"{roe:.1f}% vs median {proe:.1f}%" if (roe is not None and proe is not None) else "", "needs ≥3 peers", "pp")
    return I


def _label(score: Optional[float], table: list[list[Any]]) -> Optional[str]:
    if score is None:
        return None
    for limit, name in table:
        if score < limit:
            return name
    return table[-1][1]


def score_category(rules: list[dict[str, Any]], inputs: dict[str, dict[str, Any]], min_completeness: float) -> dict[str, Any]:
    items, total_w, avail_w, acc = [], 0.0, 0.0, 0.0
    for r in rules:
        total_w += r["weight"]
        inp = inputs.get(r["key"], {"value": None, "reason": "not computed"})
        s = F.lerp_score(inp["value"], r["points"]) if inp["value"] is not None else None
        if s is not None:
            avail_w += r["weight"]
            acc += s * r["weight"]
        items.append({"key": r["key"], "label": r["label"], "weight": r["weight"], "input": inp["value"],
                      "unit": inp.get("unit"), "basis": inp.get("basis"), "score": s, "points": r["points"],
                      "reason": inp.get("reason") if s is None else None})
    completeness = avail_w / total_w if total_w else 0.0
    score = acc / avail_w if avail_w else None
    sufficient = score is not None and completeness >= min_completeness
    return {"score": score if sufficient else None, "raw_score": score, "completeness": completeness,
            "sufficient": sufficient, "items": items,
            "note": None if sufficient else f"Insufficient data: only {completeness*100:.0f}% of this category's "
                                            "inputs are available, so it is not scored."}


def _weighted(cats: dict[str, dict[str, Any]], weights: dict[str, float]) -> tuple[Optional[float], float]:
    acc, w_av, w_all = 0.0, 0.0, 0.0
    for k, w in weights.items():
        w_all += w
        s = cats.get(k, {}).get("score")
        if s is not None:
            acc += s * w
            w_av += w
    return (acc / w_av if w_av else None), (w_av / w_all if w_all else 0.0)


INDIA_ONLY_INPUTS = {"pledge_pct"}  # promoter pledging is an Indian (SEBI) disclosure


def score_company(bundle: dict[str, Any], metrics: dict[str, Any], val: dict[str, Any], flags: list[dict[str, Any]],
                  peers: list[dict[str, Any]], notes: Optional[dict[str, Any]], cfg: Optional[dict[str, Any]] = None,
                  market: str = "IN") -> dict[str, Any]:
    cfg = cfg or load_config()
    model = metrics["model"]
    profile_name, profile_cfg = select_profile(cfg, bundle.get("profile") or {})
    inputs = build_inputs(bundle, metrics, val, peers, notes, profile_cfg)
    rules = cfg["categories"][model]
    if market != "IN":  # inputs that only exist in Indian disclosures must not count as "missing" elsewhere
        rules = {name: [r for r in rs if r["key"] not in INDIA_ONLY_INPUTS] for name, rs in rules.items()}
    cats = {name: score_category(r, inputs, cfg["min_category_completeness"]) for name, r in rules.items()}
    if model == "financial":
        cats["cash_flow"] = {"score": None, "raw_score": None, "completeness": 0.0, "sufficient": False, "items": [],
                             "not_applicable": True,
                             "note": "Not applicable to lenders: operating cash flow mostly reflects loan-book changes."}
        if market != "IN":
            cats["asset_quality"] = {
                "score": None, "raw_score": None, "completeness": 0.0, "sufficient": False, "items": [],
                "not_applicable": True,
                "note": "Not assessed for non-Indian banks: the inputs (gross/net NPA, RBI capital adequacy, provision "
                        "coverage) are Indian disclosures, and comparable US figures are not in the free data."}

    # Verdict 1: business quality
    bq, bq_cov = _weighted(cats, cfg["business_quality_weights"][model])
    core_ok = cats["growth"]["score"] is not None and cats["profitability"]["score"] is not None
    if not core_ok:
        bq = None

    # Verdict 2: financial risk (higher = riskier)
    rcfg = cfg["risk"]
    resilience, res_cov = _weighted(cats, rcfg["resilience_weights"][model])
    fp = sum(rcfg["flag_points"][f["severity"]] for f in flags if f["category"] in rcfg["flag_categories"])
    fp = min(fp, rcfg["flag_points_cap"])
    if resilience is not None:
        risk = max(0.0, min(100.0, rcfg["base_share"] * (100 - resilience) + fp))
    else:
        risk = None
    risk_label = _label(risk, rcfg["labels"])

    # Verdict 3: valuation attractiveness
    vs = cats["valuation"]["score"]
    fv_label = (val.get("fair_value") or {}).get("label") or "Cannot reliably assess"

    composite, comp_cov = _weighted(cats, cfg["composite_weights"][model])

    # Data completeness: share of composite weight backed by data (item level)
    w_all = w_av = 0.0
    for k, w in cfg["composite_weights"][model].items():
        c = cats.get(k)
        if not c:
            continue
        if c.get("not_applicable"):
            continue
        w_all += w
        w_av += w * c["completeness"]
    completeness = (w_av / w_all * 100) if w_all else 0.0

    # Confidence
    conf = 100 - (100 - completeness) * 0.6
    reasons = []
    yrs = metrics["years_available"]
    if yrs < 4:
        conf -= 15
        reasons.append(f"only {yrs} years of annual data")
    if (bundle.get("freshness") or {}).get("stale"):
        conf -= 10
        reasons.append("data is stale (provider unavailable; served from cache)")
    nflag = sum(1 for r in val.get("reconciliation", []) if r.get("flag"))
    nmajor = sum(1 for r in val.get("reconciliation", []) if r.get("major"))
    if nflag:
        conf -= min(10, 5 * nflag) + (10 if nmajor else 0)
        reasons.append(f"{nflag} computed value(s) differ >10% from provider-reported figures"
                       + (f" ({nmajor} by more than 20%)" if nmajor else ""))
    if (val.get("fair_value") or {}).get("wide"):
        conf -= 5
        reasons.append("valuation methods disagree widely")
    if completeness < 70:
        reasons.append(f"data completeness {completeness:.0f}%")
    conf = max(0.0, min(100.0, conf))
    if nmajor:
        conf = min(conf, 69.0)  # a >20% disagreement in core inputs caps confidence at Medium
    conf_label = "High" if conf >= 70 else "Medium" if conf >= 45 else "Low"

    # Decision-support label
    if bq is None or completeness < 50:
        decision = "Insufficient evidence"
    elif risk is not None and risk >= 55:
        decision = "Elevated financial risk"
    elif bq >= 70 and (risk is None or risk < 35):
        decision = ("Fundamentally sound, valuation needs scrutiny"
                    if (fv_label == "Potentially overvalued" or (vs is not None and vs < 40)) else "Strong fundamentals")
    elif bq >= 55 and (fv_label == "Potentially overvalued" or (vs is not None and vs < 40)):
        decision = "Fundamentally sound, valuation needs scrutiny"
    else:
        decision = "Mixed financial picture"

    # Contributing factors
    pos, neg = [], []
    for cname, c in cats.items():
        for it in c.get("items", []):
            if it["score"] is None:
                continue
            entry = {"category": cname, "label": it["label"], "input": it["input"], "unit": it["unit"],
                     "basis": it["basis"], "score": it["score"], "weight": it["weight"]}
            if it["score"] >= 75:
                pos.append(entry)
            elif it["score"] <= 30:
                neg.append(entry)
    pos.sort(key=lambda e: -(e["score"] - 50) * e["weight"])
    neg.sort(key=lambda e: -(50 - e["score"]) * e["weight"])

    return {
        "model": model,
        "profile": {"name": profile_name, **{k: v for k, v in profile_cfg.items() if not k.startswith("match_")}},
        "verdicts": {
            "business_quality": {"score": bq, "label": _label(bq, cfg["quality_labels"]) if bq is not None else "Insufficient evidence",
                                 "coverage": bq_cov,
                                 "question": "Is the company fundamentally strong?",
                                 "components": cfg["business_quality_weights"][model]},
            "financial_risk": {"score": risk, "label": risk_label or "Insufficient evidence", "resilience": resilience,
                               "flag_points": fp, "coverage": res_cov,
                               "question": "How vulnerable is it to debt, cash-flow problems or deterioration?",
                               "formula": f"{rcfg['base_share']} × (100 − resilience) + red-flag points (cap {rcfg['flag_points_cap']})"},
            "valuation": {"score": vs, "label": fv_label,
                          "score_label": _label(vs, cfg["valuation_score_labels"]) if vs is not None else None,
                          "question": "Is the current price reasonable relative to fundamentals?"},
        },
        "composite": {"score": composite, "coverage": comp_cov, "weights": cfg["composite_weights"][model]},
        "categories": cats,
        "data_completeness": completeness,
        "confidence": {"score": conf, "label": conf_label, "reasons": reasons},
        "decision_label": decision,
        "positives": pos[:8],
        "negatives": neg[:8],
        "inputs": inputs,
    }
