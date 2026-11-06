"""FastAPI application factory for the job kernel.

The factory never runs at import time: creating an engine would create the
default data directory as a side effect.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from backend.app.api.errors import install_error_handlers
from backend.app.api.v1.exports import router as exports_router
from backend.app.api.v1.jobs import router as jobs_router
from backend.app.api.v1.market import router as market_router
from backend.app.api.v1.meta import router as meta_router
from backend.app.api.v1.reports import router as reports_router
from backend.app.api.v1.stocks import router as stocks_router
from backend.app.core.db import build_engine
from backend.app.core.journal_probe import JournalProbe
from backend.app.core.server_config import ServerConfig, load_server_config
from backend.app.services.event_stream import EventStream
from backend.app.services.export_service import ExportService
from backend.app.services.job_service import JobService
from backend.app.services.market_cache import MarketCache
from backend.app.services.market_providers import DefaultMarketProviders
from backend.app.services.report_query import ReportQuery
from backend.app.services.report_store import ReportStore
from backend.app.services.ticker_directory import TickerDirectory


def create_app(
    *,
    service: JobService | None = None,
    server_config: ServerConfig | None = None,
    report_store: ReportStore | None = None,
    event_stream: EventStream | None = None,
    ticker_directory: TickerDirectory | None = None,
    journal_probe: JournalProbe | None = None,
    export_service: ExportService | None = None,
    market_providers: DefaultMarketProviders | None = None,
    market_cache: MarketCache | None = None,
) -> FastAPI:
    config = server_config or load_server_config()
    job_service = service or JobService(build_engine(), config)
    exports = export_service or ExportService(job_service.engine)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        exports.shutdown()

    app = FastAPI(title="AStock Pro API", version="0.9.0", lifespan=_lifespan)
    app.state.server_config = config
    app.state.job_service = job_service
    app.state.report_query = ReportQuery(job_service.engine)
    app.state.report_store = report_store or ReportStore.from_env()
    app.state.event_stream = event_stream or EventStream(job_service)
    app.state.ticker_directory = ticker_directory or TickerDirectory()
    app.state.journal_probe = journal_probe or JournalProbe()
    app.state.export_service = exports
    app.state.market_providers = market_providers or DefaultMarketProviders()
    app.state.market_cache = market_cache or MarketCache()
    # A worker from the previous process cannot finish its queued/rendering rows.
    exports.sweep_stale()
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
    app.include_router(market_router)
    app.include_router(meta_router)
    app.include_router(reports_router)
    app.include_router(stocks_router)
    app.include_router(exports_router)
    return app
