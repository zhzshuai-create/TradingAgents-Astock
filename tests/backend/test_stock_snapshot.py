"""P4-03 acceptance: stock snapshot blocks (STK-01 to STK-03, STK-10 quote/valuation/sector TTLs)."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.market_providers import ProviderError  # noqa: E402
from tests.backend.stock_helpers import (  # noqa: E402
    NOW,
    QUOTE,
    SECTOR_BLOCKS,
    VALUATION,
    make_service,
    set_ok,
    validator,
)

VALIDATOR = validator()
UNITS = {"price": "元", "amount": "万元", "mcap": "亿元"}
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


@pytest.fixture()
def env():
    return make_service()


def _seed(env) -> None:
    set_ok(env, "quote", QUOTE, "tencent")
    set_ok(env, "valuation", VALUATION, "ths")
    set_ok(env, "sector_blocks", SECTOR_BLOCKS, "baidu")


# STK-01 ---------------------------------------------------------------


def test_snapshot_three_blocks_units_and_quote_keys(env):
    _seed(env)

    envelope = env.service.snapshot("600519")
    VALIDATOR.validate(envelope)

    assert envelope["status"] == "ok"
    assert envelope["source"] == "mixed"
    assert envelope["partial"] is False
    assert envelope["failed_blocks"] == []
    assert envelope["as_of"] == "2026-11-06T10:00:00+08:00"

    data = envelope["data"]
    assert data["quote"] == QUOTE
    assert set(data["quote"]) == QUOTE_KEYS
    assert data["valuation"] == VALUATION
    assert data["sector_blocks"] == SECTOR_BLOCKS
    assert data["units"] == UNITS

    assert envelope["blocks"]["quote"]["source"] == "tencent"
    assert envelope["blocks"]["valuation"]["source"] == "ths"
    assert envelope["blocks"]["sector_blocks"]["source"] == "baidu"


# STK-02 ---------------------------------------------------------------


def test_valuation_failure_is_partial_not_total(env):
    set_ok(env, "quote", QUOTE, "tencent")
    set_ok(env, "sector_blocks", SECTOR_BLOCKS, "baidu")
    env.providers.set("valuation", error=ProviderError("timeout"))

    envelope = env.service.snapshot("600519")
    VALIDATOR.validate(envelope)

    assert envelope["status"] == "ok"
    assert envelope["partial"] is True
    assert envelope["failed_blocks"] == ["valuation"]
    assert envelope["data"]["valuation"] is None
    assert envelope["data"]["quote"] == QUOTE
    assert envelope["data"]["units"] == UNITS
    block = envelope["blocks"]["valuation"]
    assert block["status"] == "error"
    assert block["error_code"] == "upstream_timeout"
    assert block["error_message"]


# STK-03 ---------------------------------------------------------------


def test_all_blocks_failing_is_an_error_envelope(env):
    for method in ("quote", "valuation", "sector_blocks"):
        env.providers.set(method, error=ProviderError("timeout"))

    envelope = env.service.snapshot("600519")
    VALIDATOR.validate(envelope)

    assert envelope["status"] == "error"
    assert envelope["data"] is None
    assert envelope["as_of"] is None
    assert envelope["error_code"] == "upstream_timeout"
    assert envelope["partial"] is False
    assert set(envelope["blocks"]) == {"quote", "valuation", "sector_blocks"}
    assert all(
        block["status"] == "error" for block in envelope["blocks"].values()
    )


def test_all_blocks_empty_is_an_empty_envelope(env):
    envelope = env.service.snapshot("600519")
    VALIDATOR.validate(envelope)

    assert envelope["status"] == "empty"
    assert envelope["data"] is None
    assert envelope["as_of"] is None
    assert envelope["error_code"] is None
    assert envelope["partial"] is False


# STK-10: snapshot thresholds ------------------------------------------


def test_snapshot_thresholds_quote_valuation_sector(env):
    _seed(env)
    first = env.service.snapshot("600519")
    assert first["status"] == "ok"

    env.clock.advance(seconds=61)
    env.providers.set("quote", error=ProviderError("timeout"))

    stale_quote = env.service.snapshot("600519")
    assert stale_quote["status"] == "stale"
    assert stale_quote["stale_reason"] == "ttl_exceeded"
    assert stale_quote["blocks"]["quote"]["status"] == "stale"
    assert stale_quote["blocks"]["quote"]["stale_reason"] == "ttl_exceeded"
    assert stale_quote["blocks"]["valuation"]["status"] == "ok"
    assert stale_quote["blocks"]["sector_blocks"]["status"] == "ok"
    assert stale_quote["as_of"] == first["as_of"]
    assert env.providers.calls["valuation"] == 1
    assert env.providers.calls["sector_blocks"] == 1

    env.clock.set(NOW + timedelta(hours=4, seconds=1))
    env.providers.set("valuation", error=ProviderError("timeout"))

    stale_valuation = env.service.snapshot("600519")
    assert stale_valuation["blocks"]["valuation"]["status"] == "stale"
    assert stale_valuation["blocks"]["valuation"]["stale_reason"] == "ttl_exceeded"
    assert stale_valuation["blocks"]["sector_blocks"]["status"] == "ok"
    assert env.providers.calls["sector_blocks"] == 1

    env.clock.set(NOW + timedelta(hours=24, seconds=1))
    env.providers.set("sector_blocks", error=ProviderError("timeout"))

    stale_sector = env.service.snapshot("600519")
    assert stale_sector["status"] == "stale"
    assert stale_sector["blocks"]["sector_blocks"]["status"] == "stale"
    assert (
        stale_sector["blocks"]["sector_blocks"]["stale_reason"]
        == "ttl_exceeded"
    )
    assert env.providers.calls["sector_blocks"] == 2
