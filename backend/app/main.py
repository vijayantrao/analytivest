"""FastAPI application: JSON API under /api plus hosting of the built frontend."""
from __future__ import annotations

import csv
import io
import logging
import re
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import alerts, backup, backup_crypto, config, db, screener
from .analysis import analyse, summary_row
from .ingest.annual_report import parse_annual_report
from .markets import market_for_symbol
from .ml import anomaly
from .ml.features import extract as extract_ml_features
from .ingest.screener_import import ImportError_, parse_screener_export
from .portfolio import HoldingsError, parse_holdings, resolve_symbol
from .engine.ipo import analyse_ipo
from .engine.ipo_decision import decide as decide_ipo
from .engine.metrics import METRIC_DEFS
from .engine.scoring import load_config
from .glossary import GLOSSARY
from .ingest.extract import MAX_BYTES, ExtractionError, extract_text, ocr_status
from .ingest.rhp import parse_offer_document
from .ingest.sample_rhp import build_sample_rhp
from .providers import registry
from .providers.base import ProviderError
from .providers.sample import SAMPLE_IPO

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("stockiq")

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.conn()
    if not db.ipo_get(SAMPLE_IPO["id"]):
        db.ipo_put(SAMPLE_IPO["id"], SAMPLE_IPO["name"], SAMPLE_IPO["status"], SAMPLE_IPO["payload"], is_sample=True)
    stop = threading.Event()
    if not config.OFFLINE:
        threading.Thread(target=alerts.scheduler_loop, args=(stop,), daemon=True, name="alerts-scheduler").start()
        threading.Thread(target=backup.scheduler_loop, args=(stop,), daemon=True, name="backup-scheduler").start()
    yield
    stop.set()


app = FastAPI(title="Analytivest API", version="1.0.0", lifespan=lifespan,
              description="Research & decision support for Indian stocks and IPOs. Not investment advice.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

# ---------------- request guard: host, origin, session token, rate limit ----------------
# The server listens on localhost only, but any web page open in the browser can still send requests to
# localhost. These checks stop such pages from reading or changing data:
#  * Host header must be a local name (defeats DNS rebinding, where evil.com is re-pointed at 127.0.0.1);
#  * cross-site requests (Origin / Sec-Fetch-Site) are refused;
#  * every API call must carry a random per-start token, which only same-origin pages can obtain.
_hits: dict[str, deque] = defaultdict(deque)
TOKEN_HEADER = "X-Analytivest-Token"
_TOKEN_EXEMPT = {"/api/session"}
_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def _hostname(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _origin_allowed(origin: str) -> bool:
    try:
        u = urlsplit(origin)
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and (u.hostname or "") in config.ALLOWED_HOSTS and port in (config.PORT, 5173)


def _deny(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, "retryable": False}, status_code=status)


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if _hostname(request.headers.get("host", "")) not in config.ALLOWED_HOSTS:
        return _deny(400, "bad_host", "Unknown host name. Open the app at http://127.0.0.1:%d" % config.PORT)
    if path.startswith("/api/"):
        origin = request.headers.get("origin")
        if (origin and not _origin_allowed(origin)) or request.headers.get("sec-fetch-site") == "cross-site":
            return _deny(403, "cross_site", "Requests from other websites are not allowed.")
        if request.method != "OPTIONS" and path not in _TOKEN_EXEMPT and not secrets.compare_digest(
                request.headers.get(TOKEN_HEADER, ""), config.SESSION_TOKEN):
            return _deny(401, "session_expired", "Session expired (the server restarted). Reload the page.")
        key = request.client.host if request.client else "local"
        q, now = _hits[key], time.time()
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= config.RATE_LIMIT_PER_MINUTE:
            return JSONResponse({"error": "rate_limited", "message": "Too many requests; wait a minute and retry."},
                                status_code=429)
        q.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError):
    status = 404 if exc.not_found else 503
    return JSONResponse({"error": "not_found" if exc.not_found else "provider_unavailable", "message": str(exc),
                         "retryable": exc.retryable}, status_code=status)


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError):
    return JSONResponse({"error": "invalid_input", "message": str(exc)}, status_code=400)


# ---------------- models ----------------
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


class WatchIn(BaseModel):
    symbol: str
    note: Optional[str] = Field(None, max_length=500)


class SavedIn(BaseModel):
    symbol: str
    label: Optional[str] = Field(None, max_length=120)


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


# ---------------- routes ----------------
@app.get("/api/session")
def session():
    """Hands the per-start token to the app's own pages (other sites cannot read this response)."""
    return {"token": config.SESSION_TOKEN, "header": TOKEN_HEADER}


@app.get("/api/health")
def health():
    return {"status": "ok", "providers": registry.provider_status(), "offline": config.OFFLINE,
            "cache": db.cache_stats(), "time": time.time()}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=60)):
    return registry.search(q)


@app.get("/api/company/{symbol}/analysis")
def company_analysis(symbol: str, refresh: bool = False):
    return analyse(registry.validate_symbol(symbol), force=refresh)


@app.post("/api/company/{symbol}/dcf")
def company_dcf(symbol: str, body: DcfIn):
    a = analyse(registry.validate_symbol(symbol), dcf_overrides=body.model_dump(exclude_none=True))
    return {"dcf": a["valuation"]["dcf"], "fair_value": a["valuation"]["fair_value"],
            "estimates": a["valuation"]["estimates"], "price": a["valuation"]["price"]}


@app.get("/api/company/{symbol}/prices")
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


@app.get("/api/company/{symbol}/notes")
def get_notes(symbol: str):
    return db.notes_get(registry.validate_symbol(symbol)) or {}


@app.put("/api/company/{symbol}/notes")
def put_notes(symbol: str, body: NotesIn):
    db.notes_put(registry.validate_symbol(symbol), body.model_dump(exclude_none=True))
    return {"ok": True}


@app.get("/api/company/{symbol}/export.csv")
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


@app.get("/api/compare")
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


@app.get("/api/watchlist")
def watchlist(details: bool = False):
    items = db.watchlist_list()
    if details:
        for it in items:
            try:
                it["summary"] = summary_row(analyse(it["symbol"], include_peers=True))
            except ProviderError as e:
                it["error"] = str(e)
    return {"items": items}


@app.post("/api/watchlist")
def watch_add(body: WatchIn):
    sym = registry.validate_symbol(body.symbol)
    try:
        name = registry.get_bundle(sym)["profile"]["name"]
    except ProviderError:
        name = None
    db.watchlist_add(sym, name, body.note)
    return {"ok": True}


@app.delete("/api/watchlist/{symbol}")
def watch_remove(symbol: str):
    db.watchlist_remove(registry.validate_symbol(symbol))
    return {"ok": True}


@app.get("/api/saved")
def saved_list():
    return {"items": db.saved_list()}


@app.post("/api/saved")
def saved_add(body: SavedIn):
    a = analyse(registry.validate_symbol(body.symbol))
    payload = {"summary": summary_row(a), "verdicts": a["scores"]["verdicts"], "flags": a["flags"],
               "narrative": a["narrative"], "fair_value": a["valuation"]["fair_value"],
               "source_label": a["source_label"], "freshness": a["freshness"]}
    return {"id": db.saved_add(a["symbol"], body.label, payload)}


@app.get("/api/saved/{id_}")
def saved_get(id_: int):
    s = db.saved_get(id_)
    if not s:
        raise HTTPException(404, "Not found")
    return s


@app.delete("/api/saved/{id_}")
def saved_delete(id_: int):
    db.saved_delete(id_)
    return {"ok": True}


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


@app.get("/api/ipos")
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


@app.post("/api/ipos")
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


@app.post("/api/ipos/upload")
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


@app.get("/api/ipos/sample-rhp")
def ipo_sample_rhp():
    return Response(build_sample_rhp(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="SAMPLE-RHP-fictional-Demo-Precision.pdf"'})


@app.get("/api/ipos/{id_}")
def ipo_get(id_: str):
    r = db.ipo_get(id_)
    if not r:
        raise HTTPException(404, "IPO not found")
    return r


@app.put("/api/ipos/{id_}")
def ipo_update(id_: str, body: IpoIn):
    r = db.ipo_get(id_)
    if not r:
        raise HTTPException(404, "IPO not found")
    if r["is_sample"]:
        raise HTTPException(400, "The sample IPO is read-only; create a new IPO instead.")
    db.ipo_put(id_, body.company_name, body.status, body.model_dump())
    return {"ok": True}


@app.delete("/api/ipos/{id_}")
def ipo_delete(id_: str):
    r = db.ipo_get(id_)
    if r and r["is_sample"]:
        raise HTTPException(400, "The sample IPO cannot be deleted.")
    db.ipo_delete(id_)
    return {"ok": True}


@app.get("/api/ipos/{id_}/analysis")
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


# ---------------- company summary (portfolio rows, screener) ----------------
@app.get("/api/company/{symbol}/summary")
def company_summary(symbol: str):
    a = analyse(registry.validate_symbol(symbol))
    row = summary_row(a)
    q = a.get("quarterly") or {}
    row["quarter"] = {"latest": q.get("latest"), "verdict": q.get("verdict")} if q.get("available") else None
    row["fair_value"] = {k: a["valuation"]["fair_value"].get(k) for k in ("low", "mid", "high", "label")}
    return row


# ---------------- Screener.in history import ----------------
def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large.")
    return data


@app.post("/api/company/{symbol}/import")
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


@app.delete("/api/company/{symbol}/import")
def company_import_delete(symbol: str):
    db.import_delete(registry.validate_symbol(symbol))
    return {"ok": True}


# ---------------- Annual report facts ----------------
@app.post("/api/company/{symbol}/annual-report")
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


# ---------------- Portfolio ----------------
class HoldingIn(BaseModel):
    symbol: str
    quantity: float = Field(..., gt=0)
    avg_cost: Optional[float] = Field(None, ge=0)


@app.get("/api/portfolio")
def portfolio():
    return {"holdings": db.holdings_list()}


@app.post("/api/portfolio")
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


@app.get("/api/fx")
def fx(pair: str = Query(..., pattern="^[A-Z]{6}$")):
    return registry.fx_rate(pair)


@app.post("/api/portfolio/import")
def portfolio_import(file: UploadFile = File(...), mode: str = Query("replace", pattern="^(replace|merge)$"),
                     market: str = Query("IN", pattern="^(IN|US)$")):
    try:
        parsed = parse_holdings(_read_upload(file), file.filename or "holdings")
    except HoldingsError as e:
        raise HTTPException(422, str(e))
    if mode == "replace":
        db.holdings_clear()
    added, unresolved = [], []
    for it in parsed["items"]:
        sym, note = resolve_symbol(it, registry.search, market)
        if not sym:
            unresolved.append({"name": it["raw"], "reason": note})
            continue
        db.holding_put(sym, it.get("name") or it["raw"], it["quantity"], it.get("avg_cost"), file.filename or "import")
        added.append({"symbol": sym, "from": it["raw"], "note": note})
    return {"added": added, "unresolved": unresolved, "skipped": parsed["skipped"]}


@app.delete("/api/portfolio/{symbol}")
def portfolio_remove(symbol: str):
    db.holding_delete(registry.validate_symbol(symbol))
    return {"ok": True}


@app.delete("/api/portfolio")
def portfolio_clear():
    db.holdings_clear()
    return {"ok": True}


# ---------------- Alerts ----------------
class AlertSettingsIn(BaseModel):
    enabled: bool = True
    time: str = Field("18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ReadIn(BaseModel):
    ids: Optional[list[int]] = None


@app.get("/api/alerts")
def alerts_list(unread_only: bool = False, limit: int = Query(100, ge=1, le=500)):
    return {"alerts": db.alerts_list(limit, unread_only), "unread": db.alerts_unread_count(),
            "last_run": db.setting_get("alerts_last_run"), "settings": db.setting_get("alerts", {"enabled": True, "time": "18:30"}),
            "tracked": alerts.tracked_symbols(), "job": db.job_latest("alerts")}


@app.get("/api/alerts/count")
def alerts_count():
    return {"unread": db.alerts_unread_count()}


@app.post("/api/alerts/read")
def alerts_read(body: ReadIn):
    db.alerts_mark_read(body.ids)
    return {"ok": True}


@app.post("/api/alerts/check")
def alerts_check():
    if not alerts.tracked_symbols():
        raise HTTPException(400, "Nothing to check yet: add companies to your watchlist or portfolio.")
    job_id = f"alerts-{uuid.uuid4().hex[:8]}"
    db.job_put(job_id, "alerts", "queued", 0, len(alerts.tracked_symbols()), "queued", time.time())
    alerts.start_background(job_id)
    return {"job_id": job_id}


@app.put("/api/alerts/settings")
def alerts_settings(body: AlertSettingsIn):
    db.setting_put("alerts", body.model_dump())
    return {"ok": True}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = db.job_get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j


# ---------------- Stock screener ----------------
class ScanIn(BaseModel):
    size: int = Field(100, ge=10, le=500)
    include_peers: bool = False
    market: str = Field("IN", pattern="^(IN|US)$")


def _ml_scores(scan_rows: list[dict[str, Any]], market: str) -> tuple[Optional[anomaly.Fitted], dict[str, dict[str, Any]]]:
    fitted, rows = anomaly.fitted_for(scan_rows, market)
    if fitted is None:
        return None, {}
    return fitted, {r["symbol"]: anomaly.score(fitted, r["features"]) for r in rows}


@app.get("/api/screener")
def screener_results(market: str = Query("IN", pattern="^(IN|US)$")):
    rows = [r for r in db.scan_list() if screener.market_of(r) == market]
    _, ml = _ml_scores(rows, market)
    return {"results": rows, "job": db.job_latest("scan"),
            "ml": {k: {"percentile": v["percentile"], "level": v["level"], "reasons": [r["text"] for r in v["reasons"]]}
                   for k, v in ml.items() if v["available"]},
            "estimates": {str(n): {"fast": screener.estimate_minutes(n, False), "peers": screener.estimate_minutes(n, True)}
                          for n in (50, 100, 200, 500)}}


@app.get("/api/ml/anomalies")
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


@app.get("/api/company/{symbol}/anomaly")
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


@app.post("/api/screener/scan")
def screener_scan(body: ScanIn):
    if config.OFFLINE:
        raise HTTPException(400, "Scanning needs the live data provider (offline mode is on).")
    j = db.job_latest("scan")
    if j and j["status"] in ("queued", "running"):
        raise HTTPException(409, "A scan is already running.")
    return {"job_id": screener.start(body.size, body.include_peers, body.market)}


@app.post("/api/screener/cancel")
def screener_cancel():
    screener.cancel()
    return {"ok": True}


# ---------------- Backup, restore and security status ----------------
class BackupSettingsIn(BaseModel):
    auto: bool = True
    folder: str = Field("", max_length=500)
    keep: int = Field(8, ge=1, le=52)
    cloud: str = Field("none", pattern="^(none|gdrive)$")
    gdrive_path: str = Field("", max_length=500)
    encrypt: bool = False
    password: Optional[str] = Field(None, max_length=200)  # only when setting or changing it; never returned


class RestoreFileIn(BaseModel):
    name: str = Field(..., max_length=120)
    location: str = Field("local", pattern="^(local|gdrive)$")
    password: Optional[str] = Field(None, max_length=200)


@app.exception_handler(backup.BackupError)
async def backup_error_handler(_: Request, exc: backup.BackupError):
    return JSONResponse({"error": exc.code, "detail": str(exc), "message": str(exc), "retryable": False},
                        status_code=422)


def _backup_call(fn, *args):
    try:
        return fn(*args)
    except OSError as e:
        raise HTTPException(500, f"Backup folder error: {e.strerror or e}")


@app.get("/api/backup")
def backup_download():
    name = f"analytivest-backup-{time.strftime('%Y%m%d-%H%M%S')}-manual.json"
    return Response(backup.to_bytes(backup.export_data()), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class EncryptedDownloadIn(BaseModel):
    password: Optional[str] = Field(None, max_length=200)  # omitted -> the saved encryption password


@app.post("/api/backup/encrypted")
def backup_download_encrypted(body: EncryptedDownloadIn):
    name = f"analytivest-backup-{time.strftime('%Y%m%d-%H%M%S')}-manual.enc.json"
    return Response(backup.encrypted_export(body.password), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/backup/status")
def backup_status():
    f = backup.folder()
    db_files = [config.DB_PATH, config.DB_PATH.with_name(config.DB_PATH.name + "-wal")]
    last = db.setting_get("backup_last_auto")
    detected, gfolder = backup.detect_gdrive(), backup.gdrive_folder()
    return {
        "settings": backup.settings(), "folder": str(f), "folder_default": str(config.BACKUP_DIR_DEFAULT),
        "folder_synced": backup.in_synced_folder(f), "files": backup.list_all(), "last_auto": last,
        "gdrive": {"detected": str(detected) if detected else None, "folder": str(gfolder) if gfolder else None,
                   "last": backup.cloud_status(),
                   "plain_copies": sum(1 for x in backup.list_files("gdrive") if not x["encrypted"])},
        "encryption": {"available": backup_crypto.can_store_password(), "has_password": bool(backup.stored_password()),
                       "min_password": backup_crypto.MIN_PASSWORD_LEN},
        "next_auto": (last + backup.AUTO_EVERY_DAYS * 86400) if last else None, "counts": backup.counts(),
        "data": {"db_path": str(config.DB_PATH), "size": sum(p.stat().st_size for p in db_files if p.exists()),
                 "in_synced_folder": backup.in_synced_folder(config.DB_PATH.parent),
                 "legacy_copy_present": config.LEGACY_DB_PATH.exists() and config.LEGACY_DB_PATH != config.DB_PATH},
        "security": {"bind_host": config.HOST, "local_only": config.HOST in ("127.0.0.1", "localhost", "::1"),
                     "allowed_hosts": sorted(config.ALLOWED_HOSTS), "session_token": True,
                     "cross_site_blocked": True, "upload_limit_mb": MAX_BYTES // (1024 * 1024)},
    }


@app.post("/api/backup/run")
def backup_run():
    p = _backup_call(backup.write_file, "manual")
    cloud = backup.cloud_status() if backup.settings()["cloud"] == "gdrive" else None
    return {"name": p.name, "folder": str(p.parent), "cloud": cloud}


@app.put("/api/backup/settings")
def backup_settings(body: BackupSettingsIn):
    return _backup_call(backup.update_settings, body.auto, body.folder, body.keep, body.cloud, body.gdrive_path,
                        body.encrypt, body.password)


@app.post("/api/backup/purge-plain-cloud")
def backup_purge_plain_cloud():
    return {"deleted": _backup_call(backup.purge_plain_cloud)}


@app.post("/api/backup/restore")
def backup_restore(file: UploadFile = File(...), password: Optional[str] = Form(None, max_length=200)):
    return _backup_call(backup.restore, _read_upload(file), password)


@app.post("/api/backup/restore-file")
def backup_restore_file(body: RestoreFileIn):
    return _backup_call(backup.restore_file, body.name, body.location, body.password)


@app.get("/api/methodology")
def methodology():
    return {"scoring": load_config(), "metrics": METRIC_DEFS,
            "principles": [
                "Missing data is excluded from scores (weights re-normalised) and lowers completeness/confidence; it is never scored as zero.",
                "Ratios with zero or negative denominators are marked 'not meaningful' rather than computed.",
                "CAGR is only computed when start and end values are positive; the exact period is always shown.",
                "Historical EPS and share counts are adjusted for later splits/bonus issues when the period is detected as unadjusted.",
                "Banks/NBFCs/insurers use a separate model; industrial ratios (D/E, EV/EBITDA, FCF) are not applied to them.",
                "Business quality, financial risk and valuation are separate verdicts; a good business can be an expensive stock.",
            ]}


@app.get("/api/glossary")
def glossary():
    return {"terms": GLOSSARY}


# ---------------- frontend hosting ----------------
if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = config.FRONTEND_DIST / path
        if path and f.is_file() and config.FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(config.FRONTEND_DIST / "index.html")
