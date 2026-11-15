"""Helpers shared by several routers."""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

from ..ingest.extract import MAX_BYTES


def read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large.")
    return data
