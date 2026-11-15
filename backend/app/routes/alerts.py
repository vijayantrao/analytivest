"""Alerts and background-job status."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import alerts, db

log = logging.getLogger("stockiq")
router = APIRouter()


# ---------------- Alerts ----------------
class AlertSettingsIn(BaseModel):
    enabled: bool = True
    time: str = Field("18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # Indian stocks, local time
    time_us: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # None = after the New York close


class ReadIn(BaseModel):
    ids: Optional[list[int]] = None


@router.get("/api/alerts")
def alerts_list(unread_only: bool = False, limit: int = Query(100, ge=1, le=500)):
    return {"alerts": db.alerts_list(limit, unread_only), "unread": db.alerts_unread_count(),
            "last_run": db.setting_get("alerts_last_run"), "settings": alerts.settings(),
            "schedule": {"times": alerts.check_times(alerts.settings()), "us_auto": alerts.us_auto_time(),
                         "last_runs": alerts.last_runs(),
                         "tracked": {m: len(alerts.tracked_symbols(m)) for m in ("IN", "US")}},
            "tracked": alerts.tracked_symbols(), "job": db.job_latest("alerts")}


@router.get("/api/alerts/count")
def alerts_count():
    return {"unread": db.alerts_unread_count()}


@router.post("/api/alerts/read")
def alerts_read(body: ReadIn):
    db.alerts_mark_read(body.ids)
    return {"ok": True}


@router.post("/api/alerts/check")
def alerts_check():
    if not alerts.tracked_symbols():
        raise HTTPException(400, "Nothing to check yet: add companies to your watchlist or portfolio.")
    job_id = f"alerts-{uuid.uuid4().hex[:8]}"
    db.job_put(job_id, "alerts", "queued", 0, len(alerts.tracked_symbols()), "queued", time.time())
    alerts.start_background(job_id)
    return {"job_id": job_id}


@router.put("/api/alerts/settings")
def alerts_settings(body: AlertSettingsIn):
    db.setting_put("alerts", body.model_dump())
    return {"ok": True}


@router.get("/api/jobs/{job_id}")
def job(job_id: str):
    j = db.job_get(job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return j
