"""Provider registry: provider selection, cache-first reads, stale fallback on failure."""
from __future__ import annotations

import copy
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from .. import config, db
from ..markets import market_for_symbol
from ..normalize import needs_fx, normalize_bundle
from .base import ProviderError
from .sample import SampleProvider

log = logging.getLogger("stockiq.registry")

# Bump when provider field mappings change so older raw cache entries are re-fetched.
RAW_SCHEMA = 2

SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^&\-]{1,24}$")

_providers: dict[str, Any] = {}


def providers() -> dict[str, Any]:
    if not _providers:
        for name in config.PROVIDERS:
            try:
                if name == "yahoo" and not config.OFFLINE:
                    from .yahoo import YahooProvider
                    _providers["yahoo"] = YahooProvider()
                elif name == "sample":
                    _providers["sample"] = SampleProvider()
            except Exception as e:  # e.g. yfinance missing
                log.error("Provider %s unavailable: %s", name, e)
        _providers.setdefault("sample", SampleProvider())
    return _providers


def provider_status() -> list[dict[str, Any]]:
    return [{"name": n, "label": p.source_label} for n, p in providers().items()]


def _chain(symbol: str) -> list[Any]:
    return [p for p in providers().values() if p.supports(symbol)]


def validate_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not SYMBOL_RE.match(s):
        raise ValueError("Invalid symbol format")
    market_for_symbol(s)  # raises UnsupportedMarket (a ValueError) for exchanges without market rules
    return s


def _freshness(fetched_at: float, ttl: int, served_from: str, error: Optional[str] = None) -> dict[str, Any]:
    age = time.time() - fetched_at
    return {"retrieved_at": fetched_at, "age_seconds": age, "ttl_seconds": ttl,
            "stale": age > ttl or served_from == "stale-cache", "served_from": served_from, "error": error}


def get_bundle(symbol: str, force: bool = False) -> dict[str, Any]:
    """Normalised fundamentals bundle + freshness metadata."""
    b = _get_bundle(symbol, force)
    if b.get("is_sample"):  # synthetic data never goes stale
        for k in ("freshness", "quote_freshness"):
            if b.get(k):
                b[k] = {**b[k], "stale": False, "served_from": "sample"}
    return b


def _get_bundle(symbol: str, force: bool = False) -> dict[str, Any]:
    symbol = validate_symbol(symbol)
    key = f"fund:{symbol}"
    cached = db.cache_get(key)
    ttl = config.TTL["fundamentals"]
    # The cache holds the provider's raw (un-normalised) bundle; normalisation is cheap and re-run on
    # every read so improvements to it apply without re-fetching.
    # Bundles cached before currency conversion existed lack FX data: refetch those.
    usable = cached and cached["payload"].get("_schema") == RAW_SCHEMA and not (
        needs_fx(cached["payload"]) and "fx" not in cached["payload"])
    if usable and not force and time.time() - cached["fetched_at"] < ttl:
        bundle = normalize_bundle(cached["payload"], db.import_get(symbol))
        bundle["freshness"] = _freshness(cached["fetched_at"], ttl, "cache")
        _maybe_refresh_quote(symbol, bundle)
        return bundle

    errors = []
    for p in _chain(symbol):
        try:
            raw = p.fundamentals(symbol)
        except ProviderError as e:
            errors.append(f"{p.source_label}: {e}")
            continue
        prices = raw.pop("_prices", [])
        raw["quote_retrieved_at"] = time.time()
        raw["_schema"] = RAW_SCHEMA
        fetched = db.cache_put(key, "fundamentals", raw, p.name)
        db.cache_put(f"prices:{symbol}", "prices", {"prices": prices}, p.name)
        bundle = normalize_bundle(copy.deepcopy(raw), db.import_get(symbol))
        bundle["freshness"] = _freshness(fetched, ttl, "live")
        bundle["quote_freshness"] = _freshness(fetched, config.TTL["quote"], "live")
        return bundle

    if cached:
        bundle = normalize_bundle(cached["payload"], db.import_get(symbol))
        bundle["freshness"] = _freshness(cached["fetched_at"], ttl, "stale-cache", "; ".join(errors))
        qt = bundle.get("quote_retrieved_at") or cached["fetched_at"]
        bundle["quote_freshness"] = _freshness(qt, config.TTL["quote"], "stale-cache", "; ".join(errors))
        return bundle
    not_found = any("not found" in e.lower() for e in errors) or not _chain(symbol)
    raise ProviderError("; ".join(errors) or f"No provider supports {symbol}",
                        retryable=not not_found, not_found=not_found)


def _maybe_refresh_quote(symbol: str, bundle: dict[str, Any]) -> None:
    """Refresh just the quote when the cached quote is older than the quote TTL."""
    # A newer quote may be cached separately from the (older) fundamentals.
    qc = db.cache_get(f"quote:{symbol}")
    qt = bundle.get("quote_retrieved_at") or bundle["freshness"]["retrieved_at"]
    if qc and qc["fetched_at"] > qt:
        bundle["quote"].update({k: v for k, v in qc["payload"].items() if v is not None})
        qt = qc["fetched_at"]
    bundle["quote_retrieved_at"] = qt
    if time.time() - qt < config.TTL["quote"] or bundle.get("is_sample"):
        bundle["quote_freshness"] = _freshness(qt, config.TTL["quote"], "cache")
        return
    p = providers().get(bundle.get("provider"))
    if p is None or not hasattr(p, "quote"):
        bundle["quote_freshness"] = _freshness(qt, config.TTL["quote"], "cache")
        return
    try:
        q = p.quote(symbol)
        fetched = db.cache_put(f"quote:{symbol}", "quote", q, p.name)
        bundle["quote"].update({k: v for k, v in q.items() if v is not None})
        bundle["quote_retrieved_at"] = fetched
        bundle["quote_freshness"] = _freshness(fetched, config.TTL["quote"], "live")
    except ProviderError as e:
        bundle["quote_freshness"] = _freshness(qt, config.TTL["quote"], "stale-cache", str(e))


FX_TTL = 6 * 3600


def fx_rate(pair: str) -> dict[str, Any]:
    """Latest daily close of a currency pair such as USDINR (Yahoo "USDINR=X"), cached for 6 hours.
    Used to add holdings in different currencies together; never used to restate statements."""
    key = f"fx:{pair}"
    cached = db.cache_get(key)
    if cached and time.time() - cached["fetched_at"] < FX_TTL:
        return {**cached["payload"], "served_from": "cache"}
    if not config.OFFLINE:
        try:
            import yfinance as yf

            from .yahoo import _throttle
            _throttle()
            h = yf.Ticker(f"{pair}=X").history(period="5d")
            closes = [(i, float(r["Close"])) for i, r in h.iterrows() if r["Close"] == r["Close"]]
            if closes:
                when, rate = closes[-1]
                payload = {"pair": pair, "rate": round(rate, 4), "as_of": str(when.date()),
                           "source": "Yahoo Finance FX (daily close)"}
                db.cache_put(key, "fx", payload, "yahoo")
                return {**payload, "served_from": "live"}
        except Exception as e:  # fall back to an older cached rate below
            log.warning("FX %s failed: %s", pair, e)
    if cached:
        return {**cached["payload"], "served_from": "stale-cache"}
    raise ProviderError(f"No exchange rate available for {pair}.", retryable=True)


def get_prices(symbol: str) -> dict[str, Any]:
    symbol = validate_symbol(symbol)
    key = f"prices:{symbol}"
    cached = db.cache_get(key)
    if cached and time.time() - cached["fetched_at"] < config.TTL["prices"]:
        return {"prices": cached["payload"]["prices"],
                "freshness": _freshness(cached["fetched_at"], config.TTL["prices"], "cache")}
    try:
        get_bundle(symbol, force=True)
        cached = db.cache_get(key)
        return {"prices": cached["payload"]["prices"],
                "freshness": _freshness(cached["fetched_at"], config.TTL["prices"], "live")}
    except ProviderError as e:
        if cached:
            return {"prices": cached["payload"]["prices"],
                    "freshness": _freshness(cached["fetched_at"], config.TTL["prices"], "stale-cache", str(e))}
        raise


def search(query: str) -> dict[str, Any]:
    q = (query or "").strip()
    if not q or len(q) > 60:
        return {"results": [], "errors": []}
    key = f"search:{q.lower()}"
    cached = db.cache_get(key)
    if cached and time.time() - cached["fetched_at"] < config.TTL["search"]:
        return cached["payload"]
    rows, errors = [], []
    for name, p in providers().items():
        try:
            rows.extend(p.search(q))
        except ProviderError as e:
            errors.append(str(e))
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = re.sub(r"[^a-z0-9]", "", (r["name"] or "").lower().replace("limited", "ltd"))
        g = groups.setdefault(k, {"name": r["name"], "sector": r.get("sector"), "industry": r.get("industry"),
                                  "market": r.get("market"), "is_sample": r.get("is_sample", False),
                                  "listings": []})
        g["listings"].append({"symbol": r["symbol"], "exchange": r.get("exchange")})
        g["sector"] = g["sector"] or r.get("sector")
        g["industry"] = g["industry"] or r.get("industry")
    results = []
    for g in groups.values():
        # Prefer the NSE listing as the primary symbol for Indian companies.
        order = {"NSE": 0, "BSE": 1}
        g["listings"].sort(key=lambda x: order.get(x.get("exchange") or "", 2))
        g["primary_symbol"] = g["listings"][0]["symbol"]
        g["duplicate_listings"] = len(g["listings"]) > 1
        results.append(g)
    # Indian listings first (primary market), then the rest in provider order.
    results.sort(key=lambda g: (g["market"] != "IN", g.get("is_sample", False)))
    payload = {"results": results[:12], "errors": errors}
    if results and not errors:
        db.cache_put(key, "search", payload, "mixed")
    return payload


def get_peers(symbol: str, bundle: dict[str, Any], limit: int = 6) -> dict[str, Any]:
    symbol = validate_symbol(symbol)
    key = f"peers:{symbol}"
    cached = db.cache_get(key)
    if cached and time.time() - cached["fetched_at"] < config.TTL["peers"]:
        out = copy.deepcopy(cached["payload"])
        out["freshness"] = _freshness(cached["fetched_at"], config.TTL["peers"], "cache")
        return out
    p = providers().get("yahoo")
    if bundle.get("is_sample") or p is None:
        return {"peers": [], "method": None, "note": "Peer discovery is unavailable for sample companies/offline mode.",
                "freshness": None}
    industry = bundle["profile"].get("industry")
    region = market_for_symbol(symbol).screener_region
    try:
        candidates = p.peers(symbol, industry, region)
    except ProviderError as e:
        if cached:
            out = cached["payload"]
            out["freshness"] = _freshness(cached["fetched_at"], config.TTL["peers"], "stale-cache", str(e))
            return out
        return {"peers": [], "method": None, "note": f"Peer lookup failed: {e}", "freshness": None}
    self_name = (bundle["profile"].get("name") or "").strip().lower()
    base = symbol.split(".")[0]
    candidates = [c for c in candidates if (c.get("name") or "").strip().lower() != self_name
                  and (c.get("symbol") or "").split(".")[0] != base]
    selected = candidates[:limit]
    def fetch(c):
        try:
            d = p.peer_details(c["symbol"])
            d["exchange"] = c.get("exchange")
            return d
        except ProviderError:
            return c
    # A few concurrent requests (each still passes the provider's throttle) keep cold loads reasonable.
    with ThreadPoolExecutor(max_workers=3) as ex:
        details = list(ex.map(fetch, selected))
    payload = {
        "peers": details,
        "method": f"Largest {len(details)} companies by market cap in Yahoo industry '{industry}' "
                  f"(region {region.upper()}), excluding this company. NSE/BSE duplicates collapsed.",
        "source": "Yahoo Finance screener + quote summary (provider-reported ratios, trailing twelve months)",
        "note": "Peer ratios are as reported by Yahoo, not recalculated; definitions may differ slightly "
                "from this app's own calculations.",
    }
    fetched = db.cache_put(key, "peers", payload, "yahoo")
    payload["freshness"] = _freshness(fetched, config.TTL["peers"], "live")
    return payload
