"""最小修复包回归测试：三表解析 / PE 口径警示 / 记忆替换 / 北向停发护栏."""

import pytest


# ---------------------------------------------------------------------------
# 1. 新浪三表解析（getFinanceReport2022 实际返回结构）
# ---------------------------------------------------------------------------

_SINA_FIXTURE = {
    "result": {
        "data": {
            "report_list": {
                "20260630": {
                    "publish_date": "20260821",
                    "data": [
                        {"item_field": "BIZTOTINCO", "item_value": "3094871633.96"},
                        {"item_field": "PARENETP", "item_value": "311714541.87"},
                        {"item_field": "BASICEPS", "item_value": "0.31"},
                        {"item_field": "NULLFIELD", "item_value": None},
                    ],
                },
                "20251231": {
                    "publish_date": "20260423",
                    "data": [
                        {"item_field": "BIZTOTINCO", "item_value": "5181200000"},
                        {"item_field": "PARENETP", "item_value": "285000000"},
                    ],
                },
                "20240630": {
                    "publish_date": "20240820",
                    "data": [
                        {"item_field": "BIZTOTINCO", "item_value": "2431400000"},
                        {"item_field": "PARENETP", "item_value": "190000000"},
                    ],
                },
            }
        }
    }
}


class _FakeSinaResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _patch_sina(monkeypatch, payload):
    from tradingagents.dataflows.a_stock import fundamentals

    monkeypatch.setattr(
        fundamentals._requests,
        "get",
        lambda *args, **kwargs: _FakeSinaResponse(payload),
    )
    return fundamentals


def test_sina_statements_parse_report_list_shape(monkeypatch):
    """新版嵌套结构（report_list 字典）能解析出宽表且科目已重命名."""
    fundamentals = _patch_sina(monkeypatch, _SINA_FIXTURE)
    df = fundamentals._get_financial_report_sina("601208", "利润表", "quarterly")

    assert not df.empty
    assert list(df["报告期"]) == ["2026-06-30", "2025-12-31", "2024-06-30"]
    assert "归母净利润" in df.columns
    row = df[df["报告期"] == "2026-06-30"].iloc[0]
    assert row["归母净利润"] == pytest.approx(311714541.87)
    assert row["披露日"] == "2026-08-21"
    # 全空列（NULLFIELD）必须被剔除
    assert "NULLFIELD" not in df.columns


def test_sina_statements_annual_filter(monkeypatch):
    """annual 口径只保留报告期 12-31 的行."""
    fundamentals = _patch_sina(monkeypatch, _SINA_FIXTURE)
    df = fundamentals._get_financial_report_sina("601208", "利润表", "annual")
    assert list(df["报告期"]) == ["2025-12-31"]


def test_sina_statements_curr_date_blocks_unpublished(monkeypatch):
    """curr_date 按披露日过滤：报告期早但未披露的报表不可见（防未来函数）."""
    fundamentals = _patch_sina(monkeypatch, _SINA_FIXTURE)
    # 2026-06-01 时点：2026 中报报告期 06-30 已过但 08-21 才披露 → 不可见
    df = fundamentals._get_financial_report_sina(
        "601208", "利润表", "quarterly", curr_date="2026-06-01"
    )
    assert list(df["报告期"]) == ["2025-12-31", "2024-06-30"]


def test_sina_statements_old_shape_returns_empty(monkeypatch):
    """旧版行列表结构 / 空数据 → 空 DataFrame，由调用方报 No data found."""
    fundamentals = _patch_sina(monkeypatch, {"result": {"data": {}}})
    df = fundamentals._get_financial_report_sina("601208", "利润表", "quarterly")
    assert df.empty


def test_sina_statement_tools_render_csv(monkeypatch):
    """工具层输出 CSV 文本，带单位与来源标注."""
    fundamentals = _patch_sina(monkeypatch, _SINA_FIXTURE)
    out = fundamentals.get_income_statement("601208")
    assert "No income statement" not in out
    assert "归母净利润" in out
    assert "# Units: CNY yuan (元)" in out


# ---------------------------------------------------------------------------
# 2. PE 口径警示（腾讯 v52 是最新定期报告年化，非上年报静态 PE）
# ---------------------------------------------------------------------------


def test_get_fundamentals_flags_interim_annualized_pe(monkeypatch):
    """get_fundamentals 输出必须带口径警示，字段更名为 Interim-annualized."""
    from tradingagents.dataflows.a_stock import fundamentals

    fake_quote = {
        "601208": {
            "name": "东材科技",
            "price": 48.22,
            "pe_ttm": 119.73,
            "pe_static": 78.13,
            "pb": 8.03,
            "mcap_yi": 487.11,
            "float_mcap_yi": 487.11,
            "turnover_pct": 4.88,
            "change_pct": -4.57,
            "limit_up": 53.04,
            "limit_down": 43.40,
        }
    }
    monkeypatch.setattr(
        fundamentals._common, "_tencent_quote", lambda codes: fake_quote
    )
    monkeypatch.setattr(
        fundamentals._common,
        "_get_mootdx_client",
        lambda: (_ for _ in ()).throw(RuntimeError("skip")),
    )
    monkeypatch.setattr(
        fundamentals._common,
        "_em_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("skip")),
    )
    monkeypatch.setattr(
        fundamentals._common,
        "_ths_eps_forecast",
        lambda code: (_ for _ in ()).throw(RuntimeError("skip")),
    )

    out = fundamentals.get_fundamentals("601208")

    assert "PE (Interim-annualized): 78.13" in out
    assert "PE (Static)" not in out
    assert "NOT a last-fiscal-year static PE" in out
    assert "use get_income_statement" in out


# ---------------------------------------------------------------------------
# 3. 记忆条目：同键重跑决策变化 → 替换旧 pending 条目
# ---------------------------------------------------------------------------

_DECISION_BUY = "**Rating**: Buy\n\n在 46.5-47 元建立试探性仓位。"
_DECISION_UNDERWEIGHT = "**Rating**: Underweight\n\n减持至 60-70%。"


def _make_log(tmp_path):
    from tradingagents.agents.utils.memory import TradingMemoryLog

    return TradingMemoryLog({"memory_log_path": str(tmp_path / "mem.md")})


def test_store_decision_replaces_changed_rerun(tmp_path):
    """同键重跑且决策文本变化：替换旧条目而非静默跳过."""
    log = _make_log(tmp_path)
    log.store_decision("601208", "2026-10-06", _DECISION_BUY)
    log.store_decision("601208", "2026-10-06", _DECISION_UNDERWEIGHT)

    entries = log.load_entries()
    assert len(entries) == 1
    assert entries[0]["rating"] == "Underweight"
    assert "Underweight" in entries[0]["decision"]
    assert "试探性仓位" not in entries[0]["decision"]


def test_store_decision_idempotent_still_holds(tmp_path):
    """同键重跑且决策文本相同：保持幂等（不产生重复条目）."""
    log = _make_log(tmp_path)
    log.store_decision("601208", "2026-10-06", _DECISION_UNDERWEIGHT)
    log.store_decision("601208", "2026-10-06", _DECISION_UNDERWEIGHT)
    assert len(log.load_entries()) == 1


def test_store_decision_replace_keeps_other_entries(tmp_path):
    """替换只影响同键条目，其他日期/标的条目原样保留."""
    log = _make_log(tmp_path)
    log.store_decision("600519", "2026-10-01", _DECISION_BUY)
    log.store_decision("601208", "2026-10-06", _DECISION_BUY)
    log.store_decision("601208", "2026-10-06", _DECISION_UNDERWEIGHT)

    entries = log.load_entries()
    assert len(entries) == 2
    by_key = {(e["ticker"], e["date"]): e for e in entries}
    assert by_key[("600519", "2026-10-01")]["rating"] == "Buy"
    assert by_key[("601208", "2026-10-06")]["rating"] == "Underweight"


# ---------------------------------------------------------------------------
# 4. 北向停发护栏：冻结值不给方向信号、不落盘
# ---------------------------------------------------------------------------

_DAYCHART_FROZEN = {
    "time": ["09:35", "09:40", "09:45"],
    "hgt": ["-9.28", "-9.28", "-9.28"],
    "sgt": ["379.75", "379.75", "379.75"],
}


class _FakeHsgtResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _patch_northbound(monkeypatch, payload, cached_tail, save_calls):
    from tradingagents.dataflows.a_stock import signals

    monkeypatch.setattr(
        "requests.get", lambda *args, **kwargs: _FakeHsgtResponse(payload)
    )
    monkeypatch.setattr(signals, "_load_northbound_history", lambda n=20: cached_tail)
    monkeypatch.setattr(
        signals, "_save_northbound_snapshot", lambda *args: save_calls.append(args)
    )


def test_northbound_frozen_value_suppresses_signal(monkeypatch):
    """返回值与缓存快照一致（非今日）→ 冻结警告、无方向信号、不落盘."""
    save_calls: list = []
    _patch_northbound(
        monkeypatch, _DAYCHART_FROZEN, [("2026-09-30", -9.28, 379.75)], save_calls
    )
    from tradingagents.dataflows.a_stock import signals

    out = signals.get_northbound_flow("2026-10-06")

    assert "数据停发警示" in out
    assert "冻结值警告" in out
    assert "Signal: Net northbound" not in out
    assert "方向信号不可用" in out
    assert save_calls == []


def test_northbound_fresh_value_keeps_signal(monkeypatch):
    """返回值与缓存不同（真实更新）→ 正常给方向信号."""
    save_calls: list = []
    _patch_northbound(
        monkeypatch, _DAYCHART_FROZEN, [("2026-09-30", -50.00, 100.00)], save_calls
    )
    from tradingagents.dataflows.a_stock import signals

    out = signals.get_northbound_flow("2026-10-06")

    assert "冻结值警告" not in out
    assert "Signal: Net northbound INFLOW (bullish)" in out


def test_northbound_notice_always_present(monkeypatch):
    """无论冻结与否，停发警示都必须出现在输出头部."""
    save_calls: list = []
    _patch_northbound(monkeypatch, _DAYCHART_FROZEN, [], save_calls)
    from tradingagents.dataflows.a_stock import signals

    out = signals.get_northbound_flow("2026-10-06")
    assert "数据停发警示" in out


# ---------------------------------------------------------------------------
# 5. 防回归：无数据时仍返回明确的 No data found（不抛异常）
# ---------------------------------------------------------------------------


def test_statement_tools_return_no_data_marker_on_empty(monkeypatch):
    fundamentals = _patch_sina(monkeypatch, {"result": {"data": {}}})
    assert "No balance sheet data" in fundamentals.get_balance_sheet("601208")
    assert "No cash flow data" in fundamentals.get_cashflow("601208")
    assert "No income statement data" in fundamentals.get_income_statement("601208")
