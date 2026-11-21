"""Time-window and exchange-prefix behaviour for the news layer (L8/M11)."""

from __future__ import annotations

from datetime import datetime

import pytest

from tradingagents.dataflows.a_stock import _common, news


class _FakeResponse:
    def __init__(self, payload=None, text: str = ""):
        self._payload = payload
        self.text = text
        self.encoding = "utf-8"

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_sina_stock_news_uses_bj_prefix_for_8xxxxx(monkeypatch):
    seen: dict[str, str] = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        return _FakeResponse(text="")

    monkeypatch.setattr(news._requests, "get", fake_get)

    news._fetch_news_sina("832000")

    assert "symbol=bj832000" in seen["url"]


def test_global_news_drops_undated_and_out_of_window(monkeypatch):
    in_window = int(datetime(2026, 11, 20, 10, 0).timestamp())
    too_old = int(datetime(2026, 10, 1, 10, 0).timestamp())
    cls_payload = {
        "data": {
            "roll_data": [
                {"title": "in-window", "brief": "", "content": "", "ctime": in_window},
                {"title": "too-old", "brief": "", "content": "", "ctime": too_old},
                {"title": "undated", "brief": "", "content": "", "ctime": ""},
            ]
        }
    }
    em_payload = {
        "data": {
            "fastNewsList": [
                {
                    "title": "em-old",
                    "summary": "",
                    "showTime": "2026-11-01 09:00:00",
                }
            ]
        }
    }

    def fake_get(url, **kwargs):
        if "eastmoney" in url:
            return _FakeResponse(em_payload)
        return _FakeResponse(cls_payload)

    monkeypatch.setattr(news._requests, "get", fake_get)
    monkeypatch.setattr(_common, "_em_get", fake_get)

    out = news.get_global_news("2026-11-21", look_back_days=7, limit=10)

    assert "in-window" in out
    assert "too-old" not in out
    assert "undated" not in out
    assert "em-old" not in out
    assert "2026-11-14" in out


def test_global_news_all_filtered_says_none(monkeypatch):
    payload = {
        "data": {
            "roll_data": [
                {
                    "title": "ancient",
                    "brief": "",
                    "content": "",
                    "ctime": int(datetime(2020, 1, 1).timestamp()),
                }
            ]
        }
    }
    fake = _FakeResponse(payload)
    monkeypatch.setattr(news._requests, "get", lambda *a, **k: fake)
    monkeypatch.setattr(_common, "_em_get", lambda *a, **k: fake)

    out = news.get_global_news("2026-11-21", look_back_days=7)

    assert out == "No global news found for 2026-11-21"


def test_stock_news_drops_undated_rows(monkeypatch):
    monkeypatch.setattr(
        news,
        "_fetch_news_eastmoney",
        lambda code, page_size=20: [
            {"title": "kept", "content": "", "time": "2026-11-20", "url": ""},
            {"title": "undated", "content": "", "time": "", "url": ""},
            {"title": "outside", "content": "", "time": "2026-11-01", "url": ""},
        ],
    )

    out = news.get_news("000001", "2026-11-19", "2026-11-21")

    assert "kept" in out
    assert "undated" not in out
    assert "outside" not in out


@pytest.mark.parametrize(
    ("code", "prefix"),
    [("600000", "sh"), ("900901", "sh"), ("000001", "sz"), ("832000", "bj")],
)
def test_sina_kline_prefix(monkeypatch, code, prefix):
    seen: dict[str, str] = {}

    def fake_get(url, params=None, **kwargs):
        seen["symbol"] = params["symbol"]
        return _FakeResponse(payload=[], text="[]")

    monkeypatch.setattr(_common._requests, "get", fake_get)

    df = _common._sina_kline_fallback(code)

    assert df.empty
    assert seen["symbol"] == f"{prefix}{code}"