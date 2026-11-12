"""Settings from environment variables (see .env.example). No secrets are required."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = BASE_DIR.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

def _default_data_dir() -> Path:
    # Outside the project (which may sit in a OneDrive/Dropbox folder): syncing a live SQLite
    # database uploads private data and can corrupt it.
    if os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Analytivest"
    return Path.home() / ".local" / "share" / "analytivest"


DATA_DIR = Path(os.environ.get("STOCKIQ_DATA_DIR") or _default_data_dir())
DB_PATH = Path(os.environ.get("STOCKIQ_DB_PATH") or DATA_DIR / "stockiq.db")
LEGACY_DB_PATH = BASE_DIR / "data" / "stockiq.db"  # location before v1.1; migrated automatically
BACKUP_DIR_DEFAULT = DATA_DIR / "backups"
HOST = os.environ.get("STOCKIQ_HOST", "127.0.0.1")
PORT = int(os.environ.get("STOCKIQ_PORT", "8000"))
# Host names the server answers to (blocks DNS-rebinding attacks from web pages). Add more, comma-separated,
# only if you deliberately expose the app on your network.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"} | {
    h.strip().lower() for h in os.environ.get("STOCKIQ_ALLOWED_HOSTS", "").split(",") if h.strip()}
# Random per start unless set; every API call must carry it (tests set a fixed value).
SESSION_TOKEN = os.environ.get("STOCKIQ_SESSION_TOKEN") or secrets.token_urlsafe(32)
# Comma-separated provider order. "yahoo" = Yahoo Finance via yfinance; "sample" = fictional demo data.
PROVIDERS = [p.strip() for p in os.environ.get("STOCKIQ_PROVIDERS", "yahoo,sample").split(",") if p.strip()]
OFFLINE = os.environ.get("STOCKIQ_OFFLINE", "0") == "1"  # true -> never call external providers
MIN_SECONDS_BETWEEN_PROVIDER_CALLS = float(os.environ.get("STOCKIQ_PROVIDER_MIN_INTERVAL", "0.35"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("STOCKIQ_RATE_LIMIT_PER_MINUTE", "300"))
FRONTEND_DIST = Path(os.environ.get("STOCKIQ_FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))

# Cache TTLs in seconds
TTL = {
    "quote": 15 * 60,
    "fundamentals": 24 * 3600,
    "prices": 12 * 3600,
    "peers": 24 * 3600,
    "search": 24 * 3600,
}
