"""SQLite persistence: cache, watchlist, user notes, saved analyses, IPO records."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from . import config

_lock = threading.RLock()
log = logging.getLogger("stockiq.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
  key TEXT PRIMARY KEY, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
  fetched_at REAL NOT NULL, provider TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
  symbol TEXT PRIMARY KEY, name TEXT, added_at REAL NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS company_notes (
  symbol TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_analysis (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, label TEXT,
  payload_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ipo (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT, payload_json TEXT NOT NULL,
  is_sample INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
-- v2: user-imported financial history, portfolio, alerts, screener scans, background jobs
CREATE TABLE IF NOT EXISTS imports (
  symbol TEXT PRIMARY KEY, source TEXT NOT NULL, payload_json TEXT NOT NULL, imported_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS holdings (
  symbol TEXT PRIMARY KEY, name TEXT, quantity REAL NOT NULL, avg_cost REAL, source TEXT, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
  symbol TEXT NOT NULL, taken_at REAL NOT NULL, summary_json TEXT NOT NULL, PRIMARY KEY (symbol, taken_at)
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, kind TEXT NOT NULL, severity TEXT NOT NULL,
  title TEXT NOT NULL, message TEXT NOT NULL, created_at REAL NOT NULL, read INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scan_results (
  symbol TEXT PRIMARY KEY, summary_json TEXT NOT NULL, scanned_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0, message TEXT, started_at REAL, finished_at REAL
);
"""
SCHEMA_VERSION = 2

_conn: Optional[sqlite3.Connection] = None


def migrate_legacy(old: Path, new: Path) -> bool:
    """Move a database from its pre-v1.1 location (inside the project, often a synced OneDrive folder) to
    the local data folder. Copies with SQLite's backup API (includes un-checkpointed WAL pages), verifies
    the copy, and only then deletes the old files. Returns True if a migration happened."""
    if new.exists() or not old.exists() or old.resolve() == new.resolve():
        return False
    new.parent.mkdir(parents=True, exist_ok=True)
    tmp = new.with_suffix(".migrating")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(old)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("integrity check failed on the migrated copy")
            for (t,) in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                q = f'SELECT COUNT(*) FROM "{t}"'
                if src.execute(q).fetchone()[0] != dst.execute(q).fetchone()[0]:
                    raise RuntimeError(f"row count mismatch in {t}")
        finally:
            dst.close()
    finally:
        src.close()
    tmp.replace(new)
    for suffix in ("", "-wal", "-shm"):
        Path(str(old) + suffix).unlink(missing_ok=True)
    log.info("Moved the database from %s to %s", old, new)
    return True


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            if "STOCKIQ_DB_PATH" not in os.environ:
                try:
                    migrate_legacy(config.LEGACY_DB_PATH, config.DB_PATH)
                except Exception as e:  # keep the old file; start on it rather than lose data
                    log.error("Could not move the database (%s); still using %s", e, config.LEGACY_DB_PATH)
                    config.DB_PATH = config.LEGACY_DB_PATH
            config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            _conn = c
            _init(c)
        return _conn


def reset_connection() -> None:
    """Used by tests that point the DB somewhere else."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None


def _init(c: sqlite3.Connection) -> None:
    c.executescript(SCHEMA)
    row = c.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        c.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif row["version"] < SCHEMA_VERSION:
        # v1 -> v2 only adds tables (created above by CREATE TABLE IF NOT EXISTS)
        c.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
    c.commit()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def _query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, args).fetchall()


# ---------- cache ----------
def cache_get(key: str) -> Optional[dict[str, Any]]:
    rows = _query("SELECT payload_json, fetched_at, provider FROM cache WHERE key=?", (key,))
    if not rows:
        return None
    r = rows[0]
    return {"payload": json.loads(r["payload_json"]), "fetched_at": r["fetched_at"], "provider": r["provider"]}


def cache_put(key: str, kind: str, payload: Any, provider: str) -> float:
    now = time.time()
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO cache(key, kind, payload_json, fetched_at, provider) VALUES (?,?,?,?,?)",
                  (key, kind, json.dumps(payload, default=str), now, provider))
    return now


def cache_stats() -> dict[str, Any]:
    rows = _query("SELECT kind, COUNT(*) n, MAX(fetched_at) last, SUM(LENGTH(payload_json)) bytes FROM cache "
                  "GROUP BY kind")
    return {r["kind"]: {"count": r["n"], "last_fetched_at": r["last"], "bytes": r["bytes"] or 0} for r in rows}


# Symbols the user has chosen to keep around are never pruned: their cached data is what makes them open offline.
_KEPT_SYMBOLS_SQL = ("SELECT symbol FROM watchlist UNION SELECT symbol FROM holdings UNION SELECT symbol FROM "
                     "company_notes UNION SELECT symbol FROM saved_analysis UNION SELECT symbol FROM imports")


def cache_prune(max_age_days: float = 30, max_bytes: int = 150_000_000, now: Optional[float] = None) -> dict[str, Any]:
    """Delete cached provider data nobody needs any more, so the database does not grow without limit.

    1. Anything not refreshed for ``max_age_days`` is removed (it would be refetched before use anyway, since every
       cache entry is older than its freshness limit by then), except for kept symbols (watchlist, portfolio, notes,
       saved analyses, imports).
    2. If the cache is still above ``max_bytes``, the least recently fetched unkept companies are removed until it
       fits. Screener results and the ML model use the stored scan summaries, not this cache, so they are unaffected.
    """
    now = now or time.time()
    kept = {r["symbol"] for r in _query(_KEPT_SYMBOLS_SQL)}

    def unkept(key: str) -> bool:
        kind, _, rest = key.partition(":")
        return not (kind in ("fund", "prices", "quote", "peers") and rest in kept)

    removed = 0
    with tx() as c:
        old = [r["key"] for r in c.execute("SELECT key FROM cache WHERE fetched_at < ?",
                                           (now - max_age_days * 86400,)).fetchall()]
        doomed = [k for k in old if unkept(k)]
        c.executemany("DELETE FROM cache WHERE key=?", [(k,) for k in doomed])
        removed += len(doomed)
        total = c.execute("SELECT COALESCE(SUM(LENGTH(payload_json)), 0) FROM cache").fetchone()[0]
        if total > max_bytes:
            # Oldest companies first; a company's fundamentals and prices go together.
            rows = c.execute("SELECT key, LENGTH(payload_json) n FROM cache WHERE kind IN ('fundamentals', 'prices') "
                             "ORDER BY fetched_at").fetchall()
            for r in rows:
                if total <= max_bytes:
                    break
                if unkept(r["key"]):
                    c.execute("DELETE FROM cache WHERE key=?", (r["key"],))
                    total -= r["n"]
                    removed += 1
    out = {"removed": removed, "bytes_after": total, "kept_symbols": len(kept)}
    if removed:
        with _lock:
            conn().execute("VACUUM")  # give the freed space back to the disk
        log.info("Cache pruned: %d entries removed, %.0f MB left", removed, total / 1e6)
    return out


# ---------- watchlist ----------
def watchlist_list() -> list[dict[str, Any]]:
    return [dict(r) for r in _query("SELECT * FROM watchlist ORDER BY added_at DESC")]


def watchlist_add(symbol: str, name: str | None, note: str | None = None) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO watchlist(symbol, name, added_at, note) VALUES (?,?,?,?)",
                  (symbol, name, time.time(), note))


def watchlist_remove(symbol: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))


# ---------- notes (user-entered governance facts) ----------
def notes_get(symbol: str) -> Optional[dict[str, Any]]:
    rows = _query("SELECT payload_json, updated_at FROM company_notes WHERE symbol=?", (symbol,))
    if not rows:
        return None
    d = json.loads(rows[0]["payload_json"])
    d["updated_at"] = rows[0]["updated_at"]
    return d


def notes_put(symbol: str, payload: dict[str, Any]) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO company_notes(symbol, payload_json, updated_at) VALUES (?,?,?)",
                  (symbol, json.dumps(payload), time.time()))


# ---------- saved analyses ----------
def saved_list() -> list[dict[str, Any]]:
    out = []
    for r in _query("SELECT id, symbol, label, created_at, payload_json FROM saved_analysis ORDER BY created_at DESC"):
        p = json.loads(r["payload_json"])
        out.append({"id": r["id"], "symbol": r["symbol"], "label": r["label"], "created_at": r["created_at"],
                    "summary": p.get("summary")})
    return out


def saved_get(id_: int) -> Optional[dict[str, Any]]:
    rows = _query("SELECT * FROM saved_analysis WHERE id=?", (id_,))
    if not rows:
        return None
    r = rows[0]
    return {"id": r["id"], "symbol": r["symbol"], "label": r["label"], "created_at": r["created_at"],
            "payload": json.loads(r["payload_json"])}


def saved_add(symbol: str, label: str | None, payload: dict[str, Any]) -> int:
    with tx() as c:
        cur = c.execute("INSERT INTO saved_analysis(symbol, label, payload_json, created_at) VALUES (?,?,?,?)",
                        (symbol, label, json.dumps(payload, default=str), time.time()))
        return int(cur.lastrowid)


def saved_delete(id_: int) -> None:
    with tx() as c:
        c.execute("DELETE FROM saved_analysis WHERE id=?", (id_,))


# ---------- IPOs ----------
def _ipo_row(r: sqlite3.Row) -> dict[str, Any]:
    return {"id": r["id"], "name": r["name"], "status": r["status"], "is_sample": bool(r["is_sample"]),
            "updated_at": r["updated_at"], "payload": json.loads(r["payload_json"])}


def ipo_list() -> list[dict[str, Any]]:
    return [_ipo_row(r) for r in _query("SELECT * FROM ipo ORDER BY is_sample ASC, updated_at DESC")]


def ipo_get(id_: str) -> Optional[dict[str, Any]]:
    rows = _query("SELECT * FROM ipo WHERE id=?", (id_,))
    return _ipo_row(rows[0]) if rows else None


def ipo_put(id_: str, name: str, status: str | None, payload: dict[str, Any], is_sample: bool = False) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO ipo(id, name, status, payload_json, is_sample, updated_at) "
                  "VALUES (?,?,?,?,?,?)", (id_, name, status, json.dumps(payload), int(is_sample), time.time()))


def ipo_delete(id_: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM ipo WHERE id=?", (id_,))


# ---------- imported financial history (e.g. Screener.in export) ----------
def import_get(symbol: str) -> Optional[dict[str, Any]]:
    rows = _query("SELECT * FROM imports WHERE symbol=?", (symbol,))
    if not rows:
        return None
    r = rows[0]
    return {"symbol": r["symbol"], "source": r["source"], "imported_at": r["imported_at"],
            "payload": json.loads(r["payload_json"])}


def import_put(symbol: str, source: str, payload: dict[str, Any]) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO imports(symbol, source, payload_json, imported_at) VALUES (?,?,?,?)",
                  (symbol, source, json.dumps(payload), time.time()))


def import_delete(symbol: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM imports WHERE symbol=?", (symbol,))


# ---------- portfolio ----------
def holdings_list() -> list[dict[str, Any]]:
    return [dict(r) for r in _query("SELECT * FROM holdings ORDER BY symbol")]


def holding_put(symbol: str, name: str | None, quantity: float, avg_cost: float | None, source: str) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO holdings(symbol, name, quantity, avg_cost, source, updated_at) VALUES (?,?,?,?,?,?)",
                  (symbol, name, quantity, avg_cost, source, time.time()))


def holding_delete(symbol: str) -> None:
    with tx() as c:
        c.execute("DELETE FROM holdings WHERE symbol=?", (symbol,))


def holdings_clear() -> None:
    with tx() as c:
        c.execute("DELETE FROM holdings")


def holdings_replace(rows: list[tuple[str, str | None, float, float | None, str]]) -> None:
    """Swap the whole portfolio for `rows` (symbol, name, quantity, avg_cost, source) in one transaction,
    so a failure part-way leaves the previous holdings untouched."""
    now = time.time()
    with tx() as c:
        c.execute("DELETE FROM holdings")
        c.executemany("INSERT OR REPLACE INTO holdings(symbol, name, quantity, avg_cost, source, updated_at) "
                      "VALUES (?,?,?,?,?,?)", [(*r, now) for r in rows])


def jobs_fail_unfinished(kind: str, older_than_seconds: float = 0.0) -> int:
    """Mark jobs of `kind` still 'queued' or 'running' as failed. Jobs run in threads of this process, so after
    a restart any such row belongs to a process that no longer exists and would otherwise block new jobs."""
    now = time.time()
    with tx() as c:
        cur = c.execute(
            "UPDATE jobs SET status='error', finished_at=?, message='Interrupted: the app was closed before this "
            "finished (' || progress || ' of ' || total || ' done). Start it again.' "
            "WHERE kind=? AND status IN ('queued','running') AND COALESCE(started_at, 0) <= ?",
            (now, kind, now - older_than_seconds))
        return cur.rowcount


# ---------- snapshots & alerts ----------
def snapshot_last(symbol: str) -> Optional[dict[str, Any]]:
    rows = _query("SELECT * FROM snapshots WHERE symbol=? ORDER BY taken_at DESC LIMIT 1", (symbol,))
    return {"taken_at": rows[0]["taken_at"], "summary": json.loads(rows[0]["summary_json"])} if rows else None


def snapshot_put(symbol: str, summary: dict[str, Any]) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO snapshots(symbol, taken_at, summary_json) VALUES (?,?,?)",
                  (symbol, time.time(), json.dumps(summary, default=str)))
        # keep the latest 30 snapshots per symbol
        c.execute("""DELETE FROM snapshots WHERE symbol=? AND taken_at NOT IN
                     (SELECT taken_at FROM snapshots WHERE symbol=? ORDER BY taken_at DESC LIMIT 30)""", (symbol, symbol))


def alert_add(symbol: str, kind: str, severity: str, title: str, message: str) -> None:
    with tx() as c:
        c.execute("INSERT INTO alerts(symbol, kind, severity, title, message, created_at) VALUES (?,?,?,?,?,?)",
                  (symbol, kind, severity, title, message, time.time()))


def alerts_list(limit: int = 100, unread_only: bool = False) -> list[dict[str, Any]]:
    q = "SELECT * FROM alerts" + (" WHERE read=0" if unread_only else "") + " ORDER BY created_at DESC LIMIT ?"
    return [dict(r, read=bool(r["read"])) for r in _query(q, (limit,))]


def alerts_unread_count() -> int:
    return int(_query("SELECT COUNT(*) n FROM alerts WHERE read=0")[0]["n"])


def alerts_mark_read(ids: Optional[list[int]] = None) -> None:
    with tx() as c:
        if ids:
            c.executemany("UPDATE alerts SET read=1 WHERE id=?", [(i,) for i in ids])
        else:
            c.execute("UPDATE alerts SET read=1")


# ---------- screener scans ----------
def scan_put(symbol: str, summary: dict[str, Any]) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO scan_results(symbol, summary_json, scanned_at) VALUES (?,?,?)",
                  (symbol, json.dumps(summary, default=str), time.time()))


def scan_list() -> list[dict[str, Any]]:
    return [{"symbol": r["symbol"], "scanned_at": r["scanned_at"], "summary": json.loads(r["summary_json"])}
            for r in _query("SELECT * FROM scan_results")]


# ---------- background jobs ----------
def job_put(id_: str, kind: str, status: str, progress: int = 0, total: int = 0, message: str | None = None,
            started_at: float | None = None, finished_at: float | None = None) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO jobs(id, kind, status, progress, total, message, started_at, finished_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (id_, kind, status, progress, total, message, started_at, finished_at))


def job_get(id_: str) -> Optional[dict[str, Any]]:
    rows = _query("SELECT * FROM jobs WHERE id=?", (id_,))
    return dict(rows[0]) if rows else None


def job_latest(kind: str) -> Optional[dict[str, Any]]:
    rows = _query("SELECT * FROM jobs WHERE kind=? ORDER BY started_at DESC LIMIT 1", (kind,))
    return dict(rows[0]) if rows else None


def setting_get(key: str, default: Any = None) -> Any:
    rows = _query("SELECT value_json FROM settings WHERE key=?", (key,))
    return json.loads(rows[0]["value_json"]) if rows else default


def setting_put(key: str, value: Any) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO settings(key, value_json) VALUES (?,?)", (key, json.dumps(value)))
