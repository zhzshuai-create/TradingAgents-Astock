"""Shared data and builders for P4-03 stock tests (not collected by pytest)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from backend.app.services.market_cache import MarketCache
from backend.app.services.market_clock import CST, format_cst
from backend.app.services.market_providers import FakeMarketProviders, Fetched
from backend.app.services.stock_service import StockService

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "upgrade" / "contracts" / "market-data-envelope-v1.json"

# Friday, intraday session: "today" and the "latest trading day" are the same.
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=CST)

QUOTE = {
    "name": "贵州茅台",
    "price": 1720.0,
    "last_close": 1700.0,
    "open": 1705.0,
    "high": 1730.0,
    "low": 1698.0,
    "change_pct": 1.18,
    "change_amt": 20.0,
    "amount_wan": 523000.0,
    "turnover_pct": 0.42,
    "pe_ttm": 28.5,
    "pb": 9.1,
    "amplitude_pct": 1.88,
    "float_mcap_yi": 21600.0,
    "mcap_yi": 21600.0,
    "limit_up": 1870.0,
}

VALUATION = {
    "eps_forecast": 60.5,
    "pe_forward": 28.43,
    "peg": 1.2,
    "pe_digestion_years": 0.0,
}

SECTOR_BLOCKS = {
    "industry": [{"name": "白酒", "change_pct": 1.2, "desc": "白酒行业"}],
    "concept": [{"name": "消费", "change_pct": 0.5, "desc": ""}],
    "region": [],
}

KLINE_DATA = {
    "adjust": "none",
    "bars": [
        {
            "date": "2026-10-28",
            "open": 10.0,
            "high": 10.5,
            "low": 9.9,
            "close": 10.3,
            "volume": 1000.0,
            "amount": None,
        },
        {
            "date": "2026-10-29",
            "open": 10.3,
            "high": 10.8,
            "low": 10.2,
            "close": 10.7,
            "volume": 1200.0,
            "amount": 1234500.0,
        },
    ],
    "units": {"price": "元", "volume": "手", "amount": "元"},
}

INTRADAY_DATA = {
    "date": "2026-11-06",
    "points": [
        {"time": "09:30", "price": 1700.0, "volume": 100.0, "avg_price": 1700.0},
        {"time": "09:31", "price": 1702.0, "volume": 120.0, "avg_price": 1701.09},
    ],
    "session_gaps": [["11:30", "13:00"]],
    "units": {"price": "元", "volume": "手", "amount": "元"},
}

NEWS_ITEMS = [
    {
        "title": "公司发布三季报",
        "content": "营收同比增长 10%",
        "published_at": "2026-11-05T18:00:00+08:00",
        "source": "东方财富",
        "url": "https://example.com/news/1",
    }
]

FUND_FLOW_ITEMS = [
    {
        "time": "09:31",
        "main_net": 1200000.0,
        "small_net": -300000.0,
        "mid_net": -200000.0,
        "large_net": 500000.0,
        "super_net": 700000.0,
    },
    {
        "time": "09:32",
        "main_net": 1500000.0,
        "small_net": -400000.0,
        "mid_net": -100000.0,
        "large_net": 600000.0,
        "super_net": 900000.0,
    },
]


class Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


def validator() -> Draft202012Validator:
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def make_service(clock: Clock | None = None) -> SimpleNamespace:
    clock = clock or Clock()
    providers = FakeMarketProviders()
    cache = MarketCache(clock=clock)
    service = StockService(providers, cache, clock=clock)
    return SimpleNamespace(
        service=service, providers=providers, cache=cache, clock=clock
    )


def set_ok(env, method: str, data, source: str):
    """Provider answer whose ``as_of`` tracks the frozen clock."""

    def fetch(*_args):
        return Fetched(data=data, as_of=format_cst(env.clock()), source=source)

    env.providers.set(method, fetch)


def set_record(env, method: str, data, source: str) -> list[tuple]:
    seen: list[tuple] = []

    def fetch(*args):
        seen.append(args)
        return Fetched(data=data, as_of=format_cst(env.clock()), source=source)

    env.providers.set(method, fetch)
    return seen
