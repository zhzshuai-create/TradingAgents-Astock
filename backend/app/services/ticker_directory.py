"""Offline stock-name directory behind market search and job projections.

The directory never touches the network. Its default source is the daily
mootdx name table the legacy data layer already keeps on disk
(``name-code-map-YYYYMMDD.json``). Reading it must not create the cache
directory, block a job read or trigger a full-market fetch; when the table is
missing the directory reports an upstream error and ``name()`` returns None.

Sources are injected so tests and the dev entry (``--ticker-fixture``) can
supply an in-memory map instead of the disk cache.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))

ENVELOPE_SOURCE_DISK = "mootdx-cache"
ENVELOPE_SOURCE_STATIC = "static"

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
STALE_AFTER = timedelta(hours=24)
FAILURE_RETRY = timedelta(seconds=30)

_CODE_RE = re.compile(r"\d{6}")
_CACHE_DATE_RE = re.compile(r"name-code-map-(\d{8})\.json$")


class DirectoryUnavailable(RuntimeError):
    """The name table could not be loaded from its source."""


@dataclass(frozen=True)
class SearchResult:
    """One search answer, ready to be wrapped in a market envelope."""

    status: str
    items: tuple[dict[str, str], ...]
    truncated: bool
    source: str
    as_of: str | None
    fetched_at: str
    error_code: str | None = None
    stale_reason: str | None = None


class StaticNameSource:
    """In-memory code -> name map used by tests and ``--ticker-fixture``."""

    label = ENVELOPE_SOURCE_STATIC

    def __init__(self, names: Mapping[str, str]) -> None:
        self._names = dict(names)

    def load(self) -> tuple[Mapping[str, str], str | None]:
        return self._names, None


class DiskNameCache:
    """Reads the newest parseable daily name table under the data cache dir.

    The file layout matches ``tradingagents.dataflows.a_stock._common``; this
    reader is deliberately read-only (no ``makedirs``, no mootdx rebuild).
    """

    label = ENVELOPE_SOURCE_DISK

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root).expanduser() if root is not None else None

    def _cache_dir(self) -> Path:
        if self._root is not None:
            return self._root
        from tradingagents.dataflows.config import get_config

        configured = get_config().get("data_cache_dir") or os.path.expanduser(
            "~/.tradingagents/cache"
        )
        return Path(configured).expanduser()

    def load(self) -> tuple[Mapping[str, str], str | None]:
        try:
            root = self._cache_dir()
            files = sorted(
                root.glob("name-code-map-*.json"),
                key=lambda path: path.name,
                reverse=True,
            )
        except OSError as exc:
            raise DirectoryUnavailable("股票名称缓存不可读") from exc
        if not files:
            raise DirectoryUnavailable("股票名称缓存尚未生成")

        last_error: Exception | None = None
        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                names = payload["c2n"]
                if not isinstance(names, Mapping):
                    raise ValueError("c2n is not a mapping")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                continue
            return names, _cache_date(path)
        raise DirectoryUnavailable("股票名称缓存不可读") from last_error


def market_for(code: str) -> str:
    """Exchange prefix used by the frozen search item shape."""
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


class TickerDirectory:
    """Name index with search, lookup and a once-per-day snapshot cache."""

    def __init__(
        self,
        source: StaticNameSource | DiskNameCache | Mapping[str, str] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if source is None:
            source = DiskNameCache()
        elif isinstance(source, Mapping):
            source = StaticNameSource(source)
        self._source = source
        self._clock = clock or (lambda: datetime.now(CST))
        self._lock = threading.Lock()
        self._names: dict[str, str] | None = None
        self._as_of: str | None = None
        self._loaded_on: date | None = None
        self._failure: Exception | None = None
        self._failed_at: datetime | None = None

    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> SearchResult:
        now = self._clock()
        fetched_at = _iso(now)
        limit = _clamp_limit(limit)
        text = (query or "").strip().replace(" ", "").replace("　", "")
        if not text:
            return SearchResult(
                "empty", (), False, self._source.label, None, fetched_at
            )

        try:
            names, as_of = self._snapshot()
        except TimeoutError:
            return SearchResult(
                "error",
                (),
                False,
                self._source.label,
                None,
                fetched_at,
                "upstream_timeout",
            )
        except Exception:
            return SearchResult(
                "error",
                (),
                False,
                self._source.label,
                None,
                fetched_at,
                "upstream_error",
            )

        ordered = _matches(names, text)
        truncated = len(ordered) > limit
        items = tuple(
            {
                "ticker_code": code,
                "ticker_name": name,
                "market": market_for(code),
            }
            for code, name in ordered[:limit]
        )
        stale_reason = _stale_reason(as_of, now)
        return SearchResult(
            "stale" if stale_reason else "ok",
            items,
            truncated,
            self._source.label,
            as_of,
            fetched_at,
            None,
            stale_reason,
        )

    def name(self, code: str) -> str | None:
        """Resolve one code; a broken source must never break a job read."""
        try:
            names, _ = self._snapshot()
        except Exception:
            return None
        return names.get(str(code).strip())

    def _snapshot(self) -> tuple[dict[str, str], str]:
        now = self._clock()
        today = now.date()
        with self._lock:
            if self._names is not None and self._loaded_on == today:
                return self._names, self._as_of or _iso(now)
            if (
                self._failure is not None
                and self._failed_at is not None
                and now - self._failed_at < FAILURE_RETRY
            ):
                raise self._failure
            try:
                raw, as_of = self._source.load()
            except Exception as exc:
                self._names = None
                self._as_of = None
                self._loaded_on = None
                self._failure = exc
                self._failed_at = now
                raise
            names = _clean(raw)
            recorded = as_of or _iso(now)
            self._names = names
            self._as_of = recorded
            self._loaded_on = today
            self._failure = None
            self._failed_at = None
            return names, recorded


def _clean(raw: Mapping[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for code, name in raw.items():
        code_text = str(code).strip()
        name_text = str(name).strip()
        if _CODE_RE.fullmatch(code_text) and name_text:
            names[code_text] = name_text
    return names


def _matches(names: Mapping[str, str], text: str) -> list[tuple[str, str]]:
    code_query = _code_query(text)
    ranked: list[tuple[int, str, str]] = []
    for code, name in names.items():
        if code_query is not None and code == code_query:
            ranked.append((0, code, name))
        elif name.startswith(text):
            ranked.append((1, code, name))
        elif text in name:
            ranked.append((2, code, name))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [(code, name) for _, code, name in ranked]


def _code_query(text: str) -> str | None:
    value = text.upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    for prefix in ("SH", "SZ", "BJ"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return value if _CODE_RE.fullmatch(value) else None


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _cache_date(path: Path) -> str | None:
    match = _CACHE_DATE_RE.search(path.name)
    if match is not None:
        stamp = match.group(1)
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, CST).date().isoformat()
    except OSError:
        return None


def _stale_reason(as_of: str, now: datetime) -> str | None:
    try:
        moment = datetime.fromisoformat(as_of)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    return "ttl_exceeded" if now - moment > STALE_AFTER else None


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CST)
    return moment.isoformat(timespec="seconds")
