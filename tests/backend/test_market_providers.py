"""P4-01 acceptance: provider error classification and test doubles.

ENV-05 lives here. The default adapters never run against the network in this
file; only the classification helpers and ``FakeMarketProviders`` are used.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.market_envelope import (  # noqa: E402
    BlockResult,
    build_blocks_envelope,
)
from backend.app.services.market_providers import (  # noqa: E402
    DefaultMarketProviders,
    FakeMarketProviders,
    Fetched,
    ProviderError,
    as_provider_error,
    classify_exception,
)

AS_OF = "2026-11-06T10:00:00+08:00"


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _http_error(status_code: int) -> requests.HTTPError:
    error = requests.HTTPError(f"HTTP {status_code}")
    error.response = _Response(status_code)
    return error


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("timeout", "upstream_timeout"),
        ("rate_limited", "upstream_rate_limited"),
        ("parse_error", "data_parse_error"),
        ("upstream", "upstream_error"),
    ],
)
def test_env05_provider_error_maps_four_codes(kind, code):
    error = ProviderError(kind)
    assert error.code == code
    assert as_provider_error(error) is error


def test_env05_classify_requests_exceptions():
    assert classify_exception(requests.Timeout()) == "timeout"
    assert classify_exception(_http_error(429)) == "rate_limited"
    assert classify_exception(_http_error(500)) == "upstream"
    assert classify_exception(RuntimeError("boom")) == "upstream"


def test_env05_unexpected_exception_becomes_upstream_error():
    error = as_provider_error(RuntimeError("boom"))
    assert isinstance(error, ProviderError)
    assert error.code == "upstream_error"


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("timeout", "upstream_timeout"),
        ("rate_limited", "upstream_rate_limited"),
        ("parse_error", "data_parse_error"),
        ("upstream", "upstream_error"),
    ],
)
def test_env05_fake_provider_errors_flow_through(kind, code):
    fake = FakeMarketProviders()
    fake.set("quote", error=ProviderError(kind))
    with pytest.raises(ProviderError) as caught:
        fake.quote("300750")
    assert as_provider_error(caught.value).code == code
    assert fake.calls["quote"] == 1


def test_fake_provider_returns_fixed_success_and_counts_calls():
    fake = FakeMarketProviders()
    fake.set(
        "quote",
        Fetched(data={"price": 186.42}, as_of=AS_OF, source="tencent"),
    )
    first = fake.quote("300750")
    second = fake.quote("300750")
    assert first.data["price"] == 186.42
    assert second is first
    assert fake.calls["quote"] == 2


def test_fake_provider_defaults_to_empty():
    fake = FakeMarketProviders()
    result = fake.kline("300750", "day", 120)
    assert result.status == "empty"
    assert result.data is None


def test_default_kline_parses_the_sina_fallback_dataframe(monkeypatch):
    import pandas as pd

    import backend.app.services.market_providers as providers

    def bars(*args, **kwargs):
        return pd.DataFrame(
            [
                {"date": "2026-11-06", "open": 2.7, "high": 2.8, "low": 2.69,
                 "close": 2.76, "volume": 1000, "amount": 2760},
                {"date": "2026-11-07", "open": 2.76, "high": 2.79, "low": 2.71,
                 "close": 2.75, "volume": 900, "amount": 2475},
            ]
        )

    monkeypatch.setattr(providers, "_mootdx_bars", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(providers, "_sina_daily_bars", bars)

    result = DefaultMarketProviders().kline("000629", "day", 60)

    assert result.status == "ok"
    assert result.source == "mixed"
    assert result.as_of == "2026-11-07"
    assert [bar["date"] for bar in result.data["bars"]] == ["2026-11-06", "2026-11-07"]
    assert result.data["bars"][-1] == {
        "date": "2026-11-07",
        "open": 2.76,
        "high": 2.79,
        "low": 2.71,
        "close": 2.75,
        "volume": 900.0,
        "amount": 2475.0,
    }


def test_fake_provider_supports_delay():
    fake = FakeMarketProviders()
    fake.set("northbound", Fetched(data={}, as_of=AS_OF, source="hexin"), delay=0.02)
    started = time.perf_counter()
    fake.northbound()
    assert time.perf_counter() - started >= 0.02


def test_fake_provider_supports_per_block_failure():
    fake = FakeMarketProviders()
    fake.set("quote", Fetched(data={"price": 1}, as_of=AS_OF, source="tencent"))
    fake.set("valuation", error=ProviderError("timeout"))
    fake.set(
        "sector_blocks",
        Fetched(data={"industry": []}, as_of=AS_OF, source="baidu"),
    )

    blocks = {}
    with pytest.raises(ProviderError):
        fake.valuation("300750")
    blocks["quote"] = BlockResult("ok", "tencent", AS_OF, AS_OF, fake.quote("300750").data)
    blocks["valuation"] = BlockResult(
        "error",
        "ths",
        None,
        AS_OF,
        error_code="upstream_timeout",
        error_message="数据服务响应超时",
    )
    blocks["sector_blocks"] = BlockResult(
        "ok", "baidu", AS_OF, AS_OF, fake.sector_blocks("300750").data
    )
    doc = build_blocks_envelope(blocks)
    assert doc["status"] == "ok"
    assert doc["partial"] is True
    assert doc["failed_blocks"] == ["valuation"]


def test_both_provider_objects_expose_the_full_surface():
    methods = (
        "indices",
        "northbound",
        "industries",
        "constituents",
        "strong_stocks",
        "newsflash",
        "quote",
        "valuation",
        "sector_blocks",
        "kline",
        "intraday",
        "stock_news",
        "fund_flow",
    )
    default = DefaultMarketProviders()
    fake = FakeMarketProviders()
    for name in methods:
        assert callable(getattr(default, name)), name
        assert callable(getattr(fake, name)), name


# -- R1 Baidu transport ------------------------------------------------------


class _JsonResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _baidu_payload(ticker: str = "600000") -> dict:
    return {
        "ResultCode": "0",
        "Result": {
            ticker: [
                {
                    "name": "行业",
                    "list": [{"name": "银行", "increase": "1.25", "describe": "银行"}],
                },
                {
                    "name": "概念",
                    "list": [{"name": "沪股通", "increase": "0.5"}],
                },
                {
                    "name": "地域",
                    "list": [{"name": "上海", "increase": "0.3"}],
                },
            ]
        },
    }


def test_r1_t8_sector_blocks_uses_curl_cffi_browser_fingerprint(monkeypatch):
    import curl_cffi.requests as curl_requests

    seen: dict = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return _JsonResponse(200, _baidu_payload())

    monkeypatch.setattr(curl_requests, "get", fake_get)

    result = DefaultMarketProviders().sector_blocks("600000")

    assert "finance.pae.baidu.com" in seen["url"]
    assert seen["impersonate"] == "chrome"
    assert seen["timeout"] == 10
    assert seen["headers"]["User-Agent"]
    assert result.status == "ok"
    assert result.source == "baidu"
    assert [item["name"] for item in result.data["industry"]] == ["银行"]
    assert [item["name"] for item in result.data["concept"]] == ["沪股通"]
    assert [item["name"] for item in result.data["region"]] == ["上海"]


def test_r1_t9_sector_blocks_falls_back_when_curl_cffi_missing(monkeypatch):
    import backend.app.services.market_providers as providers

    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    seen: dict = {}

    def fake_get(url, **kwargs):
        seen.update(kwargs)
        return _JsonResponse(200, _baidu_payload())

    monkeypatch.setattr(providers.requests, "get", fake_get)

    result = providers.DefaultMarketProviders().sector_blocks("600000")

    assert "impersonate" not in seen
    assert result.status == "ok"
    assert result.data["industry"][0]["name"] == "银行"


def test_r1_t10_http_403_is_risk_control(monkeypatch):
    import curl_cffi.requests as curl_requests

    monkeypatch.setattr(curl_requests, "get", lambda *args, **kwargs: _JsonResponse(403, {}))

    with pytest.raises(ProviderError) as caught:
        DefaultMarketProviders().sector_blocks("600000")

    assert caught.value.code == "upstream_error"
    assert caught.value.message == "百度接口风控拦截"


def test_r1_t10_result_code_403_in_200_body_is_risk_control(monkeypatch):
    import curl_cffi.requests as curl_requests

    payload = {"ResultCode": "0", "Result": {"code": 403}}
    monkeypatch.setattr(
        curl_requests, "get", lambda *args, **kwargs: _JsonResponse(200, payload)
    )

    with pytest.raises(ProviderError) as caught:
        DefaultMarketProviders().sector_blocks("600000")

    assert caught.value.code == "upstream_error"
    assert caught.value.message == "百度接口风控拦截"


def test_r1_sector_timeout_maps_to_upstream_timeout(monkeypatch):
    import curl_cffi.requests as curl_requests

    def boom(*args, **kwargs):
        raise curl_requests.exceptions.Timeout("read timed out")

    monkeypatch.setattr(curl_requests, "get", boom)

    with pytest.raises(ProviderError) as caught:
        DefaultMarketProviders().sector_blocks("600000")

    assert caught.value.code == "upstream_timeout"
