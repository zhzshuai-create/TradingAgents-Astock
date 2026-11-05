"""Market routes (api-v1.md section 3), starting with stock search.

Search always answers HTTP 200 with a ``market-envelope-v1`` body: an empty
query is ``empty``, a broken name table is ``error`` with an ``upstream_*``
code, and a stale disk cache is ``stale`` but still carries its items. The
route is read-only and has no database or worker dependency.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from backend.app.api.errors import CODE_MESSAGE
from backend.app.services.ticker_directory import DEFAULT_LIMIT

router = APIRouter(prefix="/api/v1/market", tags=["market"])

ENVELOPE_VERSION = "market-envelope-v1"
UNAVAILABLE_STATUSES = ("empty", "error")


@router.get("/search")
def search_tickers(
    request: Request, q: str = "", limit: int = DEFAULT_LIMIT
) -> dict[str, Any]:
    result = request.app.state.ticker_directory.search(q, limit)
    return {
        "schema_version": ENVELOPE_VERSION,
        "status": result.status,
        "source": result.source,
        "as_of": result.as_of,
        "fetched_at": result.fetched_at,
        "is_stale": result.status == "stale",
        "stale_reason": result.stale_reason,
        "error_code": result.error_code,
        "error_message": (
            CODE_MESSAGE.get(result.error_code) if result.error_code else None
        ),
        "partial": False,
        "failed_blocks": [],
        "data": (
            None
            if result.status in UNAVAILABLE_STATUSES
            else {"items": list(result.items), "truncated": result.truncated}
        ),
    }
