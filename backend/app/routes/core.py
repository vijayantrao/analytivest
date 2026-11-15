"""Health, search, methodology and glossary."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query

from .. import config, db, schemas
from ..engine.metrics import METRIC_DEFS
from ..engine.scoring import load_config
from ..glossary import GLOSSARY
from ..providers import registry

log = logging.getLogger("stockiq")
router = APIRouter()


@router.get("/api/health", response_model=schemas.Health)
def health():
    return {"status": "ok", "providers": registry.provider_status(), "offline": config.OFFLINE,
            "cache": db.cache_stats(), "time": time.time()}


@router.get("/api/search")
def search(q: str = Query(..., min_length=1, max_length=60)):
    return registry.search(q)



@router.get("/api/methodology")
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


@router.get("/api/glossary")
def glossary():
    return {"terms": GLOSSARY}
