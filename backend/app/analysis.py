"""Orchestrates provider data -> metrics -> valuation -> red flags -> scores -> narrative."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from . import db
from .engine import valuation as V
from .engine.metrics import compute_metrics
from .engine.narrative import build_narrative
from .engine.quarterly import quarter_flags, quarterly_check
from .engine.redflags import compute_flags
from .engine.scoring import load_config, score_company, select_profile
from .markets import market_for_symbol
from .providers import registry
from .providers.base import CANONICAL_FIELDS, ProviderError

log = logging.getLogger("stockiq.analysis")


def _returns(prices: list[list[Any]]) -> dict[str, Any]:
    """Price return and total shareholder return (adjusted close includes dividends)."""
    if not prices:
        return {}
    end_d = date.fromisoformat(prices[-1][0])
    out = {}
    for label, yrs in (("1y", 1), ("3y", 3), ("5y", 5), ("10y", 10)):
        start = (end_d - timedelta(days=int(365.25 * yrs))).isoformat()
        if prices[0][0] > start:
            out[label] = None
            continue
        p0 = V.price_on_or_before(prices, start)
        row0 = next((p for p in reversed(prices) if p[0] <= start), None)
        if not p0 or not row0:
            out[label] = None
            continue
        pr = prices[-1][1] / row0[1] - 1
        tsr = prices[-1][2] / row0[2] - 1 if row0[2] else None
        out[label] = {"price_return_pct": pr * 100, "tsr_pct": tsr * 100 if tsr is not None else None,
                      "tsr_cagr_pct": ((1 + tsr) ** (1 / yrs) - 1) * 100 if (tsr is not None and tsr > -1) else None,
                      "from": row0[0], "to": prices[-1][0]}
    return out


def _links(symbol: str, bundle: dict[str, Any]) -> list[dict[str, str]]:
    base = symbol.split(".")[0]
    links = []
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        links += [
            {"label": "NSE quote & filings", "url": f"https://www.nseindia.com/get-quotes/equity?symbol={base}"},
            {"label": "NSE corporate announcements", "url": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"},
            {"label": "BSE corporate announcements", "url": "https://www.bseindia.com/corporates/ann.html"},
            {"label": "Screener.in (10-yr financials, manual reading)", "url": f"https://www.screener.in/company/{base}/consolidated/"},
        ]
    p = bundle.get("profile") or {}
    if p.get("ir_website"):
        links.append({"label": "Investor relations", "url": p["ir_website"]})
    elif p.get("website"):
        links.append({"label": "Company website", "url": p["website"]})
    return links


def _statements(bundle: dict[str, Any]) -> dict[str, Any]:
    def table(periods):
        rows = {"income": [], "balance": [], "cashflow": []}
        for key, (stmt, label, kind) in CANONICAL_FIELDS.items():
            vals = [p["fields"].get(key) for p in periods]
            if any(v is not None for v in vals):
                rows[stmt].append({"key": key, "label": label, "kind": kind, "values": vals})
        return {"labels": [p["label"] for p in periods], "period_ends": [p["period_end"] for p in periods],
                "notes": [p.get("notes", []) for p in periods], "rows": rows}
    return {"annual": table(bundle.get("annual") or []), "quarterly": table(bundle.get("quarterly") or [])}


def analyse(symbol: str, *, force: bool = False, dcf_overrides: Optional[dict[str, Any]] = None,
            include_peers: bool = True) -> dict[str, Any]:
    bundle = registry.get_bundle(symbol, force=force)
    symbol = bundle["symbol"]
    market = market_for_symbol(symbol)
    metrics = compute_metrics(bundle, market.statutory_tax_rate)
    try:
        pr = registry.get_prices(symbol)
        prices, price_fresh = pr["prices"], pr["freshness"]
    except ProviderError as e:
        prices, price_fresh = [], {"error": str(e)}

    peers_payload = {"peers": [], "method": None, "note": "skipped"}
    if include_peers:
        try:
            peers_payload = registry.get_peers(symbol, bundle)
        except Exception as e:  # peers are optional
            log.warning("peers failed for %s: %s", symbol, e)
            peers_payload = {"peers": [], "method": None, "note": f"Peer lookup failed: {e}"}
    peers = V.sanitize_peers(peers_payload.get("peers") or [])
    peers_payload = {**peers_payload, "peers": peers}

    val = V.multiples(bundle, metrics)
    val["history"] = V.historical_multiples(bundle, metrics, prices)
    val["dcf"] = V.dcf_analysis(bundle, metrics, market, dcf_overrides, shares=val["shares"])
    nd = metrics["latest"].get("net_debt", {}).get("value")
    val["comps"] = V.comps_valuation(metrics, peers, val["shares"], nd)
    val["ddm"] = V.ddm(bundle, metrics, market)
    val["justified_pb"] = V.justified_pb(metrics, market)
    estimates = []
    if val["dcf"].get("applicable"):
        estimates.append({"method": "DCF (base case)", "value_per_share": val["dcf"]["result"].get("value_per_share")})
    for m in val["comps"]["methods"]:
        estimates.append(m)
    if val["ddm"].get("applicable") and not val["ddm"].get("low_payout_warning"):
        estimates.append({"method": "Dividend discount model", "value_per_share": val["ddm"]["value_per_share"]})
    if val["justified_pb"].get("applicable") and metrics["is_financial"]:
        estimates.append({"method": "Justified P/B", "value_per_share": val["justified_pb"]["value_per_share"]})
    val["estimates"] = estimates
    val["fair_value"] = V.fair_value_range(val["price"], estimates)
    major = [r["metric"] for r in val["reconciliation"] if r.get("major")]
    if major:
        val["fair_value"]["data_warning"] = (f"Calculated {', '.join(major)} differs from the provider's figure by more than 20%, "
                                             "so one of the inputs (often balance-sheet equity) may be misstated. "
                                             "Treat this valuation with extra caution.")

    data_quality = list(bundle.get("data_quality", []))
    for r in val["reconciliation"]:
        if r.get("major"):
            data_quality.insert(0, {"period": "latest", "check": f"reconciliation_{r['metric']}", "severity": "high",
                                    "message": f"{r['metric']}: calculated {r['calculated']:.2f} vs provider "
                                               f"{r['provider']:.2f} ({r['diff_pct']:+.0f}%). {r.get('explanation') or ''}"})
    for k, g in metrics["growth"].items():
        if g.get("base_effect"):
            data_quality.append({"period": g.get("period"), "check": f"base_effect_{k}", "severity": "low",
                                 "message": f"{k.replace('_', ' ')}: {g['reason']}. Excluded from scoring."})

    notes = db.notes_get(symbol)
    cfg = load_config()
    _, profile_cfg = select_profile(cfg, bundle.get("profile") or {})
    flags = compute_flags(bundle, metrics, val, notes, profile_cfg)
    quarterly = quarterly_check(bundle, metrics["is_financial"])
    flags += quarter_flags(quarterly)
    flags.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}[f["severity"]])
    scores = score_company(bundle, metrics, val, flags, peers, notes, cfg, market=market.code)
    name = (bundle.get("profile") or {}).get("name") or symbol
    narrative = build_narrative(name, metrics, val, scores, flags)

    divs = bundle.get("dividends") or []
    dps = V.dividends_per_fy(divs, metrics["annual"]["period_ends"])
    watch = {w["symbol"] for w in db.watchlist_list()}
    return {
        "symbol": symbol,
        "is_sample": bundle.get("is_sample", False),
        "source_label": bundle.get("source_label"),
        "provider": bundle.get("provider"),
        "market": {"code": market.code, "name": market.name, "currency": market.currency,
                   "display_units": market.display_units, "notes": list(market.notes)},
        "profile": bundle.get("profile"),
        "quote": bundle.get("quote"),
        "freshness": bundle.get("freshness"),
        "quote_freshness": bundle.get("quote_freshness"),
        "price_freshness": price_fresh,
        "data_quality": data_quality,
        "statements": _statements(bundle),
        "metrics": metrics,
        "valuation": val,
        "peers": peers_payload,
        "flags": flags,
        "quarterly": quarterly,
        "imported": bundle.get("imported"),
        "scores": scores,
        "narrative": narrative,
        "holders": bundle.get("holders"),
        "notes": notes,
        "news": bundle.get("news") or [],
        "links": _links(symbol, bundle),
        "dividends": {"per_fy": [{"period": l, "dps": d} for l, d in zip(metrics["annual"]["labels"], dps)],
                      "history": divs[-40:], "splits": bundle.get("splits") or []},
        "returns": _returns(prices),
        "in_watchlist": symbol in watch,
        "disclaimer": "Research and decision support only. Not investment advice, not a recommendation, and no "
                      "guarantee of future returns. Quotes are delayed. Verify figures against company filings.",
    }


def summary_row(a: dict[str, Any]) -> dict[str, Any]:
    """Compact row used for watchlist/compare/saved."""
    s, m, L = a["scores"], a["valuation"]["multiples"], a["metrics"]["latest"]
    g = a["metrics"]["growth"]
    gv = lambda k: None if (g.get(k) or {}).get("base_effect") else (g.get(k) or {}).get("value")  # noqa: E731
    lv = lambda k: (L.get(k) or {}).get("value")  # noqa: E731
    return {
        "symbol": a["symbol"], "name": a["profile"].get("name"), "is_sample": a["is_sample"],
        "sector": a["profile"].get("sector"), "industry": a["profile"].get("industry"),
        "price": a["quote"].get("price"), "change_pct": a["quote"].get("change_pct"),
        "currency": a["quote"].get("currency"), "market_cap": a["valuation"]["market_cap"],
        "decision_label": s["decision_label"],
        "business_quality": s["verdicts"]["business_quality"]["score"],
        "business_quality_label": s["verdicts"]["business_quality"]["label"],
        "financial_risk": s["verdicts"]["financial_risk"]["score"],
        "financial_risk_label": s["verdicts"]["financial_risk"]["label"],
        "valuation_score": s["verdicts"]["valuation"]["score"],
        "valuation_label": s["verdicts"]["valuation"]["label"],
        "composite": s["composite"]["score"], "completeness": s["data_completeness"],
        "confidence": s["confidence"]["label"], "model": s["model"],
        "metrics": {
            "revenue_cagr_3y": gv("revenue_cagr_3y") if gv("revenue_cagr_3y") is not None else gv("revenue_cagr_max"),
            "eps_cagr_3y": gv("eps_cagr_3y") if gv("eps_cagr_3y") is not None else gv("eps_cagr_max"),
            "roe": lv("roe"), "roce": lv("roce"), "operating_margin": lv("operating_margin"),
            "net_margin": lv("net_margin"), "debt_to_equity": lv("debt_to_equity"),
            "interest_coverage": lv("interest_coverage"), "cash_conversion": lv("cash_conversion"),
            "fcf_margin": lv("fcf_margin"),
            "pe": m["pe"]["value"], "pb": m["pb"]["value"], "ev_ebitda": m["ev_ebitda"]["value"],
            "dividend_yield": m["dividend_yield"]["value"], "fcf_yield": m["fcf_yield"]["value"],
        },
        "flags_high": sum(1 for f in a["flags"] if f["severity"] == "high"),
        "flags_total": len(a["flags"]),
        "latest_period": (a["metrics"]["annual"]["labels"] or [None])[-1],
        "retrieved_at": (a.get("freshness") or {}).get("retrieved_at"),
    }
