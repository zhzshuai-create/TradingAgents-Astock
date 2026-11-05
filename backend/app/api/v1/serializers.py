"""Projection of a jobs row into the frozen JobDetail shape (api-v1.md 1.1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from backend.app.models.job import ALLOWED_ACTIONS, TERMINAL_STATUSES, Job
from backend.app.models.stage import STAGE_IDS, STAGE_NAMES

TOTAL_STAGES = len(STAGE_IDS)
STATS_KEYS = ("model_calls", "tokens_in", "tokens_out", "elapsed_ms")


class TickerNameLookup(Protocol):
    def name(self, code: str) -> str | None: ...


def job_detail(
    job: Job,
    *,
    stages: Mapping[str, Mapping[str, Any]] | None = None,
    stats: Mapping[str, int] | None = None,
    reconcile_notes: Sequence[Mapping[str, str]] = (),
    ticker_name: str | None = None,
    ticker_directory: TickerNameLookup | None = None,
) -> dict[str, Any]:
    entries = [
        _stage_entry(stage_id, index, (stages or {}).get(stage_id))
        for index, stage_id in enumerate(STAGE_IDS, 1)
    ]
    return {
        "job_id": job.id,
        "status": job.status,
        "pending_action": job.pending_action,
        "ticker_code": job.ticker_code,
        "ticker_name": _resolved_name(job, ticker_name, ticker_directory),
        "analysis_date": job.analysis_date,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "current_stage": _current_stage(job.status, entries),
        "stages": entries,
        "stats": {key: int((stats or {}).get(key, 0)) for key in STATS_KEYS},
        "report_id": job.report_id,
        "error": (
            {"code": job.error_code, "message": job.error_message}
            if job.error_code
            else None
        ),
        "config_digest": job.config_hash,
        "graph_version": job.graph_version,
        "retry_of_job_id": job.retry_of_job_id,
        "resume_of_job_id": job.resume_of_job_id,
        "resume_from_stage": job.resume_from_stage,
        "allowed_actions": list(ALLOWED_ACTIONS[job.status]),
        "links": {
            "self": f"/api/v1/jobs/{job.id}",
            "events": f"/api/v1/jobs/{job.id}/events",
            "report": (
                f"/api/v1/reports/{job.report_id}" if job.report_id else None
            ),
        },
        "reconcile_notes": [dict(note) for note in reconcile_notes],
    }


def job_summary(job: Job, **kwargs: Any) -> dict[str, Any]:
    """JobDetail minus ``stages`` (api-v1.md 1.1 JobSummary)."""
    payload = job_detail(job, **kwargs)
    payload.pop("stages")
    return payload


def _resolved_name(
    job: Job,
    override: str | None,
    directory: TickerNameLookup | None,
) -> str | None:
    if override and override.strip():
        return override
    if job.ticker_name and job.ticker_name.strip():
        return job.ticker_name
    if directory is None:
        return None
    try:
        return directory.name(job.ticker_code)
    except Exception:
        # An injected directory must never turn a job read into an error.
        return None


def _stage_entry(
    stage_id: str, index: int, view: Mapping[str, Any] | None
) -> dict[str, Any]:
    view = view or {}
    return {
        "id": stage_id,
        "name": STAGE_NAMES[stage_id],
        "index": index,
        "status": view.get("status", "pending"),
        "started_at": view.get("started_at"),
        "finished_at": view.get("finished_at"),
        "duration_ms": view.get("duration_ms"),
    }


def _current_stage(
    status: str, entries: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    if status == "queued" or status in TERMINAL_STATUSES:
        return None
    active = next((entry for entry in entries if entry["status"] == "active"), None)
    if active is None:
        return None
    return {
        "id": active["id"],
        "name": active["name"],
        "index": active["index"],
        "total": TOTAL_STAGES,
        "status": active["status"],
    }
