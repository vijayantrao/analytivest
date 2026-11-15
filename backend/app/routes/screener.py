"""Stock screener scans and the ML anomaly check."""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import config, db, screener
from ..analysis import analyse
from ..markets import market_for_symbol
from ..ml import anomaly
from ..ml.features import extract as extract_ml_features
from ..providers import registry

log = logging.getLogger("stockiq")
router = APIRouter()


# ---------------- Stock screener ----------------
class ScanIn(BaseModel):
    size: int = Field(100, ge=10, le=500)
    include_peers: bool = False
    market: str = Field("IN", pattern="^(IN|US)$")


def _ml_scores(scan_rows: list[dict[str, Any]], market: str) -> tuple[Optional[anomaly.Fitted], dict[str, dict[str, Any]]]:
    return anomaly.scores_for(scan_rows, market)


@router.get("/api/screener")
def screener_results(market: str = Query("IN", pattern="^(IN|US)$")):
    rows = [r for r in db.scan_list() if screener.market_of(r) == market]
    _, ml = _ml_scores(rows, market)
    return {"results": rows, "job": db.job_latest("scan"),
            "ml": {k: {"percentile": v["percentile"], "level": v["level"], "reasons": [r["text"] for r in v["reasons"]]}
                   for k, v in ml.items() if v["available"]},
            "estimates": {str(n): {"fast": screener.estimate_minutes(n, False), "peers": screener.estimate_minutes(n, True)}
                          for n in (50, 100, 200, 500)}}


@router.get("/api/ml/anomalies")
def ml_anomalies(market: str = Query("IN", pattern="^(IN|US)$")):
    """The whole scanned universe of one market ranked by the earnings-quality anomaly model."""
    scan_rows = db.scan_list()
    fitted, scores = _ml_scores(scan_rows, market)
    if fitted is None:
        usable = sum(1 for r in anomaly.universe_rows(scan_rows, market) if anomaly.usable(r["features"]))
        return {"available": False, "model": anomaly.MODEL_CARD,
                "reason": f"The model needs at least {anomaly.MIN_UNIVERSE} non-financial companies with enough data "
                          f"from a screener scan; {usable} available. Run a scan of 100+ companies."}
    names = {r["symbol"]: r["summary"].get("name") for r in scan_rows}
    flags = {r["symbol"]: r["summary"].get("flag_ids", []) for r in scan_rows}
    ranked = sorted(({"symbol": k, "name": names.get(k), "rule_flags": flags.get(k, []), **v}
                     for k, v in scores.items() if v["available"]), key=lambda x: -x["score"])
    return {"available": True, "n": fitted.n, "model": anomaly.MODEL_CARD, "results": ranked}


@router.get("/api/company/{symbol}/anomaly")
def company_anomaly(symbol: str):
    sym = registry.validate_symbol(symbol)
    market = market_for_symbol(sym)
    scan_rows = db.scan_list()
    fitted, rows = anomaly.fitted_for(scan_rows, market.code)
    if fitted is None:
        return {"available": False, "model": anomaly.MODEL_CARD, "market": market.code,
                "reason": f"Run a screener scan of 100+ {market.name} companies first: the model compares a company "
                          f"only with its own market and needs at least {anomaly.MIN_UNIVERSE} scanned companies."}
    row = next((r for r in rows if r["symbol"] == sym), None)
    features = row["features"] if row else extract_ml_features(analyse(sym))
    if features is None:
        return {"available": False, "model": anomaly.MODEL_CARD,
                "reason": "Not applied to banks and other financials: their accounts do not fit these features."}
    return {**anomaly.score(fitted, features), "n": fitted.n, "in_universe": row is not None, "market": market.code,
            "market_name": market.name, "model": anomaly.MODEL_CARD}


@router.post("/api/screener/scan")
def screener_scan(body: ScanIn):
    if config.OFFLINE:
        raise HTTPException(400, "Scanning needs the live data provider (offline mode is on).")
    j = db.job_latest("scan")
    if j and j["status"] in ("queued", "running"):
        raise HTTPException(409, "A scan is already running.")
    return {"job_id": screener.start(body.size, body.include_peers, body.market)}


@router.post("/api/screener/cancel")
def screener_cancel():
    screener.cancel()
    return {"ok": True}
