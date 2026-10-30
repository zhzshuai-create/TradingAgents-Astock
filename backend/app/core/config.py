"""Runtime settings for the job kernel, kept apart from the legacy app."""

from __future__ import annotations

import os
from pathlib import Path

JOBS_DB_ENV = "TA_JOBS_DB"


def get_jobs_db_path() -> Path:
    """Path of the job kernel database; the legacy app never reads it."""
    override = os.environ.get(JOBS_DB_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".tradingagents" / "jobs.db"
