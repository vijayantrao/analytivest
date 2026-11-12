"""Backup and restore of everything you entered or imported (not the re-downloadable provider cache).

A backup is one readable JSON file:
    {"app": "Analytivest", "format": 1, "schema_version": n, "created_at": "...", "counts": {...},
     "tables": {"watchlist": [row, ...], "holdings": [...], ...}}
Restoring replaces the tables present in the file, inside one transaction, after first saving a safety
backup of the current data. Automatic backups run weekly while the app runs.

Backups are always written to a local folder. Optionally each one is also copied into Google Drive through the
folder that Google Drive for desktop provides ("My Drive"), which uploads it. The app never holds Google
credentials: sign-in and upload are handled by Google's own app.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import string
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import backup_crypto, config, db

log = logging.getLogger("stockiq.backup")

FORMAT = 1
# Tables with user data. The provider cache, screener scans and job records are rebuilt automatically.
USER_TABLES = ("watchlist", "company_notes", "saved_analysis", "ipo", "settings", "imports", "holdings",
               "snapshots", "alerts")
# Machine-specific settings: neither exported nor overwritten by a restore.
LOCAL_SETTINGS = ("backup", "backup_last_auto", "backup_cloud_last", "backup_secret")
# folder "" = default local folder; cloud "none" = keep local only; gdrive_path "" = detect "My Drive"
# encrypt: password-encrypt the Google Drive copies (local copies stay readable on this computer)
DEFAULTS: dict[str, Any] = {"auto": True, "folder": "", "keep": 8, "cloud": "none", "gdrive_path": "",
                            "encrypt": False}
AUTO_EVERY_DAYS = 7
KEEP_SAFETY = 3
NAME_RE = re.compile(r"^analytivest-backup-\d{8}-\d{6}(?:-(before-restore|manual))?(\.enc)?\.json$")
SYNCED_FOLDER_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "my drive", "icloud")
GDRIVE_SUBFOLDER = "Analytivest Backups"
LOCATIONS = ("local", "gdrive")


class BackupError(Exception):
    def __init__(self, message: str, code: str = "backup_error"):
        super().__init__(message)
        self.code = code  # "password_required" / "wrong_password" let the UI ask for the password


def stored_password() -> str | None:
    sealed = db.setting_get("backup_secret")
    if not sealed:
        return None
    try:
        return backup_crypto.unseal(sealed)
    except OSError as e:  # e.g. the database was copied to another Windows account
        log.warning("saved backup password unavailable: %s", e)
        return None


# ---------------- settings ----------------
def settings() -> dict[str, Any]:
    return {**DEFAULTS, **(db.setting_get("backup") or {})}


def folder() -> Path:
    f = settings()["folder"]
    return Path(f) if f else config.BACKUP_DIR_DEFAULT


def detect_gdrive() -> Path | None:
    """The "My Drive" folder of Google Drive for desktop: a virtual drive (G: by default, any letter
    possible) in streaming mode, or a folder under the user profile in mirror mode."""
    candidates = [Path(f"{d}:\\") / "My Drive" for d in string.ascii_uppercase[3:]] if os.name == "nt" else []
    home = Path.home()
    candidates += [home / "My Drive", home / "Google Drive" / "My Drive", home / "Google Drive"]
    for c in candidates:
        try:
            if c.is_dir():
                return c
        except OSError:  # e.g. a disconnected drive letter
            continue
    return None


def gdrive_folder(s: dict[str, Any] | None = None) -> Path | None:
    """Where Google Drive copies go, or None when local-only or Google Drive is not available."""
    s = s or settings()
    if s["cloud"] != "gdrive":
        return None
    base = Path(s["gdrive_path"]) if s["gdrive_path"] else detect_gdrive()
    return base / GDRIVE_SUBFOLDER if base and base.is_dir() else None


def _writable(p: Path) -> None:
    try:
        p.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=p, prefix=".write-test-"):
            pass
    except OSError as e:
        raise BackupError(f"Cannot write to {p}: {e.strerror or e}") from e


def _abs_path(text: str) -> Path:
    p = Path(os.path.expandvars(text)).expanduser()
    if not p.is_absolute():
        raise BackupError(f"Enter a full folder path (for example D:\\Backups), not {text!r}.")
    return p


def update_settings(auto: bool, folder_str: str, keep: int, cloud: str = "none", gdrive_path: str = "",
                    encrypt: bool = False, password: str | None = None) -> dict[str, Any]:
    folder_str, gdrive_path = (folder_str or "").strip(), (gdrive_path or "").strip()
    if encrypt:
        if password:
            if len(password) < backup_crypto.MIN_PASSWORD_LEN:
                raise BackupError(f"Use a password of at least {backup_crypto.MIN_PASSWORD_LEN} characters.")
            if not backup_crypto.can_store_password():
                raise BackupError("Encrypted automatic backups need Windows to keep the password safe.")
        elif not stored_password():
            raise BackupError("Set a password to encrypt the Google Drive copies.")
    if folder_str:
        p = _abs_path(folder_str)
        _writable(p)
        folder_str = str(p)
    if not 1 <= keep <= 52:
        raise BackupError("Keep between 1 and 52 backups.")
    if cloud not in ("none", "gdrive"):
        raise BackupError("Choose local only or Google Drive.")
    if cloud == "gdrive":
        if gdrive_path:
            base = _abs_path(gdrive_path)
            if not base.is_dir():
                raise BackupError(f"{base} does not exist. Enter the path of your Google Drive \"My Drive\" folder.")
            gdrive_path = str(base)
        else:
            base = detect_gdrive()
            if base is None:
                raise BackupError("Google Drive for desktop was not found. Install it and sign in, or enter the path "
                                  "of your \"My Drive\" folder.")
        _writable(base / GDRIVE_SUBFOLDER)
    if encrypt and password:
        db.setting_put("backup_secret", backup_crypto.seal(password))
    elif not encrypt:
        db.setting_put("backup_secret", None)  # don't keep a password that is no longer used
    db.setting_put("backup", {"auto": bool(auto), "folder": folder_str, "keep": int(keep), "cloud": cloud,
                              "gdrive_path": gdrive_path, "encrypt": bool(encrypt)})
    return settings()


def in_synced_folder(p: Path) -> bool:
    return any(any(m in part.lower() for m in SYNCED_FOLDER_MARKERS) for part in p.resolve().parts)


# ---------------- export ----------------
def _columns(c: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in c.execute(f'PRAGMA table_info("{table}")')}


def export_data() -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    with db.tx() as c:
        for t in USER_TABLES:
            rows = [dict(r) for r in c.execute(f'SELECT * FROM "{t}"')]
            if t == "settings":
                rows = [r for r in rows if r["key"] not in LOCAL_SETTINGS]
            tables[t] = rows
    return {"app": "Analytivest", "format": FORMAT, "schema_version": db.SCHEMA_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "counts": {t: len(r) for t, r in tables.items()}, "tables": tables}


def to_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def encrypted_export(password: str | None = None) -> bytes:
    """A password-encrypted backup to upload anywhere by hand (e.g. drive.google.com in the browser).
    Uses the given password, else the saved encryption password."""
    if password and len(password) < backup_crypto.MIN_PASSWORD_LEN:
        raise BackupError(f"Use a password of at least {backup_crypto.MIN_PASSWORD_LEN} characters.")
    pw = password or stored_password()
    if not pw:
        raise BackupError("Enter a password to encrypt the backup.", "password_required")
    return backup_crypto.encrypt(to_bytes(export_data()), pw)


def counts() -> dict[str, int]:
    with db.tx() as c:
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in USER_TABLES}


# ---------------- files ----------------
def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def write_file(tag: str = "") -> Path:
    """Writes a backup locally and, unless it is a safety copy or local-only is chosen, to Google Drive.
    The Google Drive outcome is recorded (see cloud_status) rather than raised: the local copy still counts."""
    f = folder()
    f.mkdir(parents=True, exist_ok=True)
    name = f"analytivest-backup-{datetime.now():%Y%m%d-%H%M%S}{'-' + tag if tag else ''}.json"
    data = to_bytes(export_data())
    path = f / name
    _atomic_write(path, data)
    prune("local")
    log.info("Backup written to %s", path)
    s = settings()
    if s["cloud"] == "gdrive" and tag != "before-restore":
        g = gdrive_folder(s)
        try:
            if g is None:
                raise BackupError("Google Drive folder not found. Is Google Drive for desktop running and signed in?")
            cloud_name, cloud_data = name, data
            if s["encrypt"]:
                pw = stored_password()
                if not pw:
                    raise BackupError("The encryption password is missing. Set it again under Backups; "
                                      "nothing unencrypted was copied to Google Drive.")
                cloud_name, cloud_data = name[:-5] + ".enc.json", backup_crypto.encrypt(data, pw)
            g.mkdir(parents=True, exist_ok=True)
            _atomic_write(g / cloud_name, cloud_data)
            prune("gdrive")
            status = {"ok": True, "message": f"Copied to {g}", "name": cloud_name, "encrypted": s["encrypt"]}
        except (OSError, BackupError) as e:
            status = {"ok": False, "message": str(e) if isinstance(e, BackupError) else f"Google Drive copy failed: {e}"}
            log.warning("backup: %s", status["message"])
        db.setting_put("backup_cloud_last", {**status, "at": time.time()})
    return path


def cloud_status() -> dict[str, Any] | None:
    return db.setting_get("backup_cloud_last")


def _folder_for(location: str) -> Path | None:
    if location not in LOCATIONS:
        raise BackupError("Unknown backup location.")
    return folder() if location == "local" else gdrive_folder()


def list_files(location: str = "local") -> list[dict[str, Any]]:
    f = _folder_for(location)
    if f is None or not f.is_dir():
        return []
    out = []
    for p in f.iterdir():
        m = NAME_RE.match(p.name)
        if m and p.is_file():
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "modified": st.st_mtime, "kind": m.group(1) or "auto",
                        "location": location, "encrypted": bool(m.group(2))})
    return sorted(out, key=lambda x: x["name"][19:34], reverse=True)  # by the timestamp in the name


def list_all() -> list[dict[str, Any]]:
    return list_files("local") + list_files("gdrive")


def prune(location: str) -> None:
    f = _folder_for(location)
    files = list_files(location)
    regular = [x for x in files if x["kind"] != "before-restore"]
    safety = [x for x in files if x["kind"] == "before-restore"]
    for x in regular[settings()["keep"]:] + safety[KEEP_SAFETY:]:
        (f / x["name"]).unlink(missing_ok=True)


# ---------------- restore ----------------
def parse(data: bytes) -> dict[str, Any]:
    try:
        d = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BackupError("This is not an Analytivest backup file (it is not valid JSON).") from e
    if not isinstance(d, dict) or d.get("app") != "Analytivest" or not isinstance(d.get("tables"), dict):
        raise BackupError("This is not an Analytivest backup file.")
    if not isinstance(d.get("format"), int) or d["format"] > FORMAT:
        raise BackupError("This backup was made by a newer version of Analytivest. Update the app first.")
    if not isinstance(d.get("schema_version"), int) or d["schema_version"] > db.SCHEMA_VERSION:
        raise BackupError("This backup was made by a newer version of Analytivest. Update the app first.")
    with db.tx() as c:
        for t, rows in d["tables"].items():
            if t not in USER_TABLES:
                raise BackupError(f"Unexpected table in backup: {t!r}.")
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                raise BackupError(f"Malformed rows for {t}.")
            cols = _columns(c, t)
            for r in rows:
                if not set(r) <= cols:
                    raise BackupError(f"Unknown columns in {t}: {sorted(set(r) - cols)}.")
                if not all(v is None or isinstance(v, (str, int, float)) for v in r.values()):
                    raise BackupError(f"Malformed value in {t}.")
    return d


def decrypt_if_needed(data: bytes, password: str | None) -> bytes:
    env = backup_crypto.envelope(data)
    if env is None:
        return data
    pw = password or stored_password()
    if not pw:
        raise BackupError("This backup is encrypted. Enter its password.", "password_required")
    try:
        return backup_crypto.decrypt(env, pw)
    except backup_crypto.WrongPassword as e:
        raise BackupError("Wrong password for this encrypted backup." if password else
                          "This backup was encrypted with a different password. Enter its password.",
                          "wrong_password") from e
    except ValueError as e:
        raise BackupError(str(e)) from e


def purge_plain_cloud() -> int:
    """Deletes unencrypted backup copies from the Google Drive folder (they go to Google Drive's trash)."""
    f = gdrive_folder()
    plain = [x for x in list_files("gdrive") if not x["encrypted"]] if f else []
    for x in plain:
        (f / x["name"]).unlink(missing_ok=True)
    return len(plain)


def restore(data: bytes, password: str | None = None) -> dict[str, Any]:
    d = parse(decrypt_if_needed(data, password))
    safety = write_file("before-restore")
    restored: dict[str, int] = {}
    try:
        with db.tx() as c:
            for t, rows in d["tables"].items():
                if t == "settings":
                    c.execute(f"DELETE FROM settings WHERE key NOT IN ({','.join('?' * len(LOCAL_SETTINGS))})",
                              LOCAL_SETTINGS)
                    rows = [r for r in rows if r.get("key") not in LOCAL_SETTINGS]
                else:
                    c.execute(f'DELETE FROM "{t}"')
                for r in rows:  # column names were checked against the table schema in parse()
                    cols = list(r)
                    c.execute(f'INSERT INTO "{t}" ({",".join(chr(34) + k + chr(34) for k in cols)}) '
                              f'VALUES ({",".join("?" * len(cols))})', [r[k] for k in cols])
                restored[t] = len(rows)
    except sqlite3.Error as e:
        raise BackupError(f"The backup could not be restored ({e}); nothing was changed.") from e
    return {"restored": restored, "created_at": d.get("created_at"), "safety_backup": safety.name,
            "safety_folder": str(safety.parent)}


def restore_file(name: str, location: str = "local", password: str | None = None) -> dict[str, Any]:
    if not NAME_RE.match(name or ""):
        raise BackupError("Unknown backup file.")
    f = _folder_for(location)
    p = f / name if f else None
    if p is None or not p.is_file():
        raise BackupError("That backup file no longer exists.")
    return restore(p.read_bytes(), password)


# ---------------- automatic weekly backups ----------------
def maybe_auto() -> Path | None:
    if not settings()["auto"]:
        return None
    last = db.setting_get("backup_last_auto")
    if last and time.time() - last < AUTO_EVERY_DAYS * 86400:
        return None
    c = counts()
    if not any(n for t, n in c.items() if t not in ("ipo", "settings")):  # nothing of yours to back up yet
        return None
    path = write_file()
    db.setting_put("backup_last_auto", time.time())
    return path


def scheduler_loop(stop: threading.Event) -> None:
    """Checks two minutes after start, then hourly; writes a backup when the last one is a week old."""
    delay = 120
    while not stop.wait(delay):
        delay = 3600
        try:
            maybe_auto()
        except Exception as e:
            log.warning("automatic backup failed: %s", e)
