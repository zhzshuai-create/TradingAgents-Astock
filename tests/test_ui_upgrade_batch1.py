# -*- coding: utf-8 -*-
"""UI 升级第一批回归: 板块行强度条 / 强势股行网格 / 报告页决策卡解析.

纯函数层测试(无 IO); 点击链路依赖 JS 桥, 由 Playwright 实测覆盖。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.stock_display import sector_rows_html, stock_rows_html  # noqa: E402
from web.components.report_viewer import decision_facts  # noqa: E402


def test_sector_rows_have_strength_bar_scaled_to_max():
    rows = [
        {"code": "BK1", "name": "航空", "change_pct": 4.0, "up_count": 10, "down_count": 2},
        {"code": "BK2", "name": "银行", "change_pct": -1.0, "up_count": 3, "down_count": 9},
        {"code": "BK3", "name": "地产", "change_pct": 0.0, "up_count": 5, "down_count": 5},
    ]
    html = sector_rows_html(rows)
    assert html.count("sr-bar") >= 2          # 非零涨跌幅行有条
    assert 'sr-bar--up' in html and 'sr-bar--down' in html
    assert 'width:100.0%' in html             # 最大值行满宽
    assert 'width:25.0%' in html              # 1.0/4.0 = 25%
    assert "width" not in html.split("BK3")[1].split("</div>")[0].replace('data-code="BK3"', "") \
        or 'sr-bar' not in html.split('data-code="BK3"')[1].split("</div>")[0]


def test_stock_rows_html_structure_and_escape():
    rows = [
        {"code": "002694", "name": "瀛通通讯", "change_pct": -0.98, "reason": "军工+消费电子"},
        {"code": "601208", "name": "东材科技", "change_pct": 10.0, "reason": "<b>题材</b>&x"},
    ]
    html = stock_rows_html(rows)
    assert '<div class="stock-table">' in html
    assert html.count('class="stock-row"') == 2       # 表头行单独 class 不计
    assert "stock-row--head" in html
    assert "&lt;b&gt;题材&lt;/b&gt;&amp;x" in html      # reason 转义
    assert "+10.00%" in html and "-0.98%" in html
    assert 'data-code="002694"' in html               # 点击桥挂点
    assert "st-bar--up" in html and "st-bar--down" in html
    assert html.index('st-bar--up"') > html.index("+10.00%")  # 条在数值格内


def test_stock_rows_empty_and_garbage_pct():
    assert stock_rows_html([]) == '<div class="stock-table"><div class="stock-row stock-row--head"><span class="st-code">代码</span><span class="st-name">名称</span><span class="st-pct-wrap"><span class="st-pct">涨跌幅</span></span><span class="st-reason">题材归因</span></div></div>'
    html = stock_rows_html([{"code": "X", "name": "n", "change_pct": "垃圾", "reason": ""}])
    assert "+0.00%" in html and "sr-bar" not in html


def test_decision_facts_parses_real_formats():
    state = {
        "final_trade_decision": (
            "**Rating**: Underweight\n**Executive Summary**: 摘要文字\n"
            "**Price Target**: 2.93\n**Time Horizon**: 1-2个月（至2026年三季报披露落地）"
        ),
        "trader_investment_decision": "若跌破2.59立即加速减仓；硬止损 2.45 元。",
    }
    f = decision_facts(state)
    assert f["rating"] == "Underweight"
    assert f["target"] == "2.93"
    assert f["stop"] == "2.45"
    assert "1-2个月" in f["horizon"]


def test_decision_facts_chinese_labels_and_missing():
    state = {"investment_plan": "维持增持评级，目标价 46.5 元，时间范围 3 个月。"}
    f = decision_facts(state)
    assert f["rating"] is not None and "增持" in f["rating"]
    assert f["target"] == "46.5"
    assert f["stop"] is None          # 无止损 → None(渲染层显示 —, 不编造)
    empty = decision_facts({})
    assert all(v is None for v in empty.values())


def test_decision_strip_has_mobile_two_column_layout():
    css = (PROJECT_ROOT / "web" / "theme.py").read_text(encoding="utf-8")
    mobile = css.split("@media (max-width: 768px)", 1)[1]
    decision = mobile.split(".decision-strip", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in decision
