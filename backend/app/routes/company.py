"""Company analysis, DCF, prices, notes, CSV export, compare, summary, history import and annual-report facts."""
from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import db, schemas
from ..analysis import analyse, summary_row
from ..engine.metrics import METRIC_DEFS
from ..ingest.annual_report import parse_annual_report
from ..ingest.extract import ExtractionError, extract_text
from ..ingest.screener_import import ImportError_, parse_screener_export
from ..providers import registry
from ..providers.base import ProviderError
from ._shared import read_upload as _read_upload

log = logging.getLogger("stockiq")
router = APIRouter()


class NotesIn(BaseModel):
    promoter_holding_pct: Optional[float] = Field(None, ge=0, le=100)
    promoter_pledge_pct: Optional[float] = Field(None, ge=0, le=100)
    fii_pct: Optional[float] = Field(None, ge=0, le=100)
    dii_pct: Optional[float] = Field(None, ge=0, le=100)
    public_pct: Optional[float] = Field(None, ge=0, le=100)
    auditor_qualification: Optional[bool] = None
    auditor_resigned: Optional[bool] = None
    auditor_note: Optional[str] = Field(None, max_length=1000)
    material_litigation: Optional[bool] = None
    litigation_note: Optional[str] = Field(None, max_length=1000)
    rpt_concern: Optional[bool] = None
    rpt_note: Optional[str] = Field(None, max_length=1000)
    source: Optional[str] = Field(None, max_length=300)
    as_of: Optional[str] = Field(None, max_length=40)
    free_text: Optional[str] = Field(None, max_length=4000)
    # Banks / NBFCs (from quarterly results or the annual report)
    gnpa_pct: Optional[float] = Field(None, ge=0, le=100)
    nnpa_pct: Optional[float] = Field(None, ge=0, le=100)
    car_pct: Optional[float] = Field(None, ge=0, le=100)
    pcr_pct: Optional[float] = Field(None, ge=0, le=100)
    bank_as_of: Optional[str] = Field(None, max_length=40)
    contingent_liabilities_cr: Optional[float] = Field(None, ge=0)
    rpt_total_cr: Optional[float] = Field(None, ge=0)
    annual_report: Optional[dict[str, Any]] = None  # metadata of an uploaded annual report the facts came from


class DcfIn(BaseModel):
    base_fcf: Optional[float] = None
    growth: Optional[float] = Field(None, ge=-20, le=50)
    years: Optional[int] = Field(None, ge=1, le=15)
    fade_years: Optional[int] = Field(None, ge=1, le=15)
    discount: Optional[float] = Field(None, ge=4, le=30)
    terminal: Optional[float] = Field(None, ge=-2, le=10)



@router.get("/api/company/{symbol}/analysis", response_model=schemas.Analysis)
def company_analysis(symbol: str, refresh: bool = False):
    return analyse(registry.validate_symbol(symbol), force=refresh)


@router.post("/api/company/{symbol}/dcf", response_model=schemas.DcfResponse)
def company_dcf(symbol: str, body: DcfIn):
    a = analyse(registry.validate_symbol(symbol), dcf_overrides=body.model_dump(exclude_none=True))
    return {"dcf": a["valuation"]["dcf"], "fair_value": a["valuation"]["fair_value"],
            "estimates": a["valuation"]["estimates"], "price": a["valuation"]["price"]}


@router.get("/api/company/{symbol}/prices")
def company_prices(symbol: str, range: str = Query("5y", pattern="^(1m|6m|1y|3y|5y|10y|max)$")):
    sym = registry.validate_symbol(symbol)
    data = registry.get_prices(sym)
    prices = data["prices"]
    days = {"1m": 31, "6m": 183, "1y": 366, "3y": 3 * 366, "5y": 5 * 366, "10y": 10 * 366}.get(range)
    if days and prices:
        from datetime import date, timedelta
        cutoff = (date.fromisoformat(prices[-1][0]) - timedelta(days=days)).isoformat()
        prices = [p for p in prices if p[0] >= cutoff]
    # Thin long ranges to weekly points to keep charts light
    if len(prices) > 800:
        step = len(prices) // 600 + 1
        prices = prices[::step] + ([prices[-1]] if (len(prices) - 1) % step else [])
    available_from = data["prices"][0][0] if data["prices"] else None
    return {"symbol": sym, "range": range, "available_from": available_from,
            "points": [{"date": p[0], "close": p[1], "adj_close": p[2], "volume": p[3]} for p in prices],
            "freshness": data["freshness"],
            "note": "Close is split/bonus-adjusted; adjusted close also reinvests dividends (used for total return)."}


@router.get("/api/company/{symbol}/notes")
def get_notes(symbol: str):
    return db.notes_get(registry.validate_symbol(symbol)) or {}


@router.put("/api/company/{symbol}/notes")
def put_notes(symbol: str, body: NotesIn):
    db.notes_put(registry.validate_symbol(symbol), body.model_dump(exclude_none=True))
    return {"ok": True}


@router.get("/api/company/{symbol}/export.csv")
def export_csv(symbol: str):
    a = analyse(registry.validate_symbol(symbol))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["# Analytivest export", a["profile"].get("name"), a["symbol"], "source: " + (a.get("source_label") or ""),
                "retrieved_at_epoch: " + str((a.get("freshness") or {}).get("retrieved_at")),
                "SAMPLE DATA" if a["is_sample"] else ""])
    w.writerow(["# Research only; not investment advice."])
    w.writerow([])
    w.writerow(["section", "item", "period", "value", "unit", "quality", "formula_or_note"])
    st = a["statements"]["annual"]
    for stmt, rows in st["rows"].items():
        for r in rows:
            for lbl, v in zip(st["labels"], r["values"]):
                w.writerow([f"statement:{stmt}", r["label"], lbl, v, a["quote"].get("currency"), "reported", ""])
    ser = a["metrics"]["annual"]
    for key, cells in ser["series"].items():
        d = METRIC_DEFS.get(key, {})
        for lbl, c in zip(ser["labels"], cells):
            w.writerow(["metric", d.get("label", key), lbl, c["value"], d.get("unit"),
                        "calculated" if c["value"] is not None else c["status"], d.get("formula") or c.get("reason")])
    for k, g in a["metrics"]["growth"].items():
        w.writerow(["growth", k, g.get("period"), g.get("value"), "pct", "calculated", g.get("reason") or "CAGR"])
    for k, m in a["valuation"]["multiples"].items():
        w.writerow(["valuation", m["label"], m["basis"], m["value"], m["unit"], m["quality"], m["formula"]])
    for name, v in a["scores"]["verdicts"].items():
        w.writerow(["verdict", name, "", v.get("score"), "0-100", "calculated", v.get("label")])
    for f in a["flags"]:
        w.writerow(["red_flag", f["title"], f["period"], f["severity"], "", "calculated", f["evidence"]])
    fname = re.sub(r"[^A-Za-z0-9_.-]", "_", a["symbol"]) + "_stockiq.csv"
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/api/compare", response_model=schemas.CompareResponse)
def compare(symbols: str = Query(..., max_length=200)):
    syms = [registry.validate_symbol(s) for s in symbols.split(",") if s.strip()]
    if not 1 <= len(syms) <= 5:
        raise HTTPException(400, "Compare between 1 and 5 symbols")
    rows, errors = [], []
    for s in syms:
        try:
            a = analyse(s)
            row = summary_row(a)
            row["series"] = {"labels": a["metrics"]["annual"]["labels"],
                             "revenue": [c["value"] for c in a["metrics"]["annual"]["series"]["revenue"]],
                             "net_income": [c["value"] for c in a["metrics"]["annual"]["series"]["net_income"]],
                             "roe": [c["value"] for c in a["metrics"]["annual"]["series"]["roe"]]}
            rows.append(row)
        except ProviderError as e:
            errors.append({"symbol": s, "message": str(e)})
    return {"rows": rows, "errors": errors}



# ---------------- company summary (portfolio rows, screener) ----------------
@router.get("/api/company/{symbol}/summary", response_model=schemas.CompanySummary)
def company_summary(symbol: str):
    a = analyse(registry.validate_symbol(symbol))
    row = summary_row(a)
    q = a.get("quarterly") or {}
    row["quarter"] = {"latest": q.get("latest"), "verdict": q.get("verdict")} if q.get("available") else None
    row["fair_value"] = {k: a["valuation"]["fair_value"].get(k) for k in ("low", "mid", "high", "label")}
    return row


# ---------------- Screener.in history import ----------------
@router.post("/api/company/{symbol}/import")
def company_import(symbol: str, file: UploadFile = File(...)):
    sym = registry.validate_symbol(symbol)
    try:
        parsed = parse_screener_export(_read_upload(file))
    except ImportError_ as e:
        raise HTTPException(422, str(e))
    warnings = list(parsed["warnings"])
    try:
        prof_name = registry.get_bundle(sym)["profile"]["name"]
    except ProviderError:
        prof_name = None
    if parsed.get("company_name") and prof_name:
        norm = lambda s: set(re.sub(r"[^a-z0-9 ]", " ", s.lower()).replace("limited", " ").replace("ltd", " ").split())  # noqa: E731
        a, b = norm(parsed["company_name"]), norm(prof_name)
        if a and len(a & b) / len(a) < 0.5:
            raise HTTPException(422, f"This export is for '{parsed['company_name']}', not {prof_name}. Open the right "
                                     "company on Screener.in and export again.")
    db.import_put(sym, parsed["source"], parsed)
    return {"ok": True, "years": parsed["years"], "range": parsed["range"], "quarters": len(parsed["quarterly"]),
            "company_name": parsed["company_name"], "warnings": warnings}


@router.delete("/api/company/{symbol}/import")
def company_import_delete(symbol: str):
    db.import_delete(registry.validate_symbol(symbol))
    return {"ok": True}


# ---------------- Annual report facts ----------------
@router.post("/api/company/{symbol}/annual-report")
def company_annual_report(symbol: str, file: UploadFile = File(...)):
    registry.validate_symbol(symbol)
    try:
        doc = extract_text(_read_upload(file), file.filename or "annual-report")
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    if doc.char_count < 500:
        raise HTTPException(422, "Very little text could be read from this file.")
    res = parse_annual_report(doc.pages)
    res["document"] = doc.meta()
    res["warnings"] = doc.warnings + res["warnings"]
    return res
