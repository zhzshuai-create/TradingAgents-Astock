"""Job routes: create, detail, control actions and per-stage reports.

api-v1.md sections 1.3, 1.5, 1.6 and 1.10. Control actions only record the
request (or refuse it); the worker lands pause/cancel at a stage boundary and
resume on a free worker. The stage endpoint is read-only: it does not
reconcile, change status, emit events or rerun a stage.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.api.errors import ApiError
from backend.app.api.v1.serializers import job_detail
from backend.app.models.stage import STAGE_IDS, STAGE_NAMES
from backend.app.services.job_service import JobControlError, JobCreateError

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

# api-v1.md 1.6 freezes this literal for every accepted control request.
EXPECTED_EFFECT = "at_stage_boundary"


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    analysis_date: str
    config: dict[str, Any]


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["pause", "resume", "cancel"]


@router.post("")
def create_job(
    payload: CreateJobRequest, request: Request, response: Response
) -> dict[str, Any]:
    idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
    if not idempotency_key:
        raise ApiError("idempotency_key_required")

    service = request.app.state.job_service
    try:
        outcome = service.create_job(
            payload.model_dump(), idempotency_key=idempotency_key
        )
    except JobCreateError as exc:
        raise ApiError.from_create_error(exc) from exc

    if outcome.replayed:
        response.headers["Idempotency-Replayed"] = "1"
    if outcome.existing:
        response.headers["X-Existing-Job"] = outcome.job.id
    response.status_code = outcome.status_code
    return job_detail(outcome.job, **service.detail_parts(outcome.job.id))


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    service = request.app.state.job_service
    job = service.get_job(job_id)
    if job is None:
        raise ApiError("job_not_found")
    return job_detail(job, **service.detail_parts(job_id))


@router.post("/{job_id}/actions")
def control_job(
    job_id: str,
    payload: ControlRequest,
    request: Request,
    response: Response,
) -> dict[str, Any]:
    service = request.app.state.job_service
    try:
        outcome = service.control(job_id, payload.action)
    except JobControlError as exc:
        raise ApiError.from_control_error(exc) from exc

    response.status_code = outcome.status_code
    if not outcome.accepted:
        return {
            "job_id": job_id,
            "accepted": False,
            "reason": outcome.reason,
            "status": outcome.job.status,
        }
    return {
        "job_id": job_id,
        "accepted": True,
        "action": outcome.action,
        "accepted_at": outcome.accepted_at,
        "expected_effect": EXPECTED_EFFECT,
        "status": outcome.job.status,
    }


@router.get("/{job_id}/stages/{stage_id}")
def get_stage_report(job_id: str, stage_id: str, request: Request) -> dict[str, Any]:
    if stage_id not in STAGE_IDS:
        raise ApiError("stage_not_found")

    location = request.app.state.job_service.get_stage_location(job_id, stage_id)
    if location is None:
        raise ApiError("job_not_found")

    markdown = None
    truncated = False
    full_length = 0
    updated_at = None
    if location.status in ("done", "failed") and location.report_path:
        report = request.app.state.report_store.read_stage_report(
            location.report_path
        )
        if report is not None:
            markdown = report.markdown
            truncated = report.truncated
            full_length = report.full_length
            updated_at = report.updated_at

    return {
        "job_id": job_id,
        "stage_id": stage_id,
        "stage_name": STAGE_NAMES[stage_id],
        "index": STAGE_IDS.index(stage_id) + 1,
        "status": location.status,
        "markdown": markdown,
        "truncated": truncated,
        "full_length": full_length,
        "updated_at": updated_at,
    }
