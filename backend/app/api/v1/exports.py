"""PDF export routes (api-v1.md 2.4-2.5).

``POST`` is the only report route allowed to write files, and only when the
user asks. Status and file GETs never queue work or change a row. First request
returns 202 with ``Location``; a cache hit returns 200 with
``X-Export-Cached: 1``; ``/file`` is 409 until the row is ready.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.app.api.errors import ApiError
from backend.app.models.report_export import EXPORT_TEMPLATES, ReportExport
from backend.app.services.export_service import export_status

router = APIRouter(prefix="/api/v1", tags=["exports"])


class PdfExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str = "default"


@router.post("/reports/{report_id}/exports/pdf", status_code=202)
def create_pdf_export(
    report_id: str,
    request: Request,
    body: PdfExportRequest | None = None,
) -> JSONResponse:
    template = (body.template if body else "default") or "default"
    if template not in EXPORT_TEMPLATES:
        raise ApiError(
            "invalid_request",
            details={
                "field": "template",
                "allowed_values": list(EXPORT_TEMPLATES),
            },
        )
    report = request.app.state.report_query.get_report(report_id)
    if report is None:
        raise ApiError("report_not_found")
    row, cached = request.app.state.export_service.request_pdf(report, template)
    poll_url = f"/api/v1/exports/{row.export_id}"
    headers = {"Location": poll_url}
    if cached:
        headers["X-Export-Cached"] = "1"
    return JSONResponse(
        status_code=200 if cached else 202,
        content={
            "export_id": row.export_id,
            "status": row.status,
            "poll_url": poll_url,
        },
        headers=headers,
    )


@router.get("/exports/{export_id}")
def get_export(export_id: str, request: Request) -> dict[str, Any]:
    return export_status(_export(request, export_id))


@router.get("/exports/{export_id}/file")
def get_export_file(export_id: str, request: Request) -> FileResponse:
    service = request.app.state.export_service
    row = _export(request, export_id)
    path = service.file_path(row)
    if row.status != "ready" or path is None or not path.is_file():
        raise ApiError("export_not_ready")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{row.export_id}.pdf",
    )


def _export(request: Request, export_id: str) -> ReportExport:
    row = request.app.state.export_service.get(export_id)
    if row is None:
        raise ApiError("export_not_found")
    return row
