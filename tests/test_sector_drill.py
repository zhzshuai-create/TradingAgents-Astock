"""行业板块点击下钻（看板总览 → 板块成分股前十）的测试.

数据层: industry_stocks 解析/容错（_em_get 打桩, 离线）.
视图层: sector_stock_rows_html 纯函数（着色/降级）.
链路: AppTest 点击板块按钮 → 详情区出现成分股（industry_comparison/
industry_stocks/ths_hot_reason 全打桩, 不依赖东财可用性）.
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

_BOARDS = [
    {"rank": 1, "name": "航空机场", "change_pct": 1.70, "code": "BK0475",
     "up_count": 14, "down_count": 0, "leader": "南方航空", "leader_change": 2.15},
    {"rank": 2, "name": "铁路公路", "change_pct": 0.59, "code": "BK0476",
     "up_count": 27, "down_count": 7, "leader": "大秦铁路", "leader_change": 1.02},
]
_STOCKS = [
    {"code": "600029", "name": "南方航空", "price": 5.86, "change_pct": 2.15},
    {"code": "601111", "name": "中国国航", "price": "-", "change_pct": "-"},
]


def _stub_overview(monkeypatch):
    """看板总览三个网络入口全部打桩（AppTest 全程离线）."""
    import web.components.data_dashboard as dash

    monkeypatch.setattr(dash, "industry_comparison", lambda n=10: {
        "top": _BOARDS, "bottom": [], "total": len(_BOARDS)})
    monkeypatch.setattr(dash, "industry_stocks", lambda code, n=10: _STOCKS)
    monkeypatch.setattr(dash, "ths_hot_reason", lambda: pd.DataFrame())
    return dash


def test_industry_stocks_parses_diff_and_tolerates_suspended(monkeypatch):
    import web.data_functions as df

    class FakeResp:
        def json(self):
            return {"data": {"diff": [
                {"f12": "600029", "f14": "南方航空", "f2": 5.86, "f3": 2.15},
                {"f12": "601111", "f14": "中国国航", "f2": "-", "f3": "-"},
            ]}}

    monkeypatch.setattr(df._core, "_em_get", lambda *a, **k: FakeResp())
    out = df.industry_stocks("BK0475", 10)
    assert out[0] == {"code": "600029", "name": "南方航空",
                      "price": 5.86, "change_pct": 2.15}
    assert out[1]["price"] == "-"  # 停牌原始值透传, UI 侧降级 "--"


def test_industry_stocks_failure_returns_empty(monkeypatch):
    import web.data_functions as df

    def _boom(*a, **k):
        raise RuntimeError("em down")

    monkeypatch.setattr(df._core, "_em_get", _boom)
    assert df.industry_stocks("BK0001") == []


def test_sector_stock_rows_html_coloring_and_fallback():
    from web.stock_display import sector_stock_rows_html

    h = sector_stock_rows_html(_STOCKS)
    assert 'class="sector-stocks"' in h
    assert "pc--up" in h and "+2.15%" in h and "5.86" in h
    assert "pc--flat" in h and ">--<" in h  # 停牌降级
    assert 'data-code' not in h  # 明细行非交互元素


def test_sector_click_drills_into_top10(monkeypatch):
    """点击板块行 → 全宽详情区出现该板块成分股前十；再点同一板块收起."""
    _stub_overview(monkeypatch)
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=APP_TIMEOUT)
    at.session_state["app_mode"] = "data"
    at.session_state["data_code"] = ""  # 总览分支
    at.run()
    assert not at.exception

    btn = at.button(key="sector_BK0475")
    assert btn is not None
    btn.click()
    at.run()
    assert not at.exception
    assert at.session_state["sector_detail"] == "BK0475"
    mds = [m.value for m in at.markdown]
    assert any('class="sector-stocks"' in m for m in mds)
    assert any("南方航空" in m for m in mds)

    # 再点同一板块 → 收起
    at.button(key="sector_BK0475").click()
    at.run()
    assert not at.exception
    assert at.session_state["sector_detail"] is None
    mds2 = [m.value for m in at.markdown]
    assert not any('class="sector-stocks"' in m for m in mds2)


# ── _em_get 浏览器指纹兜底（东财 TLS 指纹断连的根修）──

def test_em_get_falls_back_to_curl_cffi(monkeypatch):
    """requests 两连败 → curl_cffi 兜底被调用并返回其响应."""
    import tradingagents.dataflows.a_stock._common as core

    calls = {"requests": 0}

    def _conn_error(*a, **k):
        calls["requests"] += 1
        raise core._requests.ConnectionError("fingerprint blocked")

    class FakeCurlResp:
        status_code = 200
        def json(self):
            return {"data": {"diff": [{"f12": "BK0420", "f14": "航空机场"}]}}

    captured = {}
    def fake_curl_get(url, params=None, headers=None, timeout=None, **k):
        captured["url"] = url
        captured["no_ua"] = not any(k.lower() == "user-agent"
                                    for k in (headers or {}))
        return FakeCurlResp()

    monkeypatch.setattr(core._EM_SESSION, "get", _conn_error)
    fake_curl = type(sys)("fake_curl_cffi")
    fake_curl.requests = type(sys)("fake_curl_requests")
    fake_curl.requests.get = fake_curl_get
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_curl.requests)

    resp = core._em_get("https://push2.eastmoney.com/api/qt/clist/get",
                        params={"fs": "m:90+t:2"})
    assert resp.json()["data"]["diff"][0]["f14"] == "航空机场"
    assert calls["requests"] == 2          # 先按原行为重试两次
    assert captured["no_ua"] is True       # UA 交给 impersonate, 不手动覆盖


def test_em_get_without_curl_cffi_reraises(monkeypatch):
    """未安装 curl_cffi 时维持历史行为: 抛出原连接错误."""
    import tradingagents.dataflows.a_stock._common as core

    def _conn_error(*a, **k):
        raise core._requests.ConnectionError("fingerprint blocked")

    monkeypatch.setattr(core._EM_SESSION, "get", _conn_error)
    monkeypatch.setitem(sys.modules, "curl_cffi", None)  # import 触发 ImportError

    with pytest.raises(core._requests.ConnectionError):
        core._em_get("https://push2.eastmoney.com/api/qt/clist/get")
