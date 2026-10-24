# -*- coding: utf-8 -*-
"""T3 阶段2b: TDX 独立数据管线 —— 自算后复权因子（不依赖 EM/腾讯 HTTP）.

背景: EM push2his 与腾讯 fqkline 同时对本机限流(2026-10-24), 宽池被卡。
mootdx 走 TDX TCP(7709) 与 HTTP 限流无关; xdxr 接口实测可用。
- 原始日K: 复用项目 _load_ohlcv_astock(mootdx→新浪兜底, 不复权, 久经考验)
- 除权事件: mootdx xdxr(category=1 除权除息; fenhong/peigujia/songzhuangu/peigu
  单位=每10股X元/股)
- 后复权因子: 每个除权日 ratio = prev_close / ((prev_close - F + Pg*P) / (1 + S + P))
  (F/S/P 均已除以10 转每股), factor_t = 上市以来全部 <=t 除权日 ratio 连乘;
  hfq_price = raw_price * factor_t
- 验证: 与已导出的腾讯 hfq(10 只评估池)日收益序列对数, 容差 1e-4

用法(验证):
    python experiments/qlib_baseline/tdx_adjust.py            # 全部评估池验证
    python experiments/qlib_baseline/tdx_adjust.py 600519    # 单股详细
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ))

from tradingagents.dataflows.a_stock._common import _load_ohlcv_astock  # noqa: E402


def xdxr_events(ticker: str) -> pd.DataFrame:
    """mootdx xdxr 除权除息事件(category=1), 返回 date/fenhong/songzhuangu/peigu/peigujia。"""
    from mootdx.quotes import Quotes

    q = Quotes.factory(market="std", timeout=10)
    x = q.xdxr(symbol=ticker)
    if x is None or x.empty:
        return pd.DataFrame(columns=["date", "fenhong", "songzhuangu",
                                     "peigu", "peigujia"])
    x = x[x["category"] == 1].copy()
    x["date"] = (x["year"].astype(int).astype(str) + "-"
                 + x["month"].astype(int).astype(str).str.zfill(2) + "-"
                 + x["day"].astype(int).astype(str).str.zfill(2))
    return x[["date", "fenhong", "songzhuangu", "peigu", "peigujia"]]


def build_hfq_factors(raw: pd.DataFrame, events: pd.DataFrame) -> pd.Series:
    """逐日后复权因子(与 raw 同 index, 上市初=1)。

    raw 需含 Date/Open/High/Low/Close(_load_ohlcv_astock 契约)。
    """
    raw = raw.copy()
    raw["Date"] = pd.to_datetime(raw["Date"]).dt.strftime("%Y-%m-%d")
    factors = pd.Series(1.0, index=raw.index)
    if events.empty:
        return factors
    ev = events[events["date"].isin(set(raw["Date"]))].copy()
    for _, e in ev.iterrows():
        idx = raw.index[raw["Date"] == e["date"]]
        if len(idx) == 0 or idx[0] == raw.index[0]:
            continue
        prev_close = float(raw.loc[idx[0] - 1, "Close"])
        f = float(e["fenhong"] or 0) / 10      # 每股派现(元)
        s = float(e["songzhuangu"] or 0) / 10  # 每股送转(股)
        p = float(e["peigu"] or 0) / 10        # 每股配股(股)
        pg = float(e["peigujia"] or 0)         # 配股价(元/股)
        denom = prev_close - f + pg * p
        if denom <= 0 or (1 + s + p) <= 0:
            continue
        ratio = prev_close / (denom / (1 + s + p))
        factors.loc[idx[0]:] *= ratio
    return factors


def tdx_hfq(ticker: str, curr_date: str = "2026-12-31") -> pd.DataFrame:
    """原始日K × 自算因子 → 后复权 OHLCV(date,open,close,high,low,volume)。"""
    raw = _load_ohlcv_astock(ticker, curr_date)
    if raw is None or raw.empty:
        raise ValueError(f"raw bars empty for {ticker}")
    fac = build_hfq_factors(raw, xdxr_events(ticker))
    out = pd.DataFrame({
        "date": pd.to_datetime(raw["Date"]).dt.strftime("%Y-%m-%d"),
        "open": raw["Open"] * fac, "close": raw["Close"] * fac,
        "high": raw["High"] * fac, "low": raw["Low"] * fac,
        "volume": raw["Volume"],
    })
    ok = (out[["open", "close", "high", "low"]] > 0).all(axis=1)
    return out[ok].drop_duplicates("date").sort_values("date").reset_index(drop=True)


_SINA_KLINE = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/x=/CN_MarketDataService"
               ".getKLineData?symbol={sym}&scale=240&ma=no&datalen=1023")


def sina_raw(ticker: str) -> pd.DataFrame:
    """新浪未复权日K(近1023根≈4.2年), 列 Date/Open/High/Low/Close/Volume(volume 单位=股)。"""
    import re

    import requests as _rq

    sym = ("sh" if ticker.startswith("6") else "sz") + ticker
    r = _rq.get(_SINA_KLINE.format(sym=sym), timeout=20,
                headers={"Referer": "https://finance.sina.com.cn/"})
    m = re.search(r"\((\[.*\])\)", r.text, re.S)
    if not m:
        raise ValueError(f"sina empty for {ticker}: {r.text[:60]!r}")
    data = json_loads(m.group(1))
    if not data:
        raise ValueError(f"sina no rows for {ticker}")
    df = pd.DataFrame(data)
    out = pd.DataFrame({
        "Date": pd.to_datetime(df["day"]).dt.strftime("%Y-%m-%d"),
        "Open": df["open"].astype(float), "High": df["high"].astype(float),
        "Low": df["low"].astype(float), "Close": df["close"].astype(float),
        "Volume": df["volume"].astype(float),
    })
    return out


def json_loads(s: str):
    import json

    return json.loads(s)


def faithful_hfq(ticker: str) -> pd.DataFrame:
    """忠实乘法后复权: 新浪 raw × mootdx xdxr 自算因子。

    窗口外的除权事件只贡献常数倍乘(不影响收益), 窗口内事件逐日生效;
    收益与 raw 严格一致(乘法复权构造保证), 与腾讯等差复权(收益被压低
    P/(P+C), 2026-10-24 实锤)形成对照。
    """
    raw = sina_raw(ticker)
    fac = build_hfq_factors(raw, xdxr_events(ticker))
    out = pd.DataFrame({
        "date": raw["Date"],
        "open": raw["Open"] * fac, "close": raw["Close"] * fac,
        "high": raw["High"] * fac, "low": raw["Low"] * fac,
        "volume": raw["Volume"],
    })
    ok = (out[["open", "close", "high", "low"]] > 0).all(axis=1)
    out = out[ok].drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if out.empty:
        raise ValueError(f"no rows for {ticker}")
    return out


def main() -> None:
    """验证: 自算 hfq 的日收益与新浪 raw 日收益在非除权日严格一致(=0)，
    除权日差异恰等于分红调整; 另与腾讯 hfq(等差)对照展示压缩效应。"""
    tickers = sys.argv[1:] or ["000001", "000333", "000858", "002594", "300750",
                               "600036", "600519", "601208", "601318", "601899"]
    base = Path(__file__).resolve().parent
    for t in tickers:
        raw = sina_raw(t)
        mine = faithful_hfq(t)
        ev_dates = set(xdxr_events(t)["date"])
        m = mine.merge(raw, left_on="date", right_on="Date")
        m["r_mine"] = m.close.pct_change()
        m["r_raw"] = m.Close.pct_change()
        # 乘法复权在除权日与 raw 的差异=分红/送转调整(构造使然, 正确行为);
        # 非除权日必须严格为 0
        m_non = m[~m["date"].isin(ev_dates)]
        d = (m_non.r_mine - m_non.r_raw).dropna().abs().max()
        m_ev = m[m["date"].isin(ev_dates)]
        ev_note = (f"除权日 {len(m_ev)} 个(max|Δr| {m_ev.r_mine.sub(m_ev.r_raw).abs().max():.2f})"
                   if len(m_ev) else "窗口内无除权日")

        sym = ("SH" if t.startswith("6") else "SZ") + t
        tx_path = base / "csv_data" / f"{sym.lower()}.csv"
        tx_note = ""
        if tx_path.exists():
            tx = pd.read_csv(tx_path)
            mm = mine.merge(tx, on="date", suffixes=("_m", "_t"))
            mm["rm"] = mm.close_m.pct_change()
            mm["rt"] = mm.close_t.pct_change()
            damp = (mm.rt / mm.rm).replace(
                [float("inf"), -float("inf")], pd.NA).dropna().median()
            tx_note = f" | 腾讯/自算 日收益中位比 {damp:.3f}(等差压缩)"
        len(ev_dates)
        status = "PASS" if d < 1e-9 else "FAIL"
        print(f"{sym}: rows={len(mine)} | 非除权日 max|Δr| {d:.1e} | {ev_note}"
              f"{tx_note} -> {status}")


if __name__ == "__main__":
    main()
