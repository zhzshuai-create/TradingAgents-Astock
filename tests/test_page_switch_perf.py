"""页面切换性能修复的回归测试（2026-10-25）。

覆盖三件事：
1. TDX bars 通道熔断（核心层 _load_ohlcv_astock）：撞一次空返回后熔断生效，
   熔断期内 mootdx 完全不碰、新浪兜底照常出数；
2. web 层 _get_kline_full 尊重同一熔断（不再每次冷拉白等 4s+ 空表）；
3. 顶栏 segmented_control 切模式：单轮渲染看板内容、app_mode 同步、无异常
   （原先"写 session + st.rerun()"的双跑已移除）。

网络调用全部打桩，可离线重复。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

APP_PATH = PROJECT_ROOT / "web" / "app.py"
APP_TIMEOUT = 120  # 与 test_app_smoke / test_kline_intraday_jump 同口径


def _sina_bars() -> pd.DataFrame:
    return pd.DataFrame({
        "Date": pd.to_datetime(["2026-06-10", "2026-06-11"]),
        "Open": [50.8, 53.29], "High": [55.8, 58.8],
        "Low": [50.5, 52.96], "Close": [53.45, 57.47],
        "Volume": [149046.0, 205219.0],
    })


@pytest.fixture(autouse=True)
def _reset_bars_fuse(monkeypatch):
    """每个用例独立熔断状态（模块全局可变，跨用例必须复位）。"""
    from tradingagents.dataflows.a_stock import _common

    monkeypatch.setattr(_common, "_TDX_BARS_FUSE_UNTIL", 0.0)
    yield


# ── 单元: bars 通道熔断（核心层） ──────────────────────────────────────────

def test_empty_bars_blows_fuse_and_serves_sina(tmp_path, monkeypatch):
    from tradingagents.dataflows import config as dataflow_config
    from tradingagents.dataflows.a_stock import _common

    monkeypatch.setattr(
        dataflow_config, "get_config", lambda: {"data_cache_dir": str(tmp_path)}
    )
    calls = {"bars": 0}

    class _EmptyBarsClient:
        def bars(self, symbol, category, offset):
            calls["bars"] += 1
            return pd.DataFrame()

    monkeypatch.setattr(_common, "_get_mootdx_client", lambda: _EmptyBarsClient())
    monkeypatch.setattr(_common, "_sina_kline_fallback", lambda *a: _sina_bars())

    result = _common._load_ohlcv_astock("000628", "2026-06-11")

    assert len(result) == 2
    assert calls["bars"] == 1            # 只撞一次空，随即熔断
    assert _common._tdx_bars_blown()     # 熔断已生效


def test_fused_load_skips_mootdx_entirely(tmp_path, monkeypatch):
    from tradingagents.dataflows import config as dataflow_config
    from tradingagents.dataflows.a_stock import _common

    monkeypatch.setattr(
        dataflow_config, "get_config", lambda: {"data_cache_dir": str(tmp_path)}
    )
    _common._blow_tdx_bars_fuse()

    def _no_client():
        raise AssertionError("熔断期内不得构建 mootdx 客户端")

    monkeypatch.setattr(_common, "_get_mootdx_client", _no_client)
    monkeypatch.setattr(_common, "_sina_kline_fallback", lambda *a: _sina_bars())

    result = _common._load_ohlcv_astock("000628", "2026-06-11")
    assert len(result) == 2              # 新浪兜底照常出数


# ── 单元: web 层 _get_kline_full 尊重熔断 ─────────────────────────────────

def test_web_kline_full_respects_fuse(monkeypatch):
    from web import data_functions as df
    from tradingagents.dataflows.a_stock import _common

    _common._blow_tdx_bars_fuse()

    def _no_client():
        raise AssertionError("熔断期内 _get_kline_full 不得拉 mootdx")

    monkeypatch.setattr(df, "_tdx_client", _no_client)
    monkeypatch.setattr(df._core, "_load_ohlcv_astock", lambda code, d: _sina_bars())

    # 用伪造代码避开 st.cache_data 跨用例缓存
    out = df._get_kline_full("980001")
    assert list(out.columns) == ["datetime", "open", "high", "low", "close", "vol"]
    assert len(out) == 2


# ── AppTest: 顶栏切模式 → 看板当轮渲染 ────────────────────────────────────

@pytest.fixture
def _stub_network(monkeypatch):
    """离线桩：顶栏指数（app.py 每轮 from-import 重解析，打 df 命名空间即生效）
    + 看板总览两路数据源（data_dashboard 是模块级 from-import，必须打 dash）。"""
    import web.components.data_dashboard as dash
    import web.data_functions as df

    monkeypatch.setattr(df, "index_spot", lambda: {}, raising=True)
    monkeypatch.setattr(df, "tencent_quote", lambda codes: {}, raising=True)
    monkeypatch.setattr(
        dash, "industry_comparison",
        lambda n=10: {"top": [], "bottom": [], "total": 0},
    )
    monkeypatch.setattr(dash, "ths_hot_reason", lambda *a, **k: pd.DataFrame())


def test_mode_switch_to_dashboard_renders_in_one_run(_stub_network):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.run()
    assert not at.exception
    assert at.session_state["app_mode"] == "analysis"

    at.segmented_control(key="top_mode").set_value("实时数据看板")
    at.run()

    assert not at.exception
    assert at.session_state["app_mode"] == "data"
    # 看板内容已在树上（总览空态 + 分区 radio），而非停留在分析报告页
    assert any(r.label == "看板分区" for r in at.radio)
    assert any("输入股票代码" in c.value for c in at.caption)
