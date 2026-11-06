"""P4-02 acceptance: five market GET endpoints (MKT-01 to MKT-09).

Everything runs on ``FakeMarketProviders`` and a frozen test clock: no socket,
no API key, no real name cache. Every HTTP 200 body is validated against the
frozen ``market-data-envelope-v1`` JSON Schema.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import create_app  # noqa: E402
from backend.app.services.market_cache import MarketCache  # noqa: E402
from backend.app.services.market_clock import CST, format_cst  # noqa: E402
from backend.app.services.market_providers import (  # noqa: E402
    FakeMarketProviders,
    Fetched,
    ProviderError,
)
from backend.app.services.market_service import MarketService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.services.ticker_directory import TickerDirectory  # noqa: E402

NOW = datetime(2026, 11, 5, 10, 0, tzinfo=CST)
CONTRACT = ROOT / "docs" / "upgrade" / "contracts" / "market-data-envelope-v1.json"

INDICES = [
    {
        "code": "000001",
        "name": "上证指数",
        "price": 3412.34,
        "change_pct": 0.52,
        "change_amt": 17.6,
    },
    {
        "code": "399001",
        "name": "深证成指",
        "price": 10880.12,
        "change_pct": -0.31,
        "change_amt": -33.8,
    },
    {
        "code": "399006",
        "name": "创业板指",
        "price": 2210.5,
        "change_pct": 1.2,
        "change_amt": 26.2,
    },
]

NORTHBOUND = {
    "points": [
        {"time": "09:31", "hgt_yi": 1.2, "sgt_yi": 0.4},
        {"time": "09:32", "hgt_yi": 1.5, "sgt_yi": 0.6},
    ],
    "latest": {"hgt_yi": 1.5, "sgt_yi": 0.6},
}

INDUSTRY_TOP = [
    {
        "rank": 1,
        "name": "银行",
        "code": "BK0475",
        "change_pct": 2.31,
        "up_count": 40,
        "down_count": 2,
        "leader": "浦发银行",
        "leader_change": 6.1,
    },
    {
        "rank": 2,
        "name": "保险",
        "code": "BK0474",
        "change_pct": 1.8,
        "up_count": 6,
        "down_count": 0,
        "leader": "中国平安",
        "leader_change": 3.2,
    },
]
INDUSTRY_BOTTOM = [
    {
        "rank": 3,
        "name": "煤炭",
        "code": "BK0476",
        "change_pct": -1.42,
        "up_count": 1,
        "down_count": 34,
        "leader": "中国神华",
        "leader_change": 0.4,
    }
]
INDUSTRIES = {"top": INDUSTRY_TOP, "bottom": INDUSTRY_BOTTOM, "total": 3}

CONSTITUENTS = [
    {"code": "600000", "name": "浦发银行", "price": 10.52, "change_pct": 1.25},
    {"code": "600015", "name": "华夏银行", "price": None, "change_pct": None},
]

STRONG_ITEMS = [
    {
        "ticker_code": "600519",
        "name": "贵州茅台",
        "reason": "白酒板块领涨",
        "market": "sh",
        "change_pct": 9.98,
        "change_amt": 156.2,
        "close": 1720.0,
        "turnover_pct": 3.4,
    }
]

NEWSFLASH_ITEMS = [
    {
        "title": "快讯标题",
        "content": "快讯内容",
        "published_at": "2026-11-05T10:05:00+08:00",
    }
]


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


class _StubService:
    """create_app only needs an engine and a clock to build the SSE stream."""

    engine = None

    def now(self) -> datetime:
        return NOW


class _StubExports:
    def sweep_stale(self) -> int:
        return 0

    def shutdown(self) -> None:
        return None


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _make_env(tmp_path: Path, validator: Draft202012Validator) -> SimpleNamespace:
    clock = Clock(NOW)
    providers = FakeMarketProviders()
    cache = MarketCache(clock=clock)
    service = MarketService(providers, cache, clock=clock)
    app = create_app(
        service=_StubService(),
        report_store=ReportStore(tmp_path / "reports"),
        ticker_directory=TickerDirectory({}, clock=clock),
        export_service=_StubExports(),
        market_providers=providers,
        market_cache=cache,
    )
    app.state.market_service = service
    return SimpleNamespace(
        app=app,
        providers=providers,
        cache=cache,
        clock=clock,
        validator=validator,
        tmp=tmp_path,
    )


@pytest.fixture()
def env(tmp_path, validator):
    env = _make_env(tmp_path, validator)
    with TestClient(env.app) as client:
        env.client = client
        yield env


def _ok(env, method: str, data, source: str):
    """Provider answer whose ``as_of`` tracks the frozen clock."""
    provider = env.providers

    def fetch(*_args):
        return Fetched(data=data, as_of=format_cst(env.clock()), source=source)

    provider.set(method, fetch)


def _record(env, method: str, data, source: str) -> list[tuple]:
    seen: list[tuple] = []
    provider = env.providers

    def fetch(*args):
        seen.append(args)
        return Fetched(data=data, as_of=format_cst(env.clock()), source=source)

    provider.set(method, fetch)
    return seen


def _seed_market(env) -> None:
    _ok(env, "indices", INDICES, "tencent")
    _ok(env, "northbound", NORTHBOUND, "hexin")
    _ok(env, "industries", INDUSTRIES, "eastmoney")


def _get(env, url: str, **params) -> dict:
    response = env.client.get(url, params=params or None)
    assert response.status_code == 200, response.text
    payload = response.json()
    env.validator.validate(payload)
    return payload


def _error(response) -> dict:
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    return error


# MKT-01 ---------------------------------------------------------------


def test_overview_returns_three_indices_and_northbound(env):
    _seed_market(env)

    payload = _get(env, "/api/v1/market/overview")

    assert payload["status"] == "ok"
    assert payload["source"] == "mixed"
    assert payload["partial"] is False
    assert payload["failed_blocks"] == []
    assert [row["code"] for row in payload["data"]["indices"]] == [
        "000001",
        "399001",
        "399006",
    ]
    assert payload["data"]["northbound"] == NORTHBOUND
    assert payload["data"]["market_session"] == "trading"
    assert payload["blocks"]["indices"]["source"] == "tencent"
    assert payload["blocks"]["northbound"]["source"] == "hexin"


@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2026, 11, 5, 9, 29, tzinfo=CST), "pre_open"),
        (datetime(2026, 11, 5, 9, 30, tzinfo=CST), "trading"),
        (datetime(2026, 11, 5, 11, 30, tzinfo=CST), "lunch_break"),
        (datetime(2026, 11, 5, 13, 0, tzinfo=CST), "trading"),
        (datetime(2026, 11, 5, 15, 0, tzinfo=CST), "closed"),
        (datetime(2026, 11, 5, 15, 1, tzinfo=CST), "closed"),
        (datetime(2026, 11, 7, 10, 0, tzinfo=CST), "closed"),
    ],
)
def test_overview_market_session_boundaries(env, moment, expected):
    _seed_market(env)
    env.clock.set(moment)

    payload = _get(env, "/api/v1/market/overview")

    assert payload["data"]["market_session"] == expected


# MKT-02 ---------------------------------------------------------------


def test_overview_keeps_indices_when_northbound_fails(env):
    _ok(env, "indices", INDICES, "tencent")
    env.providers.set("northbound", error=ProviderError("timeout"))

    payload = _get(env, "/api/v1/market/overview")

    assert payload["status"] == "ok"
    assert payload["partial"] is True
    assert payload["failed_blocks"] == ["northbound"]
    assert payload["data"]["indices"] == INDICES
    assert payload["data"]["northbound"] is None
    block = payload["blocks"]["northbound"]
    assert block["status"] == "error"
    assert block["error_code"] == "upstream_timeout"
    assert block["error_message"]


def test_overview_with_both_blocks_failing_is_an_error_envelope(env):
    env.providers.set("indices", error=ProviderError("timeout"))
    env.providers.set("northbound", error=ProviderError("timeout"))

    payload = _get(env, "/api/v1/market/overview")

    assert payload["status"] == "error"
    assert payload["data"] is None
    assert payload["as_of"] is None
    assert payload["error_code"] == "upstream_timeout"
    assert set(payload["blocks"]) == {"indices", "northbound"}
    assert payload["partial"] is False


# MKT-03 ---------------------------------------------------------------


def test_industries_returns_top_bottom_total_and_leader_fields(env):
    _seed_market(env)

    payload = _get(env, "/api/v1/market/industries", top="2")

    assert payload["status"] == "ok"
    assert payload["source"] == "eastmoney"
    assert payload["data"] == INDUSTRIES
    assert set(payload["data"]["top"][0]) == {
        "rank",
        "name",
        "code",
        "change_pct",
        "up_count",
        "down_count",
        "leader",
        "leader_change",
    }


@pytest.mark.parametrize("top", ["1", "50"])
def test_industries_top_accepts_range_boundaries(env, top):
    _seed_market(env)

    payload = _get(env, "/api/v1/market/industries", top=top)

    assert payload["status"] == "ok"


# MKT-04 ---------------------------------------------------------------


def test_constituents_passes_board_and_limit_and_keeps_null_prices(env):
    _seed_market(env)
    seen = _record(env, "constituents", {"items": CONSTITUENTS}, "eastmoney")

    payload = _get(env, "/api/v1/market/industries/BK0475/stocks", limit="10")

    assert seen == [("BK0475", 10)]
    assert payload["status"] == "ok"
    assert payload["data"]["items"] == CONSTITUENTS
    assert payload["data"]["items"][1]["price"] is None
    assert payload["data"]["items"][1]["change_pct"] is None


def test_constituents_rejects_a_board_missing_from_the_snapshot(env):
    _seed_market(env)

    error = _error(env.client.get("/api/v1/market/industries/BK9999/stocks"))

    assert error["details"] == {
        "field": "boardCode",
        "allowed_values": ["BK0000-BK9999"],
    }
    assert env.providers.calls["constituents"] == 0


@pytest.mark.parametrize("limit", ["1", "100"])
def test_constituents_limit_accepts_range_boundaries(env, limit):
    _seed_market(env)
    _ok(env, "constituents", {"items": CONSTITUENTS}, "eastmoney")

    payload = _get(env, f"/api/v1/market/industries/BK0475/stocks", limit=limit)

    assert payload["status"] == "ok"


# MKT-05 ---------------------------------------------------------------


def test_strong_stocks_defaults_to_the_latest_trading_day(env):
    seen = _record(env, "strong_stocks", {"items": STRONG_ITEMS}, "ths")

    payload = _get(env, "/api/v1/market/strong-stocks")

    assert seen == [("2026-11-05",)]
    assert payload["status"] == "ok"
    assert payload["source"] == "ths"
    assert payload["data"] == {"items": STRONG_ITEMS, "untrusted": True}


def test_strong_stocks_uses_an_explicit_date(env):
    seen = _record(env, "strong_stocks", {"items": STRONG_ITEMS}, "ths")

    _get(env, "/api/v1/market/strong-stocks", date="2026-10-29")

    assert seen == [("2026-10-29",)]


def test_strong_stocks_on_a_non_trading_day_is_empty_not_an_error(env):
    payload = _get(env, "/api/v1/market/strong-stocks", date="2026-11-07")

    assert payload["status"] == "empty"
    assert payload["data"] is None
    assert payload["as_of"] is None
    assert payload["error_code"] is None
    assert env.providers.calls["strong_stocks"] == 0


# MKT-06 ---------------------------------------------------------------


def test_newsflash_marks_text_untrusted_and_passes_the_limit(env):
    seen = _record(env, "newsflash", {"items": NEWSFLASH_ITEMS}, "cls")

    payload = _get(env, "/api/v1/market/newsflash", limit="30")

    assert seen == [(30,)]
    assert payload["status"] == "ok"
    assert payload["source"] == "cls"
    assert payload["data"] == {"items": NEWSFLASH_ITEMS, "untrusted": True}


@pytest.mark.parametrize("limit", ["1", "100"])
def test_newsflash_limit_accepts_range_boundaries(env, limit):
    _ok(env, "newsflash", {"items": NEWSFLASH_ITEMS}, "cls")

    payload = _get(env, "/api/v1/market/newsflash", limit=limit)

    assert payload["status"] == "ok"


# MKT-07 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "url, params, field, allowed",
    [
        ("/api/v1/market/industries", {"top": "0"}, "top", ["1-50"]),
        ("/api/v1/market/industries", {"top": "51"}, "top", ["1-50"]),
        ("/api/v1/market/industries", {"top": "abc"}, "top", ["1-50"]),
        ("/api/v1/market/newsflash", {"limit": "0"}, "limit", ["1-100"]),
        ("/api/v1/market/newsflash", {"limit": "101"}, "limit", ["1-100"]),
        ("/api/v1/market/newsflash", {"limit": "abc"}, "limit", ["1-100"]),
        (
            "/api/v1/market/industries/BK0475/stocks",
            {"limit": "0"},
            "limit",
            ["1-100"],
        ),
        (
            "/api/v1/market/industries/BK0475/stocks",
            {"limit": "101"},
            "limit",
            ["1-100"],
        ),
        (
            "/api/v1/market/industries/BK12/stocks",
            {},
            "boardCode",
            ["BK0000-BK9999"],
        ),
        (
            "/api/v1/market/industries/600519/stocks",
            {},
            "boardCode",
            ["BK0000-BK9999"],
        ),
        (
            "/api/v1/market/strong-stocks",
            {"date": "2026/10/29"},
            "date",
            ["YYYY-MM-DD"],
        ),
        (
            "/api/v1/market/strong-stocks",
            {"date": "2026-11-31"},
            "date",
            ["YYYY-MM-DD"],
        ),
        (
            "/api/v1/market/strong-stocks",
            {"date": "20261029"},
            "date",
            ["YYYY-MM-DD"],
        ),
    ],
)
def test_bad_parameters_are_400_with_the_offending_field(
    env, url, params, field, allowed
):
    error = _error(env.client.get(url, params=params or None))

    assert error["details"]["field"] == field
    assert error["details"]["allowed_values"] == allowed


# MKT-08 ---------------------------------------------------------------


def test_market_gets_write_nothing(tmp_path, validator, monkeypatch):
    env = _make_env(tmp_path, validator)
    _seed_market(env)
    _ok(env, "constituents", {"items": CONSTITUENTS}, "eastmoney")
    _ok(env, "strong_stocks", {"items": STRONG_ITEMS}, "ths")
    _ok(env, "newsflash", {"items": NEWSFLASH_ITEMS}, "cls")

    def _blocked(*_args, **_kwargs):
        raise AssertionError("market GET must not open a database")

    monkeypatch.setattr(sqlite3, "connect", _blocked)
    with TestClient(env.app) as client:
        for url in (
            "/api/v1/market/overview",
            "/api/v1/market/industries",
            "/api/v1/market/industries/BK0475/stocks",
            "/api/v1/market/strong-stocks",
            "/api/v1/market/newsflash",
        ):
            response = client.get(url)
            assert response.status_code == 200, response.text
            env.validator.validate(response.json())

    assert list(tmp_path.iterdir()) == []
    assert env.providers.calls == {
        "indices": 1,
        "northbound": 1,
        "industries": 2,
        "constituents": 1,
        "strong_stocks": 1,
        "newsflash": 1,
    }


# MKT-09 ---------------------------------------------------------------


def test_stale_thresholds_per_endpoint(env):
    _seed_market(env)
    first = _get(env, "/api/v1/market/overview")
    assert first["status"] == "ok"
    assert _get(env, "/api/v1/market/industries")["status"] == "ok"
    original_as_of = first["as_of"]
    original_fetched_at = first["fetched_at"]

    env.clock.advance(seconds=11)
    env.providers.set("indices", error=ProviderError("timeout"))
    env.providers.set("northbound", error=ProviderError("timeout"))

    payload = _get(env, "/api/v1/market/overview")
    assert payload["status"] == "stale"
    assert payload["stale_reason"] == "ttl_exceeded"
    assert payload["as_of"] == original_as_of
    assert payload["fetched_at"] == original_fetched_at
    assert payload["blocks"]["indices"]["status"] == "stale"
    assert payload["blocks"]["indices"]["stale_reason"] == "ttl_exceeded"
    assert payload["blocks"]["northbound"]["status"] == "ok"

    env.clock.advance(seconds=20)
    payload = _get(env, "/api/v1/market/overview")
    assert payload["blocks"]["northbound"]["status"] == "stale"
    assert payload["blocks"]["northbound"]["stale_reason"] == "ttl_exceeded"

    assert _get(env, "/api/v1/market/industries")["status"] == "ok"

    env.clock.set(NOW + timedelta(minutes=5, seconds=1))
    env.providers.set("industries", error=ProviderError("timeout"))

    stale = _get(env, "/api/v1/market/industries")
    assert stale["status"] == "stale"
    assert stale["stale_reason"] == "ttl_exceeded"
    assert stale["data"] == INDUSTRIES
    assert stale["as_of"] == original_as_of
