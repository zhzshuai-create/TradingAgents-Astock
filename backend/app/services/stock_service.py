"""Stock endpoint orchestration for api-v1.md 3.2-3.4 and 3.6.

The router resolves the ticker and validates parameters; this service owns the
cache endpoint ids, the three snapshot blocks and the text-trust flag. Reports
are read through :class:`ReportQuery` by the router, not here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.app.services.market_cache import MarketCache
from backend.app.services.market_clock import latest_trading_day, now_cst
from backend.app.services.market_envelope import build_blocks_envelope
from backend.app.services.market_providers import MarketProviderProtocol
from backend.app.services.market_service import block_result, single_envelope

DEFAULT_KLINE_PERIOD = "day"
KLINE_PERIODS = ("day", "week", "month")
DEFAULT_KLINE_LIMIT = 120
MAX_KLINE_LIMIT = 5000
DEFAULT_NEWS_LIMIT = 20
MAX_NEWS_LIMIT = 100

SNAPSHOT_UNITS = {"price": "元", "amount": "万元", "mcap": "亿元"}


class StockService:
    def __init__(
        self,
        providers: MarketProviderProtocol,
        cache: MarketCache,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._providers = providers
        self._cache = cache
        self._clock = clock or now_cst

    def snapshot(self, ticker: str) -> dict[str, Any]:
        params = {"ticker": ticker}
        quote = self._cache.get_or_fetch(
            "stock:snapshot:quote",
            params,
            lambda: self._providers.quote(ticker),
            source="tencent",
        )
        valuation = self._cache.get_or_fetch(
            "stock:snapshot:valuation",
            params,
            lambda: self._providers.valuation(ticker),
            source="ths",
        )
        sector = self._cache.get_or_fetch(
            "stock:snapshot:sector_blocks",
            params,
            lambda: self._providers.sector_blocks(ticker),
            source="baidu",
        )
        return build_blocks_envelope(
            {
                "quote": block_result(quote),
                "valuation": block_result(valuation),
                "sector_blocks": block_result(sector),
            },
            extra_data={"units": dict(SNAPSHOT_UNITS)},
        )

    def kline(
        self,
        ticker: str,
        period: str = DEFAULT_KLINE_PERIOD,
        limit: int = DEFAULT_KLINE_LIMIT,
    ) -> dict[str, Any]:
        outcome = self._cache.get_or_fetch(
            "stock:kline",
            {"ticker": ticker, "period": period, "limit": limit},
            lambda: self._providers.kline(ticker, period, limit),
            source="mootdx",
        )
        return single_envelope(outcome)

    def intraday(
        self, ticker: str, date_str: str | None = None
    ) -> dict[str, Any]:
        today = latest_trading_day(self._clock()).isoformat()
        endpoint = (
            "stock:intraday:today"
            if date_str is None or date_str == today
            else "stock:intraday:history"
        )
        outcome = self._cache.get_or_fetch(
            endpoint,
            {"ticker": ticker, "date": date_str or today},
            lambda: self._providers.intraday(ticker, date_str),
            source="mootdx",
        )
        return single_envelope(outcome)

    def news(self, ticker: str, limit: int = DEFAULT_NEWS_LIMIT) -> dict[str, Any]:
        outcome = self._cache.get_or_fetch(
            "stock:news",
            {"ticker": ticker, "limit": limit},
            lambda: self._providers.stock_news(ticker, limit),
            source="eastmoney",
        )
        return single_envelope(outcome, untrusted=True)

    def fund_flow(self, ticker: str) -> dict[str, Any]:
        outcome = self._cache.get_or_fetch(
            "stock:fund-flow",
            {"ticker": ticker},
            lambda: self._providers.fund_flow(ticker),
            source="eastmoney",
        )
        return single_envelope(outcome)
