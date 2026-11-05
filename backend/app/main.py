"""FastAPI application factory for the job kernel.

The factory never runs at import time: creating an engine would create the
default data directory as a side effect.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request

from backend.app.api.errors import install_error_handlers
from backend.app.api.v1.jobs import router as jobs_router
from backend.app.core.db import build_engine
from backend.app.core.server_config import ServerConfig, load_server_config
from backend.app.services.event_stream import EventStream
from backend.app.services.job_service import JobService
from backend.app.services.report_store import ReportStore


def create_app(
    *,
    service: JobService | None = None,
    server_config: ServerConfig | None = None,
    report_store: ReportStore | None = None,
    event_stream: EventStream | None = None,
) -> FastAPI:
    config = server_config or load_server_config()
    job_service = service or JobService(build_engine(), config)

    app = FastAPI(title="AStock Pro API", version="0.9.0")
    app.state.server_config = config
    app.state.job_service = job_service
    app.state.report_store = report_store or ReportStore.from_env()
    app.state.event_stream = event_stream or EventStream(job_service)
    install_error_handlers(app)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or (
            f"req_{uuid.uuid4().hex[:16]}"
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    app.include_router(jobs_router)
    return app
