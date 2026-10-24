# -*- coding: utf-8 -*-
"""PDF/Markdown 导出文本清洗的回归测试.

背景(2026-10-06 首份 MiMo 报告评审实锤): PDF 混入 FINAL TRANSACTION
PROPOSAL 原始标记、裸 markdown 反引号围栏、决策文本跨章节整段重复。
清洗在 _collect_sections 统一收口（PDF 与 Markdown 双格式共用）。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.pdf_export import (  # noqa: E402
    _collect_sections,
    dedup_paragraphs,
    strip_code_fences,
    strip_framework_markers,
)


def test_strip_framework_markers():
    text = ("分析结论如下。\nFINAL TRANSACTION PROPOSAL: SELL\n"
            "final transaction proposal：Hold\n理由:估值偏高。")
    out = strip_framework_markers(text)
    assert "FINAL TRANSACTION" not in out
    assert "final transaction" not in out
    assert "分析结论如下" in out and "理由:估值偏高" in out


def test_strip_code_fences_keeps_inner_text():
    text = "正文A\n```python\nprint(1)\n```\n正文B"
    out = strip_code_fences(text)
    assert "```" not in out
    assert "print(1)" in out
    assert "正文A" in out and "正文B" in out


def test_dedup_within_and_across_sections():
    seen: set[str] = set()
    para = ("维持减持评级，目标价四十六元五角，建议分两批执行建仓操作，"
            "同时设置百分之五的硬性止损线以控制下行风险敞口。")
    first = dedup_paragraphs(f"{para}\n独有内容第一段。", seen)
    second = dedup_paragraphs(f"{para}\n独有内容第二段。", seen)
    assert para in first
    assert para not in second  # 跨调用(跨章节)重复被丢弃
    assert "独有内容第二段" in second
    # 短行(标题/标签)不去重
    third = dedup_paragraphs("=== 风控决策 ===\n=== 风控决策 ===", seen)
    assert third.count("=== 风控决策 ===") == 2


def test_collect_sections_dedups_and_skips_empty():
    body = ("综合评估后建议减持该标的，目标价四十六元五角，分两批建仓执行，"
            "同时设置百分之五的硬性止损线以控制下行风险敞口。")
    final_state = {
        "trader_investment_decision": f"FINAL TRANSACTION PROPOSAL: SELL\n{body}",
        "investment_plan": f"```text\n{body}\n```\n{body}",
        "final_trade_decision": body,  # 整节重复 → 清洗后为空 → 跳过
    }
    sections = _collect_sections(final_state, ticker=None)
    titles = [t for t, _ in sections]
    assert "交易员决策" in titles
    assert "最终决策" not in titles  # 整节重复被清空跳过
    joined = "\n".join(c for _, c in sections)
    assert joined.count("综合评估后建议减持") == 1  # 三节重复只留一次
    assert "FINAL TRANSACTION" not in joined
    assert "```" not in joined


def test_risk_judge_identical_to_final_renders_once():
    """框架把同一文本存 risk.judge_decision 与 final_trade_decision 两个字段
    （真实报告实测）——正文只在「最终决策」渲染，风控评估不重复带出。"""
    body = ("综合风险评估后维持减持评级，建议将单一个股敞口压至组合百分之三以内，"
            "并在三季报披露前保持最低跟踪仓位等待右侧确认信号再行操作。")
    final_state = {
        "risk_debate_state": {
            "conservative_history": "保守观点正文，关注流动性与估值风险。",
            "judge_decision": body,
        },
        "final_trade_decision": body,
    }
    sections = dict(_collect_sections(final_state, ticker=None))
    assert "风控评估" in sections and "最终决策" in sections
    assert "综合风险评估后维持减持" not in sections["风控评估"]
    assert "综合风险评估后维持减持" in sections["最终决策"]
    assert "保守观点正文" in sections["风控评估"]


def test_collect_sections_keeps_normal_content():
    final_state = {"market_report": "技术面呈现高位放量滞涨形态，均线系统多头排列。"}
    sections = _collect_sections(final_state, ticker=None)
    assert sections and "高位放量滞涨" in sections[0][1]


def test_analyst_lines_quoted_by_decisions_are_kept():
    """决策章节合法复述分析师报告证据是综合不是重复，必须保留。

    2026-10-24 v2.6 真实报告实测：全章节共享 seen 时，最终投资建议的
    复述段被误删只剩孤壳标题——跨章节去重必须只在决策族章节间生效。
    """
    evidence = ("2026H1归母净利润2.21亿元，其中一季度0.72亿、二季度1.50亿，"
                "环比翻倍增长，毛利率从去年同期的9.0%提升至12.3%。")
    final_state = {
        "fundamentals_report": f"业绩拆解：{evidence}",
        "investment_plan": f"综合判断：基本面证据明确（{evidence}），维持减持。",
    }
    sections = dict(_collect_sections(final_state, ticker=None))
    assert "基本面报告" in sections and "最终投资建议" in sections
    # 两节各出现一次（合法复述），最终建议的综合语句完整保留
    assert sections["基本面报告"].count("环比翻倍增长") == 1
    assert sections["最终投资建议"].count("环比翻倍增长") == 1
    assert "维持减持" in sections["最终投资建议"]
