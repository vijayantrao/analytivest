"""Valuation engine: multiples, EV, historical ranges, DCF (+ sensitivity), comps, DDM,
justified P/B, and a fair-value range.

None of these produce "the" value of a stock. Each method returns its assumptions and
limitations so the user can judge them.
"""
from __future__ import annotations

import bisect
from datetime import date, timedelta
from typing import Any, Optional

from . import formulas as F
from .formulas import is_num


def _v(x: Any) -> Optional[float]:
    if isinstance(x, dict):
        x = x.get("value")
    return float(x) if is_num(x) else None


def price_on_or_before(prices: list[list[Any]], d: str) -> Optional[float]:
    if not prices:
        return None
    dates = [p[0] for p in prices]
    i = bisect.bisect_right(dates, d) - 1
    if i < 0:
        return None
    # Do not use a price more than 10 days before the requested date (gap in history)
    if (date.fromisoformat(d) - date.fromisoformat(prices[i][0])).days > 10:
        return None
    return float(prices[i][1])


def dividends_per_fy(dividends: list[list[Any]], period_ends: list[str]) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for pe in period_ends:
        end = date.fromisoformat(pe)
        start = end - timedelta(days=365)
        out.append(sum(float(a) for d, a in dividends if start < date.fromisoformat(d) <= end))
    return out


def ttm_dps(dividends: list[list[Any]], as_of: date) -> float:
    start = as_of - timedelta(days=365)
    return sum(float(a) for d, a in dividends if start < date.fromisoformat(d) <= as_of)


def _m(value: Optional[float], *, label: str, unit: str, formula: str, basis: str, quality: str = "calculated",
       reason: Optional[str] = None) -> dict[str, Any]:
    return {"value": value, "label": label, "unit": unit, "formula": formula, "basis": basis, "quality": quality,
            "status": "ok" if value is not None else ("not_meaningful" if reason and "not meaningful" in reason else "missing"),
            "reason": reason if value is None else None}


def multiples(bundle: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    q = bundle.get("quote") or {}
    price, shares = _v(q.get("price")), _v(q.get("shares_outstanding"))
    L = metrics["latest"]
    period = (bundle.get("annual") or [{}])[-1].get("label", "latest FY") if bundle.get("annual") else "n/a"
    ps = bundle.get("provider_stats") or {}

    mcap = price * shares if (price is not None and shares is not None) else None
    if bundle.get("fx_unconverted"):  # statements and price in different currencies: no valid multiples
        L = {}
    debt, cash = _v(L.get("total_debt")), _v(L.get("cash_and_sti"))
    mi = None
    if bundle.get("annual"):
        mi = _v(bundle["annual"][-1]["fields"].get("minority_interest"))
    ev = (mcap + (debt or 0) - (cash or 0) + (mi or 0)) if (mcap is not None and debt is not None and cash is not None) else None

    ni, rev, ebitda = _v(L.get("net_income")), _v(L.get("revenue")), _v(L.get("ebitda"))
    usable = bool(bundle.get("annual")) and not bundle.get("fx_unconverted")
    ebit = _v(bundle["annual"][-1]["fields"].get("ebit")) if usable else None
    eq = _v(bundle["annual"][-1]["fields"].get("equity")) if usable else None
    fcf = _v(L.get("fcf"))

    def r(num, den, name):
        c = F.ratio(num, den, name=name)
        return c.value, (c.reason if c.value is None else None)

    out: dict[str, Any] = {}
    out["price"] = _m(price, label="Share price", unit="per_share", formula="Last price from provider (delayed)",
                      basis=q.get("market_time") or "", quality="reported")
    out["market_cap"] = _m(mcap, label="Market capitalisation", unit="currency", formula="Price × Shares outstanding",
                           basis="current price × latest share count")
    out["enterprise_value"] = _m(ev, label="Enterprise value", unit="currency",
                                 formula="Market cap + Total debt + Minority interest − Cash & short-term investments",
                                 basis=f"current price; debt & cash as of {period}",
                                 reason=None if ev is not None else "debt or cash not available")
    v, why = r(mcap, ni, "P/E")
    out["pe"] = _m(v, label="P/E (latest FY)", unit="x", formula="Market cap / Net profit (latest fiscal year)",
                   basis=period, reason=why if ni is None or ni > 0 else "not meaningful: company made a loss")
    # TTM P/E from consecutive quarters, else provider-reported (labelled)
    ttm_eps = metrics["ttm"]["eps"]
    if ttm_eps.get("value") and ttm_eps["value"] > 0 and price:
        out["pe_ttm"] = _m(price / ttm_eps["value"], label="P/E (TTM)", unit="x",
                           formula="Price / sum of last 4 quarterly diluted EPS", basis=ttm_eps.get("period", "TTM"))
    elif _v(ps.get("trailingPE")):
        out["pe_ttm"] = _m(_v(ps.get("trailingPE")), label="P/E (TTM)", unit="x",
                           formula="As reported by provider", basis="TTM (provider)", quality="provider_reported")
    else:
        out["pe_ttm"] = _m(None, label="P/E (TTM)", unit="x", formula="Price / TTM EPS", basis="TTM",
                           reason=ttm_eps.get("reason") or "TTM EPS not available")
    a = bundle.get("analyst") or {}
    fe, na = _v(a.get("forward_eps")), a.get("n_analysts") or 0
    if fe and fe > 0 and price and na >= 3:
        out["forward_pe"] = _m(price / fe, label="Forward P/E", unit="x", formula="Price / consensus next-year EPS",
                               basis=f"consensus of {na} analysts (provider estimate)", quality="provider_estimate")
    else:
        out["forward_pe"] = _m(None, label="Forward P/E", unit="x", formula="Price / consensus next-year EPS",
                               basis="consensus", reason="no credible forward estimate (fewer than 3 analysts or not provided)")
    v, why = r(mcap, eq, "P/B")
    out["pb"] = _m(v, label="Price / book", unit="x", formula="Market cap / Shareholders' equity", basis=period, reason=why)
    v, why = r(mcap, rev, "P/S")
    out["ps"] = _m(v, label="Price / sales", unit="x", formula="Market cap / Revenue", basis=period, reason=why)
    fin = metrics["is_financial"]
    if fin:
        reason = "not meaningful for banks/financials (debt is raw material, not financing)"
        out["ev_ebitda"] = _m(None, label="EV / EBITDA", unit="x", formula="EV / EBITDA", basis=period, reason=reason)
        out["ev_ebit"] = _m(None, label="EV / EBIT", unit="x", formula="EV / EBIT", basis=period, reason=reason)
        out["fcf_yield"] = _m(None, label="FCF yield", unit="pct", formula="FCF / Market cap", basis=period,
                              reason="not meaningful for banks/financials (loan growth flows through operating cash flow)")
    else:
        v, why = r(ev, ebitda, "EV/EBITDA")
        out["ev_ebitda"] = _m(v, label="EV / EBITDA", unit="x", formula="Enterprise value / EBITDA", basis=period, reason=why)
        v, why = r(ev, ebit, "EV/EBIT")
        out["ev_ebit"] = _m(v, label="EV / EBIT", unit="x", formula="Enterprise value / EBIT", basis=period, reason=why)
        c = F.pct(fcf, mcap, name="FCF yield")
        out["fcf_yield"] = _m(c.value, label="FCF yield", unit="pct", formula="Free cash flow / Market cap × 100",
                              basis=period, reason=c.reason)
    c = F.pct(ni, mcap, name="earnings yield", den_must_be_positive=True)
    out["earnings_yield"] = _m(c.value, label="Earnings yield", unit="pct", formula="Net profit / Market cap × 100",
                               basis=period, reason=c.reason)
    dps = ttm_dps(bundle.get("dividends") or [], date.today())
    out["dps_ttm"] = _m(dps if bundle.get("dividends") is not None else None, label="Dividend per share (TTM)",
                        unit="per_share", formula="Sum of dividends with ex-date in the last 365 days",
                        basis="last 12 months", quality="calculated")
    out["dividend_yield"] = _m((dps / price * 100) if price else None, label="Dividend yield", unit="pct",
                               formula="TTM dividend per share / Price × 100", basis="last 12 months")
    # PEG
    g = metrics["growth"]
    eg = next((g[k] for k in ("eps_cagr_3y", "eps_cagr_max")
               if _v(g.get(k)) is not None and not g[k].get("base_effect")), None)
    pe_v = out["pe"]["value"]
    if pe_v and eg and _v(eg) and _v(eg) > 0:
        out["peg"] = _m(pe_v / _v(eg), label="PEG", unit="x", formula="P/E / historical EPS CAGR (%)",
                        basis=f"P/E {period}; EPS CAGR {eg.get('period')}")
        out["peg"]["caveat"] = "Uses past growth; future growth may differ. Not meaningful for low or erratic growth."
    else:
        out["peg"] = _m(None, label="PEG", unit="x", formula="P/E / EPS CAGR", basis="",
                        reason="EPS growth not positive or P/E not meaningful")

    # Reconciliation against provider-reported figures (same provider, independent calculation)
    recon = []
    checks = [("market_cap", "marketCap", "Market cap"), ("pb", "priceToBook", "P/B")]
    if not fin:
        checks += [("enterprise_value", "enterpriseValue", "Enterprise value"), ("ev_ebitda", "enterpriseToEbitda", "EV/EBITDA")]
    for key, pkey, label in checks:
        mine, theirs = out[key]["value"], _v(ps.get(pkey))
        if mine is not None and theirs is not None and theirs != 0:
            diff = (mine / theirs - 1) * 100
            lo_hi = PEER_BOUNDS.get(key)
            if lo_hi and not (lo_hi[0] < theirs <= lo_hi[1]):
                recon.append({"metric": label, "calculated": mine, "provider": theirs, "diff_pct": diff, "flag": False,
                              "major": False, "provider_implausible": True,
                              "explanation": "The provider's own figure is implausible (often a currency mix-up in its "
                                             "calculation), so it is ignored; this app's value is computed from statements."})
                continue
            expl = None
            if abs(diff) > 20 and key == "pb":
                expl = ("Large gap: the provider's balance-sheet equity disagrees with its own per-share book value "
                        "(possibly consolidated vs standalone, or minority interest/merger reserves). ROE and P/B "
                        "may be misstated; check the annual report.")
            elif abs(diff) > 10:
                expl = ("Differences usually come from TTM vs fiscal-year inputs, share-count dates, "
                        "or the provider including other items in debt/cash.")
            recon.append({"metric": label, "calculated": mine, "provider": theirs, "diff_pct": diff,
                          "flag": abs(diff) > 10,
                          # Only like-for-like checks count as major: EV-based figures differ by design
                          # (provider uses trailing-twelve-month EBITDA and latest-quarter debt/cash).
                          "major": abs(diff) > 20 and key in ("market_cap", "pb"), "explanation": expl})
    return {"multiples": out, "reconciliation": recon, "market_cap": mcap, "ev": ev, "price": price, "shares": shares}


def historical_multiples(bundle: dict[str, Any], metrics: dict[str, Any], prices: list[list[Any]]) -> dict[str, Any]:
    """Fiscal-year-end multiples and a weekly trailing P/E band over the last 5 years.

    For each date the EPS used is that of the latest fiscal year that ended at least 60 days
    earlier (≈ when results are published), so the series has no look-ahead.
    """
    A = metrics["annual"]
    ends, eps_s = A["period_ends"], [c["value"] for c in A["series"].get("eps", [])]
    bvps = [c["value"] for c in A["series"].get("book_value_per_share", [])]
    fy_rows = []
    for i, pe_end in enumerate(ends):
        p = price_on_or_before(prices, pe_end)
        e = eps_s[i] if i < len(eps_s) else None
        b = bvps[i] if i < len(bvps) else None
        fy_rows.append({"period": A["labels"][i], "price": p,
                        "pe": (p / e) if (p and e and e > 0) else None,
                        "pb": (p / b) if (p and b and b > 0) else None})
    band = []
    if prices and ends:
        cutoff = (date.today() - timedelta(days=5 * 365)).isoformat()
        pub = [(date.fromisoformat(e) + timedelta(days=60)).isoformat() for e in ends]
        last_week = None
        for d, close, *_ in prices:
            if d < cutoff:
                continue
            wk = date.fromisoformat(d).isocalendar()[:2]
            if wk == last_week:
                continue
            last_week = wk
            j = bisect.bisect_right(pub, d) - 1
            if j < 0:
                continue
            e = eps_s[j]
            if e and e > 0:
                band.append({"date": d, "pe": close / e, "eps_period": A["labels"][j]})
    pes = [b["pe"] for b in band]
    stats = None
    if len(pes) >= 20:
        stats = {"min": min(pes), "p25": F.percentile(pes, 25), "median": F.median(pes),
                 "p75": F.percentile(pes, 75), "max": max(pes), "n_weeks": len(pes),
                 "from": band[0]["date"], "to": band[-1]["date"]}
    return {"fiscal_year_end": fy_rows, "pe_band": band, "pe_stats": stats,
            "method": "Weekly closing price ÷ diluted EPS of the latest fiscal year published ≥60 days earlier."}


def dcf(base_fcf: float, *, growth: float, years: int, fade_years: int, discount: float, terminal: float,
        net_debt: float, shares: float) -> dict[str, Any]:
    """Two-stage FCF DCF. Growth is constant for ``years`` then fades linearly to ``terminal`` over
    ``fade_years``. Rates are in %.
    """
    if discount <= terminal + 0.5:
        return {"value_per_share": None, "reason": "discount rate must exceed terminal growth by more than 0.5 pp"}
    r, gT = discount / 100, terminal / 100
    flows, fcf, pv_sum = [], base_fcf, 0.0
    N = years + fade_years
    for t in range(1, N + 1):
        if t <= years:
            g = growth / 100
        else:
            k = t - years
            g = (growth + (terminal - growth) * k / fade_years) / 100
        fcf = fcf * (1 + g)
        pv = fcf / (1 + r) ** t
        pv_sum += pv
        flows.append({"year": t, "growth_pct": g * 100, "fcf": fcf, "pv": pv})
    tv = fcf * (1 + gT) / (r - gT)
    pv_tv = tv / (1 + r) ** N
    ev = pv_sum + pv_tv
    equity = ev - net_debt
    return {"enterprise_value": ev, "equity_value": equity, "value_per_share": equity / shares if shares else None,
            "pv_explicit": pv_sum, "terminal_value": tv, "pv_terminal": pv_tv,
            "terminal_share_pct": pv_tv / ev * 100 if ev else None, "flows": flows}


def dcf_analysis(bundle: dict[str, Any], metrics: dict[str, Any], market, overrides: Optional[dict[str, Any]] = None,
                 shares: Optional[float] = None) -> dict[str, Any]:
    overrides = overrides or {}
    limitations = [
        "Highly sensitive to the discount rate and terminal growth; small changes move the result a lot.",
        "Uses historical free cash flow as the base; it does not know about future capex cycles or new businesses.",
        "Free cash flow is defined here as CFO − capex (before interest in Indian reporting, so it approximates "
        "free cash flow to the firm); net debt is then subtracted to reach equity value.",
    ]
    if metrics["is_financial"]:
        return {"applicable": False, "reason": "DCF on free cash flow is not meaningful for banks and other "
                "lenders: lending is their operating activity, so CFO swings with loan growth. "
                "Use P/B-based methods instead.", "limitations": limitations}
    fcf_series = [c["value"] for c in metrics["annual"]["series"].get("fcf", [])]
    recent = [x for x in fcf_series[-3:] if x is not None]
    if not recent:
        return {"applicable": False, "reason": "free cash flow history not available", "limitations": limitations}
    base_default = sum(recent) / len(recent)
    base_method = f"average of last {len(recent)} years' FCF"
    if base_default <= 0:
        return {"applicable": False, "reason": f"{base_method} is negative or zero, so an FCF-based DCF is not "
                "meaningful. Valuation relies on other methods.", "limitations": limitations,
                "base_fcf": base_default}
    g = metrics["growth"]
    rc = _v(g.get("revenue_cagr_3y")) if _v(g.get("revenue_cagr_3y")) is not None else _v(g.get("revenue_cagr_max"))
    growth_default = min(max(rc if rc is not None else 8.0, 2.0), 18.0)
    L = metrics["latest"]
    nd = _v(L.get("net_debt"))
    mi = _v(bundle["annual"][-1]["fields"].get("minority_interest")) if bundle.get("annual") else None
    shares = shares or _v((bundle.get("quote") or {}).get("shares_outstanding"))
    if nd is None or not shares:
        return {"applicable": False, "reason": "net debt or share count not available", "limitations": limitations}
    a = {
        "base_fcf": float(overrides.get("base_fcf") or base_default),
        "growth": float(overrides.get("growth", growth_default)),
        "years": int(overrides.get("years", 5)),
        "fade_years": int(overrides.get("fade_years", 5)),
        "discount": float(overrides.get("discount", market.default_cost_of_equity)),
        "terminal": float(overrides.get("terminal", market.default_terminal_growth)),
    }
    a["years"] = max(1, min(a["years"], 15))
    a["fade_years"] = max(1, min(a["fade_years"], 15))
    net_claims = nd + (mi or 0)
    base = dcf(a["base_fcf"], growth=a["growth"], years=a["years"], fade_years=a["fade_years"],
               discount=a["discount"], terminal=a["terminal"], net_debt=net_claims, shares=shares)
    grid_r = [a["discount"] + d for d in (-2, -1, 0, 1, 2)]
    grid_g = [a["terminal"] + d for d in (-1, -0.5, 0, 0.5, 1)]
    grid = [[dcf(a["base_fcf"], growth=a["growth"], years=a["years"], fade_years=a["fade_years"], discount=r,
                 terminal=gg, net_debt=net_claims, shares=shares).get("value_per_share") for gg in grid_g] for r in grid_r]
    growth_sens = [{"growth": gr, "value_per_share": dcf(a["base_fcf"], growth=gr, years=a["years"],
                    fade_years=a["fade_years"], discount=a["discount"], terminal=a["terminal"], net_debt=net_claims,
                    shares=shares).get("value_per_share")} for gr in (a["growth"] - 4, a["growth"] - 2, a["growth"],
                                                                     a["growth"] + 2, a["growth"] + 4)]
    if base.get("terminal_share_pct") and base["terminal_share_pct"] > 75:
        limitations.append(f"Terminal value is {base['terminal_share_pct']:.0f}% of enterprise value, so the result "
                           "depends mostly on assumptions far in the future.")
    return {
        "applicable": True, "assumptions": a,
        "defaults": {"base_fcf": base_default, "growth": growth_default, "years": 5, "fade_years": 5,
                     "discount": market.default_cost_of_equity, "terminal": market.default_terminal_growth},
        "assumption_notes": {
            "base_fcf": base_method + " (CFO − capex)",
            "growth": "default = 3-yr revenue CAGR clipped to 2–18%",
            "discount": f"default {market.default_cost_of_equity}% ≈ {market.cost_of_equity_basis}; "
                        "for leveraged firms a WACC slightly below this may be appropriate",
            "terminal": f"default {market.default_terminal_growth}% nominal long-run growth",
            "net_debt": "latest fiscal-year net debt plus minority interest is subtracted",
        },
        "result": base, "net_debt_used": net_claims, "shares_used": shares,
        "sensitivity": {"discount_rates": grid_r, "terminal_growths": grid_g, "values": grid},
        "growth_sensitivity": growth_sens,
        "limitations": limitations,
    }


PEER_BOUNDS = {"pe": (0, 300), "pb": (0, 100), "ev_ebitda": (0, 150), "ps": (0, 100), "roe": (-100, 200),
               "net_margin": (-100, 100), "operating_margin": (-100, 100), "revenue_growth": (-100, 500),
               "debt_to_equity": (0, 20)}


def sanitize_peers(peers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop implausible provider-reported peer ratios instead of letting them skew medians.

    Two checks: absolute plausibility bounds, then (for valuation multiples with ≥4 values) values more
    than 4× away from the median of the others. Excluded values are kept in ``excluded`` with a reason.
    """
    out = [dict(p, excluded=dict(p.get("excluded") or {})) for p in peers]
    for k, (lo, hi) in PEER_BOUNDS.items():
        for p in out:
            v = p.get(k)
            if is_num(v) and not (lo < v <= hi if k in ("pe", "pb", "ev_ebitda", "ps") else lo <= v <= hi):
                p["excluded"][k] = f"implausible provider value {v:,.1f} (outside {lo}–{hi})"
                p[k] = None
    for k in ("pe", "pb", "ev_ebitda", "ps"):
        for p in out:
            v = p.get(k)
            others = [q.get(k) for q in out if q is not p and is_num(q.get(k))]
            if is_num(v) and len(others) >= 3:
                m = F.median(others)
                if m and (v > 4 * m or v < m / 4):
                    p["excluded"][k] = f"outlier: {v:,.1f} vs peer median {m:,.1f}"
                    p[k] = None
    return out


def comps_valuation(metrics: dict[str, Any], peers: list[dict[str, Any]], shares: Optional[float],
                    net_debt: Optional[float]) -> dict[str, Any]:
    L = metrics["latest"]
    out: dict[str, Any] = {"methods": [], "medians": {}, "n_peers": len(peers)}
    def med(key):
        vals = [p.get(key) for p in peers if is_num(p.get(key)) and p.get(key) > 0]
        return (F.median(vals), len(vals)) if vals else (None, 0)
    for key in ("pe", "pb", "ev_ebitda", "ps", "roe", "net_margin", "revenue_growth", "debt_to_equity"):
        m, n = med(key) if key not in ("debt_to_equity",) else (F.median([p.get(key) for p in peers if is_num(p.get(key))]),
                                                               sum(1 for p in peers if is_num(p.get(key))))
        out["medians"][key] = {"value": m, "n": n}
    eps, bvps = _v(L.get("eps")), _v(L.get("book_value_per_share"))
    ebitda = _v(L.get("ebitda"))
    pe_m, n = out["medians"]["pe"]["value"], out["medians"]["pe"]["n"]
    if pe_m and n >= 3 and eps and eps > 0:
        out["methods"].append({"method": "Peer median P/E × EPS", "value_per_share": pe_m * eps,
                               "inputs": f"median P/E {pe_m:.1f}× ({n} peers) × EPS {eps:.2f}"})
    if not metrics["is_financial"]:
        ev_m, n = out["medians"]["ev_ebitda"]["value"], out["medians"]["ev_ebitda"]["n"]
        if ev_m and n >= 3 and ebitda and ebitda > 0 and shares and net_debt is not None:
            out["methods"].append({"method": "Peer median EV/EBITDA", "value_per_share": (ev_m * ebitda - net_debt) / shares,
                                   "inputs": f"median EV/EBITDA {ev_m:.1f}× ({n} peers); less net debt"})
    pb_m, n = out["medians"]["pb"]["value"], out["medians"]["pb"]["n"]
    if metrics["is_financial"] and pb_m and n >= 3 and bvps and bvps > 0:
        out["methods"].append({"method": "Peer median P/B × BVPS", "value_per_share": pb_m * bvps,
                               "inputs": f"median P/B {pb_m:.2f}× ({n} peers) × BVPS {bvps:.2f}"})
    out["limitations"] = ["Assumes peers are correctly valued and comparable in growth, risk and accounting.",
                          "Peer multiples are trailing (provider-reported) while this company's inputs are latest fiscal year."]
    return out


def ddm(bundle: dict[str, Any], metrics: dict[str, Any], market) -> dict[str, Any]:
    divs = bundle.get("dividends") or []
    ends = metrics["annual"]["period_ends"]
    dps = dividends_per_fy(divs, ends)
    paid_years = [d for d in dps[-4:] if d and d > 0]
    payout = _v(metrics["latest"].get("payout_ratio"))
    if len(paid_years) < 3:
        return {"applicable": False, "reason": "needs dividends in at least 3 of the last 4 fiscal years"}
    if payout is not None and payout > 110:
        return {"applicable": False, "reason": f"payout ratio {payout:.0f}% exceeds earnings; dividend not sustainable "
                "enough for a dividend discount model"}
    ke, g = market.default_cost_of_equity, market.default_terminal_growth
    d0 = ttm_dps(divs, date.today()) or paid_years[-1]
    d1 = d0 * (1 + g / 100)
    value = d1 / ((ke - g) / 100)
    note = "Most informative for mature, high-payout companies; understates value when profits are reinvested at high returns."
    return {"applicable": True, "value_per_share": value, "assumptions": {"d0": d0, "growth": g, "cost_of_equity": ke},
            "dps_history": [{"period": lbl, "dps": v} for lbl, v in zip(metrics["annual"]["labels"], dps)],
            "formula": "Value = D₀ × (1 + g) / (kₑ − g)", "limitations": [note],
            "low_payout_warning": payout is not None and payout < 30}


def justified_pb(metrics: dict[str, Any], market) -> dict[str, Any]:
    roe_vals = [c["value"] for c in metrics["annual"]["series"].get("roe", [])[-3:] if c["value"] is not None]
    bvps = _v(metrics["latest"].get("book_value_per_share"))
    if len(roe_vals) < 2 or not bvps or bvps <= 0:
        return {"applicable": False, "reason": "needs ≥2 years of ROE and a positive book value per share"}
    roe = sum(roe_vals) / len(roe_vals)
    ke, g = market.default_cost_of_equity, market.default_terminal_growth
    if roe <= g:
        return {"applicable": False, "reason": "average ROE is below the assumed growth rate; formula not meaningful"}
    pb = (roe - g) / (ke - g)
    return {"applicable": True, "justified_pb": pb, "value_per_share": pb * bvps,
            "assumptions": {"avg_roe": roe, "cost_of_equity": ke, "growth": g, "bvps": bvps},
            "formula": "Justified P/B = (ROE − g) / (kₑ − g); value = Justified P/B × BVPS",
            "limitations": ["Assumes recent average ROE is sustainable for the long run."]}


def fair_value_range(price: Optional[float], estimates: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [e["value_per_share"] for e in estimates if is_num(e.get("value_per_share")) and e["value_per_share"] > 0]
    if price is None or len(vals) < 2:
        return {"label": "Cannot reliably assess", "low": None, "mid": None, "high": None, "n_methods": len(vals),
                "reason": "fewer than two independent valuation methods were applicable" if price else "no price"}
    if len(vals) >= 4:
        low, high = F.percentile(vals, 25), F.percentile(vals, 75)
    else:
        low, high = min(vals), max(vals)
    mid = F.median(vals)
    width = (high - low) / mid * 100 if mid else None
    if price < low:
        label = "Potentially undervalued"
    elif price > high:
        label = "Potentially overvalued"
    else:
        label = "Within estimated fair-value range"
    return {"label": label, "low": low, "mid": mid, "high": high, "n_methods": len(vals),
            "upside_to_mid_pct": (mid / price - 1) * 100 if mid else None,
            "range_width_pct": width,
            "wide": width is not None and width > 80,
            "reason": "Methods disagree widely, so treat this range with caution." if width and width > 80 else None}
