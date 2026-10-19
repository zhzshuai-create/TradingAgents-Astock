"""双击K线 → 单日历史行情 功能的测试.

覆盖三层:
1. minute_timeline 纯函数 (分时时间轴: 上午 120 分钟 + 下午 120 分钟);
2. get_intraday_view 数据路由 (m1 分时优先 / 东财 5 分钟K线回退 / 双空);
3. AppTest 冒烟: 隐藏 text_input 带回日期 → 回调切视图 → 历史单日渲染,
   以及「回到今日」按钮清除选中日期.

网络调用全部打桩, 可离线重复.
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
APP_TIMEOUT = 120  # 冷启动导入链约 5.6s, 与 test_app_smoke 同口径
CODE = "300750"


# ── 单元: minute_timeline ─────────────────────────────────────────────────

def test_minute_timeline_basic():
    from web.data_functions import minute_timeline

    idx = minute_timeline("2026-08-27", 240)
    assert len(idx) == 240
    assert idx[0] == pd.Timestamp("2026-08-27 09:30")
    assert idx[119] == pd.Timestamp("2026-08-27 11:29")   # 上午收在 11:29
    assert idx[120] == pd.Timestamp("2026-08-27 13:00")   # 下午从 13:00 起
    assert idx[-1] == pd.Timestamp("2026-08-27 14:59")    # 收在 14:59
    assert all(ts.date() == pd.Timestamp("2026-08-27").date() for ts in idx)


def test_minute_timeline_partial_and_overflow():
    from web.data_functions import minute_timeline

    partial = minute_timeline("2026-08-27", 100)
    assert len(partial) == 100
    assert partial[-1] == pd.Timestamp("2026-08-27 11:09")  # 09:30 + 99min

    overflow = minute_timeline("2026-08-27", 242)  # 数据点超出 240 时顺延兜底
    assert len(overflow) == 242


def test_minute_timeline_zero_and_negative():
    """n<=0 必须返回空索引——负数交给切片会变成从尾部裁剪（历史 bug）。"""
    from web.data_functions import minute_timeline

    assert len(minute_timeline("2026-08-27", 0)) == 0
    assert len(minute_timeline("2026-08-27", -3)) == 0


# ── 单元: get_intraday_view 数据路由 ──────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_cached_sources():
    """清掉带 TTL 缓存的数据源函数, 避免跨测试污染."""
    import web.data_functions as df

    fns = [df.get_minute_history, df._em_5min_bars]
    for fn in fns:
        fn.clear()
    yield
    for fn in fns:
        fn.clear()


def test_intraday_view_prefers_m1(monkeypatch):
    import web.data_functions as df

    m1 = pd.DataFrame({"price": range(240), "vol": [1] * 240})
    monkeypatch.setattr(df, "get_minute_history", lambda code, d: m1)

    def _boom(*a, **k):
        raise AssertionError("分时可用时不应触发 5 分钟回退")

    monkeypatch.setattr(df, "_em_5min_bars", _boom)
    out, kind = df.get_intraday_view(CODE, "2026-08-27")
    assert kind == "m1"
    assert len(out) == 240
    assert out.index[0] == pd.Timestamp("2026-08-27 09:30")
    assert list(out.columns) == ["price", "vol"]


def test_intraday_view_falls_back_to_m5(monkeypatch):
    import web.data_functions as df

    monkeypatch.setattr(df, "get_minute_history", lambda code, d: pd.DataFrame())
    m5 = pd.DataFrame(
        {"price": [1.0, 2.0], "vol": [10, 20]},
        index=pd.DatetimeIndex(["2026-08-27 09:35", "2026-08-27 09:40"]),
    )
    monkeypatch.setattr(df, "_em_5min_bars", lambda code, d: m5)
    out, kind = df.get_intraday_view(CODE, "2026-08-27")
    assert kind == "m5"
    assert len(out) == 2


def test_intraday_view_both_empty(monkeypatch):
    import web.data_functions as df

    monkeypatch.setattr(df, "get_minute_history", lambda code, d: pd.DataFrame())
    monkeypatch.setattr(df, "_em_5min_bars", lambda code, d: pd.DataFrame())
    out, kind = df.get_intraday_view(CODE, "2026-08-27")
    assert kind == ""
    assert out.empty


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_em_5min_bars_parses_klines(monkeypatch):
    """东财 push2his klt=5 的 klines 逗号串解析 → datetime 索引 + price/vol 列."""
    import web.data_functions as df

    payload = {"data": {"klines": [
        "2026-08-27 09:35,4.60,4.64,4.66,4.59,12300,5698800.00",
        "2026-08-27 09:40,4.64,4.70,4.72,4.63,15000,7000000.00",
    ]}}
    monkeypatch.setattr(df._core, "_em_get", lambda *a, **k: _FakeResp(payload))
    out = df._em_5min_bars("600519", "2026-08-27")
    assert len(out) == 2
    assert out.index[0] == pd.Timestamp("2026-08-27 09:35")
    assert out["price"].iloc[0] == 4.64  # price = close
    assert out["vol"].iloc[1] == 15000


def test_em_5min_bars_empty_and_error(monkeypatch):
    import web.data_functions as df

    monkeypatch.setattr(df._core, "_em_get", lambda *a, **k: _FakeResp({"data": None}))
    assert df._em_5min_bars("600519", "2026-08-27").empty

    def _raise(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(df._core, "_em_get", _raise)
    assert df._em_5min_bars("600519", "2026-08-27").empty


def test_em_5min_bars_skips_malformed_rows(monkeypatch):
    """脏行（缺列/非数值）跳过并告警，不能炸穿看板渲染。"""
    import web.data_functions as df

    payload = {"data": {"klines": [
        "2026-08-27 09:35,4.60,4.64,4.66,4.59,12300,5698800.00",
        "2026-08-27 09:40,4.64,4.70",                        # 列数不足
        "2026-08-27 09:45,4.64,4.70,4.72,4.63,N/A,7000000",  # 非数值
        "2026-08-27 09:50,4.70,4.71,4.73,4.69,13100,6800000",
    ]}}
    monkeypatch.setattr(df._core, "_em_get", lambda *a, **k: _FakeResp(payload))
    out = df._em_5min_bars("600519", "2026-08-27")
    assert len(out) == 2
    assert out.index[0] == pd.Timestamp("2026-08-27 09:35")
    assert out.index[-1] == pd.Timestamp("2026-08-27 09:50")


def test_normalize_pick_date():
    """双击桥日期归一化：格式收敛、垃圾/未来日期拒绝（纯函数直测）。"""
    from web.components.data_dashboard import _normalize_pick_date

    assert _normalize_pick_date("2026-08-27") == "2026-08-27"
    assert _normalize_pick_date("20260827") == "2026-08-27"
    assert _normalize_pick_date("2026-8-7") == "2026-08-07"
    assert _normalize_pick_date(" 2026-08-27 ") == "2026-08-27"
    assert _normalize_pick_date("garbage") is None
    assert _normalize_pick_date("") is None
    assert _normalize_pick_date(None) is None
    assert _normalize_pick_date("2999-01-01") is None  # 未来日期无行情可显示


def test_candlestick_chart_collapses_suspended_days():
    """停牌日（区间内工作日但无数据行）必须从 x 轴剔除，不留空槽。"""
    from web.components.data_dashboard import _candlestick_chart

    days = pd.bdate_range("2026-09-21", periods=6)  # 周一~下周一，含周末压缩
    kdf = pd.DataFrame({
        "datetime": days, "open": 1.0, "high": 2.0,
        "low": 0.5, "close": 1.5, "vol": 100.0,
    })
    kdf = kdf.drop(kdf.index[3])  # 停牌 2026-09-24（周四，索引是 RangeIndex）
    fig = _candlestick_chart(kdf)
    rbs = fig.layout.xaxis.rangebreaks
    assert any(tuple(rb.bounds) == ("sat", "mon") for rb in rbs)  # 周末剔除仍在
    value_breaks = [d for rb in rbs if rb.values for d in rb.values]
    assert pd.Timestamp("2026-09-24") in value_breaks


def test_candlestick_hover_includes_pct_change():
    """悬停蜡烛必须给出当日涨跌幅，且按昨收（非开盘）计算。"""
    from web.components.data_dashboard import _candlestick_chart

    kdf = pd.DataFrame({
        "datetime": pd.bdate_range("2026-09-21", periods=3),
        "open": [10.0, 10.5, 10.0],
        "high": [10.6, 10.8, 10.2],
        "low": [9.8, 10.2, 9.9],
        "close": [10.5, 10.0, 10.2],  # 第2天 -4.76%，第3天 +2.00%
        "vol": [100.0, 120.0, 90.0],
    })
    fig = _candlestick_chart(kdf)
    hover = fig.data[0].customdata
    template = fig.data[0].hovertemplate

    assert "%{customdata}" in template
    assert "涨跌幅 +nan" not in hover[0].lower()
    assert "涨跌幅 —" in hover[0]  # 首根没有昨收
    assert "涨跌幅 -4.76%" in hover[1]
    assert "涨跌幅 +2.00%" in hover[2]
    assert "开 10.50" in hover[1] and "收 10.00" in hover[1]


def test_candlestick_hover_pct_uses_close_before_display_window():
    """5日视图只显示窗口内 5 根，但首根涨跌幅仍要用缓冲区里的前一日收盘。"""
    from web.components.data_dashboard import _candlestick_chart

    closes = [10.0 + i for i in range(25)]
    kdf = pd.DataFrame({
        "datetime": pd.bdate_range("2026-08-03", periods=25),
        "open": closes,
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "close": closes,
        "vol": [100.0] * 25,
    })
    fig = _candlestick_chart(kdf, display_tail=5)
    hover = fig.data[0].customdata

    assert len(hover) == 5
    # 展示首根是第 21 根（closes=30.0），昨收 29.0 → +3.45%
    assert "涨跌幅 +3.45%" in hover[0]


def test_candlestick_terminal_overlays():
    """终端化细节：最新价虚线/价签、十字光标、暗色可复用的 hover 框配置。"""
    from web.components.data_dashboard import _candlestick_chart

    kdf = pd.DataFrame({
        "datetime": pd.bdate_range("2026-09-21", periods=3),
        "open": [10.0, 10.5, 10.0],
        "high": [10.6, 10.8, 10.2],
        "low": [9.8, 10.2, 9.9],
        "close": [10.5, 10.0, 10.2],  # 最后一日收 10.2 > 开 10.0
        "vol": [100.0, 120.0, 90.0],
    })
    fig = _candlestick_chart(kdf)

    shape = fig.layout.shapes[0]
    assert shape.name == "last-close"
    assert shape.y0 == shape.y1 == 10.2
    assert shape.line.dash == "dot"

    tag = fig.layout.annotations[0]
    assert tag.name == "last-tag-up"  # 最后一日收涨
    assert tag.text == "10.20"
    assert tag.bgcolor == "#e03131"

    # 十字光标只在底部 x 轴与价格 y 轴上开启，避免上下两条重复竖线
    assert fig.layout.xaxis2.showspikes is True
    assert fig.layout.xaxis2.spikemode == "across"
    assert not fig.layout.xaxis.showspikes
    assert fig.layout.yaxis.showspikes is True

    assert fig.layout.hoverlabel.bgcolor == "#ffffff"
    assert "成交" in fig.data[4].hovertemplate


def test_candlestick_last_tag_turns_green_on_down_day():
    from web.components.data_dashboard import _candlestick_chart

    kdf = pd.DataFrame({
        "datetime": pd.bdate_range("2026-09-21", periods=2),
        "open": [10.0, 10.5],
        "high": [10.6, 10.6],
        "low": [9.8, 9.9],
        "close": [10.5, 10.0],
        "vol": [100.0, 90.0],
    })
    fig = _candlestick_chart(kdf)

    assert fig.layout.annotations[0].name == "last-tag-down"
    assert fig.layout.annotations[0].bgcolor == "#2f9e44"
    assert fig.layout.shapes[0].line.color == "#2f9e44"


def test_candlestick_chart_no_suspension_keeps_bounds_only():
    """数据连续（无停牌）时不应引入 values 剔除——避免多余计算与行为漂移。"""
    from web.components.data_dashboard import _candlestick_chart

    days = pd.bdate_range("2026-09-21", periods=6)
    kdf = pd.DataFrame({
        "datetime": days, "open": 1.0, "high": 2.0,
        "low": 0.5, "close": 1.5, "vol": 100.0,
    })
    fig = _candlestick_chart(kdf)
    rbs = fig.layout.xaxis.rangebreaks
    assert any(tuple(rb.bounds) == ("sat", "mon") for rb in rbs)
    assert not any(rb.values for rb in rbs)


def test_intraday_view_maps_alias_columns(monkeypatch):
    """mootdx 分钟列名的版本差异（close/volume 别名）就近映射，不炸看板。"""
    import web.data_functions as df

    m1 = pd.DataFrame({"close": range(240), "volume": [1] * 240})
    monkeypatch.setattr(df, "get_minute_history", lambda code, d: m1)
    out, kind = df.get_intraday_view(CODE, "2026-08-27")
    assert kind == "m1"
    assert list(out.columns) == ["price", "vol"]
    assert out["price"].iloc[0] == 0  # close → price


def test_intraday_view_rejects_unknown_columns(monkeypatch):
    """列名完全对不上时降级走 5 分钟回退，而不是 KeyError 炸渲染。"""
    import web.data_functions as df

    m1 = pd.DataFrame({"junk_a": [1], "junk_b": [2]})
    monkeypatch.setattr(df, "get_minute_history", lambda code, d: m1)
    m5 = pd.DataFrame({"price": [1.0], "vol": [10]},
                      index=pd.DatetimeIndex(["2026-08-27 09:35"]))
    monkeypatch.setattr(df, "_em_5min_bars", lambda code, d: m5)
    out, kind = df.get_intraday_view(CODE, "2026-08-27")
    assert kind == "m5"
    assert len(out) == 1


# ── 冒烟: AppTest 全链路 (桥回调 → 切视图 → 历史渲染 → 回到今日) ────────────

def _ss_has(ss, key: str) -> bool:
    """AppTest 的 session_state 代理不支持 .get()/in，用下标探测."""
    try:
        ss[key]
        return True
    except KeyError:
        return False


def _canned_kdf(n: int = 60, end: str = "2026-08-31") -> pd.DataFrame:
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({
        "datetime": idx, "open": 10.0, "high": 10.5,
        "low": 9.8, "close": 10.2, "vol": 1000.0,
    })


@pytest.fixture
def _stub_dashboard(monkeypatch):
    """打桩 data_dashboard 的全部网络数据源 (注意: 打在 data_dashboard 的
    名字空间上, 因为它是 from-import 绑定, 打 web.data_functions 无效)."""
    import web.components.data_dashboard as dash
    import web.data_functions as df
    import web.journal_service as js

    monkeypatch.setattr(df, "index_spot", lambda: {}, raising=True)
    monkeypatch.setattr(js, "start_journal", lambda: None, raising=True)

    q = {
        "name": "测试股", "price": 10.2, "change_amt": 0.1, "change_pct": 0.99,
        "pe_ttm": 20.0, "pb": 2.0, "mcap_yi": 100.0, "float_mcap_yi": 80.0,
        "turnover_pct": 1.0, "amount_wan": 5000.0,
        "limit_up": 11.22, "limit_down": 9.18,
        "open": 10.1, "high": 10.4, "low": 10.0, "last_close": 10.1,
    }
    monkeypatch.setattr(dash, "tencent_quote", lambda codes: {CODE: q})
    monkeypatch.setattr(dash, "ths_eps_forecast", lambda code: pd.DataFrame())
    monkeypatch.setattr(dash, "baidu_concept_blocks", lambda code: {})
    monkeypatch.setattr(dash, "get_kline_data", lambda code, days=60: _canned_kdf())
    monkeypatch.setattr(dash, "eastmoney_stock_news", lambda code, n=8: [])
    monkeypatch.setattr(dash, "get_minute_data", lambda code, date_str=None: pd.DataFrame())

    m1 = pd.DataFrame(
        {"price": [10.0] * 240, "vol": [100] * 240},
        index=df.minute_timeline("2026-08-27", 240),
    )
    monkeypatch.setattr(dash, "get_intraday_view", lambda code, d: (m1, "m1"))
    monkeypatch.setattr(dash, "_get_kline_full", lambda code: _canned_kdf(120))


def _run_data_mode():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.session_state["app_mode"] = "data"
    at.session_state["data_code"] = CODE
    at.run()
    return at


def _pick_date(at, date_str: str):
    """模拟双击桥：写隐藏输入框 → 点击隐藏表单提交按钮."""
    pick = next(w for w in at.text_input if w.key == "kline_pick_date")
    pick.set_value(date_str)
    at.button(key="kline_pick_submit").click()
    at.run()


def test_double_click_date_switches_to_single_day_view(_stub_dashboard):
    at = _run_data_mode()
    assert not at.exception
    assert at.radio(key=f"kperiod_{CODE}").value == "30日"  # 默认周期不变

    _pick_date(at, "2026-08-27")

    assert not at.exception
    assert at.session_state["single_day_date"] == "2026-08-27"
    assert at.radio(key=f"kperiod_{CODE}").value == "单日详情"
    assert any("2026-08-27" in c.value for c in at.caption)
    assert {m.label for m in at.metric} >= {"开盘", "最高", "最低", "收盘"}
    assert any(b.key == "back_to_today" for b in at.button)


def test_back_to_today_clears_picked_date(_stub_dashboard):
    at = _run_data_mode()
    _pick_date(at, "2026-08-27")
    assert _ss_has(at.session_state, "single_day_date")
    assert at.session_state["single_day_date"] == "2026-08-27"

    at.button(key="back_to_today").click()
    at.run()
    assert not at.exception
    assert not _ss_has(at.session_state, "single_day_date")
    # 今日视图回归: 实时指标 (今开/最高/最低/昨收) 重新出现
    assert {m.label for m in at.metric} >= {"今开", "最高", "最低", "昨收"}


def test_switching_stock_clears_picked_date(_stub_dashboard):
    """换股后上一只股票选中的日期不得串台 (render_data_mode 门控)."""
    at = _run_data_mode()
    _pick_date(at, "2026-08-27")
    assert _ss_has(at.session_state, "single_day_date")

    at.session_state["data_code"] = "600519"
    at.run()
    assert not at.exception
    assert not _ss_has(at.session_state, "single_day_date")


def test_hot_view_button_jump_does_not_raise(_stub_dashboard, monkeypatch):
    """回归：强势股归因「查看」按钮曾 inline 写 dash_tab（分区 radio 已在
    本轮实例化）→ StreamlitAPIException。跳转改为 pending 模式后必须无异常、
    落到个股估值分区且 data_code 正确。"""
    import web.components.data_dashboard as dash

    hot = pd.DataFrame([{
        "代码": "002694", "名称": "瀛通通讯", "涨幅%": -0.98,
        "题材归因": "军工+消费电子", "连板数": 1, "流通市值": 30.0,
    }])
    monkeypatch.setattr(dash, "ths_hot_reason", lambda *a, **k: hot)

    at = _run_data_mode()
    assert not at.exception
    at.radio(key="dash_tab").set_value("强势股归因")
    at.run()
    assert not at.exception

    btn = next(b for b in at.button if b.key and b.key.startswith("hot_"))
    btn.click()
    at.run()

    assert not at.exception
    assert at.session_state["data_code"] == "002694"
    assert at.radio(key="dash_tab").value == "个股估值"
