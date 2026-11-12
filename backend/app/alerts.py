"""Daily checks on watchlist and portfolio companies, producing alerts when something material changes.

Each check compares today's analysis summary with the previous snapshot:
new or resolved red flags, decision-label changes, score moves of 10+ points, valuation-label changes,
new quarterly results, and big price moves. The first check of a company only records a baseline.

Run from the app (scheduler thread or 'Check now'), or from Windows Task Scheduler with:
    .venv\\Scripts\\python -m app.alerts
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from . import db

log = logging.getLogger("analytivest.alerts")
_job_lock = threading.Lock()

SCORE_STEP = 10.0
PRICE_MOVE_PCT = 8.0


def snapshot_from_analysis(a: dict[str, Any]) -> dict[str, Any]:
    from .analysis import summary_row
    s = summary_row(a)
    fv = a["valuation"]["fair_value"]
    q = a.get("quarterly") or {}
    s.update({"flag_ids": {f["id"]: {"title": f["title"], "severity": f["severity"]} for f in a["flags"]},
              "fv_low": fv.get("low"), "fv_high": fv.get("high"),
              "quarter": q.get("latest") if q.get("available") else None, "quarter_verdict": q.get("verdict")})
    return s


def diff(prev: dict[str, Any], cur: dict[str, Any]) -> list[dict[str, Any]]:
    """Alerts implied by moving from snapshot `prev` to `cur` (pure function; unit-tested)."""
    out = []
    name = cur.get("name") or cur.get("symbol")

    def add(kind, severity, title, message):
        out.append({"kind": kind, "severity": severity, "title": title, "message": message})

    new_flags = set(cur.get("flag_ids", {})) - set(prev.get("flag_ids", {}))
    gone = set(prev.get("flag_ids", {})) - set(cur.get("flag_ids", {}))
    for fid in sorted(new_flags):
        f = cur["flag_ids"][fid]
        add("new_flag", f["severity"], f"{name}: new red flag", f["title"])
    for fid in sorted(gone):
        add("flag_resolved", "low", f"{name}: red flag cleared", prev["flag_ids"][fid]["title"])
    if prev.get("decision_label") and cur.get("decision_label") != prev.get("decision_label"):
        add("decision_change", "medium", f"{name}: verdict changed",
            f"{prev['decision_label']} → {cur['decision_label']}")
    for key, label, worse_up in (("business_quality", "Business quality", False), ("financial_risk", "Financial risk", True)):
        a, b = prev.get(key), cur.get(key)
        if a is not None and b is not None and abs(b - a) >= SCORE_STEP:
            worse = (b > a) if worse_up else (b < a)
            add("score_move", "medium" if worse else "low", f"{name}: {label.lower()} {'worsened' if worse else 'improved'}",
                f"{label} {a:.0f} → {b:.0f}")
    if prev.get("valuation_label") and cur.get("valuation_label") != prev.get("valuation_label"):
        add("valuation_change", "medium" if cur["valuation_label"] == "Potentially undervalued" else "low",
            f"{name}: valuation now '{cur['valuation_label']}'", f"Was '{prev['valuation_label']}'.")
    p0, p1 = prev.get("price"), cur.get("price")
    if p0 and p1:
        mv = (p1 / p0 - 1) * 100
        if abs(mv) >= PRICE_MOVE_PCT:
            add("price_move", "low", f"{name}: price {'up' if mv > 0 else 'down'} {abs(mv):.1f}%",
                f"₹{p0:,.2f} → ₹{p1:,.2f} since the last check.")
        low = cur.get("fv_low")
        if low and p1 < low <= p0:
            add("below_fair_range", "medium", f"{name}: price fell below the estimated fair-value range",
                f"Price ₹{p1:,.2f} vs range low ₹{low:,.2f}.")
    if cur.get("quarter") and prev.get("quarter") and cur["quarter"] != prev["quarter"]:
        sev = "medium" if cur.get("quarter_verdict") in ("Weak quarter", "Soft quarter") else "low"
        add("new_results", sev, f"{name}: new quarterly results ({cur['quarter']})", f"{cur.get('quarter_verdict')}.")
    return out


def check_symbol(symbol: str) -> list[dict[str, Any]]:
    from .analysis import analyse
    a = analyse(symbol)
    cur = snapshot_from_analysis(a)
    prev = db.snapshot_last(symbol)
    alerts = diff(prev["summary"], cur) if prev else []
    for al in alerts:
        db.alert_add(symbol, al["kind"], al["severity"], al["title"], al["message"])
    db.snapshot_put(symbol, cur)
    return alerts


def tracked_symbols() -> list[str]:
    syms = [w["symbol"] for w in db.watchlist_list()] + [h["symbol"] for h in db.holdings_list()]
    return sorted(set(syms))


def run_checks(job_id: Optional[str] = None, symbols: Optional[list[str]] = None) -> str:
    """Run checks for all tracked companies, recording progress in the jobs table."""
    job_id = job_id or f"alerts-{uuid.uuid4().hex[:8]}"
    symbols = symbols if symbols is not None else tracked_symbols()
    if not _job_lock.acquire(blocking=False):
        raise RuntimeError("A check is already running.")
    try:
        started = time.time()
        db.job_put(job_id, "alerts", "running", 0, len(symbols), "starting", started)
        new, errors = 0, []
        for k, s in enumerate(symbols):
            db.job_put(job_id, "alerts", "running", k, len(symbols), f"checking {s}", started)
            try:
                new += len(check_symbol(s))
            except Exception as e:  # keep going; report at the end
                log.warning("alert check %s failed: %s", s, e)
                errors.append(f"{s}: {e}")
        msg = f"{len(symbols)} companies checked, {new} new alert(s)" + (f", {len(errors)} failed" if errors else "")
        db.job_put(job_id, "alerts", "done", len(symbols), len(symbols), msg, started, time.time())
        db.setting_put("alerts_last_run", time.time())
        return job_id
    finally:
        _job_lock.release()


def start_background(job_id: str) -> None:
    threading.Thread(target=lambda: _safe_run(job_id), daemon=True, name="alerts-run").start()


def _safe_run(job_id: str) -> None:
    try:
        run_checks(job_id)
    except Exception as e:
        db.job_put(job_id, "alerts", "error", 0, 0, str(e), time.time(), time.time())


def scheduler_loop(stop: threading.Event) -> None:
    """While the app runs: once a day after the configured time (default 18:30, after market close)."""
    while not stop.wait(60 * 15):
        try:
            cfg = db.setting_get("alerts", {"enabled": True, "time": "18:30"})
            if not cfg.get("enabled", True):
                continue
            now = datetime.now()
            hh, mm = (int(x) for x in str(cfg.get("time", "18:30")).split(":"))
            last = db.setting_get("alerts_last_run")
            ran_today = last and datetime.fromtimestamp(last).date() == now.date()
            if not ran_today and (now.hour, now.minute) >= (hh, mm) and tracked_symbols():
                run_checks()
        except Exception as e:
            log.warning("alert scheduler: %s", e)


if __name__ == "__main__":  # for Windows Task Scheduler / manual runs
    logging.basicConfig(level=logging.INFO)
    jid = run_checks()
    print(db.job_get(jid)["message"])
