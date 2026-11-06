"""Report read routes: list, detail, Markdown (api-v1.md 2.1-2.3).

All three are GETs over existing ``reports`` rows. They never reconcile, never
create export rows, never request market data and never write files. Detail and
Markdown recompute ``content_hash`` from ``sections``; a mismatch is a 500
instead of returning half a report.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from backend.app.api.errors import ApiError
from backend.app.models.report import REPORT_RATINGS
from backend.app.services.report_document import compute_content_hash
from backend.app.services.report_query import (
    LIST_DEFAULT_LIMIT,
    InvalidCursor,
    report_summary,
)
from backend.app.services.report_render import render_markdown

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

_TICKER_RE = re.compile(r"^[0-9]{6}$")


@router.get("")
def list_reports(
    request: Request,
    ticker: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    rating: str | None = Query(default=None),
    limit: int = Query(default=LIST_DEFAULT_LIMIT),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    ticker_code = _ticker(ticker)
    ratings = _ratings(rating)
    query = request.app.state.report_query
    try:
        page = query.list_reports(
            ticker=ticker_code,
            date_from=_lenient_date(date_from),
            date_to=_lenient_date(date_to),
            ratings=ratings,
            limit=limit,
            cursor=_cursor(cursor),
        )
    except InvalidCursor as exc:
        raise ApiError("invalid_request", details={"field": "cursor"}) from exc
    return {
        "items": [report_summary(report) for report in page.items],
        "next_cursor": page.next_cursor,
    }


@router.get("/{report_id}")
def get_report(report_id: str, request: Request) -> dict[str, Any]:
    payload = _verified_payload(request, report_id)
    return payload


@router.get("/{report_id}/markdown")
def get_report_markdown(report_id: str, request: Request) -> Response:
    payload = _verified_payload(request, report_id)
    etag = f'"{payload["meta"]["content_hash"]}"'
    if _etag_matches(request.headers.get("If-None-Match"), etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=render_markdown(payload),
        media_type="text/markdown",
        headers={"ETag": etag},
    )


def _verified_payload(request: Request, report_id: str) -> dict[str, Any]:
    report = request.app.state.report_query.get_report(report_id)
    if report is None:
        raise ApiError("report_not_found")
    payload = report.payload
    meta = payload.get("meta") if isinstance(payload, dict) else None
    sections = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(meta, dict) or not isinstance(sections, dict):
        raise ApiError("internal_error")
    if meta.get("content_hash") != compute_content_hash(sections):
        raise ApiError("internal_error")
    return payload


def _ticker(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if not _TICKER_RE.match(value):
        raise ApiError("invalid_request", details={"field": "ticker"})
    return value


def _lenient_date(raw: str | None) -> str | None:
    """Invalid single ends are dropped, not rejected (P3-01 card section 5)."""
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _ratings(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return ()
    values = [part.strip() for part in raw.split(",") if part.strip()]
    if any(value not in REPORT_RATINGS for value in values):
        raise ApiError(
            "invalid_request",
            details={"field": "rating", "allowed_values": list(REPORT_RATINGS)},
        )
    return tuple(dict.fromkeys(values))


def _cursor(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _etag_matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    for candidate in header.split(","):
        value = candidate.strip()
        if value == "*" or value == etag or value == f"W/{etag}":
            return True
    return False
