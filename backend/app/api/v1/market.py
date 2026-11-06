"""Market routes (api-v1.md section 3).

Every route answers HTTP 200 with a ``market-envelope-v1`` body: data-source
failures are ``empty`` / ``error`` / ``stale`` states, never HTTP errors. Only
malformed parameters are 400 ``invalid_request``. All routes are read-only and
have no database or worker dependency; upstream access lives in providers.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request

from backend.app.api.errors import CODE_MESSAGE, ApiError
from backend.app.services.market_clock import parse_day
from backend.app.services.market_service import (
    DEFAULT_CONSTITUENTS_LIMIT,
    DEFAULT_NEWSFLASH_LIMIT,
    DEFAULT_TOP,
    MAX_CONSTITUENTS_LIMIT,
    MAX_NEWSFLASH_LIMIT,
    MAX_TOP,
    MarketRequestError,
    MarketService,
)
from backend.app.services.ticker_directory import DEFAULT_LIMIT

router = APIRouter(prefix="/api/v1/market", tags=["market"])

ENVELOPE_VERSION = "market-envelope-v1"
UNAVAILABLE_STATUSES = ("empty", "error")

_BOARD_CODE_RE = re.compile(r"BK\d{4}")
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _service(request: Request) -> MarketService:
    service = getattr(request.app.state, "market_service", None)
    if service is None:
        service = MarketService(
            request.app.state.market_providers,
            request.app.state.market_cache,
        )
        request.app.state.market_service = service
    return service


def _range_error(field: str, low: int, high: int) -> ApiError:
    return ApiError(
        "invalid_request",
        details={"field": field, "allowed_values": [f"{low}-{high}"]},
    )


def _check_range(field: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        raise _range_error(field, low, high)


def _check_count(
    field: str,
    raw: str | None,
    default: int,
    low: int,
    high: int,
) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _range_error(field, low, high) from None
    _check_range(field, value, low, high)
    return value


def _check_board_code(board_code: str) -> None:
    if not _BOARD_CODE_RE.fullmatch(board_code):
        raise ApiError(
            "invalid_request",
            details={"field": "boardCode", "allowed_values": ["BK0000-BK9999"]},
        )


def _check_day(value: str) -> None:
    if not _DAY_RE.fullmatch(value) or parse_day(value) is None:
        raise ApiError(
            "invalid_request",
            details={"field": "date", "allowed_values": ["YYYY-MM-DD"]},
        )


def _guard(call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return call()
    except MarketRequestError as exc:
        raise ApiError("invalid_request", details=exc.details) from exc


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


@router.get("/overview")
def market_overview(request: Request) -> dict[str, Any]:
    return _guard(lambda: _service(request).overview())


@router.get("/industries")
def market_industries(
    request: Request, top: str | None = None
) -> dict[str, Any]:
    count = _check_count("top", top, DEFAULT_TOP, 1, MAX_TOP)
    return _guard(lambda: _service(request).industries(count))


@router.get("/industries/{board_code}/stocks")
def industry_constituents(
    request: Request,
    board_code: str,
    limit: str | None = None,
) -> dict[str, Any]:
    _check_board_code(board_code)
    count = _check_count(
        "limit", limit, DEFAULT_CONSTITUENTS_LIMIT, 1, MAX_CONSTITUENTS_LIMIT
    )
    return _guard(lambda: _service(request).constituents(board_code, count))


@router.get("/strong-stocks")
def market_strong_stocks(
    request: Request, date: str | None = None
) -> dict[str, Any]:
    if date is not None:
        _check_day(date)
    return _guard(lambda: _service(request).strong_stocks(date))


@router.get("/newsflash")
def market_newsflash(
    request: Request, limit: str | None = None
) -> dict[str, Any]:
    count = _check_count(
        "limit", limit, DEFAULT_NEWSFLASH_LIMIT, 1, MAX_NEWSFLASH_LIMIT
    )
    return _guard(lambda: _service(request).newsflash(count))
