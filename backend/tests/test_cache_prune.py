"""The provider cache is pruned by age and size, but data for companies the user keeps is never removed."""
import time

from app import db

DAY = 86400


def _put(key, kind, age_days, size=10):
    db.cache_put(key, kind, {"blob": "x" * size}, "test")
    with db.tx() as c:
        c.execute("UPDATE cache SET fetched_at=? WHERE key=?", (time.time() - age_days * DAY, key))


def _keys():
    return {r["key"] for r in db._query("SELECT key FROM cache WHERE provider='test'")}


def _clear():
    with db.tx() as c:
        c.execute("DELETE FROM cache WHERE provider='test'")
        c.execute("DELETE FROM watchlist WHERE symbol IN ('KEEP.NS', 'OLD.NS', 'NEW.NS')")


def test_old_entries_go_but_kept_symbols_stay():
    _clear()
    db.watchlist_add("KEEP.NS", "Kept Co")
    _put("fund:KEEP.NS", "fundamentals", 200)
    _put("prices:KEEP.NS", "prices", 200)
    _put("fund:OLD.NS", "fundamentals", 45)
    _put("prices:OLD.NS", "prices", 45)
    _put("search:old query", "search", 45)
    _put("fund:NEW.NS", "fundamentals", 2)
    out = db.cache_prune(max_age_days=30, max_bytes=10**12)
    assert _keys() == {"fund:KEEP.NS", "prices:KEEP.NS", "fund:NEW.NS"}
    assert out["removed"] >= 3
    _clear()


def test_size_cap_removes_oldest_unkept_companies_first():
    _clear()
    db.watchlist_add("KEEP.NS", "Kept Co")
    _put("prices:KEEP.NS", "prices", 20, size=5000)  # oldest, but kept
    _put("prices:OLD.NS", "prices", 10, size=5000)
    _put("prices:NEW.NS", "prices", 1, size=5000)
    other = db._query("SELECT COALESCE(SUM(LENGTH(payload_json)), 0) n FROM cache WHERE provider!='test'")[0]["n"]
    db.cache_prune(max_age_days=30, max_bytes=other + 11_000)  # room for two of the three
    assert _keys() == {"prices:KEEP.NS", "prices:NEW.NS"}
    _clear()


def test_cache_stats_report_size():
    _clear()
    _put("fund:NEW.NS", "fundamentals", 1, size=100)
    assert db.cache_stats()["fundamentals"]["bytes"] >= 100
    _clear()
