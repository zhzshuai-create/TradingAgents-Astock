"""P4-01 acceptance: TTL cache, single-flight and zero side effects.

ENV-03, ENV-04 and ENV-06 live here, plus the two micro-measurements the
ticket asks to record (cache hit cost and 20-way single-flight wait).
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.market_cache import MarketCache, normalize_params  # noqa: E402
from backend.app.services.market_clock import CST, format_cst  # noqa: E402
from backend.app.services.market_envelope import (  # noqa: E402
    BlockResult,
    build_blocks_envelope,
    build_envelope,
)
from backend.app.services.market_providers import (  # noqa: E402
    FakeMarketProviders,
    Fetched,
    ProviderError,
)

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=CST)
AS_OF = format_cst(NOW)


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


def fetched(value: int = 1) -> Fetched:
    return Fetched(data={"value": value}, as_of=AS_OF, source="static")


# -- ENV-03 ------------------------------------------------------------------


def test_env03_hit_does_not_call_provider():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    def fetch() -> Fetched:
        calls["n"] += 1
        return fetched()

    first = cache.get_or_fetch("market:industries", {"top": 20}, fetch, source="static")
    second = cache.get_or_fetch("market:industries", {"top": 20}, fetch, source="static")

    assert calls["n"] == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.data == {"value": 1}


def test_env03_expired_entry_refetches():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    def fetch() -> Fetched:
        calls["n"] += 1
        return fetched(calls["n"])

    cache.get_or_fetch("market:industries", {"top": 20}, fetch, source="static")
    clock.advance(minutes=6)
    second = cache.get_or_fetch("market:industries", {"top": 20}, fetch, source="static")

    assert calls["n"] == 2
    assert second.data == {"value": 2}
    assert second.from_cache is False


def test_env03_failure_with_old_data_returns_stale():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    def good() -> Fetched:
        calls["n"] += 1
        return fetched()

    def broken() -> Fetched:
        raise ProviderError("timeout")

    cache.get_or_fetch("market:industries", {"top": 20}, good, source="static")
    clock.advance(minutes=6)
    outcome = cache.get_or_fetch(
        "market:industries", {"top": 20}, broken, source="static"
    )

    assert outcome.status == "stale"
    assert outcome.stale_reason == "ttl_exceeded"
    assert outcome.data == {"value": 1}
    assert outcome.as_of == AS_OF


def test_env03_failure_without_old_data_returns_error():
    cache = MarketCache(clock=_Clock(NOW))

    def broken() -> Fetched:
        raise ProviderError("rate_limited")

    outcome = cache.get_or_fetch("market:newsflash", {"limit": 30}, broken, source="cls")

    assert outcome.status == "error"
    assert outcome.error_code == "upstream_rate_limited"
    assert outcome.data is None
    assert outcome.source == "cls"


def test_env03_trading_day_mismatch_forces_refresh_and_stale_reason():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    previous = "2026-11-05T10:00:00+08:00"

    cache.get_or_fetch(
        "market:overview:indices",
        {},
        lambda: Fetched(data={"value": 1}, as_of=previous, source="tencent"),
        source="tencent",
    )
    outcome = cache.get_or_fetch(
        "market:overview:indices",
        {},
        lambda: (_ for _ in ()).throw(ProviderError("upstream")),
        source="tencent",
    )

    assert outcome.status == "stale"
    assert outcome.stale_reason == "trading_day_mismatch"


def test_env03_fallback_success_is_stale_with_upstream_fallback():
    cache = MarketCache(clock=_Clock(NOW))
    outcome = cache.get_or_fetch(
        "market:newsflash",
        {"limit": 30},
        lambda: Fetched(
            data={"items": []},
            as_of=AS_OF,
            source="mixed",
            status="stale",
            stale_reason="upstream_fallback",
        ),
        source="cls",
    )

    assert outcome.status == "stale"
    assert outcome.stale_reason == "upstream_fallback"
    cached = cache.get_or_fetch(
        "market:newsflash",
        {"limit": 30},
        lambda: (_ for _ in ()).throw(AssertionError("must not refetch")),
        source="cls",
    )
    assert cached.from_cache is True


def test_env03_empty_is_cached_not_errored():
    cache = MarketCache(clock=_Clock(NOW))
    calls = {"n": 0}

    def empty() -> Fetched:
        calls["n"] += 1
        return Fetched(status="empty", data=None, as_of=None, source="ths")

    first = cache.get_or_fetch("market:strong-stocks", {}, empty, source="ths")
    second = cache.get_or_fetch("market:strong-stocks", {}, empty, source="ths")

    assert first.status == second.status == "empty"
    assert calls["n"] == 1


def test_normalize_params_is_order_insensitive():
    assert normalize_params({"b": 2, "a": [3, 4]}) == normalize_params({"a": (3, 4), "b": "2"})


# -- ENV-04 ------------------------------------------------------------------


def test_env04_twenty_concurrent_calls_hit_provider_once():
    cache = MarketCache(clock=_Clock(NOW))
    calls = {"n": 0}
    barrier = threading.Barrier(20)

    def fetch() -> Fetched:
        calls["n"] += 1
        time.sleep(0.05)
        return fetched()

    def worker():
        barrier.wait()
        return cache.get_or_fetch("market:industries", {"top": 20}, fetch, source="static")

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = [future.result() for future in [pool.submit(worker) for _ in range(20)]]

    assert calls["n"] == 1
    assert all(outcome.status == "ok" for outcome in outcomes)


def test_env04_micro_measurements(capsys):
    cache = MarketCache(clock=_Clock(NOW))
    cache.get_or_fetch("market:industries", {}, lambda: fetched(), source="static")

    started = time.perf_counter()
    for _ in range(100_000):
        cache.get_or_fetch("market:industries", {}, None, source="static")
    elapsed = time.perf_counter() - started
    print(f"cache hit: {elapsed / 100_000 * 1e9:.0f} ns/op")

    barrier = threading.Barrier(20)
    calls = {"n": 0}

    def fetch() -> Fetched:
        calls["n"] += 1
        time.sleep(0.02)
        return fetched()

    def worker():
        barrier.wait()
        return cache.get_or_fetch("market:newsflash", {}, fetch, source="static")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=20) as pool:
        [future.result() for future in [pool.submit(worker) for _ in range(20)]]
    wait = time.perf_counter() - started
    print(f"20-way single flight: {wait:.3f}s, provider calls={calls['n']}")

    assert calls["n"] == 1


# -- ENV-06 ------------------------------------------------------------------


def _tree(root: Path) -> dict[str, tuple[int, int, bool]]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        stat = path.stat()
        snapshot[str(path.relative_to(root))] = (
            stat.st_mtime_ns,
            stat.st_size,
            path.is_dir(),
        )
    return snapshot


def test_env06_read_paths_do_not_touch_home_or_temp(tmp_path, monkeypatch):
    import sqlite3

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("TA_LEGACY_PROJECTION", "0")
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("market read path must not open a database")
        ),
    )
    (home / "marker.txt").write_text("keep", encoding="utf-8")
    before = _tree(home)

    build_envelope(
        status="ok",
        source="static",
        as_of=AS_OF,
        fetched_at=AS_OF,
        data={"items": []},
    )
    build_envelope(
        status="error",
        source="static",
        as_of=None,
        fetched_at=AS_OF,
        data=None,
        error_code="upstream_timeout",
    )
    build_blocks_envelope(
        {
            "quote": BlockResult("ok", "tencent", AS_OF, AS_OF, data={"x": 1}),
            "valuation": BlockResult(
                "error",
                "ths",
                None,
                AS_OF,
                error_code="upstream_error",
                error_message="失败",
            ),
        }
    )

    cache = MarketCache(clock=_Clock(NOW))
    cache.get_or_fetch("stock:news", {"ticker": "300750"}, lambda: fetched(), source="eastmoney")
    cache.get_or_fetch(
        "stock:news",
        {"ticker": "300750"},
        lambda: (_ for _ in ()).throw(ProviderError("parse_error")),
        source="eastmoney",
    )

    fake = FakeMarketProviders()
    fake.set("quote", Fetched(data={"price": 1}, as_of=AS_OF, source="tencent"))
    fake.quote("300750")
    fake.set("valuation", error=ProviderError("timeout"))
    with pytest.raises(ProviderError):
        fake.valuation("300750")

    assert _tree(home) == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["home"]


def test_env06_provider_source_has_no_write_or_legacy_access():
    source = (ROOT / "backend" / "app" / "services" / "market_providers.py").read_text(
        encoding="utf-8"
    )
    for token in ("import web", "from web", "web.", "makedirs", ".to_csv(", "open("):
        assert token not in source, token


# -- R1 negative cache -------------------------------------------------------

R1_ENDPOINT = "stock:snapshot:sector_blocks"
R1_PARAMS = {"ticker": "600000"}


def _broken(calls: dict[str, int], *, kind: str = "upstream"):
    def fetch() -> Fetched:
        calls["n"] += 1
        raise ProviderError(kind)

    return fetch


def test_r1_t1_repeated_failure_calls_provider_once():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    outcomes = [
        cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
        for _ in range(5)
    ]

    assert calls["n"] == 1
    assert [outcome.status for outcome in outcomes] == ["error"] * 5
    assert {outcome.error_code for outcome in outcomes} == {"upstream_error"}
    assert {outcome.fetched_at for outcome in outcomes} == {format_cst(NOW)}
    assert outcomes[0].from_cache is False
    assert all(outcome.from_cache for outcome in outcomes[1:])


def test_r1_t2_negative_cache_expires_and_retries():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
    clock.advance(seconds=60)
    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
    assert calls["n"] == 1, "60 秒内负缓存必须仍然生效"

    clock.advance(seconds=1)
    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
    clock.advance(seconds=30)
    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")

    assert calls["n"] == 2, "到期后应重试一次，并重新进入 60 秒窗口"


def test_r1_t3_negative_cache_never_masks_old_data():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}
    old = {"industry": [{"name": "银行"}], "concept": [], "region": []}

    cache.get_or_fetch(
        R1_ENDPOINT,
        R1_PARAMS,
        lambda: Fetched(data=old, as_of=AS_OF, source="baidu"),
        source="baidu",
    )
    clock.advance(hours=25)
    first = cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
    later = [
        cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
        for _ in range(3)
    ]

    assert calls["n"] == 1
    assert first.status == "stale"
    assert first.data == old
    assert [outcome.status for outcome in later] == ["stale"] * 3
    assert all(outcome.data == old for outcome in later)
    assert {outcome.fetched_at for outcome in later} == {AS_OF}


def test_r1_t4_success_after_expiry_clears_negative_cache():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
    clock.advance(seconds=61)
    recovered = cache.get_or_fetch(
        R1_ENDPOINT,
        R1_PARAMS,
        lambda: Fetched(data={"industry": []}, as_of=format_cst(clock()), source="baidu"),
        source="baidu",
    )
    again = cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")

    assert recovered.status == "ok"
    assert again.status == "ok"
    assert again.from_cache is True
    assert calls["n"] == 1
    assert cache._failures == {}


def test_r1_t5_unregistered_endpoint_retries_every_time():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    for _ in range(3):
        outcome = cache.get_or_fetch(
            "stock:snapshot:quote", R1_PARAMS, _broken(calls), source="tencent"
        )
        assert outcome.status == "error"

    assert calls["n"] == 3
    assert cache._failures == {}


def test_r1_t6_clear_drops_negative_cache_too():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")
    cache.clear()
    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")

    assert calls["n"] == 2


def test_r1_t7_concurrent_negative_hits_do_not_wait():
    clock = _Clock(NOW)
    cache = MarketCache(clock=clock)
    calls = {"n": 0}

    cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, _broken(calls), source="baidu")

    def slow_fetch() -> Fetched:
        calls["n"] += 1
        time.sleep(5)
        return fetched()

    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        return cache.get_or_fetch(R1_ENDPOINT, R1_PARAMS, slow_fetch, source="baidu")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result() for future in [pool.submit(worker) for _ in range(2)]]
    elapsed = time.perf_counter() - started

    assert calls["n"] == 1
    assert [outcome.status for outcome in outcomes] == ["error", "error"]
    assert all(outcome.from_cache for outcome in outcomes)
    assert elapsed < 1.0
