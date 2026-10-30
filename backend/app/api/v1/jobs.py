"""Job routes: create and detail (api-v1.md sections 1.3 and 1.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.api.errors import ApiError
from backend.app.api.v1.serializers import job_detail
from backend.app.services.job_service import JobCreateError

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    analysis_date: str
    config: dict[str, Any]


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
    return job_detail(outcome.job)


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, Any]:
    job = request.app.state.job_service.get_job(job_id)
    if job is None:
        raise ApiError("job_not_found")
    return job_detail(job)
