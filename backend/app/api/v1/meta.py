"""Meta options for the launcher and settings page (api-v1.md 1.8).

Everything here is server-owned: profiles and stage toggles come from
``ServerConfig``, the default date is Beijing time, and the journal block is a
probe result only. The route reads no job row and writes nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from backend.app.core.journal_probe import DEFAULT_ENTRY_URL, JournalProbe
from backend.app.models.stage import STAGE_NAMES
from backend.app.services.job_service import CST

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])

CONTRACT_VERSION = "api-v1"
MAX_ACTIVE_JOBS = 1
MAX_DATE_AHEAD_DAYS = 0
PROFILE_LABELS = {"deepseek-default": "DeepSeek 默认"}


def _now() -> datetime:
    return datetime.now(CST)


def _journal_payload(probe: JournalProbe) -> dict[str, object]:
    """A broken probe degrades to probe_failed; it never fails the response."""
    try:
        return probe.probe().as_payload()
    except Exception:
        return {
            "available": False,
            "entry_url": getattr(probe, "entry_url", DEFAULT_ENTRY_URL),
            "reason": "probe_failed",
        }


@router.get("/options")
def options(request: Request) -> dict[str, Any]:
    config = request.app.state.server_config
    now = _now().astimezone(CST)
    return {
        "app_version": request.app.version,
        "server_time": now.isoformat(timespec="seconds"),
        "default_analysis_date": now.date().isoformat(),
        "llm_profiles": [
            {"id": profile, "label": PROFILE_LABELS.get(profile, profile)}
            for profile in config.llm_profiles
        ],
        "stage_toggles": [
            {
                "id": stage_id,
                "label": STAGE_NAMES.get(stage_id, stage_id),
                "default": default,
            }
            for stage_id, default in config.stage_toggles.items()
        ],
        "limits": {
            "max_active_jobs": MAX_ACTIVE_JOBS,
            "max_date_ahead_days": MAX_DATE_AHEAD_DAYS,
        },
        "journal": _journal_payload(request.app.state.journal_probe),
        "contract_version": CONTRACT_VERSION,
    }
