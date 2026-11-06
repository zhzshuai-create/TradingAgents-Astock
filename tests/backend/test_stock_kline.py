"""P4-03 acceptance: K-line and intraday (STK-04, STK-05, related TTLs)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.market_providers import Fetched, ProviderError  # noqa: E402
from backend.app.services.market_clock import format_cst  # noqa: E402
from tests.backend.stock_helpers import (  # noqa: E402
    INTRADAY_DATA,
    KLINE_DATA,
    make_service,
    set_ok,
    set_record,
    validator,
)

VALIDATOR = validator()


@pytest.fixture()
def env():
    return make_service()


# STK-04 ---------------------------------------------------------------


def test_kline_defaults_and_forwarded_arguments(env):
    seen = set_record(env, "kline", KLINE_DATA, "mootdx")

    envelope = env.service.kline("600519")
    VALIDATOR.validate(envelope)

    assert seen == [("600519", "day", 120)]
    assert envelope["status"] == "ok"
    assert envelope["source"] == "mootdx"
    assert envelope["data"] == KLINE_DATA
    assert envelope["data"]["adjust"] == "none"
    dates = [bar["date"] for bar in envelope["data"]["bars"]]
    assert dates == sorted(dates)
    assert any(bar["amount"] is None for bar in envelope["data"]["bars"])


@pytest.mark.parametrize("period", ["day", "week", "month"])
def test_kline_forwards_each_period_and_limit(env, period):
    seen = set_record(env, "kline", KLINE_DATA, "mootdx")

    envelope = env.service.kline("600519", period, 250)

    assert seen == [("600519", period, 250)]
    assert envelope["status"] == "ok"


def test_kline_cache_key_includes_period_and_limit(env):
    seen = set_record(env, "kline", KLINE_DATA, "mootdx")

    env.service.kline("600519", "day", 120)
    env.service.kline("600519", "day", 120)
    env.service.kline("600519", "day", 250)
    env.service.kline("600519", "week", 120)

    assert seen == [
        ("600519", "day", 120),
        ("600519", "day", 250),
        ("600519", "week", 120),
    ]


def test_kline_falls_back_to_mixed_source(env):
    env.providers.set(
        "kline",
        Fetched(data=KLINE_DATA, as_of=format_cst(env.clock()), source="mixed"),
    )

    envelope = env.service.kline("600519")

    assert envelope["status"] == "ok"
    assert envelope["source"] == "mixed"


# STK-05 ---------------------------------------------------------------


def test_intraday_default_uses_latest_trading_day(env):
    seen = set_record(env, "intraday", INTRADAY_DATA, "mootdx")

    envelope = env.service.intraday("600519")
    VALIDATOR.validate(envelope)

    assert seen == [("600519", None)]
    assert envelope["status"] == "ok"
    assert envelope["data"] == INTRADAY_DATA
    assert envelope["data"]["session_gaps"] == [["11:30", "13:00"]]
    assert envelope["data"]["points"][0]["avg_price"] is not None


def test_intraday_forwards_an_explicit_history_date(env):
    seen = set_record(env, "intraday", INTRADAY_DATA, "mootdx")

    env.service.intraday("600519", "2026-10-29")

    assert seen == [("600519", "2026-10-29")]


def test_intraday_non_trading_date_uses_the_provider_fallback(env):
    fallback = {**INTRADAY_DATA, "date": "2026-11-06"}
    env.providers.set(
        "intraday",
        Fetched(data=fallback, as_of=format_cst(env.clock()), source="mootdx"),
    )

    envelope = env.service.intraday("600519", "2026-11-07")

    assert envelope["status"] == "ok"
    assert envelope["data"]["date"] == "2026-11-06"


def test_intraday_beyond_retention_is_empty_not_error(env):
    env.providers.set(
        "intraday",
        Fetched(status="empty", data=None, as_of=None, source="mixed"),
    )

    envelope = env.service.intraday("600519", "2024-01-02")
    VALIDATOR.validate(envelope)

    assert envelope["status"] == "empty"
    assert envelope["data"] is None
    assert envelope["error_code"] is None
    assert envelope["as_of"] is None


def test_intraday_today_threshold_is_30_seconds(env):
    set_ok(env, "intraday", INTRADAY_DATA, "mootdx")
    assert env.service.intraday("600519")["status"] == "ok"

    env.clock.advance(seconds=31)
    env.providers.set("intraday", error=ProviderError("timeout"))

    envelope = env.service.intraday("600519")

    assert envelope["status"] == "stale"
    assert envelope["stale_reason"] == "ttl_exceeded"
    assert envelope["data"] == INTRADAY_DATA


def test_intraday_history_threshold_is_one_hour(env):
    set_ok(env, "intraday", INTRADAY_DATA, "mootdx")
    assert env.service.intraday("600519", "2026-10-29")["status"] == "ok"
    assert env.providers.calls["intraday"] == 1

    env.clock.advance(seconds=61)
    env.providers.set("intraday", error=ProviderError("timeout"))
    still_fresh = env.service.intraday("600519", "2026-10-29")
    assert still_fresh["status"] == "ok"
    assert env.providers.calls["intraday"] == 1

    env.clock.advance(minutes=59, seconds=1)
    stale = env.service.intraday("600519", "2026-10-29")
    assert stale["status"] == "stale"
    assert stale["stale_reason"] == "ttl_exceeded"
    assert env.providers.calls["intraday"] == 2
