"""运行态进度面板的纯函数单测.

render_progress 只在分析运行中渲染, AppTest 冒烟(idle)覆盖不到 ——
运行态内联 HTML 曾是零覆盖路径, 抽出纯函数后在此锁定.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_progress_header_contains_running_pulse_and_fields():
    from web.components.progress_panel import progress_header_html

    h = progress_header_html("601208",
                             '<span class="pp-parallel">x</span>')
    assert 'status-dot--running' in h        # 绿色脉冲点（theme 全局类）
    assert 'title="分析运行中"' in h
    assert "分析进行中" in h and "601208" in h
    assert 'class="pp-parallel"' in h        # 并行徽章透传


def test_badge_covers_all_stage_statuses():
    from web.components.progress_panel import _badge

    assert 'pp-done' in _badge("done") and "✓" in _badge("done")
    assert 'pp-active' in _badge("active")
    assert 'pp-pending' in _badge("pending")
    assert 'pp-pending' in _badge("unknown")  # 未知状态归 pending, 不抛


def test_status_html_states():
    from web.stock_display import status_html

    assert 'status-dot--running' in status_html("running")
    assert 'status-dot--idle' in status_html("idle")
    assert 'status-dot--idle' in status_html("anything-else")  # 兜底 idle
