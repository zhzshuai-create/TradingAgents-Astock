"""In-process analysis jobs, keyed by the URL job id."""

from __future__ import annotations

import threading
from collections.abc import Callable

from web.progress import ProgressTracker


_jobs: dict[str, ProgressTracker] = {}
_lock = threading.RLock()


def get_job(job_id: str) -> ProgressTracker | None:
    with _lock:
        return _jobs.get(job_id)


def get_or_create_job(
    job_id: str,
    launcher: Callable[[], ProgressTracker],
) -> ProgressTracker:
    with _lock:
        tracker = _jobs.get(job_id)
        if tracker is not None:
            return tracker
        tracker = launcher()
        _jobs[job_id] = tracker
        return tracker
