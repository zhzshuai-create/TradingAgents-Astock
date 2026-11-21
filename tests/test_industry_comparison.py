"""Industry comparison must label exactly what it prints (L14)."""

from __future__ import annotations

from tradingagents.dataflows.a_stock import _common, signals


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _items():
    return [
        {"f14": "半导体", "f3": 3.5, "f104": 40, "f105": 2, "f128": "中芯国际"},
        {"f14": "煤炭", "f3": 1.2, "f104": 20, "f105": 8, "f128": "中国神华"},
        {"f14": "银行", "f3": 0.1, "f104": 10, "f105": 9, "f128": "招商银行"},
        {"f14": "地产", "f3": -2.4, "f104": 3, "f105": 30, "f128": "万科A"},
        {"f14": "传媒", "f3": -4.1, "f104": 1, "f105": 40, "f128": "分众传媒"},
    ]


def test_top_and_bottom_sections_are_sorted(monkeypatch):
    monkeypatch.setattr(
        _common,
        "_em_get",
        lambda *a, **k: _FakeResponse({"data": {"diff": list(reversed(_items()))}}),
    )

    out = signals.get_industry_comparison("000001", "2026-11-21", top_n=2)

    assert "## 涨幅前 2" in out
    assert "## 跌幅前 2" in out
    assert "showing top/bottom" not in out
    assert "全行业表现" not in out
    assert out.index("半导体") < out.index("煤炭")
    assert out.index("传媒") < out.index("地产")


def test_small_universe_prints_one_section(monkeypatch):
    monkeypatch.setattr(
        _common,
        "_em_get",
        lambda *a, **k: _FakeResponse({"data": {"diff": _items()[:2]}}),
    )

    out = signals.get_industry_comparison("000001", "2026-11-21", top_n=5)

    assert "## 涨幅前 2" in out
    assert "## 跌幅前" not in out


def test_failed_fetch_is_reported(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(_common, "_em_get", boom)

    out = signals.get_industry_comparison("000001", "2026-11-21")

    assert "行业对比查询失败" in out