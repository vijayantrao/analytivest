"""FastAPI application: JSON API under /api plus hosting of the built frontend."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import alerts, backup, config, db
from .providers.base import ProviderError
from .providers.sample import SAMPLE_IPO
from .routes import alerts as alerts_routes
from .routes import backup as backup_routes
from .routes import company, core, ipos, lists
from .routes import portfolio as portfolio_routes
from .routes import screener as screener_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("stockiq")

def _prune_cache() -> None:
    try:
        db.cache_prune()
    except Exception as e:  # never stop the app over housekeeping
        log.warning("Cache pruning failed: %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.conn()
    # The sample IPO is read-only for users, so it is refreshed on every start to match the shipped figures.
    db.ipo_put(SAMPLE_IPO["id"], SAMPLE_IPO["name"], SAMPLE_IPO["status"], SAMPLE_IPO["payload"], is_sample=True)
    # Scans only ever run inside this server; alert checks can also run from the command line, so only
    # hour-old ones are treated as dead.
    n = db.jobs_fail_unfinished("scan") + db.jobs_fail_unfinished("alerts", older_than_seconds=3600)
    if n:
        log.info("Marked %d interrupted background job(s) as failed", n)
    stop = threading.Event()
    threading.Thread(target=_prune_cache, daemon=True, name="cache-prune").start()
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



# ---------------- routes ----------------
@app.get("/api/session")
def session():
    """Hands the per-start token to the app's own pages (other sites cannot read this response)."""
    return {"token": config.SESSION_TOKEN, "header": TOKEN_HEADER}


@app.exception_handler(backup.BackupError)
async def backup_error_handler(_: Request, exc: backup.BackupError):
    return JSONResponse({"error": exc.code, "detail": str(exc), "message": str(exc), "retryable": False},
                        status_code=422)




for _r in (core, company, lists, ipos, portfolio_routes, alerts_routes, screener_routes, backup_routes):
    app.include_router(_r.router)


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
