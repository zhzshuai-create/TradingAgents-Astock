"""In-process TTL cache with single-flight refresh and stale fallback.

Keys are ``(endpoint_id, normalised params)``; values carry the data plus the
metadata a block needs. Only successful answers (ok/empty/stale) enter the
positive cache. A failed fetch may additionally be remembered for a short,
per-endpoint negative TTL so a known-failing upstream is not retried on every
request; old data still wins and is served as ``stale``.
Entirely in memory: no disk, no database, no directory creation.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.app.services.market_clock import (
    format_cst,
    now_cst,
    to_cst,
    trading_day_mismatch,
)
from backend.app.services.market_providers import Fetched, ProviderError, as_provider_error

MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)

STALE_AFTER: dict[str, timedelta] = {
    "market:search": timedelta(hours=24),
    "market:overview:indices": timedelta(seconds=10),
    "market:overview:northbound": timedelta(seconds=30),
    "market:industries": timedelta(minutes=5),
    "market:industries:stocks": timedelta(minutes=2),
    "market:strong-stocks": HOUR,
    "market:newsflash": timedelta(minutes=2),
    "stock:snapshot:quote": timedelta(seconds=60),
    "stock:snapshot:valuation": timedelta(hours=4),
    "stock:snapshot:sector_blocks": timedelta(hours=24),
    "stock:kline": timedelta(minutes=5),
    "stock:intraday:today": timedelta(seconds=30),
    "stock:intraday:history": HOUR,
    "stock:news": timedelta(minutes=5),
    "stock:fund-flow": timedelta(seconds=60),
}

NEGATIVE_TTL: dict[str, timedelta] = {
    "stock:snapshot:sector_blocks": MINUTE,
}


@dataclass(frozen=True)
class CacheOutcome:
    status: str
    data: Any
    as_of: str | None
    fetched_at: str
    source: str
    stale_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    from_cache: bool = False


@dataclass(frozen=True)
class _Entry:
    data: Any
    as_of: str | None
    fetched_at: datetime
    fetched_at_text: str
    source: str
    status: str
    stale_reason: str | None = None


@dataclass(frozen=True)
class _Failure:
    failed_at: datetime
    error_code: str
    error_message: str
    fetched_at_text: str


class _Flight:
    __slots__ = ("event", "outcome")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.outcome: CacheOutcome | None = None


def normalize_params(params: Mapping[str, Any] | None) -> tuple[tuple[str, Any], ...]:
    if not params:
        return ()
    items = []
    for key in sorted(params):
        value = params[key]
        if isinstance(value, (list, tuple)):
            value = tuple(str(item) for item in value)
        elif isinstance(value, bool):
            value = str(value).lower()
        else:
            value = str(value)
        items.append((str(key), value))
    return tuple(items)


class MarketCache:
    """Synchronous TTL cache; one provider call per key at a time."""

    def __init__(
        self,
        *,
        stale_after: Mapping[str, timedelta] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._stale_after = dict(stale_after if stale_after is not None else STALE_AFTER)
        self._negative_ttl = dict(NEGATIVE_TTL)
        self._clock = clock or now_cst
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, tuple[tuple[str, Any], ...]], _Entry] = {}
        self._failures: dict[tuple[str, tuple[tuple[str, Any], ...]], _Failure] = {}
        self._flights: dict[tuple[str, tuple[tuple[str, Any], ...]], _Flight] = {}

    def stale_after(self, endpoint_id: str) -> timedelta:
        try:
            return self._stale_after[endpoint_id]
        except KeyError as exc:
            raise KeyError(f"未登记的缓存端点: {endpoint_id}") from exc

    def get_or_fetch(
        self,
        endpoint_id: str,
        params: Mapping[str, Any] | None,
        fetcher: Callable[[], Fetched],
        *,
        source: str,
    ) -> CacheOutcome:
        ttl = self.stale_after(endpoint_id)
        key = (endpoint_id, normalize_params(params))
        now = to_cst(self._clock())

        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and not self._needs_refresh(entry, now, ttl):
                return self._from_entry(entry, from_cache=True)
            negative = self._active_failure(endpoint_id, key, now)
            if negative is not None:
                if entry is not None and entry.data is not None:
                    return self._stale_from_entry(entry, now)
                return self._error_outcome(
                    source,
                    negative.error_code,
                    negative.error_message,
                    negative.fetched_at_text,
                    from_cache=True,
                )
            flight = self._flights.get(key)
            leader = flight is None
            if leader:
                flight = _Flight()
                self._flights[key] = flight

        if not leader:
            assert flight is not None
            flight.event.wait()
            assert flight.outcome is not None
            return flight.outcome

        assert flight is not None
        failure: BaseException | None = None
        fetched: Fetched | None = None
        try:
            fetched = fetcher()
        except Exception as exc:  # noqa: BLE001 - classified below
            failure = exc
        if fetched is not None:
            if fetched.status not in ("ok", "empty", "stale"):
                failure = ValueError(f"provider 返回了非法状态: {fetched.status}")
                fetched = None
            elif fetched.status == "stale" and not fetched.stale_reason:
                failure = ValueError("provider 返回 stale 状态时必须给 stale_reason")
                fetched = None

        with self._lock:
            stale_entry = self._entries.get(key)
            if fetched is not None:
                outcome = self._store(key, fetched, now)
                self._failures.pop(key, None)
            else:
                error = as_provider_error(failure or ProviderError("upstream"))
                self._remember_failure(endpoint_id, key, now, error)
                if stale_entry is not None and stale_entry.data is not None:
                    outcome = self._stale_from_entry(stale_entry, now)
                else:
                    outcome = self._error_outcome(
                        source,
                        error.code,
                        error.message,
                        format_cst(now),
                    )
            self._flights.pop(key, None)
            flight.outcome = outcome
            flight.event.set()
        return outcome

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._failures.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _active_failure(
        self,
        endpoint_id: str,
        key: tuple[str, tuple[tuple[str, Any], ...]],
        now: datetime,
    ) -> _Failure | None:
        ttl = self._negative_ttl.get(endpoint_id)
        if ttl is None:
            return None
        failure = self._failures.get(key)
        if failure is None:
            return None
        if now - failure.failed_at > ttl:
            self._failures.pop(key, None)
            return None
        return failure

    def _remember_failure(
        self,
        endpoint_id: str,
        key: tuple[str, tuple[tuple[str, Any], ...]],
        now: datetime,
        error: ProviderError,
    ) -> None:
        if endpoint_id not in self._negative_ttl:
            return
        self._failures[key] = _Failure(
            failed_at=now,
            error_code=error.code,
            error_message=error.message,
            fetched_at_text=format_cst(now),
        )

    def _needs_refresh(self, entry: _Entry, now: datetime, ttl: timedelta) -> bool:
        if now - entry.fetched_at > ttl:
            return True
        return trading_day_mismatch(entry.as_of, now)

    def _from_entry(self, entry: _Entry, *, from_cache: bool) -> CacheOutcome:
        return CacheOutcome(
            status=entry.status,
            data=entry.data,
            as_of=entry.as_of,
            fetched_at=entry.fetched_at_text,
            source=entry.source,
            stale_reason=entry.stale_reason,
            from_cache=from_cache,
        )

    def _stale_from_entry(self, entry: _Entry, now: datetime) -> CacheOutcome:
        reason = (
            "trading_day_mismatch"
            if trading_day_mismatch(entry.as_of, now)
            else "ttl_exceeded"
        )
        return CacheOutcome(
            status="stale",
            data=entry.data,
            as_of=entry.as_of,
            fetched_at=entry.fetched_at_text,
            source=entry.source,
            stale_reason=reason,
            from_cache=True,
        )

    @staticmethod
    def _error_outcome(
        source: str,
        error_code: str,
        error_message: str,
        fetched_at: str,
        *,
        from_cache: bool = False,
    ) -> CacheOutcome:
        return CacheOutcome(
            status="error",
            data=None,
            as_of=None,
            fetched_at=fetched_at,
            source=source,
            error_code=error_code,
            error_message=error_message,
            from_cache=from_cache,
        )

    def _store(
        self,
        key: tuple[str, tuple[tuple[str, Any], ...]],
        fetched: Fetched,
        now: datetime,
    ) -> CacheOutcome:
        fetched_at_text = format_cst(now)
        entry = _Entry(
            data=fetched.data,
            as_of=fetched.as_of,
            fetched_at=now,
            fetched_at_text=fetched_at_text,
            source=fetched.source,
            status=fetched.status,
            stale_reason=fetched.stale_reason,
        )
        self._entries[key] = entry
        return self._from_entry(entry, from_cache=False)
