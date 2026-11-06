"""PDF export queue, cache and lifecycle (P3-03, D2).

One in-process worker renders queued rows; the database row is the queue to
survive restarts. The cache key is frozen at ``report_id + content_hash +
exporter_version + template``. A ready row with its file is a cache hit and is
never rendered again; a failed row or a ready row whose file vanished is
requeued in place. On process start, rows left queued/rendering are marked
failed because their worker is gone.

Files live under ``TA_EXPORTS_DIR``; the row stores a relative POSIX path and
the API only ever exposes ``/api/v1/exports/{id}/file``.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import get_exports_dir
from backend.app.models.report import Report
from backend.app.models.report_export import EXPORT_TEMPLATES, ReportExport
from backend.app.services.job_service import CST
from backend.app.services.pdf_renderer import (
    EXPORTER_VERSION,
    RenderedPdf,
    render_pdf,
)

logger = logging.getLogger(__name__)

RENDER_FAILED = "render_failed"
RENDER_FAILED_MESSAGE = "导出失败，请重试"
RENDER_INTERRUPTED_MESSAGE = "导出中断，请重试"

Renderer = Callable[..., RenderedPdf]


def export_status(export: ReportExport) -> dict[str, Any]:
    download_url = (
        f"/api/v1/exports/{export.export_id}/file"
        if export.status == "ready"
        else None
    )
    error = None
    if export.error_code:
        error = {"code": export.error_code, "message": export.error_message}
    return {
        "export_id": export.export_id,
        "report_id": export.report_id,
        "status": export.status,
        "download_url": download_url,
        "error": error,
        "created_at": export.created_at,
        "ready_at": export.ready_at,
        "exporter_version": export.exporter_version,
    }


class ExportService:
    def __init__(
        self,
        engine: Engine,
        *,
        exports_dir: Path | str | None = None,
        clock: Callable[[], datetime] | None = None,
        renderer: Renderer | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._engine = engine
        self._exports_dir = Path(exports_dir or get_exports_dir())
        self._clock = clock or (lambda: datetime.now(CST))
        self._renderer = renderer or render_pdf
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="pdf-export"
        )

    def request_pdf(
        self, report: Report, template: str = "default"
    ) -> tuple[ReportExport, bool]:
        """Return ``(row, cached)``; ``cached`` drives 200 vs 202."""
        if template not in EXPORT_TEMPLATES:
            raise ValueError("unknown export template")
        for _attempt in range(2):
            existing = self._cached(report, template)
            if existing is not None:
                if self._needs_retry(existing):
                    self._requeue(existing.export_id)
                    self._submit(existing.export_id)
                    return self._row(existing.export_id), False
                return existing, True
            created_at = self._now_text()
            row = ReportExport(
                export_id=str(uuid.uuid4()),
                report_id=report.report_id,
                content_hash=report.content_hash,
                exporter_version=EXPORTER_VERSION,
                template=template,
                status="queued",
                created_at=created_at,
            )
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    session.add(row)
                    session.commit()
            except IntegrityError:
                # A concurrent request won the cache key; read its row.
                continue
            self._submit(row.export_id)
            return row, False
        raise RuntimeError("could not create or reuse the export row")

    def get(self, export_id: str) -> ReportExport | None:
        with Session(self._engine, expire_on_commit=False) as session:
            return session.get(ReportExport, export_id)

    def file_path(self, export: ReportExport) -> Path | None:
        if not export.file_path:
            return None
        return self._exports_dir / Path(export.file_path)

    def sweep_stale(self) -> int:
        """Startup sweep: a worker from a previous process cannot resume."""
        with Session(self._engine) as session:
            result = session.execute(
                update(ReportExport)
                .where(ReportExport.status.in_(("queued", "rendering")))
                .values(
                    status="failed",
                    error_code=RENDER_FAILED,
                    error_message=RENDER_INTERRUPTED_MESSAGE,
                    file_path=None,
                    ready_at=None,
                )
            )
            session.commit()
            return result.rowcount or 0

    def shutdown(self) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _now_text(self) -> str:
        return self._clock().isoformat(timespec="seconds")

    def _cached(self, report: Report, template: str) -> ReportExport | None:
        with Session(self._engine, expire_on_commit=False) as session:
            return session.scalars(
                select(ReportExport).where(
                    ReportExport.report_id == report.report_id,
                    ReportExport.content_hash == report.content_hash,
                    ReportExport.exporter_version == EXPORTER_VERSION,
                    ReportExport.template == template,
                )
            ).first()

    def _needs_retry(self, export: ReportExport) -> bool:
        if export.status == "failed":
            return True
        if export.status != "ready":
            return False
        path = self.file_path(export)
        return path is None or not path.is_file()

    def _row(self, export_id: str) -> ReportExport:
        row = self.get(export_id)
        if row is None:
            raise RuntimeError("export row disappeared")
        return row

    def _requeue(self, export_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(ReportExport)
                .where(ReportExport.export_id == export_id)
                .values(
                    status="queued",
                    file_path=None,
                    error_code=None,
                    error_message=None,
                    ready_at=None,
                )
            )
            session.commit()

    def _submit(self, export_id: str) -> None:
        self._executor.submit(self._render, export_id)

    def _render(self, export_id: str) -> None:
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                export = session.get(ReportExport, export_id)
                if export is None or export.status != "queued":
                    return
                export.status = "rendering"
                session.commit()
                report = session.get(Report, export.report_id)
                if report is None:
                    raise LookupError("report missing")
                payload = report.payload
                report_id = report.report_id
            rendered = self._renderer(payload, exported_at=self._clock())
            relative = Path(report_id) / f"{export_id}.pdf"
            target = self._exports_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f"{target.name}.tmp")
            try:
                temporary.write_bytes(rendered.data)
                os.replace(temporary, target)
            except OSError:
                temporary.unlink(missing_ok=True)
                raise
            self._mark_ready(export_id, relative.as_posix())
        except Exception:
            logger.exception("PDF export %s failed", export_id)
            self._mark_failed(export_id)

    def _mark_ready(self, export_id: str, relative: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(ReportExport)
                .where(
                    ReportExport.export_id == export_id,
                    ReportExport.status == "rendering",
                )
                .values(
                    status="ready",
                    file_path=relative,
                    error_code=None,
                    error_message=None,
                    ready_at=self._now_text(),
                )
            )
            session.commit()

    def _mark_failed(self, export_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                update(ReportExport)
                .where(
                    ReportExport.export_id == export_id,
                    ReportExport.status.in_(("queued", "rendering")),
                )
                .values(
                    status="failed",
                    file_path=None,
                    error_code=RENDER_FAILED,
                    error_message=RENDER_FAILED_MESSAGE,
                    ready_at=None,
                )
            )
            session.commit()
