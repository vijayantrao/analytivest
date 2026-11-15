"""IPO records, offer-document upload and IPO analysis."""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from .. import config, db
from ..analysis import analyse
from ..engine.ipo import analyse_ipo
from ..engine.ipo_decision import decide as decide_ipo
from ..ingest.extract import MAX_BYTES, ExtractionError, extract_text, ocr_status
from ..ingest.rhp import parse_offer_document
from ..ingest.sample_rhp import build_sample_rhp
from ..providers import registry
from ..providers.base import ProviderError

log = logging.getLogger("stockiq")
router = APIRouter()


class UseOfProceeds(BaseModel):
    purpose: str = Field(..., max_length=200)
    amount_cr: float = Field(..., ge=0)


class IpoFinancialYear(BaseModel):
    fy: str = Field(..., max_length=20)
    revenue_cr: Optional[float] = None
    ebitda_cr: Optional[float] = None
    pat_cr: Optional[float] = None
    net_worth_cr: Optional[float] = None
    borrowings_cr: Optional[float] = Field(None, ge=0)
    cfo_cr: Optional[float] = None
    capex_cr: Optional[float] = Field(None, ge=0)


class ManualPeer(BaseModel):
    name: str = Field(..., max_length=120)
    pe: Optional[float] = None
    ev_ebitda: Optional[float] = None
    pb: Optional[float] = None
    roe: Optional[float] = None


class IpoIn(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=160)
    sector: Optional[str] = Field(None, max_length=80)
    industry: Optional[str] = Field(None, max_length=80)
    business_summary: Optional[str] = Field(None, max_length=4000)
    exchange: Optional[str] = Field(None, max_length=40)
    status: Optional[str] = Field("upcoming", max_length=20)
    price_band_low: float = Field(..., gt=0)
    price_band_high: float = Field(..., gt=0)
    lot_size: Optional[int] = Field(None, ge=1)
    face_value: Optional[float] = Field(None, gt=0)
    fresh_issue_cr: float = Field(0, ge=0)
    ofs_cr: float = Field(0, ge=0)
    pre_issue_shares: float = Field(..., gt=0)
    post_issue_shares: Optional[float] = Field(None, gt=0)
    promoter_pre_pct: Optional[float] = Field(None, ge=0, le=100)
    promoter_post_pct: Optional[float] = Field(None, ge=0, le=100)
    open_date: Optional[str] = None
    close_date: Optional[str] = None
    listing_date: Optional[str] = None
    anchor_lockin_50_date: Optional[str] = None
    anchor_lockin_100_date: Optional[str] = None
    use_of_proceeds: list[UseOfProceeds] = []
    financials: list[IpoFinancialYear] = Field(default_factory=list, max_length=6)
    cash_cr: Optional[float] = Field(None, ge=0)
    top_customer_concentration_pct: Optional[float] = Field(None, ge=0, le=100)
    contingent_liabilities_cr: Optional[float] = Field(None, ge=0)
    litigation_notes: Optional[str] = Field(None, max_length=4000)
    risk_factors: list[str] = Field(default_factory=list, max_length=40)
    subscription: Optional[dict[str, Any]] = None
    gmp: Optional[dict[str, Any]] = None
    peers: list[str] = Field(default_factory=list, max_length=8)
    manual_peers: list[ManualPeer] = Field(default_factory=list, max_length=10)
    scenario_overrides: Optional[dict[str, Any]] = None
    source_note: Optional[str] = Field(None, max_length=500)
    extraction: Optional[dict[str, Any]] = None  # document metadata + per-field evidence from an RHP upload

    @field_validator("price_band_high")
    @classmethod
    def band_order(cls, v, info):
        lo = info.data.get("price_band_low")
        if lo is not None and v < lo:
            raise ValueError("upper price band must be ≥ lower band")
        return v

    @field_validator("peers")
    @classmethod
    def peer_symbols(cls, v):
        return [registry.validate_symbol(s) for s in v if s.strip()]



def _ipo_peers(symbols: list[str]) -> list[dict[str, Any]]:
    out = []
    for s in symbols:
        try:
            a = analyse(s, include_peers=False)
            m = a["valuation"]["multiples"]
            out.append({"name": a["profile"]["name"], "symbol": s, "source": a["source_label"],
                        "pe": m["pe"]["value"], "ev_ebitda": m["ev_ebitda"]["value"], "pb": m["pb"]["value"],
                        "roe": a["metrics"]["latest"].get("roe", {}).get("value"), "is_sample": a["is_sample"]})
        except ProviderError as e:
            out.append({"name": s, "symbol": s, "error": str(e)})
    return out


@router.get("/api/ipos")
def ipos():
    items = []
    for r in db.ipo_list():
        p = r["payload"]
        items.append({"id": r["id"], "name": r["name"], "status": p.get("status") or r["status"],
                      "is_sample": r["is_sample"], "updated_at": r["updated_at"],
                      "price_band": [p.get("price_band_low"), p.get("price_band_high")],
                      "issue_size_cr": (p.get("fresh_issue_cr") or 0) + (p.get("ofs_cr") or 0),
                      "open_date": p.get("open_date"), "close_date": p.get("close_date"),
                      "listing_date": p.get("listing_date"), "industry": p.get("industry")})
    return {"items": items, "note": "Live IPO calendars are not available from free, terms-compliant sources. "
                                    "Add IPOs from the RHP published on SEBI/NSE/BSE websites."}


@router.post("/api/ipos")
def ipo_create(body: IpoIn):
    id_ = re.sub(r"[^a-z0-9]+", "-", body.company_name.lower()).strip("-")[:40] + "-" + uuid.uuid4().hex[:6]
    db.ipo_put(id_, body.company_name, body.status, body.model_dump())
    return {"id": id_}


def _match_peer_symbols(names: list[str]) -> list[dict[str, Any]]:
    """Best-effort mapping of RHP peer names to listed symbols (only confident name matches)."""
    out = []
    norm = lambda s: set(re.sub(r"[^a-z0-9 ]", " ", s.lower()).replace("limited", " ").replace("ltd", " ").split())  # noqa: E731
    for name in names[:6]:
        try:
            res = registry.search(re.sub(r"\b(limited|ltd\.?)\b", "", name, flags=re.I).strip())
        except Exception:
            continue
        want = norm(name)
        for g in res.get("results", []):
            if g.get("is_sample") or g.get("market") != "IN":
                continue
            have = norm(g["name"])
            overlap = len(want & have) / max(1, len(want))
            if overlap >= 0.75:
                out.append({"name": name, "symbol": g["primary_symbol"], "matched_name": g["name"]})
                break
    return out


@router.post("/api/ipos/upload")
def ipo_upload(file: UploadFile = File(...)):
    """Read an offer document of any format and return a draft IPO record with evidence for review."""
    data = file.file.read(MAX_BYTES + 1)
    try:
        doc = extract_text(data, file.filename or "upload")
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    if doc.char_count < 500:
        raise HTTPException(422, "Very little text could be read from this file"
                                 + (" (OCR unavailable on this installation)" if not ocr_status()["available"] else "")
                                 + ". Upload the RHP/DRHP PDF as published on the SEBI/NSE/BSE website.")
    parsed = parse_offer_document(doc.pages)
    peer_names = parsed["draft"].pop("peer_names", [])
    suggestions = [] if config.OFFLINE else _match_peer_symbols(peer_names)
    return {"document": doc.meta(), "doc_type": parsed["doc_type"], "draft": parsed["draft"],
            "evidence": parsed["evidence"], "warnings": doc.warnings + parsed["warnings"],
            "found": parsed["found"], "missing": parsed["missing"], "missing_required": parsed["missing_required"],
            "coverage": parsed["coverage"], "peer_suggestions": suggestions, "ocr": ocr_status(),
            "note": "Figures were extracted automatically by pattern matching. Check each one against the document "
                    "(page numbers are given) before relying on the analysis."}


@router.get("/api/ipos/sample-rhp")
def ipo_sample_rhp():
    return Response(build_sample_rhp(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="SAMPLE-RHP-fictional-Demo-Precision.pdf"'})


@router.get("/api/ipos/{id_}")
def ipo_get(id_: str):
    r = db.ipo_get(id_)
    if not r:
        raise HTTPException(404, "IPO not found")
    return r


@router.put("/api/ipos/{id_}")
def ipo_update(id_: str, body: IpoIn):
    r = db.ipo_get(id_)
    if not r:
        raise HTTPException(404, "IPO not found")
    if r["is_sample"]:
        raise HTTPException(400, "The sample IPO is read-only; create a new IPO instead.")
    db.ipo_put(id_, body.company_name, body.status, body.model_dump())
    return {"ok": True}


@router.delete("/api/ipos/{id_}")
def ipo_delete(id_: str):
    r = db.ipo_get(id_)
    if r and r["is_sample"]:
        raise HTTPException(400, "The sample IPO cannot be deleted.")
    db.ipo_delete(id_)
    return {"ok": True}


@router.get("/api/ipos/{id_}/analysis")
def ipo_analysis(id_: str):
    r = db.ipo_get(id_)
    if not r:
        raise HTTPException(404, "IPO not found")
    p = r["payload"]
    peers = _ipo_peers(p.get("peers") or [])
    result = analyse_ipo(p, [x for x in peers if "error" not in x])
    result["peer_errors"] = [x for x in peers if "error" in x]
    result["decision"] = decide_ipo(result, p)
    return {"id": id_, "is_sample": r["is_sample"], "input": p, "analysis": result,
            "disclaimer": "IPO analysis is based on figures entered from the offer document. It is research support, "
                          "not a recommendation to apply. Subscription levels and GMP are not reasons to invest."}
