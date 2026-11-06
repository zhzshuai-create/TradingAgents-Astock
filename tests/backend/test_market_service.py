"""P4-02 service-level orchestration: defaults, cache keys, board checks.

These bypass HTTP on purpose: they pin the provider arguments the router must
forward and the semantic failures the router maps to ``invalid_request``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.market_cache import MarketCache  # noqa: E402
from backend.app.services.market_clock import CST, format_cst  # noqa: E402
from backend.app.services.market_providers import (  # noqa: E402
    FakeMarketProviders,
    Fetched,
    ProviderError,
)
from backend.app.services.market_service import (  # noqa: E402
    MarketRequestError,
    MarketService,
)

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=CST)


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture()
def env():
    clock = Clock(NOW)
    providers = FakeMarketProviders()
    cache = MarketCache(clock=clock)
    service = MarketService(providers, cache, clock=clock)
    return SimpleNamespace(
        service=service, providers=providers, cache=cache, clock=clock
    )


def _record(env, method: str, data, source: str) -> list[tuple]:
    seen: list[tuple] = []

    def fetch(*args):
        seen.append(args)
        return Fetched(data=data, as_of=format_cst(env.clock()), source=source)

    env.providers.set(method, fetch)
    return seen

def _fetched(data, source: str = "eastmoney") -> Fetched:
    return Fetched(data=data, as_of=format_cst(NOW), source=source)


def test_default_query_arguments_are_forwarded(env):
    seen = {}
    cases = (
        ("industries", {"top": [{"code": "BK0475"}], "bottom": [], "total": 1}, "eastmoney"),
        ("constituents", {"items": []}, "eastmoney"),
        ("strong_stocks", {"items": []}, "ths"),
        ("newsflash", {"items": []}, "cls"),
    )
    for method, data, source in cases:
        seen[method] = _record(env, method, data, source)

    env.service.industries()
    env.service.constituents("BK0475")
    env.service.strong_stocks()
    env.service.newsflash()

    assert seen["industries"] == [(20,), (50,)]
    assert seen["constituents"] == [("BK0475", 10)]
    assert seen["strong_stocks"] == [("2026-11-05",)]
    assert seen["newsflash"] == [(30,)]


def test_unknown_board_raises_a_request_error_with_details(env):
    env.providers.set(
        "industries",
        _fetched({"top": [{"code": "BK0475"}], "bottom": [], "total": 1}),
    )

    with pytest.raises(MarketRequestError) as info:
        env.service.constituents("BK9999")

    assert info.value.details == {
        "field": "boardCode",
        "allowed_values": ["BK0000-BK9999"],
    }
    assert env.providers.calls["constituents"] == 0


def test_board_check_is_skipped_when_the_industry_snapshot_fails(env):
    env.providers.set("industries", error=ProviderError("timeout"))
    env.providers.set("constituents", _fetched({"items": []}))

    envelope = env.service.constituents("BK9999", 5)

    assert envelope["status"] == "ok"
    assert envelope["data"] == {"items": []}
    assert env.providers.calls["constituents"] == 1


def test_non_trading_day_returns_empty_without_calling_the_provider(env):
    envelope = env.service.strong_stocks("2026-11-07")

    assert envelope["status"] == "empty"
    assert envelope["data"] is None
    assert envelope["as_of"] is None
    assert envelope["source"] == "ths"
    assert env.providers.calls["strong_stocks"] == 0


def test_text_endpoints_mark_data_untrusted(env):
    env.providers.set(
        "newsflash", _fetched({"items": [{"title": "t"}]}, "cls")
    )
    env.providers.set(
        "strong_stocks", _fetched({"items": [{"ticker_code": "600519"}]}, "ths")
    )

    news = env.service.newsflash()
    strong = env.service.strong_stocks("2026-11-05")

    assert news["data"] == {"items": [{"title": "t"}], "untrusted": True}
    assert strong["data"] == {
        "items": [{"ticker_code": "600519"}],
        "untrusted": True,
    }


def test_cache_keys_include_the_limit(env):
    records = _record(env, "newsflash", {"items": []}, "cls")

    env.service.newsflash(10)
    env.service.newsflash(20)
    env.service.newsflash(10)

    assert records == [(10,), (20,)]
    assert env.providers.calls["newsflash"] == 2


def test_error_envelope_carries_the_mapped_code_and_source(env):
    env.providers.set("newsflash", error=ProviderError("rate_limited"))

    envelope = env.service.newsflash()

    assert envelope["status"] == "error"
    assert envelope["error_code"] == "upstream_rate_limited"
    assert envelope["error_message"]
    assert envelope["source"] == "cls"
    assert envelope["data"] is None


def test_stale_fallback_keeps_old_data_after_ttl(env):
    env.providers.set("newsflash", _fetched({"items": [{"title": "old"}]}, "cls"))
    fresh = env.service.newsflash()
    assert fresh["status"] == "ok"

    env.clock.value = NOW + timedelta(minutes=3)
    env.providers.set("newsflash", error=ProviderError("timeout"))

    stale = env.service.newsflash()

    assert stale["status"] == "stale"
    assert stale["stale_reason"] == "ttl_exceeded"
    assert stale["data"] == {"items": [{"title": "old"}], "untrusted": True}
    assert stale["as_of"] == fresh["as_of"]
