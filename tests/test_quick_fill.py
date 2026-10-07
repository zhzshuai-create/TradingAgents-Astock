"""快速开始回填链路的回归测试.

背景：快捷标的按钮曾 inline 写 st.session_state["input_ticker"]（侧边栏 widget
本轮已实例化）→ StreamlitAPIException，用户点任何快捷标的即炸。修复后按钮与
「快速开始」输入框都只落 pending key（_pending_ticker_fill），由脚本顶部
（render_sidebar 之前）消费预置 —— 与看板 _pending_jump_code 同一模式。

AppTest 全链路验证：点击按钮 / 输入回车 → 无异常 → 侧栏 input_ticker 被预置。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

APP_PATH = PROJECT_ROOT / "web" / "app.py"
APP_TIMEOUT = 120  # 冷启动导入链约 5.6s, 与 test_app_smoke 同口径


def _run_home():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.run()
    return at


def _sidebar_ticker(at):
    return [t for t in at.text_input if t.key == "input_ticker"]


def test_quick_button_fills_sidebar_without_exception():
    """回归：快捷标的按钮点击曾必抛 StreamlitAPIException（inline 写已实例化的
    input_ticker）。pending 模式下必须无异常且侧栏拿到代码。"""
    at = _run_home()
    assert not at.exception

    btns = [b for b in at.button if b.key and b.key.startswith("quick_")]
    if not btns:
        pytest.skip("无历史分析记录，快捷标的不渲染")
    btn = btns[0]
    code = btn.label

    btn.click()
    at.run()

    assert not at.exception
    ti = _sidebar_ticker(at)
    assert ti and ti[0].value == code


def test_quick_fill_input_fills_sidebar_without_exception():
    """「快速开始」输入框回车 → on_change 清空自身+落 pending → 消费点预置侧栏。"""
    at = _run_home()
    assert not at.exception

    box = next(w for w in at.text_input if w.key == "quick_fill_input")
    box.set_value("300750")
    at.run()

    assert not at.exception
    ti = _sidebar_ticker(at)
    assert ti and ti[0].value == "300750"
    box2 = next(w for w in at.text_input if w.key == "quick_fill_input")
    assert box2.value == ""  # 回填后输入框自身清空
