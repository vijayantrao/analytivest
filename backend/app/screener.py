"""Stock screener: scan a universe of the largest Indian listed companies and filter them by verdicts.

The universe comes from Yahoo's free equity screener: the largest companies by market cap in one market
(India: NSE preferred over BSE duplicates; US: NYSE/NASDAQ listings, one share class per company). Scanning runs every company through the same analysis engine
in a background job, politely throttled, and stores each summary so filtering is instant afterwards.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from . import db
from .markets import MARKETS, market_for_symbol
from .ml.features import extract as extract_features

log = logging.getLogger("analytivest.screener")
_lock = threading.Lock()
_cancel = threading.Event()
RESCAN_AFTER = 24 * 3600


def market_of(row: dict[str, Any]) -> str:
    """Market of a stored scan row (rows from before US support carry no market field)."""
    return row["summary"].get("market") or market_for_symbol(row["symbol"]).code


def universe(size: int, market: str = "IN") -> list[dict[str, Any]]:
    import yfinance as yf
    from yfinance import EquityQuery

    from .providers.yahoo import _throttle
    m = MARKETS[market]
    q = EquityQuery("eq", ["region", m.screener_region])
    seen: dict[str, dict[str, Any]] = {}
    offset = 0
    while len(seen) < size and offset < size * 3:
        _throttle()
        res = yf.screen(q, sortField="intradaymarketcap", sortAsc=False, size=min(250, size * 2), offset=offset)
        quotes = res.get("quotes", [])
        if not quotes:
            break
        for x in quotes:
            if x.get("quoteType") not in (None, "EQUITY"):
                continue
            if market == "US" and x.get("exchange") not in m.exchanges:  # skip OTC / pink-sheet listings
                continue
            name = (x.get("longName") or x.get("shortName") or x.get("symbol") or "").strip()
            key = name.lower()
            row = {"symbol": x.get("symbol"), "name": name, "market_cap": x.get("marketCap"), "exchange": x.get("exchange")}
            if key in seen:  # same company twice: NSE over BSE; for US share classes keep the first (largest)
                if market == "IN" and x.get("exchange") == "NSI":
                    seen[key] = row
                continue
            seen[key] = row
        offset += len(quotes)
    rows = sorted(seen.values(), key=lambda r: -(r["market_cap"] or 0))
    return [r for r in rows if r["symbol"]][:size]


def _scan_one(symbol: str, include_peers: bool) -> dict[str, Any]:
    from .analysis import analyse, summary_row
    a = analyse(symbol, include_peers=include_peers)
    s = summary_row(a)
    s["peer_adjusted"] = include_peers
    s["fair_value"] = {k: a["valuation"]["fair_value"].get(k) for k in ("low", "mid", "high", "label")}
    s["flags"] = [f["title"] for f in a["flags"][:5]]
    s["flag_ids"] = [f["id"] for f in a["flags"]]
    s["ml_features"] = extract_features(a)  # None for banks/financials
    s["market"] = market_for_symbol(symbol).code
    return s


def run_scan(job_id: str, size: int, include_peers: bool, market: str = "IN") -> None:
    if not _lock.acquire(blocking=False):
        db.job_put(job_id, "scan", "error", 0, 0, "A scan is already running.", time.time(), time.time())
        return
    _cancel.clear()
    started = time.time()
    try:
        db.job_put(job_id, "scan", "running", 0, size, f"building the {MARKETS[market].name} universe", started)
        try:
            uni = universe(size, market)
        except Exception as e:
            db.job_put(job_id, "scan", "error", 0, size, f"Universe lookup failed: {e}", started, time.time())
            return
        fresh = {r["symbol"]: r for r in db.scan_list() if time.time() - r["scanned_at"] < RESCAN_AFTER
                 and r["summary"].get("peer_adjusted", False) == include_peers}
        done, failed = 0, 0
        for k, u in enumerate(uni):
            if _cancel.is_set():
                db.job_put(job_id, "scan", "cancelled", k, len(uni), f"cancelled after {k} companies", started, time.time())
                return
            db.job_put(job_id, "scan", "running", k, len(uni), f"analysing {u['name']}", started)
            if u["symbol"] in fresh:
                done += 1
                continue
            try:
                db.scan_put(u["symbol"], _scan_one(u["symbol"], include_peers))
                done += 1
            except Exception as e:
                failed += 1
                log.warning("scan %s failed: %s", u["symbol"], e)
        db.job_put(job_id, "scan", "done", len(uni), len(uni),
                   f"{done} companies scanned ({MARKETS[market].name})" + (f", {failed} failed" if failed else ""),
                   started, time.time())
    finally:
        _lock.release()


def start(size: int, include_peers: bool, market: str = "IN") -> str:
    job_id = f"scan-{uuid.uuid4().hex[:8]}"
    db.job_put(job_id, "scan", "queued", 0, size, "queued", time.time())
    threading.Thread(target=run_scan, args=(job_id, size, include_peers, market), daemon=True, name="scan").start()
    return job_id


def cancel() -> None:
    _cancel.set()


def estimate_minutes(size: int, include_peers: bool) -> float:
    per = 9 if include_peers else 5  # observed seconds per company on a cold cache
    return round(size * per / 60, 1)
