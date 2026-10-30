"""Projection of a jobs row into the frozen JobDetail shape (api-v1.md 1.1)."""

from __future__ import annotations

from typing import Any

from backend.app.models.job import ALLOWED_ACTIONS, Job
from backend.app.models.stage import STAGE_IDS, STAGE_NAMES


def job_detail(job: Job) -> dict[str, Any]:
    stages = [
        {
            "id": stage_id,
            "name": STAGE_NAMES[stage_id],
            "index": index,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
        }
        for index, stage_id in enumerate(STAGE_IDS, 1)
    ]
    return {
        "job_id": job.id,
        "status": job.status,
        "pending_action": job.pending_action,
        "ticker_code": job.ticker_code,
        "ticker_name": job.ticker_name,
        "analysis_date": job.analysis_date,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "current_stage": None,
        "stages": stages,
        "stats": {
            "model_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "elapsed_ms": 0,
        },
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
        "reconcile_notes": [],
    }
