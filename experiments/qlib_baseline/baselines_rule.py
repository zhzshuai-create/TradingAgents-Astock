# -*- coding: utf-8 -*-
"""T3 阶段3(规则基线): B1 买入持有 / B2 均线 / B3 动量 vs TradingAgents 信号.

统一协议(T2 同源): 信号日收盘 → 评估日收盘; 方向判定复用
backtest_eval.signal_direction(Buy/Overweight=多, Sell/Underweight=空, Hold 中性);
价格 = csv_data 后复权 hfq 序列(全策略同源, T2 用的是不复权价, T3 统一改 hfq)。
命中规则: 多头方向区间上涨=命中, 空头反之; 中性不参与命中统计。

用法:
    python experiments/qlib_baseline/baselines_rule.py                # T2 默认口径
    python experiments/qlib_baseline/baselines_rule.py --signal-date 2026-08-13 --eval-date 2026-09-11
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
PROJ = BASE.parents[1]
RESULTS = PROJ / "experiments" / "results"
sys.path.insert(0, str(PROJ))

from experiments.backtest_eval import signal_direction  # noqa: E402  T2 同一口径


def load_hfq(ticker: str) -> pd.DataFrame:
    sym = ("SH" if ticker.startswith("6") else "SZ") + ticker
    f = BASE / "csv_data" / f"{sym.lower()}.csv"
    if not f.exists():
        raise FileNotFoundError(f"缺 {sym} 的 hfq 数据, 先跑 export_csv.py --pool eval")
    return pd.read_csv(f)


def close_at(df: pd.DataFrame, day: str) -> tuple[float, str]:
    """<=day 的最近收盘价(信号日若逢休市, 取当时可得的最近收盘, 如 10-06 国庆休市取 9-30)。"""
    sub = df[df["date"] <= day]
    if sub.empty:
        raise ValueError(f"{day} 之前无数据(首日 {df['date'].iloc[0]})")
    return float(sub["close"].iloc[-1]), str(sub["date"].iloc[-1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal-date", default="2026-08-13")
    ap.add_argument("--eval-date", default="2026-09-11")
    args = ap.parse_args()
    sd, ed = args.signal_date, args.eval_date

    # 评估集: 该信号日全部成功运行(同 T2), 同标的多跑取最新
    latest: dict[str, dict] = {}
    for f in sorted(RESULTS.glob("run_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("trade_date") != sd or d.get("error") is not None:
            continue
        if d.get("signal", "N/A") in ("N/A", ""):
            continue
        latest[d["ticker"]] = d

    rows: list[dict] = []
    for ticker, run in sorted(latest.items()):
        df = load_hfq(ticker)
        p0, d0 = close_at(df, sd)
        p1, d1 = close_at(df, ed)
        ret = p1 / p0 - 1

        idx = df.index[df["date"] == d0][0]
        closes = df["close"]
        ma5 = closes.iloc[idx - 4: idx + 1].mean()
        ma20 = closes.iloc[idx - 19: idx + 1].mean()
        mom20 = p0 / float(closes.iloc[idx - 20]) - 1

        rows.append({
            "ticker": ticker,
            "signal_date": sd, "price_date": d0, "eval_date": ed,
            "eval_price_date": d1, "ret": round(ret, 6),
            "ta": signal_direction(run["signal"]),
            "b1_buyhold": "bullish",
            "b2_ma": "bullish" if ma5 > ma20 else "bearish",
            "b3_mom20": "bullish" if mom20 > 0 else "bearish",
            "_ma5": round(ma5, 3), "_ma20": round(ma20, 3), "_mom20": round(mom20, 4),
        })

    strategies = ["ta", "b1_buyhold", "b2_ma", "b3_mom20"]
    print(f"\n评估窗口: {sd} → {ed}（{len(rows)} 标的, hfq 后复权同源）\n")
    hdr = f"{'ticker':8}" + "".join(f"{s:>12}" for s in strategies) + f"{'ret':>10}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        cells = ""
        for s in strategies:
            d = r[s]
            mark = ""
            if d == "bullish":
                mark = "✓" if r["ret"] > 0 else "✗"
            elif d == "bearish":
                mark = "✓" if r["ret"] < 0 else "✗"
            cells += f"{d[:6] + mark:>12}"
        print(f"{r['ticker']:8}{cells}{r['ret']:>+10.2%}")

    print()
    summary = {}
    for s in strategies:
        scored = [r for r in rows if r[s] in ("bullish", "bearish")]
        hits = [r for r in scored
                if (r[s] == "bullish" and r["ret"] > 0)
                or (r[s] == "bearish" and r["ret"] < 0)]
        avg = (sum(r["ret"] if r[s] == "bullish" else -r["ret"] for r in scored)
               / len(scored)) if scored else float("nan")
        summary[s] = {
            "scored": len(scored), "neutral": len(rows) - len(scored),
            "hits": len(hits), "hit_rate": round(len(hits) / len(scored), 4) if scored else None,
            "avg_directed_ret": round(avg, 6) if scored else None,
        }
        print(f"  {s:>10}: 方向样本 {len(scored)}/{len(rows)}, 命中 {len(hits)}, "
              f"命中率 {summary[s]['hit_rate']:.0%}" if scored else f"  {s:>10}: 全中性")
    print("\n  (avg_directed_ret = 方向化平均收益: 多头取 ret, 空头取 -ret)")

    out = BASE / "results"
    out.mkdir(exist_ok=True)
    payload = {"signal_date": sd, "eval_date": ed, "data": "csv_data hfq(后复权)",
               "rows": rows, "summary": summary}
    fname = out / f"baselines_rule_{sd}.json"  # 按信号日命名, 多窗口并存
    fname.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"  -> {fname}")


if __name__ == "__main__":
    main()
