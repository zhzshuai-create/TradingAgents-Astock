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


def _stub_quotes(monkeypatch):
    """AppTest 用例全程离线：快捷卡批量行情打桩返回空（卡片降级 "--"）。

    不打桩会真联网, 且 _tencent_quote 的 60s 进程级 _data_cache 会被真实
    数据灌热, 污染其他离线断言（test_astock_parsing 曾因此翻车）。
    """
    import web.data_functions as dfacade

    monkeypatch.setattr(dfacade, "tencent_quote", lambda codes: {}, raising=True)


def _sidebar_ticker(at):
    return [t for t in at.text_input if t.key == "input_ticker"]


def test_quick_button_fills_sidebar_without_exception(monkeypatch):
    """回归：快捷标的按钮点击曾必抛 StreamlitAPIException（inline 写已实例化的
    input_ticker）。pending 模式下必须无异常且侧栏拿到代码。"""
    _stub_quotes(monkeypatch)
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


def test_quick_fill_input_fills_sidebar_without_exception(monkeypatch):
    """「快速开始」输入框回车 → on_change 清空自身+落 pending → 消费点预置侧栏。"""
    _stub_quotes(monkeypatch)
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


def test_quick_start_button_starts_analysis(monkeypatch):
    """首页「开始分析」按钮：输入代码 → 点击 → start_analysis 消费、tracker 建立、
    侧栏 input_ticker 同步预置、输入框清空、toast 不再引导去侧边栏。

    run_analysis_in_thread 必须打桩（app.py 脚本轮 from-import 自 web.runner
    命名空间解析，桩打在源模块上生效）；不打桩会真起分析线程。
    """
    import web.data_functions as df
    import web.journal_service as js
    import web.runner as runner

    monkeypatch.setattr(df, "index_spot", lambda: {}, raising=True)
    monkeypatch.setattr(df, "tencent_quote", lambda codes: {}, raising=True)
    monkeypatch.setattr(js, "start_journal", lambda: None, raising=True)
    started: list[dict] = []
    monkeypatch.setattr(
        runner, "run_analysis_in_thread",
        lambda **kw: started.append(kw), raising=True,
    )

    at = _run_home()
    assert not at.exception

    btn = next(b for b in at.button if b.key == "home_start_btn")
    assert btn.disabled  # 无输入时禁用

    box = next(w for w in at.text_input if w.key == "quick_fill_input")
    box.set_value("300750")
    at.run()
    btn = next(b for b in at.button if b.key == "home_start_btn")
    assert not btn.disabled  # 有代码后解禁
    btn.click()
    at.run()  # 点击轮：if 体落 start_analysis/_pending（消费点在下一轮顶部）
    at.run()  # 消费轮：预置侧栏 + 发起分析

    assert not at.exception
    # 分析已被发起（run 桩收到调用），且 start_analysis 被消费
    assert started and started[0]["ticker"] == "300750"
    # 侧栏同步预置 + 首页输入框清空（消费点行为）
    ti = _sidebar_ticker(at)
    assert ti and ti[0].value == "300750"
    box2 = next(w for w in at.text_input if w.key == "quick_fill_input")
    assert box2.value == ""
    # toast 分流：直接启动，不再引导去侧边栏
    assert any("开始分析" in t.value for t in at.toast)


# ── 迷你行情卡 builder（纯函数，无 IO）──

def test_quick_card_html_up_down_flat_and_missing():
    from web.stock_display import quick_card_html

    up = quick_card_html("300750", "宁德时代", 291.11, 1.5)
    assert 'data-code="300750"' in up
    assert "pct--up" in up and "+1.50%" in up and "291.11" in up

    down = quick_card_html("601208", "东材科技", 48.22, -4.57)
    assert "pct--down" in down and "-4.57%" in down

    flat = quick_card_html("000001", "平安银行", 0, 0)
    assert "pct--flat" in flat and "0.00%" in flat and '"qc-price">--' in flat  # price<=0 → "--"

    missing = quick_card_html("000001", "", None, None)
    assert '"qc-price">--' in missing and "pct--flat" in missing


def test_quick_cards_render_with_stubbed_quotes(monkeypatch):
    """卡片网格带行情渲染 + 隐藏回填按钮点击链路。

    打桩在 web.data_functions 命名空间（app.py 脚本每轮 from-import 在此解析），
    返回任意请求 code 的罐头行情 → 用例不依赖本机历史记录内容。
    """
    import web.data_functions as dfacade

    monkeypatch.setattr(
        dfacade, "tencent_quote",
        lambda codes: {c: {"name": f"测试股{c}", "price": 10.0, "change_pct": 2.5}
                       for c in codes},
    )

    at = _run_home()
    assert not at.exception

    cards = [m.value for m in at.markdown if 'class="quick-card"' in m.value]
    if not cards:
        pytest.skip("无历史分析记录，快捷卡不渲染")
    assert all("pct--up" in c and "测试股" in c for c in cards)

    btn = next(b for b in at.button if b.key and b.key.startswith("quick_"))
    code = btn.label
    btn.click()
    at.run()

    assert not at.exception
    ti = [t for t in at.text_input if t.key == "input_ticker"]
    assert ti and ti[0].value == code
