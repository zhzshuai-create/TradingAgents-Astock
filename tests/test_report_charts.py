"""报告图表模块回归测试：生成 / 降级 / PDF 嵌入与临时目录清理."""


import pandas as pd
import pytest

from web.pdf_export import PDFExportError, generate_pdf, _find_cjk_fonts


def _fake_ohlcv():
    """120 根确定性合成的日K数据（含涨跌交替，MA/成交量可用）。"""
    import numpy as np

    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2026-03-02", periods=120)
    close = 50 + np.cumsum(rng.normal(0, 0.8, 120))
    open_ = close + rng.normal(0, 0.3, 120)
    high = pd.concat(
        [pd.Series(open_), pd.Series(close)], axis=1
    ).max(axis=1) + rng.uniform(0.1, 0.6, 120)
    low = pd.concat(
        [pd.Series(open_), pd.Series(close)], axis=1
    ).min(axis=1) - rng.uniform(0.1, 0.6, 120)
    vol = rng.uniform(4e6, 1e8, 120)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": vol,
        }
    )


_FAKE_KLINES = [
    f"2026-09-{d:02d},{(i - 5) * 3e7:.0f},1e6,2e6,1.5e7,{(i - 5) * 2e7:.0f},0"
    for i, d in enumerate(range(1, 21))
]

_FAKE_MARGIN_ROWS = [
    {"DATE": f"2026-09-{d:02d}", "RZYE": (10 + (i % 4)) * 1e8}
    for i, d in enumerate(range(30, 0, -1))
]

_FAKE_LOCKUP_HISTORY = [
    {"FREE_DATE": "2012-05-21 00:00:00", "FREE_RATIO": 44.58},
    {"FREE_DATE": "2014-05-21 00:00:00", "FREE_RATIO": 43.99},
    {"FREE_DATE": "2023-07-18 00:00:00", "FREE_RATIO": 0.93},
]

_FAKE_NEWS_JSONP = (
    "jQuery_chart_news(" +
    __import__("json").dumps(
        {"result": {"cmsArticleWebOld": {"list": [
            {"date": f"2026-09-{d:02d} 10:00:00"} for d in (21, 23, 23, 24, 28, 30)
        ]}}}
    ) + ")"
)


class _FakeJsonpResp:
    text = _FAKE_NEWS_JSONP


def _patch_data_sources(
    monkeypatch, ohlcv=None, klines=None, quote=None, eps=None,
    margin_rows=None, lockup_history=None, lockup_upcoming=None, news=True,
):
    """把 report_charts 依赖的全部数据入口替换为离线假数据。"""
    from tradingagents.dataflows.a_stock import _common

    if ohlcv is not None:
        monkeypatch.setattr(_common, "_load_ohlcv_astock", lambda *a, **k: ohlcv)
    if klines is not None:
        class _FakeResp:
            def json(self):
                return {"data": {"klines": klines}}

        monkeypatch.setattr(
            _common, "_em_get", lambda *a, **k: _FakeResp()
        )
    if quote is not None:
        monkeypatch.setattr(
            _common, "_tencent_quote", lambda codes: quote
        )
    if eps is not None:
        monkeypatch.setattr(_common, "_ths_eps_forecast", lambda code: eps)

    def _fake_datacenter(report_name, **kwargs):
        if report_name == "RPTA_WEB_RZRQ_GGMX":
            if margin_rows is None:
                raise RuntimeError("margin down")
            return margin_rows
        if report_name == "RPT_LIFT_STAGE":
            if ">='" in kwargs.get("filter_str", ""):
                return lockup_upcoming if lockup_upcoming is not None else []
            return lockup_history if lockup_history is not None else []
        return []

    monkeypatch.setattr(_common, "_eastmoney_datacenter", _fake_datacenter)

    if news:
        monkeypatch.setattr("requests.get", lambda *a, **k: _FakeJsonpResp())
    else:
        def _boom(*a, **k):
            raise RuntimeError("news down")

        monkeypatch.setattr("requests.get", _boom)


def _fake_quote_and_eps():
    quote = {
        "601208": {
            "name": "东材科技", "price": 48.22, "pe_ttm": 119.73,
            "pe_static": 78.13, "pb": 8.03, "mcap_yi": 487.11,
            "float_mcap_yi": 487.11, "turnover_pct": 4.88,
            "change_pct": -4.57, "limit_up": 53.04, "limit_down": 43.40,
        }
    }
    eps = pd.DataFrame(
        {
            "year": ["2026", "2027", "2028"],
            "count": [12, 12, 12],
            "min": [0.55, 0.77, 0.96],
            "mean": [0.73, 1.22, 1.78],
            "max": [0.98, 2.15, 4.55],
        }
    )
    return quote, eps


def test_generate_report_charts_all_success(tmp_path, monkeypatch):
    quote, eps = _fake_quote_and_eps()
    _patch_data_sources(
        monkeypatch, ohlcv=_fake_ohlcv(), klines=_FAKE_KLINES,
        quote=quote, eps=eps,
        margin_rows=_FAKE_MARGIN_ROWS,
        lockup_history=_FAKE_LOCKUP_HISTORY,
        lockup_upcoming=[],
    )
    from web.report_charts import generate_report_charts

    charts, out_dir = generate_report_charts("601208", "2026-10-06", out_dir=tmp_path)

    assert set(charts) == {
        "技术分析报告", "市场情绪报告", "新闻舆情报告", "基本面报告",
        "游资追踪报告", "解禁/减持报告", "最终决策",
    }
    for path in charts.values():
        assert path.exists() and path.stat().st_size > 1000


def test_chart_failure_degrades_to_partial(tmp_path, monkeypatch):
    """六张图的数据源挂掉 → 只出剩余一张，绝不抛异常."""
    quote, eps = _fake_quote_and_eps()
    _patch_data_sources(
        monkeypatch, klines=_FAKE_KLINES, quote=quote, eps=eps,
        news=False,
    )
    from tradingagents.dataflows.a_stock import _common

    def _boom(*a, **k):
        raise RuntimeError("mootdx down")

    monkeypatch.setattr(_common, "_load_ohlcv_astock", _boom)
    monkeypatch.setattr(_common, "_ths_eps_forecast", _boom)

    from web.report_charts import generate_report_charts

    charts, out_dir = generate_report_charts("601208", "2026-10-06", out_dir=tmp_path)
    assert set(charts) == {"游资追踪报告"}


def test_generate_pdf_embeds_chart_and_cleans_tmp(tmp_path, monkeypatch):
    """PDF 里真实嵌入图片对象，导出后临时目录被清理."""
    try:
        _find_cjk_fonts()
    except PDFExportError as exc:
        pytest.skip(str(exc))

    # 造一张真 PNG
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    png = tmp_path / "fake_candles.png"
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    fig.savefig(png)
    plt.close(fig)

    chart_dir = tmp_path / "chart_dir"
    chart_dir.mkdir()
    kept_png = chart_dir / "candles.png"
    png.rename(kept_png)

    from web import report_charts

    monkeypatch.setattr(
        report_charts,
        "generate_report_charts",
        lambda *a, **k: ({"技术分析报告": kept_png}, chart_dir),
    )

    state = {
        "market_report": "# 技术分析\n- 收盘 48.22，跌破 10 日 EMA。",
        "final_trade_decision": "最终建议: Underweight。",
    }
    pdf_bytes = generate_pdf(state, "601208", "2026-10-06", "Underweight")

    assert pdf_bytes.startswith(b"%PDF-")
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = sum(len(page.get_images()) for page in doc)
    assert images >= 1
    doc.close()
    assert not chart_dir.exists()  # 临时目录已清理


def test_generate_pdf_without_charts_still_works(monkeypatch):
    """图表整体不可用时（返回空集）PDF 照常导出——回归保护."""
    try:
        _find_cjk_fonts()
    except PDFExportError as exc:
        pytest.skip(str(exc))

    from web import report_charts

    monkeypatch.setattr(
        report_charts,
        "generate_report_charts",
        lambda *a, **k: ({}, None),
    )

    state = {"market_report": "# 技术分析\n- 无图模式回归测试。"}
    pdf_bytes = generate_pdf(state, "600519", "2026-05-30", "HOLD")
    assert pdf_bytes.startswith(b"%PDF-")
