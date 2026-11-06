"""Stock routes (api-v1.md 3.2-3.4 and 3.6).

Every market-data route answers HTTP 200 with a ``market-envelope-v1`` body;
only a malformed ticker or parameter is an HTTP error (422 ticker_* / 400
``invalid_request``). The report list keeps the ``/reports`` body shape and
shares its query through :func:`report_page`. All routes are read-only.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query, Request

from backend.app.api.errors import ApiError
from backend.app.api.v1.reports import report_page
from backend.app.services.market_clock import parse_day
from backend.app.services.report_query import LIST_DEFAULT_LIMIT
from backend.app.services.stock_service import (
    DEFAULT_KLINE_LIMIT,
    DEFAULT_KLINE_PERIOD,
    DEFAULT_NEWS_LIMIT,
    KLINE_PERIODS,
    MAX_KLINE_LIMIT,
    MAX_NEWS_LIMIT,
    StockService,
)
from backend.app.services.tickers import (
    TickerAmbiguous,
    TickerUnresolved,
    resolve_ticker,
)

router = APIRouter(prefix="/api/v1/stocks", tags=["stocks"])

_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _service(request: Request) -> StockService:
    service = getattr(request.app.state, "stock_service", None)
    if service is None:
        service = StockService(
            request.app.state.market_providers,
            request.app.state.market_cache,
        )
        request.app.state.stock_service = service
    return service


def _ticker(raw: str) -> str:
    try:
        return resolve_ticker(raw)
    except TickerUnresolved as exc:
        raise ApiError("ticker_unresolved") from exc
    except TickerAmbiguous as exc:
        raise ApiError(
            "ticker_ambiguous", details={"candidates": exc.candidates}
        ) from exc
    except Exception as exc:
        raise ApiError("internal_error") from exc


def _range_error(field: str, low: int, high: int) -> ApiError:
    return ApiError(
        "invalid_request",
        details={"field": field, "allowed_values": [f"{low}-{high}"]},
    )


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
    if not low <= value <= high:
        raise _range_error(field, low, high)
    return value


def _check_day(value: str) -> None:
    if not _DAY_RE.fullmatch(value) or parse_day(value) is None:
        raise ApiError(
            "invalid_request",
            details={"field": "date", "allowed_values": ["YYYY-MM-DD"]},
        )


@router.get("/{ticker}/snapshot")
def stock_snapshot(request: Request, ticker: str) -> dict[str, Any]:
    return _service(request).snapshot(_ticker(ticker))


@router.get("/{ticker}/kline")
def stock_kline(
    request: Request,
    ticker: str,
    period: str = DEFAULT_KLINE_PERIOD,
    limit: str | None = None,
) -> dict[str, Any]:
    code = _ticker(ticker)
    if period not in KLINE_PERIODS:
        raise ApiError(
            "invalid_request",
            details={"field": "period", "allowed_values": list(KLINE_PERIODS)},
        )
    count = _check_count("limit", limit, DEFAULT_KLINE_LIMIT, 1, MAX_KLINE_LIMIT)
    return _service(request).kline(code, period, count)


@router.get("/{ticker}/intraday")
def stock_intraday(
    request: Request, ticker: str, date: str | None = None
) -> dict[str, Any]:
    code = _ticker(ticker)
    if date is not None:
        _check_day(date)
    return _service(request).intraday(code, date)


@router.get("/{ticker}/news")
def stock_news(
    request: Request, ticker: str, limit: str | None = None
) -> dict[str, Any]:
    code = _ticker(ticker)
    count = _check_count("limit", limit, DEFAULT_NEWS_LIMIT, 1, MAX_NEWS_LIMIT)
    return _service(request).news(code, count)


@router.get("/{ticker}/fund-flow")
def stock_fund_flow(request: Request, ticker: str) -> dict[str, Any]:
    return _service(request).fund_flow(_ticker(ticker))


@router.get("/{ticker}/reports")
def stock_reports(
    request: Request,
    ticker: str,
    limit: int = Query(default=LIST_DEFAULT_LIMIT),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    code = _ticker(ticker)
    return report_page(
        request.app.state.report_query,
        ticker=code,
        limit=limit,
        cursor=cursor,
    )
