"""Rule-based warning system.

Each flag states the evidence, severity, period and possible implications. Flags are
signals that merit a closer look at the filings, never findings of wrongdoing.
"""
from __future__ import annotations

from typing import Any, Optional

from .formulas import is_num

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _vals(metrics: dict[str, Any], key: str) -> list[Optional[float]]:
    return [c["value"] for c in metrics["annual"]["series"].get(key, [])]


def _flag(fid: str, title: str, severity: str, category: str, evidence: str, period: str, implication: str,
          rule: str) -> dict[str, Any]:
    return {"id": fid, "title": title, "severity": severity, "category": category, "evidence": evidence,
            "period": period, "implication": implication, "rule": rule}


def _fmt_pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.1f}%"


def compute_flags(bundle: dict[str, Any], metrics: dict[str, Any], valuation: dict[str, Any],
                  notes: Optional[dict[str, Any]], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    labels = metrics["annual"]["labels"]
    if not labels:
        return flags
    last3 = labels[-3:]
    span = f"{last3[0]}–{last3[-1]}" if len(last3) > 1 else last3[0]
    fin = metrics["is_financial"]
    L = metrics["latest"]
    lv = lambda k: L.get(k, {}).get("value")  # noqa: E731

    ni = _vals(metrics, "net_income")
    # Loss-making
    if is_num(ni[-1]) and ni[-1] < 0:
        losses = sum(1 for x in ni[-3:] if is_num(x) and x < 0)
        flags.append(_flag("losses", "Company is loss-making", "high", "profitability",
                           f"Net loss in {labels[-1]}; losses in {losses} of the last {len(ni[-3:])} years.",
                           labels[-1], "Losses erode equity and may require external funding.", "Net profit < 0"))

    eq = [p["fields"].get("equity") for p in bundle["annual"]]
    if is_num(eq[-1]) and eq[-1] <= 0:
        flags.append(_flag("negative_equity", "Negative shareholders' equity", "high", "balance",
                           "Liabilities exceed assets on the latest balance sheet.", labels[-1],
                           "Accumulated losses have wiped out equity; ratios like ROE and D/E are not meaningful.",
                           "Equity ≤ 0"))

    if not fin:
        fcf = _vals(metrics, "fcf")[-3:]
        neg = sum(1 for x in fcf if is_num(x) and x < 0)
        known = sum(1 for x in fcf if is_num(x))
        if known >= 2 and neg >= 2:
            flags.append(_flag("negative_fcf", "Persistent negative free cash flow", "high" if neg == known and known >= 3 else "medium",
                               "cashflow", f"Free cash flow (CFO − capex) was negative in {neg} of the last {known} years.",
                               span, "The business consumes more cash than it generates and may depend on debt or equity "
                               "raising. Acceptable during a deliberate investment phase, if returns follow.",
                               "FCF < 0 in ≥2 of last 3 years"))

        cfo = _vals(metrics, "cfo")[-3:]
        ni3 = ni[-3:]
        if len(cfo) == len(ni3) and all(is_num(x) for x in cfo + ni3) and sum(ni3) > 0:
            conv = sum(cfo) / sum(ni3)
            growing = len(ni) >= 3 and is_num(ni[-3]) and ni[-1] > ni[-3]
            if conv < thresholds["cash_conversion_warn"] and growing:
                flags.append(_flag("profit_cash_gap", "Profits rising but operating cash flow is weak",
                                   "high" if conv < 0.5 else "medium", "quality",
                                   f"Cumulative CFO was {conv:.2f}× cumulative net profit over {span} while profit grew.",
                                   span, "Reported profits are not turning into cash; check receivables, inventory and "
                                   "revenue recognition in the notes to accounts.", "Σ CFO / Σ PAT (3y) below threshold while PAT rises"))

        om = [x for x in _vals(metrics, "operating_margin") if True]
        if len(om) >= 4 and all(is_num(x) for x in om[-4:]):
            prior = sum(om[-4:-1]) / 3
            drop = prior - om[-1]
            if drop > 3:
                flags.append(_flag("margin_decline", "Deteriorating operating margin", "high" if drop > 6 else "medium",
                                   "profitability", f"Operating margin {om[-1]:.1f}% in {labels[-1]} vs {prior:.1f}% "
                                   f"average of the previous three years ({drop:.1f} pp lower).", labels[-1],
                                   "Could reflect cost pressure, pricing weakness or mix change.",
                                   "Latest margin > 3 pp below prior 3-yr average"))

        de = lv("debt_to_equity")
        hi, med = thresholds["de_high"], thresholds["de_medium"]
        if is_num(de) and de > med:
            flags.append(_flag("high_leverage", "High debt relative to equity", "high" if de > hi else "medium", "balance",
                               f"Debt-to-equity of {de:.2f}× in {labels[-1]}.", labels[-1],
                               "Higher leverage magnifies losses in a downturn and raises refinancing risk.",
                               f"D/E > {med}× (medium) / {hi}× (high) for this sector profile"))
        nde = lv("net_debt_to_ebitda")
        if is_num(nde) and nde > thresholds["nd_ebitda_medium"]:
            flags.append(_flag("high_net_debt_ebitda", "Net debt is high relative to EBITDA",
                               "high" if nde > thresholds["nd_ebitda_high"] else "medium", "balance",
                               f"Net debt / EBITDA of {nde:.1f}× in {labels[-1]}.", labels[-1],
                               "It would take several years of operating earnings to repay debt.",
                               f"Net debt/EBITDA > {thresholds['nd_ebitda_medium']}×"))
        ic = lv("interest_coverage")
        if is_num(ic) and ic < 3:
            flags.append(_flag("weak_coverage", "Weak interest coverage", "high" if ic < 1.5 else "medium", "balance",
                               f"EBIT covers interest {ic:.1f}× in {labels[-1]}.", labels[-1],
                               "A modest fall in earnings could make interest payments difficult.", "EBIT / interest < 3×"))
        cr = lv("current_ratio")
        if is_num(cr) and cr < 1:
            flags.append(_flag("low_liquidity", "Current liabilities exceed current assets", "medium", "balance",
                               f"Current ratio of {cr:.2f}× in {labels[-1]}.", labels[-1],
                               "Short-term obligations depend on continued cash generation or refinancing. Some "
                               "businesses with advance customer payments run this way safely.", "Current ratio < 1"))

        rec = [p["fields"].get("receivables") for p in bundle["annual"]]
        rev = [p["fields"].get("revenue") for p in bundle["annual"]]
        if len(rec) >= 4 and all(is_num(x) and x > 0 for x in rec[-4:] + rev[-4:]):
            rg = ((rec[-1] / rec[-4]) ** (1 / 3) - 1) * 100
            sg = ((rev[-1] / rev[-4]) ** (1 / 3) - 1) * 100
            if rg - sg > 10:
                flags.append(_flag("receivables_outpacing", "Receivables growing much faster than sales",
                                   "high" if rg - sg > 20 else "medium", "quality",
                                   f"Receivables grew {_fmt_pct(rg)} a year vs revenue {_fmt_pct(sg)} a year "
                                   f"({labels[-4]}→{labels[-1]}).", f"{labels[-4]}–{labels[-1]}",
                                   "Customers are taking longer to pay, or sales are being booked before cash is "
                                   "collected. Check the receivables ageing in the annual report.",
                                   "Receivables CAGR − revenue CAGR > 10 pp (3y)"))

        un = _vals(metrics, "unusual_share_of_pbt")[-3:]
        big = [x for x in un if is_num(x) and x > 15]
        if len(big) >= 2:
            flags.append(_flag("exceptional_gains", "Exceptional gains repeatedly support profits",
                               "high" if max(big) > 30 else "medium", "quality",
                               f"Exceptional/unusual items exceeded 15% of profit before tax in {len(big)} of the last "
                               f"{len(un)} years (max {max(big):.0f}%).", span,
                               "Recurring 'one-offs' flatter reported profit; core earnings are lower than headline PAT.",
                               "Unusual items > 15% of PBT in ≥2 of last 3 years"))
    else:
        roa = lv("roa")
        if is_num(roa) and roa < 0.6:
            flags.append(_flag("low_roa", "Low return on assets (lender)", "medium", "profitability",
                               f"ROA of {roa:.2f}% in {labels[-1]}.", labels[-1],
                               "Thin profitability leaves little buffer for credit losses.", "ROA < 0.6% for a lender"))
        lg = lv("loan_growth")
        if is_num(lg) and lg > 30:
            flags.append(_flag("rapid_loan_growth", "Very rapid loan-book growth", "medium", "balance",
                               f"Net loans grew {lg:.1f}% in {labels[-1]}.", labels[-1],
                               "Fast lending growth can precede asset-quality problems; asset-quality data (GNPA) is not "
                               "available from the free provider, so check the latest investor presentation.",
                               "Loan growth > 30% YoY"))
        eta = lv("equity_to_assets")
        if is_num(eta) and eta < 6:
            flags.append(_flag("thin_equity", "Thin equity cushion", "medium", "balance",
                               f"Equity is {eta:.1f}% of total assets.", labels[-1],
                               "A crude leverage indicator; regulatory capital adequacy (CAR) is the proper measure "
                               "and is not available from the free provider.", "Equity / assets < 6%"))
        nb = notes or {}
        src = f"user-entered{', ' + nb['bank_as_of'] if nb.get('bank_as_of') else ''}"
        g, nn, car, pcr = (nb.get(k) for k in ("gnpa_pct", "nnpa_pct", "car_pct", "pcr_pct"))
        if is_num(g) and g > 3:
            flags.append(_flag("high_gnpa", "High gross NPAs", "high" if g > 5 else "medium", "balance",
                               f"Gross NPA of {g:.2f}% of advances ({src}).", nb.get("bank_as_of") or "user-entered",
                               "A larger share of loans has stopped paying; future provisions can eat into profits.",
                               "GNPA > 3% (high above 5%)"))
        if is_num(nn) and nn > 1.5:
            flags.append(_flag("high_nnpa", "High net NPAs", "high" if nn > 3 else "medium", "balance",
                               f"Net NPA of {nn:.2f}% after provisions ({src}).", nb.get("bank_as_of") or "user-entered",
                               "Bad loans not yet provided for put the bank's capital at risk.", "NNPA > 1.5% (high above 3%)"))
        if is_num(car) and car < 14:
            flags.append(_flag("low_car", "Thin capital adequacy", "high" if car < 12 else "medium", "balance",
                               f"Capital adequacy ratio of {car:.2f}% ({src}); the RBI minimum including the conservation "
                               "buffer is 11.5%.", nb.get("bank_as_of") or "user-entered",
                               "Little room to absorb losses or grow; may need to raise equity (dilution).", "CAR < 14% (high below 12%)"))
        if is_num(pcr) and pcr < 60:
            flags.append(_flag("low_pcr", "Low provision coverage", "medium", "balance",
                               f"Provision coverage ratio of {pcr:.1f}% ({src}).", nb.get("bank_as_of") or "user-entered",
                               "Fewer bad loans are already provided for, so future credit costs may be higher.", "PCR < 60%"))

    roe = _vals(metrics, "roe")
    if len(roe) >= 3 and all(is_num(x) for x in roe[-3:]) and roe[-3] > roe[-2] > roe[-1] and roe[-3] - roe[-1] > 5:
        flags.append(_flag("declining_returns", "Return on equity declining", "medium", "profitability",
                           f"ROE fell from {roe[-3]:.1f}% to {roe[-1]:.1f}% over {span}.", span,
                           "The business is earning less on shareholders' capital, possibly from competition, "
                           "lower margins, or excess retained cash.", "ROE down 2 years running and by > 5 pp"))

    sc = [p["fields"].get("shares_outstanding") for p in bundle["annual"]]
    if len(sc) >= 4 and is_num(sc[-1]) and is_num(sc[-4]) and sc[-4] > 0:
        dil = (sc[-1] / sc[-4] - 1) * 100
        if dil > 5:
            flags.append(_flag("dilution", "Significant increase in share count", "high" if dil > 15 else "medium", "governance",
                               f"Share count (split-adjusted) rose {dil:.1f}% from {labels[-4]} to {labels[-1]}.",
                               f"{labels[-4]}–{labels[-1]}",
                               "Each existing share owns a smaller part of the company, so per-share growth lags total growth. Causes include "
                               "fundraising, ESOPs, or issuing shares for a merger; check which applies.",
                               "Split-adjusted share count up > 5% over 3 years"))

    rg_last = lv("revenue_growth") if not fin else lv("nii_growth")
    ng_last = lv("net_income_growth")
    if (is_num(rg_last) and rg_last < -15) or (is_num(ng_last) and ng_last < -30):
        flags.append(_flag("sudden_deterioration", "Sharp deterioration in the latest year",
                           "high" if (is_num(ng_last) and ng_last < -50) or (is_num(rg_last) and rg_last < -25) else "medium",
                           "growth", f"Revenue growth {_fmt_pct(rg_last)}, net-profit growth {_fmt_pct(ng_last)} in {labels[-1]}.",
                           labels[-1], "Find out whether this is cyclical, one-off, or structural.",
                           "Revenue growth < −15% or profit growth < −30%"))

    # Valuation stretch (relative to peers or absolute with low growth)
    mult = valuation.get("multiples", {})
    pe = (mult.get("pe") or {}).get("value")
    peer_pe = ((valuation.get("comps") or {}).get("medians", {}).get("pe") or {}).get("value")
    eg = metrics["growth"].get("eps_cagr_3y", {}).get("value")
    if is_num(pe) and is_num(peer_pe) and peer_pe > 0 and pe > 1.75 * peer_pe:
        flags.append(_flag("valuation_vs_peers", "Valued well above peers", "medium", "valuation",
                           f"P/E {pe:.1f}× vs peer median {peer_pe:.1f}×.", labels[-1],
                           "The price already assumes superior growth or quality; disappointment risk is higher.",
                           "P/E > 1.75 × peer median"))
    elif is_num(pe) and pe > 60 and (not is_num(eg) or eg < 15):
        flags.append(_flag("valuation_absolute", "High P/E without matching growth", "medium", "valuation",
                           f"P/E {pe:.1f}× with 3-yr EPS CAGR {_fmt_pct(eg)}.", labels[-1],
                           "High expectations are priced in.", "P/E > 60 and EPS CAGR < 15%"))

    # User-entered governance facts
    n = notes or {}
    pledge = n.get("promoter_pledge_pct")
    if is_num(pledge) and pledge > 10:
        flags.append(_flag("pledge", "Promoter shares pledged", "high" if pledge > 50 else "medium" if pledge > 20 else "low",
                           "governance", f"{pledge:.1f}% of promoter holding is pledged (user-entered"
                           f"{', source: ' + n['source'] if n.get('source') else ''}).", n.get("as_of") or "user-entered",
                           "A falling share price can trigger forced selling by lenders.", "Pledge > 10% of promoter holding"))
    if n.get("auditor_qualification"):
        flags.append(_flag("auditor", "Auditor qualification or emphasis of matter", "high", "governance",
                           n.get("auditor_note") or "User recorded an auditor qualification.", n.get("as_of") or "user-entered",
                           "Read the auditor's report; qualifications can indicate unreliable accounts.", "User-entered"))
    if n.get("auditor_resigned"):
        flags.append(_flag("auditor_resigned", "Auditor resigned mid-term", "high", "governance",
                           n.get("auditor_note") or "User recorded an auditor resignation.", n.get("as_of") or "user-entered",
                           "Mid-term auditor resignations warrant reading the resignation letter filed with the exchange.",
                           "User-entered"))
    if n.get("material_litigation"):
        flags.append(_flag("litigation", "Material litigation or regulatory action", "medium", "governance",
                           n.get("litigation_note") or "User recorded material litigation/regulatory action.",
                           n.get("as_of") or "user-entered", "Outcome uncertainty; check contingent liabilities.", "User-entered"))
    if n.get("rpt_concern"):
        flags.append(_flag("rpt", "Large related-party transactions", "medium", "governance",
                           n.get("rpt_note") or "User recorded significant related-party transactions.",
                           n.get("as_of") or "user-entered", "Value may leak to promoter entities; check terms in the annual report.",
                           "User-entered"))

    flags.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])
    return flags
