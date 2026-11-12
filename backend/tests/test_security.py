"""Request guard (host / origin / session token), zip-bomb checks, database migration, backup & restore."""
import base64
import io
import json
import os
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import backup, config, db
from app.ingest.extract import ExtractionError, check_archive, extract_text
from app.main import app
from tests.conftest import AUTH


@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers=AUTH) as c:
        yield c


@pytest.fixture(scope="module")
def anon():
    with TestClient(app) as c:
        yield c


# ---------------- request guard ----------------
def test_api_requires_session_token(anon, client):
    r = anon.get("/api/watchlist")
    assert r.status_code == 401 and r.json()["error"] == "session_expired"
    assert anon.get("/api/watchlist", headers={"X-Analytivest-Token": "wrong"}).status_code == 401
    assert client.get("/api/watchlist").status_code == 200


def test_session_endpoint_gives_token_without_one(anon):
    r = anon.get("/api/session")
    assert r.status_code == 200 and r.json()["token"] == config.SESSION_TOKEN


def test_unknown_host_is_refused(client):
    # DNS rebinding: a page on evil.example re-pointed at 127.0.0.1 still sends Host: evil.example
    r = client.get("/api/session", headers={"Host": "evil.example:8000"})
    assert r.status_code == 400 and r.json()["error"] == "bad_host"
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/session", headers={"Host": "localhost:8000"}).status_code == 200
    assert client.get("/api/session", headers={"Host": "[::1]:8000"}).status_code == 200


def test_cross_site_requests_are_refused(client):
    r = client.post("/api/watchlist", json={"symbol": "DEMO-STEADY"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "cross_site"
    assert client.get("/api/session", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/session", headers={"Origin": "null"}).status_code == 403
    # a different local port is another site too
    assert client.get("/api/session", headers={"Origin": "http://127.0.0.1:3000"}).status_code == 403
    ok = {"Origin": f"http://127.0.0.1:{config.PORT}", "Sec-Fetch-Site": "same-origin"}
    assert client.get("/api/watchlist", headers=ok).status_code == 200
    assert client.get("/api/watchlist", headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert r.headers["Cache-Control"] == "no-store"


# ---------------- zip bombs ----------------
def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_zip_bomb_is_refused():
    bomb = _zip({"word/document.xml": b"\0" * (60 * 1024 * 1024)})
    assert len(bomb) < 200_000
    with pytest.raises(ExtractionError, match="zip bomb"):
        check_archive(bomb)
    with pytest.raises(ExtractionError):
        extract_text(bomb, "report.docx")


def test_normal_zip_passes_and_nesting_is_limited():
    check_archive(_zip({"a.txt": b"Revenue grew 12% this year. " * 2000}))
    inner = _zip({"rhp.txt": b"Price band Rs 100 to Rs 105 per equity share. " * 50})
    nested = _zip({"x.zip.pdf": b"%PDF-broken"})  # not an archive member we recurse into
    assert check_archive(nested) is None
    deep = _zip({"l1.docx": _zip({"l2.docx": inner})})
    with pytest.raises(ExtractionError):
        extract_text(deep, "deep.zip")


def test_portfolio_and_screener_imports_check_archives(client):
    bomb = _zip({"xl/workbook.xml": b"\0" * (60 * 1024 * 1024)})
    r = client.post("/api/portfolio/import", files={"file": ("h.xlsx", bomb)})
    assert r.status_code == 422 and "zip bomb" in r.json()["detail"]
    r = client.post("/api/company/DEMO-STEADY/import", files={"file": ("s.xlsx", bomb)})
    assert r.status_code == 422


# ---------------- moving the database out of the project folder ----------------
def test_migrate_legacy_database(tmp_path):
    old, new = tmp_path / "proj" / "stockiq.db", tmp_path / "local" / "stockiq.db"
    old.parent.mkdir()
    c = sqlite3.connect(old)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE holdings (symbol TEXT PRIMARY KEY, quantity REAL)")
    c.executemany("INSERT INTO holdings VALUES (?,?)", [("TCS.NS", 10), ("INFY.NS", 5)])
    c.commit()  # rows are in the -wal file, not yet checkpointed
    c.close()
    assert db.migrate_legacy(old, new) is True
    assert not old.exists() and not (old.parent / "stockiq.db-wal").exists()
    rows = sqlite3.connect(new).execute("SELECT symbol, quantity FROM holdings ORDER BY symbol").fetchall()
    assert rows == [("INFY.NS", 5.0), ("TCS.NS", 10.0)]
    assert db.migrate_legacy(old, new) is False  # nothing left to move


def test_migrate_never_overwrites_existing(tmp_path):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    for p, v in ((old, "old"), (new, "new")):
        c = sqlite3.connect(p)
        c.execute("CREATE TABLE t (v TEXT)")
        c.execute("INSERT INTO t VALUES (?)", (v,))
        c.commit()
        c.close()
    assert db.migrate_legacy(old, new) is False
    assert old.exists() and sqlite3.connect(new).execute("SELECT v FROM t").fetchone()[0] == "new"


# ---------------- backup & restore ----------------
def test_backup_round_trip(client):
    client.delete("/api/portfolio")
    assert client.post("/api/portfolio", json={"symbol": "DEMO-STEADY", "quantity": 12, "avg_cost": 100}).status_code == 200
    client.post("/api/watchlist", json={"symbol": "DEMO-LEVER"})
    client.put("/api/company/DEMO-STEADY/notes", json={"promoter_pledge_pct": 7})
    r = client.get("/api/backup")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
    data = r.json()
    assert data["app"] == "Analytivest" and data["counts"]["holdings"] == 1
    assert "cache" not in data["tables"]  # market data is not part of a backup
    assert all(row["key"] not in backup.LOCAL_SETTINGS for row in data["tables"]["settings"])

    client.delete("/api/portfolio")
    client.delete("/api/watchlist/DEMO-LEVER")
    client.put("/api/company/DEMO-STEADY/notes", json={})
    r = client.post("/api/backup/restore", files={"file": ("b.json", r.content)})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["restored"]["holdings"] == 1 and res["safety_backup"].endswith("-before-restore.json")
    h = client.get("/api/portfolio").json()["holdings"]
    assert [x["symbol"] for x in h] == ["DEMO-STEADY"] and h[0]["quantity"] == 12
    assert any(w["symbol"] == "DEMO-LEVER" for w in client.get("/api/watchlist").json()["items"])
    assert client.get("/api/company/DEMO-STEADY/notes").json()["promoter_pledge_pct"] == 7

    # the safety copy restores the state before the restore (empty portfolio)
    files = client.get("/api/backup/status").json()["files"]
    safety = next(f["name"] for f in files if f["kind"] == "before-restore")
    assert client.post("/api/backup/restore-file", json={"name": safety}).status_code == 200
    assert client.get("/api/portfolio").json()["holdings"] == []


@pytest.mark.parametrize("payload, message", [
    (b"not json", "not valid JSON"),
    (json.dumps({"app": "Other", "format": 1, "schema_version": 1, "tables": {}}).encode(), "not an Analytivest"),
    (json.dumps({"app": "Analytivest", "format": 99, "schema_version": 1, "tables": {}}).encode(), "newer version"),
    (json.dumps({"app": "Analytivest", "format": 1, "schema_version": 1, "tables": {"cache": []}}).encode(), "Unexpected table"),
    (json.dumps({"app": "Analytivest", "format": 1, "schema_version": 1,
                 "tables": {"holdings": [{'symbol" ) ; DROP TABLE holdings; --': 1}]}}).encode(), "Unknown columns"),
    (json.dumps({"app": "Analytivest", "format": 1, "schema_version": 1,
                 "tables": {"holdings": [{"symbol": {"x": 1}, "quantity": 1, "updated_at": 0}]}}).encode(), "Malformed"),
])
def test_restore_rejects_bad_files(client, payload, message):
    before = client.get("/api/backup/status").json()["counts"]
    r = client.post("/api/backup/restore", files={"file": ("b.json", payload)})
    assert r.status_code == 422 and message in r.json()["detail"]
    assert client.get("/api/backup/status").json()["counts"] == before


def test_restore_file_rejects_paths(client):
    for name in ("../stockiq.db", "..\\x.json", "C:\\Windows\\win.ini", "analytivest-backup-x.json"):
        assert client.post("/api/backup/restore-file", json={"name": name}).status_code == 422


def test_backup_settings_and_pruning(client, tmp_path):
    assert client.put("/api/backup/settings", json={"auto": True, "folder": "relative\\dir", "keep": 3}).status_code == 422
    assert client.put("/api/backup/settings", json={"auto": True, "folder": "", "keep": 0}).status_code == 422
    target = tmp_path / "bk"
    r = client.put("/api/backup/settings", json={"auto": True, "folder": str(target), "keep": 2})
    assert r.status_code == 200 and r.json()["folder"] == str(target)
    for i in range(3):
        p = backup.folder() / f"analytivest-backup-2026010{i + 1}-120000.json"
        p.write_text("{}")
    assert client.post("/api/backup/run").status_code == 200
    names = [f["name"] for f in client.get("/api/backup/status").json()["files"]]
    assert len(names) == 2 and names[0].endswith("-manual.json") and "20260103" in names[1]
    client.put("/api/backup/settings", json={"auto": True, "folder": "", "keep": 8})


def test_automatic_backup_runs_weekly(client, tmp_path):
    client.put("/api/backup/settings", json={"auto": True, "folder": str(tmp_path / "auto"), "keep": 8})
    client.post("/api/portfolio", json={"symbol": "DEMO-STEADY", "quantity": 1})
    db.setting_put("backup_last_auto", 0)
    assert backup.maybe_auto() is not None
    assert backup.maybe_auto() is None  # not due again for a week
    client.put("/api/backup/settings", json={"auto": False, "folder": "", "keep": 8})
    db.setting_put("backup_last_auto", 0)
    assert backup.maybe_auto() is None
    client.delete("/api/portfolio")


# ---------------- Google Drive copies (via the Google Drive for desktop folder) ----------------
def _settings(client, **kw):
    body = {"auto": True, "folder": "", "keep": 8, "cloud": "none", "gdrive_path": ""} | kw
    return client.put("/api/backup/settings", json=body)


def test_gdrive_copies_listing_and_restore(client, tmp_path):
    my_drive = tmp_path / "My Drive"
    my_drive.mkdir()
    assert _settings(client, cloud="gdrive", gdrive_path=str(my_drive)).status_code == 200
    client.delete("/api/portfolio")
    client.post("/api/portfolio", json={"symbol": "DEMO-STEADY", "quantity": 3})
    r = client.post("/api/backup/run").json()
    assert r["cloud"]["ok"] is True
    assert (my_drive / backup.GDRIVE_SUBFOLDER / r["name"]).is_file()
    st = client.get("/api/backup/status").json()
    assert st["gdrive"]["folder"] == str(my_drive / backup.GDRIVE_SUBFOLDER)
    assert {f["location"] for f in st["files"] if f["name"] == r["name"]} == {"local", "gdrive"}

    # restore from the Google Drive copy; the safety copy stays local only
    client.delete("/api/portfolio")
    res = client.post("/api/backup/restore-file", json={"name": r["name"], "location": "gdrive"})
    assert res.status_code == 200, res.text
    assert [h["symbol"] for h in client.get("/api/portfolio").json()["holdings"]] == ["DEMO-STEADY"]
    assert not list((my_drive / backup.GDRIVE_SUBFOLDER).glob("*before-restore*"))
    assert client.post("/api/backup/restore-file", json={"name": r["name"], "location": "elsewhere"}).status_code == 422
    _settings(client)
    client.delete("/api/portfolio")


def test_gdrive_unavailable_keeps_local_backup(client, tmp_path, monkeypatch):
    my_drive = tmp_path / "My Drive"
    my_drive.mkdir()
    _settings(client, cloud="gdrive", gdrive_path=str(my_drive))
    my_drive.rename(tmp_path / "gone")  # e.g. Google Drive for desktop not running
    r = client.post("/api/backup/run")
    assert r.status_code == 200
    assert r.json()["cloud"]["ok"] is False and "not found" in r.json()["cloud"]["message"]
    assert (backup.folder() / r.json()["name"]).is_file()
    _settings(client)


def test_gdrive_setting_requires_a_drive(client, tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "detect_gdrive", lambda: None)
    r = _settings(client, cloud="gdrive")
    assert r.status_code == 422 and "Google Drive for desktop was not found" in r.json()["detail"]
    assert _settings(client, cloud="gdrive", gdrive_path=str(tmp_path / "missing")).status_code == 422
    assert _settings(client, cloud="dropbox").status_code == 422
    assert backup.settings()["cloud"] == "none"
    found = tmp_path / "G" / "My Drive"
    found.mkdir(parents=True)
    monkeypatch.setattr(backup, "detect_gdrive", lambda: found)
    assert _settings(client, cloud="gdrive").status_code == 200  # detected automatically
    assert backup.gdrive_folder() == found / backup.GDRIVE_SUBFOLDER
    _settings(client)


# ---------------- encrypted Google Drive copies ----------------
from app import backup_crypto  # noqa: E402

PW = "correct horse battery"


@pytest.fixture
def fast_kdf(monkeypatch):
    monkeypatch.setattr(backup_crypto, "SCRYPT_N", 2 ** 12)  # files record N, so decryption still works
    if os.name != "nt":  # DPAPI is Windows-only: elsewhere (Linux CI) exercise the logic with a stand-in store
        monkeypatch.setattr(backup_crypto, "can_store_password", lambda: True)
        monkeypatch.setattr(backup_crypto, "seal", lambda pw: "sealed:" + base64.b64encode(pw.encode()[::-1]).decode())
        monkeypatch.setattr(backup_crypto, "unseal", lambda s: base64.b64decode(s.split(":", 1)[1])[::-1].decode())


def test_crypto_round_trip_and_tampering(fast_kdf):
    blob = backup_crypto.encrypt(b'{"secret": "portfolio"}', PW)
    assert b"portfolio" not in blob
    env = backup_crypto.envelope(blob)
    assert env and env["kdf"]["n"] == 2 ** 12
    assert backup_crypto.decrypt(env, PW) == b'{"secret": "portfolio"}'
    with pytest.raises(backup_crypto.WrongPassword):
        backup_crypto.decrypt(env, PW + "x")
    tampered = dict(env, ciphertext=env["ciphertext"][:-4] + ("AAAA" if not env["ciphertext"].endswith("AAAA") else "BBBB"))
    with pytest.raises(backup_crypto.WrongPassword):
        backup_crypto.decrypt(tampered, PW)
    with pytest.raises(ValueError):  # absurd KDF cost in a crafted file is refused, not computed
        backup_crypto.decrypt(dict(env, kdf={**env["kdf"], "n": 2 ** 30}), PW)
    assert backup_crypto.envelope(b'{"app": "Analytivest", "tables": {}}') is None


def test_saved_password_is_protected_and_never_exported(client, tmp_path, fast_kdf):
    my_drive = tmp_path / "My Drive"
    my_drive.mkdir()
    assert _settings(client, cloud="gdrive", gdrive_path=str(my_drive), encrypt=True, password="short").status_code == 422
    r = _settings(client, cloud="gdrive", gdrive_path=str(my_drive), encrypt=True)
    assert r.status_code == 422 and "Set a password" in r.json()["detail"]
    r = _settings(client, cloud="gdrive", gdrive_path=str(my_drive), encrypt=True, password=PW)
    assert r.status_code == 200 and "password" not in r.json()
    sealed = db.setting_get("backup_secret")
    assert sealed and PW not in sealed and backup.stored_password() == PW
    st = client.get("/api/backup/status").json()
    assert st["encryption"]["has_password"] is True and PW not in json.dumps(st)
    exported = client.get("/api/backup").content.decode()
    assert "backup_secret" not in exported and sealed not in exported
    # saving again without a password keeps the stored one
    assert _settings(client, cloud="gdrive", gdrive_path=str(my_drive), encrypt=True).status_code == 200
    assert backup.stored_password() == PW
    # turning encryption off forgets it
    _settings(client)
    assert backup.stored_password() is None


def test_encrypted_gdrive_copy_and_restore(client, tmp_path, fast_kdf):
    my_drive = tmp_path / "My Drive"
    my_drive.mkdir()
    _settings(client, cloud="gdrive", gdrive_path=str(my_drive), encrypt=True, password=PW)
    client.delete("/api/portfolio")
    client.post("/api/portfolio", json={"symbol": "DEMO-STEADY", "quantity": 4})
    r = client.post("/api/backup/run").json()
    assert r["cloud"]["ok"] and r["cloud"]["encrypted"] and r["cloud"]["name"].endswith(".enc.json")
    gfile = my_drive / backup.GDRIVE_SUBFOLDER / r["cloud"]["name"]
    raw = gfile.read_bytes()
    assert b"DEMO-STEADY" not in raw and b"holdings" not in raw  # nothing readable leaves the computer
    assert b"DEMO-STEADY" in (backup.folder() / r["name"]).read_bytes()  # local copy stays readable
    files = client.get("/api/backup/status").json()["files"]
    assert any(f["location"] == "gdrive" and f["encrypted"] for f in files)

    client.delete("/api/portfolio")
    # same computer: the saved password is used automatically
    assert client.post("/api/backup/restore-file", json={"name": gfile.name, "location": "gdrive"}).status_code == 200
    assert client.get("/api/portfolio").json()["holdings"][0]["quantity"] == 4

    # another computer (no saved password): asks for it, rejects a wrong one, accepts the right one
    db.setting_put("backup_secret", None)
    r = client.post("/api/backup/restore", files={"file": (gfile.name, raw)})
    assert r.status_code == 422 and r.json()["error"] == "password_required"
    r = client.post("/api/backup/restore", files={"file": (gfile.name, raw)}, data={"password": "wrong password!"})
    assert r.status_code == 422 and r.json()["error"] == "wrong_password"
    client.delete("/api/portfolio")
    r = client.post("/api/backup/restore", files={"file": (gfile.name, raw)}, data={"password": PW})
    assert r.status_code == 200, r.text
    assert client.get("/api/portfolio").json()["holdings"][0]["quantity"] == 4

    # with the password gone, nothing unencrypted is copied to Google Drive
    before = set((my_drive / backup.GDRIVE_SUBFOLDER).iterdir())
    r = client.post("/api/backup/run").json()
    assert r["cloud"]["ok"] is False and "password is missing" in r["cloud"]["message"]
    assert set((my_drive / backup.GDRIVE_SUBFOLDER).iterdir()) == before
    _settings(client)
    client.delete("/api/portfolio")


def test_purge_plain_gdrive_copies(client, tmp_path, fast_kdf):
    my_drive = tmp_path / "My Drive"
    my_drive.mkdir()
    _settings(client, cloud="gdrive", gdrive_path=str(my_drive))
    client.post("/api/backup/run")  # unencrypted copy
    _settings(client, cloud="gdrive", gdrive_path=str(my_drive), encrypt=True, password=PW)
    client.post("/api/backup/run")  # encrypted copy
    st = client.get("/api/backup/status").json()
    assert st["gdrive"]["plain_copies"] == 1
    assert client.post("/api/backup/purge-plain-cloud").json() == {"deleted": 1}
    left = [f for f in client.get("/api/backup/status").json()["files"] if f["location"] == "gdrive"]
    assert len(left) == 1 and left[0]["encrypted"]
    assert any(f["location"] == "local" for f in client.get("/api/backup/status").json()["files"])
    _settings(client)


def test_encrypted_download_for_manual_upload(client, tmp_path, fast_kdf):
    client.delete("/api/portfolio")
    client.post("/api/portfolio", json={"symbol": "DEMO-LEVER", "quantity": 9})
    _settings(client)  # no saved password
    r = client.post("/api/backup/encrypted", json={})
    assert r.status_code == 422 and r.json()["error"] == "password_required"
    assert client.post("/api/backup/encrypted", json={"password": "short"}).status_code == 422
    r = client.post("/api/backup/encrypted", json={"password": PW})
    assert r.status_code == 200 and r.headers["Content-Disposition"].endswith('.enc.json"')
    assert b"DEMO-LEVER" not in r.content and backup_crypto.envelope(r.content)
    client.delete("/api/portfolio")
    assert client.post("/api/backup/restore", files={"file": ("b.enc.json", r.content)}).json()["error"] == "password_required"
    assert client.post("/api/backup/restore", files={"file": ("b.enc.json", r.content)}, data={"password": PW}).status_code == 200
    assert client.get("/api/portfolio").json()["holdings"][0]["symbol"] == "DEMO-LEVER"

    # with a saved password the download needs none, and restoring here needs none either
    my_drive = tmp_path / "My Drive"
    my_drive.mkdir()
    _settings(client, cloud="gdrive", gdrive_path=str(my_drive), encrypt=True, password=PW)
    r = client.post("/api/backup/encrypted", json={})
    assert r.status_code == 200
    client.delete("/api/portfolio")
    assert client.post("/api/backup/restore", files={"file": ("b.enc.json", r.content)}).status_code == 200
    assert client.get("/api/portfolio").json()["holdings"][0]["quantity"] == 9
    _settings(client)
    client.delete("/api/portfolio")
