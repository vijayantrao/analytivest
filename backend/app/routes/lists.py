"""Watchlist and saved snapshots."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..analysis import analyse, summary_row
from ..providers import registry
from ..providers.base import ProviderError

log = logging.getLogger("stockiq")
router = APIRouter()


class WatchIn(BaseModel):
    symbol: str
    note: Optional[str] = Field(None, max_length=500)


class SavedIn(BaseModel):
    symbol: str
    label: Optional[str] = Field(None, max_length=120)



@router.get("/api/watchlist")
def watchlist(details: bool = False):
    items = db.watchlist_list()
    if details:
        for it in items:
            try:
                it["summary"] = summary_row(analyse(it["symbol"], include_peers=True))
            except ProviderError as e:
                it["error"] = str(e)
    return {"items": items}


@router.post("/api/watchlist")
def watch_add(body: WatchIn):
    sym = registry.validate_symbol(body.symbol)
    try:
        name = registry.get_bundle(sym)["profile"]["name"]
    except ProviderError:
        name = None
    db.watchlist_add(sym, name, body.note)
    return {"ok": True}


@router.delete("/api/watchlist/{symbol}")
def watch_remove(symbol: str):
    db.watchlist_remove(registry.validate_symbol(symbol))
    return {"ok": True}


@router.get("/api/saved")
def saved_list():
    return {"items": db.saved_list()}


@router.post("/api/saved")
def saved_add(body: SavedIn):
    a = analyse(registry.validate_symbol(body.symbol))
    payload = {"summary": summary_row(a), "verdicts": a["scores"]["verdicts"], "flags": a["flags"],
               "narrative": a["narrative"], "fair_value": a["valuation"]["fair_value"],
               "source_label": a["source_label"], "freshness": a["freshness"]}
    return {"id": db.saved_add(a["symbol"], body.label, payload)}


@router.get("/api/saved/{id_}")
def saved_get(id_: int):
    s = db.saved_get(id_)
    if not s:
        raise HTTPException(404, "Not found")
    return s


@router.delete("/api/saved/{id_}")
def saved_delete(id_: int):
    db.saved_delete(id_)
    return {"ok": True}
