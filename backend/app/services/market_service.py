"""Market endpoint orchestration: cache keys, block merging and session.

The router owns parameter validation and HTTP mapping; this service owns which
provider feeds which block, the TTL endpoint ids and the envelope shape for the
five market GETs added in P4-02.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend.app.services.market_cache import CacheOutcome, MarketCache
from backend.app.services.market_clock import (
    format_cst,
    is_trading_day,
    latest_trading_day,
    market_session,
    now_cst,
    parse_day,
    to_cst,
)
from backend.app.services.market_envelope import (
    BlockResult,
    build_blocks_envelope,
    build_envelope,
)
from backend.app.services.market_providers import MarketProviderProtocol

DEFAULT_TOP = 20
MAX_TOP = 50
DEFAULT_CONSTITUENTS_LIMIT = 10
MAX_CONSTITUENTS_LIMIT = 100
DEFAULT_NEWSFLASH_LIMIT = 30
MAX_NEWSFLASH_LIMIT = 100


class MarketRequestError(ValueError):
    """A semantic parameter error the router maps to ``invalid_request``."""

    def __init__(
        self,
        field: str,
        *,
        allowed_values: list[Any] | None = None,
    ) -> None:
        self.field = field
        self.allowed_values = allowed_values
        super().__init__(field)

    @property
    def details(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"field": self.field}
        if self.allowed_values is not None:
            payload["allowed_values"] = self.allowed_values
        return payload


class MarketService:
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

    def now(self) -> datetime:
        return to_cst(self._clock())

    # -- endpoints ---------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        indices = self._cache.get_or_fetch(
            "market:overview:indices",
            {},
            self._providers.indices,
            source="tencent",
        )
        northbound = self._cache.get_or_fetch(
            "market:overview:northbound",
            {},
            self._providers.northbound,
            source="hexin",
        )
        return build_blocks_envelope(
            {
                "indices": _block(indices),
                "northbound": _block(northbound),
            },
            extra_data={"market_session": market_session(self._clock())},
        )

    def industries(self, top: int = DEFAULT_TOP) -> dict[str, Any]:
        outcome = self._cache.get_or_fetch(
            "market:industries",
            {"top": top},
            lambda: self._providers.industries(top),
            source="eastmoney",
        )
        return _single(outcome)

    def constituents(
        self, board_code: str, limit: int = DEFAULT_CONSTITUENTS_LIMIT
    ) -> dict[str, Any]:
        known = self._known_boards()
        if known is not None and board_code not in known:
            raise MarketRequestError(
                "boardCode", allowed_values=["BK0000-BK9999"]
            )
        outcome = self._cache.get_or_fetch(
            "market:industries:stocks",
            {"board": board_code, "limit": limit},
            lambda: self._providers.constituents(board_code, limit),
            source="eastmoney",
        )
        return _single(outcome)

    def strong_stocks(self, date_str: str | None = None) -> dict[str, Any]:
        target = (
            latest_trading_day(self._clock())
            if date_str is None
            else parse_day(date_str)
        )
        if target is None:
            raise MarketRequestError("date", allowed_values=["YYYY-MM-DD"])
        if not is_trading_day(target):
            return build_envelope(
                status="empty",
                source="ths",
                as_of=None,
                fetched_at=format_cst(self.now()),
                data=None,
            )
        outcome = self._cache.get_or_fetch(
            "market:strong-stocks",
            {"date": target.isoformat()},
            lambda: self._providers.strong_stocks(target.isoformat()),
            source="ths",
        )
        return _single(outcome, untrusted=True)

    def newsflash(self, limit: int = DEFAULT_NEWSFLASH_LIMIT) -> dict[str, Any]:
        outcome = self._cache.get_or_fetch(
            "market:newsflash",
            {"limit": limit},
            lambda: self._providers.newsflash(limit),
            source="cls",
        )
        return _single(outcome, untrusted=True)

    # -- helpers -----------------------------------------------------------
    def _known_boards(self) -> set[str] | None:
        envelope = self.industries(MAX_TOP)
        if envelope["status"] not in ("ok", "stale") or not isinstance(
            envelope["data"], dict
        ):
            return None
        rows = list(envelope["data"].get("top") or []) + list(
            envelope["data"].get("bottom") or []
        )
        return {str(row.get("code")) for row in rows if row.get("code")}


def _block(outcome: CacheOutcome) -> BlockResult:
    return BlockResult(
        status=outcome.status,
        source=outcome.source,
        as_of=outcome.as_of,
        fetched_at=outcome.fetched_at,
        data=outcome.data,
        stale_reason=outcome.stale_reason,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
    )


def _single(outcome: CacheOutcome, *, untrusted: bool = False) -> dict[str, Any]:
    data = outcome.data
    if untrusted and outcome.status in ("ok", "stale") and isinstance(data, dict):
        data = {**data, "untrusted": True}
    return build_envelope(
        status=outcome.status,
        source=outcome.source,
        as_of=outcome.as_of,
        fetched_at=outcome.fetched_at,
        data=data,
        stale_reason=outcome.stale_reason,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
    )
