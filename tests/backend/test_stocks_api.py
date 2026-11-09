"""P4-03 acceptance: six stock GET endpoints (STK-06 to STK-10).

HTTP-level behaviour runs on ``FakeMarketProviders`` plus a frozen clock: no
socket, no API key, no real name cache. Stock reports reuse the P3-01 list
query over a temporary SQLite database. Every 200 body is validated against
the frozen ``market-data-envelope-v1`` JSON Schema.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Report  # noqa: E402
from backend.app.services.market_cache import MarketCache  # noqa: E402
from backend.app.services.market_providers import (  # noqa: E402
    FakeMarketProviders,
    ProviderError,
)
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.services.stock_service import StockService  # noqa: E402
from backend.app.services.ticker_directory import TickerDirectory  # noqa: E402
from tests.backend.stock_helpers import (  # noqa: E402
    FUND_FLOW_ITEMS,
    KLINE_DATA,
    NEWS_ITEMS,
    NOW,
    QUOTE,
    Clock,
    set_ok,
    set_record,
    validator,
)

BACKEND = ROOT / "backend"
QUOTE_KEYS = {
    "name",
    "price",
    "last_close",
    "open",
    "high",
    "low",
    "change_pct",
    "change_amt",
    "amount_wan",
    "turnover_pct",
    "pe_ttm",
    "pb",
    "amplitude_pct",
    "float_mcap_yi",
    "mcap_yi",
    "limit_up",
}


class _StubService:
    """create_app only needs an engine and a clock to build the SSE stream."""

    def __init__(self, engine=None, now: datetime = NOW) -> None:
        self.engine = engine
        self._now = now

    def now(self) -> datetime:
        return self._now


class _StubExports:
    def sweep_stale(self) -> int:
        return 0

    def shutdown(self) -> None:
        return None


def _make_env(tmp_path: Path) -> SimpleNamespace:
    clock = Clock()
    providers = FakeMarketProviders()
    cache = MarketCache(clock=clock)
    app = create_app(
        service=_StubService(),
        report_store=ReportStore(tmp_path / "reports"),
        ticker_directory=TickerDirectory({}, clock=clock),
        export_service=_StubExports(),
        market_providers=providers,
        market_cache=cache,
    )
    app.state.stock_service = StockService(providers, cache, clock=clock)
    return SimpleNamespace(
        app=app,
        providers=providers,
        cache=cache,
        clock=clock,
        validator=validator(),
        tmp=tmp_path,
    )


@pytest.fixture()
def env(tmp_path):
    env = _make_env(tmp_path)
    with TestClient(env.app) as client:
        env.client = client
        yield env


def _seed_all(env) -> None:
    set_ok(env, "quote", dict(QUOTE), "tencent")
    set_ok(env, "valuation", {"eps_forecast": 60.5}, "ths")
    set_ok(
        env,
        "sector_blocks",
        {"industry": [], "concept": [], "region": []},
        "baidu",
    )
    set_ok(env, "kline", KLINE_DATA, "mootdx")
    set_ok(
        env,
        "intraday",
        {
            "date": "2026-11-06",
            "points": [],
            "session_gaps": [["11:30", "13:00"]],
            "units": {"price": "元", "volume": "手", "amount": "元"},
        },
        "mootdx",
    )
    set_ok(env, "stock_news", {"items": NEWS_ITEMS}, "eastmoney")
    set_ok(env, "fund_flow", {"items": FUND_FLOW_ITEMS}, "eastmoney")


def _get(env, url: str, **params) -> dict:
    response = env.client.get(url, params=params or None)
    assert response.status_code == 200, response.text
    payload = response.json()
    env.validator.validate(payload)
    return payload


def _error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error


# STK-06 ---------------------------------------------------------------


def test_news_marks_text_untrusted_and_passes_the_limit(env):
    seen = set_record(env, "stock_news", {"items": NEWS_ITEMS}, "eastmoney")

    payload = _get(env, "/api/v1/stocks/600519/news")

    assert seen == [("600519", 20)]
    assert payload["status"] == "ok"
    assert payload["source"] == "eastmoney"
    assert payload["data"] == {"items": NEWS_ITEMS, "untrusted": True}
    assert set(payload["data"]["items"][0]) == {
        "title",
        "content",
        "published_at",
        "source",
        "url",
    }


@pytest.mark.parametrize("limit", ["1", "100"])
def test_news_accepts_limit_bounds(env, limit):
    seen = set_record(env, "stock_news", {"items": []}, "eastmoney")

    payload = _get(env, "/api/v1/stocks/600519/news", limit=limit)

    assert payload["status"] == "ok"
    assert payload["data"] == {"items": [], "untrusted": True}
    assert seen == [("600519", int(limit))]


@pytest.mark.parametrize("limit", ["0", "101", "abc", "-1"])
def test_news_rejects_limit_outside_one_to_one_hundred(env, limit):
    error = _error(
        env.client.get("/api/v1/stocks/600519/news", params={"limit": limit}),
        400,
        "invalid_request",
    )

    assert error["details"] == {"field": "limit", "allowed_values": ["1-100"]}


def test_news_stale_after_five_minutes_keeps_untrusted(env):
    set_ok(env, "stock_news", {"items": NEWS_ITEMS}, "eastmoney")
    first = _get(env, "/api/v1/stocks/600519/news")
    assert first["status"] == "ok"

    env.clock.advance(minutes=4)
    env.providers.set("stock_news", error=ProviderError("timeout"))
    assert _get(env, "/api/v1/stocks/600519/news")["status"] == "ok"

    env.clock.advance(seconds=61)
    stale = _get(env, "/api/v1/stocks/600519/news")

    assert stale["status"] == "stale"
    assert stale["stale_reason"] == "ttl_exceeded"
    assert stale["data"] == {"items": NEWS_ITEMS, "untrusted": True}
    assert stale["as_of"] == first["as_of"]


# STK-07 ---------------------------------------------------------------


def test_fund_flow_returns_ascending_items_in_yuan(env):
    seen = set_record(env, "fund_flow", {"items": FUND_FLOW_ITEMS}, "eastmoney")

    payload = _get(env, "/api/v1/stocks/600519/fund-flow")

    assert seen == [("600519",)]
    assert payload["status"] == "ok"
    assert payload["source"] == "eastmoney"
    assert payload["data"]["items"] == FUND_FLOW_ITEMS
    assert set(payload["data"]["items"][0]) == {
        "time",
        "main_net",
        "small_net",
        "mid_net",
        "large_net",
        "super_net",
    }
    times = [item["time"] for item in payload["data"]["items"]]
    assert times == sorted(times)


def test_fund_flow_stale_after_sixty_seconds(env):
    set_ok(env, "fund_flow", {"items": FUND_FLOW_ITEMS}, "eastmoney")
    first = _get(env, "/api/v1/stocks/600519/fund-flow")

    env.clock.advance(seconds=61)
    env.providers.set("fund_flow", error=ProviderError("timeout"))
    stale = _get(env, "/api/v1/stocks/600519/fund-flow")

    assert stale["status"] == "stale"
    assert stale["stale_reason"] == "ttl_exceeded"
    assert stale["data"] == {"items": FUND_FLOW_ITEMS}
    assert stale["as_of"] == first["as_of"]


# STK-08 ---------------------------------------------------------------


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _report_row(index: int, *, ticker: str = "000629", hour: int = 15):
    report_id = f"00000000-0000-4000-8000-{index:012d}"
    generated_at = f"2026-10-24T{hour:02d}:30:00+08:00"
    meta = {
        "report_id": report_id,
        "ticker_code": ticker,
        "generated_at": generated_at,
    }
    return Report(
        report_id=report_id,
        job_id=None,
        ticker_code=ticker,
        ticker_name=None,
        analysis_date="2026-10-24",
        generated_at=generated_at,
        generated_at_source="job_clock",
        origin="new",
        schema_version="report-v1",
        content_hash="0" * 64,
        config_digest=None,
        data_quality_status="ok",
        chart_snapshot_status="frozen",
        retry_of_job_id=None,
        rating="Hold",
        signal="Hold",
        payload={"meta": meta, "sections": {}},
        created_at=generated_at,
    )


@pytest.fixture()
def report_env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    command.upgrade(_alembic_config(), "head")

    engine = build_engine()
    with Session(engine) as session:
        session.add_all(
            [
                _report_row(0, hour=15),
                _report_row(1, hour=14),
                _report_row(2, hour=13),
            ]
        )
        session.commit()

    app = create_app(
        service=_StubService(engine=engine),
        report_store=ReportStore(tmp_path / "reports"),
        ticker_directory=TickerDirectory({}, clock=lambda: NOW),
        export_service=_StubExports(),
        market_providers=FakeMarketProviders(),
        market_cache=MarketCache(clock=lambda: NOW),
    )
    client = TestClient(app)
    try:
        yield SimpleNamespace(client=client, engine=engine)
    finally:
        client.close()
        engine.dispose()


def test_stock_reports_is_the_same_body_as_the_flat_list(report_env):
    stock_page = report_env.client.get(
        "/api/v1/stocks/000629/reports", params={"limit": "2"}
    )
    flat_page = report_env.client.get(
        "/api/v1/reports", params={"ticker": "000629", "limit": "2"}
    )

    assert stock_page.status_code == 200, stock_page.text
    assert flat_page.status_code == 200, flat_page.text
    assert stock_page.json() == flat_page.json()
    body = stock_page.json()
    assert [item["meta"]["ticker_code"] for item in body["items"]] == [
        "000629",
        "000629",
    ]
    assert body["next_cursor"]


def test_stock_reports_cursor_walks_to_the_next_row(report_env):
    first = report_env.client.get(
        "/api/v1/stocks/000629/reports", params={"limit": "1"}
    ).json()
    second = report_env.client.get(
        "/api/v1/stocks/000629/reports",
        params={"limit": "1", "cursor": first["next_cursor"]},
    ).json()

    assert second["items"][0]["meta"]["report_id"] != first["items"][0]["meta"][
        "report_id"
    ]
    assert second["items"][0]["meta"]["generated_at"] == "2026-10-24T14:30:00+08:00"


def test_stock_reports_empty_page_and_invalid_cursor(report_env):
    empty = report_env.client.get("/api/v1/stocks/600519/reports").json()
    assert empty == {"items": [], "next_cursor": None}

    error = _error(
        report_env.client.get(
            "/api/v1/stocks/000629/reports", params={"cursor": "!!!"}
        ),
        400,
        "invalid_request",
    )
    assert error["details"] == {"field": "cursor"}


def test_stock_reports_rejects_a_bad_ticker(report_env):
    _error(
        report_env.client.get("/api/v1/stocks/not-a-ticker/reports"),
        422,
        "ticker_unresolved",
    )


# STK-09 ---------------------------------------------------------------


@pytest.mark.parametrize("ticker", ["abc", "12345", "1234567", "6005190", " "])
def test_unresolvable_codes_are_422(env, ticker):
    _error(
        env.client.get(f"/api/v1/stocks/{ticker}/snapshot"),
        422,
        "ticker_unresolved",
    )


def test_exchange_prefix_and_suffix_resolve_to_the_six_digit_code(env):
    seen = set_record(env, "fund_flow", {"items": []}, "eastmoney")

    _get(env, "/api/v1/stocks/SH600519/fund-flow")
    _get(env, "/api/v1/stocks/000001.SZ/fund-flow")

    assert seen == [("600519",), ("000001",)]


def test_unknown_chinese_name_is_422(env, monkeypatch):
    import backend.app.services.tickers as tickers

    def _unresolved(_raw):
        raise tickers.TickerUnresolved(_raw)

    monkeypatch.setattr(tickers, "_resolve_name", _unresolved)

    _error(
        env.client.get("/api/v1/stocks/不存在股份/snapshot"),
        422,
        "ticker_unresolved",
    )


def test_ambiguous_name_returns_candidates(env, monkeypatch):
    import backend.app.services.tickers as tickers

    candidates = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000519", "name": "中兵红箭"},
    ]

    def _ambiguous(_raw):
        raise tickers.TickerAmbiguous(candidates)

    monkeypatch.setattr(tickers, "_resolve_name", _ambiguous)

    error = _error(
        env.client.get("/api/v1/stocks/茅台/snapshot"), 422, "ticker_ambiguous"
    )

    assert error["details"] == {"candidates": candidates}


def test_name_table_crash_is_a_500_not_a_stack_trace(env, monkeypatch):
    import backend.app.services.tickers as tickers

    def _boom(_raw):
        raise RuntimeError("market map unreadable")

    monkeypatch.setattr(tickers, "_resolve_name", _boom)

    error = _error(
        env.client.get("/api/v1/stocks/茅台/snapshot"), 500, "internal_error"
    )

    assert "details" not in error
    assert "RuntimeError" not in error["message"]


def test_valid_code_without_data_is_an_empty_envelope(env):
    payload = _get(env, "/api/v1/stocks/600519/snapshot")

    assert payload["status"] == "empty"
    assert payload["data"] is None
    assert payload["error_code"] is None


def test_snapshot_is_partial_when_sector_blocks_fails(env):
    set_ok(env, "quote", dict(QUOTE), "tencent")
    set_ok(env, "valuation", {"eps_forecast": 60.5}, "ths")
    env.providers.set("sector_blocks", error=ProviderError("upstream"))

    payload = _get(env, "/api/v1/stocks/600519/snapshot")

    assert payload["status"] == "ok"
    assert payload["partial"] is True
    assert payload["failed_blocks"] == ["sector_blocks"]
    assert payload["data"]["sector_blocks"] is None
    assert payload["blocks"]["sector_blocks"]["error_code"] == "upstream_error"


def test_snapshot_with_all_three_blocks_is_not_partial(env):
    _seed_all(env)

    payload = _get(env, "/api/v1/stocks/600519/snapshot")

    assert payload["status"] == "ok"
    assert payload["partial"] is False
    assert payload["failed_blocks"] == []
    assert set(payload["data"]) == {
        "quote",
        "valuation",
        "sector_blocks",
        "units",
    }


# STK-10 ---------------------------------------------------------------


def test_stock_gets_write_nothing(tmp_path, monkeypatch):
    env = _make_env(tmp_path)
    _seed_all(env)

    def _blocked(*_args, **_kwargs):
        raise AssertionError("stock GET must not open a database")

    monkeypatch.setattr(sqlite3, "connect", _blocked)
    with TestClient(env.app) as client:
        for url in (
            "/api/v1/stocks/600519/snapshot",
            "/api/v1/stocks/600519/kline",
            "/api/v1/stocks/600519/intraday",
            "/api/v1/stocks/600519/news",
            "/api/v1/stocks/600519/fund-flow",
        ):
            response = client.get(url)
            assert response.status_code == 200, response.text
            env.validator.validate(response.json())

    assert list(tmp_path.iterdir()) == []
    assert env.providers.calls == {
        "quote": 1,
        "valuation": 1,
        "sector_blocks": 1,
        "kline": 1,
        "intraday": 1,
        "stock_news": 1,
        "fund_flow": 1,
    }


# Parameter matrix -----------------------------------------------------


@pytest.mark.parametrize(
    "url, params, field, allowed",
    [
        (
            "/api/v1/stocks/600519/kline",
            {"period": "hour"},
            "period",
            ["day", "week", "month"],
        ),
        (
            "/api/v1/stocks/600519/kline",
            {"limit": "0"},
            "limit",
            ["1-5000"],
        ),
        (
            "/api/v1/stocks/600519/kline",
            {"limit": "5001"},
            "limit",
            ["1-5000"],
        ),
        (
            "/api/v1/stocks/600519/kline",
            {"limit": "abc"},
            "limit",
            ["1-5000"],
        ),
        (
            "/api/v1/stocks/600519/intraday",
            {"date": "2026/10/29"},
            "date",
            ["YYYY-MM-DD"],
        ),
        (
            "/api/v1/stocks/600519/intraday",
            {"date": "2026-02-30"},
            "date",
            ["YYYY-MM-DD"],
        ),
    ],
)
def test_bad_parameters_are_400_with_the_offending_field(
    env, url, params, field, allowed
):
    error = _error(env.client.get(url, params=params), 400, "invalid_request")

    assert error["details"] == {"field": field, "allowed_values": allowed}


@pytest.mark.parametrize("limit", ["1", "5000"])
def test_kline_accepts_limit_bounds(env, limit):
    seen = set_record(env, "kline", KLINE_DATA, "mootdx")

    payload = _get(env, "/api/v1/stocks/600519/kline", limit=limit)

    assert payload["status"] == "ok"
    assert seen == [("600519", "day", int(limit))]


def test_non_trading_intraday_date_falls_back_to_provider_date(env):
    seen = set_record(
        env,
        "intraday",
        {
            "date": "2026-11-06",
            "points": [],
            "session_gaps": [["11:30", "13:00"]],
            "units": {"price": "元", "volume": "手", "amount": "元"},
        },
        "mootdx",
    )

    payload = _get(env, "/api/v1/stocks/600519/intraday", date="2026-11-07")

    assert seen == [("600519", "2026-11-07")]
    assert payload["status"] == "ok"
    assert payload["data"]["date"] == "2026-11-06"
