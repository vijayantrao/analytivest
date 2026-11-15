"""Backup, restore and security status."""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import backup, backup_crypto, config, db
from ..ingest.extract import MAX_BYTES
from ._shared import read_upload as _read_upload

log = logging.getLogger("stockiq")
router = APIRouter()


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



def _backup_call(fn, *args):
    try:
        return fn(*args)
    except OSError as e:
        raise HTTPException(500, f"Backup folder error: {e.strerror or e}")


@router.get("/api/backup")
def backup_download():
    name = f"analytivest-backup-{time.strftime('%Y%m%d-%H%M%S')}-manual.json"
    return Response(backup.to_bytes(backup.export_data()), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


class EncryptedDownloadIn(BaseModel):
    password: Optional[str] = Field(None, max_length=200)  # omitted -> the saved encryption password


@router.post("/api/backup/encrypted")
def backup_download_encrypted(body: EncryptedDownloadIn):
    name = f"analytivest-backup-{time.strftime('%Y%m%d-%H%M%S')}-manual.enc.json"
    return Response(backup.encrypted_export(body.password), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/backup/status")
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


@router.post("/api/backup/run")
def backup_run():
    p = _backup_call(backup.write_file, "manual")
    cloud = backup.cloud_status() if backup.settings()["cloud"] == "gdrive" else None
    return {"name": p.name, "folder": str(p.parent), "cloud": cloud}


@router.put("/api/backup/settings")
def backup_settings(body: BackupSettingsIn):
    return _backup_call(backup.update_settings, body.auto, body.folder, body.keep, body.cloud, body.gdrive_path,
                        body.encrypt, body.password)


@router.post("/api/backup/purge-plain-cloud")
def backup_purge_plain_cloud():
    return {"deleted": _backup_call(backup.purge_plain_cloud)}


@router.post("/api/backup/restore")
def backup_restore(file: UploadFile = File(...), password: Optional[str] = Form(None, max_length=200)):
    return _backup_call(backup.restore, _read_upload(file), password)


@router.post("/api/backup/restore-file")
def backup_restore_file(body: RestoreFileIn):
    return _backup_call(backup.restore_file, body.name, body.location, body.password)
