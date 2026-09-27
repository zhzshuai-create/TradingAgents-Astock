# -*- coding: utf-8 -*-
"""龙虎榜解析 fixture 钉子（审计 H3/H4/M14）.

全部离线 mock _common._eastmoney_datacenter，无网络依赖：
- H4: 带后缀代码（600379.SH，模型 tool call 常见产物）必须被规范化进 filter，
  否则静默查空后输出「未上榜」这种错误结论；
- H3: 第 1 节（上榜列表）失败时，机构动向必须显式输出「数据获取失败」，
  不许 NameError 被裸 except 无声吞掉后整节消失；
- 聚合正确性: 机构专用席位（OPERATEDEPT_CODE="0"）买卖汇总。
"""

from unittest.mock import patch

from tradingagents.dataflows.a_stock import signals

LIST_OK = [
    {
        "TRADE_DATE": "2026-09-10 00:00:00",
        "EXPLANATION": "日涨幅偏离值达7%",
        "BILLBOARD_NET_AMT": 12_345_678,
        "TURNOVERRATE": "5.5",
    },
]
BUY_INST = [
    {"OPERATEDEPT_CODE": "0", "OPERATEDEPT_NAME": "机构专用",
     "BUY": 50_000_000, "SELL": 0, "NET": 50_000_000},
]
SELL_EMPTY = []


def _fake_datacenter(results: dict):
    """results: {table: rows 或 Exception}；记录 (table, filter_str) 调用序列。"""
    calls: list[tuple[str, str]] = []

    def fake(table, filter_str="", **kw):
        calls.append((table, filter_str))
        v = results.get(table)
        if isinstance(v, Exception):
            raise v
        return v

    return fake, calls


def test_filter_uses_normalized_code():
    """H4: 600379.SH 进 filter 前必须规范成 6 位 600379。"""
    fake, calls = _fake_datacenter({
        "RPT_DAILYBILLBOARD_DETAILSNEW": LIST_OK,
        "RPT_BILLBOARD_DAILYDETAILSBUY": BUY_INST,
        "RPT_BILLBOARD_DAILYDETAILSSELL": SELL_EMPTY,
    })
    with patch.object(signals._common, "_eastmoney_datacenter", fake):
        out = signals.get_dragon_tiger_board("600379.SH", "2026-09-11")
    assert calls, "应至少发起一次 datacenter 调用"
    for _table, f in calls:
        assert 'SECURITY_CODE="600379"' in f, f"filter 未规范化: {f}"
        assert ".SH" not in f
    assert "600379" in out


def test_institution_flow_aggregates():
    fake, _ = _fake_datacenter({
        "RPT_DAILYBILLBOARD_DETAILSNEW": LIST_OK,
        "RPT_BILLBOARD_DAILYDETAILSBUY": BUY_INST,
        "RPT_BILLBOARD_DAILYDETAILSSELL": SELL_EMPTY,
    })
    with patch.object(signals._common, "_eastmoney_datacenter", fake):
        out = signals.get_dragon_tiger_board("600379", "2026-09-11")
    assert "机构动向" in out
    assert "5000" in out  # 50,000,000 元 = 5000 万


def test_section_failure_is_visible():
    """H3: 第 1 节失败时机构动向必须显式可见，不许整节无声消失。"""
    fake, _ = _fake_datacenter({
        "RPT_DAILYBILLBOARD_DETAILSNEW": RuntimeError("em datacenter down"),
    })
    with patch.object(signals._common, "_eastmoney_datacenter", fake):
        out = signals.get_dragon_tiger_board("600379", "2026-09-11")
    assert "龙虎榜列表查询失败" in out          # 第 1 节既有行为
    assert "机构动向" in out and "数据获取失败" in out  # H3 修复点
