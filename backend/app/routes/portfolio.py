"""Portfolio holdings, import and FX."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from .. import db
from ..portfolio import HoldingsError, parse_holdings, resolve_symbol
from ..providers import registry
from ..providers.base import ProviderError
from ._shared import read_upload as _read_upload

log = logging.getLogger("stockiq")
router = APIRouter()


# ---------------- Portfolio ----------------
class HoldingIn(BaseModel):
    symbol: str
    quantity: float = Field(..., gt=0)
    avg_cost: Optional[float] = Field(None, ge=0)


@router.get("/api/portfolio")
def portfolio():
    return {"holdings": db.holdings_list()}


@router.post("/api/portfolio")
def portfolio_add(body: HoldingIn):
    sym = registry.validate_symbol(body.symbol)
    try:
        name = registry.get_bundle(sym)["profile"]["name"]
    except ProviderError as e:
        if e.not_found:
            raise HTTPException(404, f"{sym} was not found.")
        name = None
    db.holding_put(sym, name, body.quantity, body.avg_cost, "manual")
    return {"ok": True}


@router.get("/api/fx")
def fx(pair: str = Query(..., pattern="^[A-Z]{6}$")):
    return registry.fx_rate(pair)


@router.post("/api/portfolio/import")
def portfolio_import(file: UploadFile = File(...), mode: str = Query("replace", pattern="^(replace|merge)$"),
                     market: str = Query("IN", pattern="^(IN|US)$")):
    try:
        parsed = parse_holdings(_read_upload(file), file.filename or "holdings")
    except HoldingsError as e:
        raise HTTPException(422, str(e))
    # Match every row first; existing holdings are only touched once we know what replaces them.
    source = file.filename or "import"
    rows, added, unresolved = [], [], []
    for it in parsed["items"]:
        sym, note = resolve_symbol(it, registry.search, market)
        if not sym:
            unresolved.append({"name": it["raw"], "reason": note})
            continue
        rows.append((sym, it.get("name") or it["raw"], it["quantity"], it.get("avg_cost"), source))
        added.append({"symbol": sym, "from": it["raw"], "note": note})
    if mode == "replace":
        if not rows:
            raise HTTPException(422, f"None of the {len(unresolved)} row(s) in this file could be matched to a listed "
                                     "company, so your existing holdings were kept. Check the file has ticker symbols "
                                     "(or that you are online, if it only has company names).")
        db.holdings_replace(rows)
    else:
        for r in rows:
            db.holding_put(*r)
    return {"added": added, "unresolved": unresolved, "skipped": parsed["skipped"]}


@router.delete("/api/portfolio/{symbol}")
def portfolio_remove(symbol: str):
    db.holding_delete(registry.validate_symbol(symbol))
    return {"ok": True}


@router.delete("/api/portfolio")
def portfolio_clear():
    db.holdings_clear()
    return {"ok": True}
