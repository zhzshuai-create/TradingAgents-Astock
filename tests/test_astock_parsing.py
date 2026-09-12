"""Offline unit tests for a_stock parsing helpers (tradingagents.dataflows.a_stock._common).

These cover the pure logic most likely to break when vendor APIs change shape:
ticker normalization, OHLCV date normalization/merge/supplement-decision, and the
Tencent quote payload parser.
"""

import io
from urllib.error import URLError

import pandas as pd
import pytest

from tradingagents.dataflows.a_stock import _common


pytestmark = pytest.mark.unit


# ── ticker normalization ─────────────────────────────────────────────────


class TestNormalizeTicker:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("688017", "688017"),
            ("SH688017", "688017"),
            ("688017.SH", "688017"),
            ("sh688017", "688017"),
            ("600379 ", "600379"),
            ("600379.sz", "600379"),
            ("BJ832000", "832000"),
        ],
    )
    def test_formats(self, raw, expected):
        assert _common._normalize_ticker(raw) == expected


class TestGetPrefix:
    @pytest.mark.parametrize(
        "code,prefix",
        [("600379", "sh"), ("688017", "sh"), ("900901", "sh"),
         ("832000", "bj"), ("000858", "sz"), ("300750", "sz")],
    )
    def test_prefix(self, code, prefix):
        assert _common._get_prefix(code) == prefix


class TestResolveTicker:
    def test_pure_code_passthrough(self):
        assert _common.resolve_ticker("SH600379") == "600379"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _common.resolve_ticker("   ")


# ── OHLCV date normalization / merge / supplement decision ───────────────


def _df(dates, close=10.0):
    return pd.DataFrame({
        "Date": pd.to_datetime(dates),
        "Open": close, "High": close, "Low": close, "Close": close,
        "Volume": 100,
    })


class TestNormalizeOhlcvDates:
    def test_strips_intraday_time(self):
        df = _df(["2026-06-10 15:00:00"])
        out = _common._normalize_ohlcv_dates(df)
        assert out["Date"].iloc[0] == pd.Timestamp("2026-06-10")

    def test_drops_invalid_dates(self):
        df = pd.DataFrame({
            "Date": ["2026-06-10", "not-a-date"],
            "Close": [1.0, 2.0],
        })
        out = _common._normalize_ohlcv_dates(df)
        assert len(out) == 1

    def test_empty_and_none_passthrough(self):
        assert _common._normalize_ohlcv_dates(None) is None
        assert _common._normalize_ohlcv_dates(pd.DataFrame()).empty


class TestNeedsSinaSupplement:
    def test_stale_when_last_date_before_target(self):
        df = _df(["2026-06-10"])
        assert _common._needs_sina_supplement(df, "2026-06-11") is True

    def test_fresh_when_last_date_equals_target(self):
        df = _df(["2026-06-11"])
        assert _common._needs_sina_supplement(df, "2026-06-11") is False

    def test_no_target_means_no_supplement(self):
        df = _df(["2026-06-10"])
        assert _common._needs_sina_supplement(df, None) is False

    def test_empty_frame_needs_supplement(self):
        assert _common._needs_sina_supplement(pd.DataFrame(), "2026-06-11") is True


class TestMergeOhlcv:
    def test_supplement_wins_on_duplicate_dates(self):
        primary = _df(["2026-06-10"], close=50.0)
        supplement = _df(["2026-06-10", "2026-06-11"], close=57.0)
        merged = _common._merge_ohlcv(primary, supplement)
        assert len(merged) == 2
        row10 = merged.loc[merged["Date"] == pd.Timestamp("2026-06-10")]
        assert row10["Close"].item() == 57.0  # supplement preferred

    def test_sorted_by_date(self):
        merged = _common._merge_ohlcv(_df(["2026-06-11"]), _df(["2026-06-10"]))
        assert list(merged["Date"]) == [pd.Timestamp("2026-06-10"), pd.Timestamp("2026-06-11")]

    def test_both_empty_returns_empty_with_columns(self):
        merged = _common._merge_ohlcv(pd.DataFrame(), pd.DataFrame())
        assert merged.empty
        assert list(merged.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]


# ── Tencent quote payload parser ─────────────────────────────────────────


def _tencent_payload(code: str, name: str) -> str:
    """Fake qt.gtimg.cn response line with values at their real indexes."""
    vals = [""] * 60
    vals[1], vals[2] = name, code
    for idx, val in [
        (3, "57.47"), (4, "53.45"), (5, "54.00"),  # price/last_close/open
        (31, "4.02"), (32, "7.52"),                # change_amt/change_pct
        (33, "58.80"), (34, "52.96"),              # high/low
        (37, "205219"), (38, "1.85"),              # amount_wan/turnover
        (39, "25.3"), (43, "10.9"),                # pe_ttm/amplitude
        (44, "2100.5"), (45, "2100.5"), (46, "5.6"),  # mcap/float_mcap/pb
        (47, "58.80"), (48, "48.11"),              # limit_up/limit_down
        (49, "2.1"), (52, "24.8"),                 # vol_ratio/pe_static
    ]:
        vals[idx] = val
    return f'v_sh{code}="{"~".join(vals)}";'


class TestTencentQuoteParsing:
    def _run(self, payload, code="000858"):
        class _FakeResp:
            def read(self):
                return payload.encode("gbk")

        monkey = pytest.MonkeyPatch()
        monkey.setattr(
            _common.urllib.request, "urlopen", lambda req, timeout=10: _FakeResp()
        )
        try:
            return _common._tencent_quote([code])
        finally:
            monkey.undo()

    def test_full_field_extraction(self):
        result = self._run(_tencent_payload("000858", "五粮液"))
        assert "000858" in result
        q = result["000858"]
        assert q["name"] == "五粮液"
        assert q["price"] == 57.47
        assert q["last_close"] == 53.45
        assert q["change_pct"] == 7.52
        assert q["change_amt"] == 4.02
        assert q["high"] == 58.80
        assert q["low"] == 52.96
        assert q["amount_wan"] == 205219.0
        assert q["turnover_pct"] == 1.85
        assert q["pe_ttm"] == 25.3
        assert q["amplitude_pct"] == 10.9
        assert q["mcap_yi"] == 2100.5
        assert q["float_mcap_yi"] == 2100.5
        assert q["pb"] == 5.6
        assert q["limit_up"] == 58.80
        assert q["limit_down"] == 48.11
        assert q["vol_ratio"] == 2.1
        assert q["pe_static"] == 24.8

    def test_skips_malformed_lines(self):
        result = self._run('garbage-line;v_pv_none="1";' + _tencent_payload("000858", "五粮液"))
        assert set(result.keys()) == {"000858"}

    def test_network_error_propagates(self):
        def _boom(req, timeout=10):
            raise URLError("down")

        monkey = pytest.MonkeyPatch()
        monkey.setattr(_common.urllib.request, "urlopen", _boom)
        try:
            with pytest.raises(URLError):
                _common._tencent_quote(["000858"])
        finally:
            monkey.undo()
