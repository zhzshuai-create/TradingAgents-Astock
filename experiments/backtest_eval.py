# -*- coding: utf-8 -*-
"""T2 回测评测: 信号方向 vs 实际涨跌吻合度（纯数据计算，零 LLM 成本）.

扫描 experiments/results/run_*.json 中 trade_date == 信号日的成功运行，
用核心数据层拉取 信号日收盘 → 评估日收盘 的实际涨跌，输出吻合度统计。
命中规则：看多信号（Buy/Overweight 等）区间上涨=命中，看空反之；
Hold 等中性信号不参与方向命中统计。

用法：
    python experiments/backtest_eval.py                      # 默认信号日 2026-08-13
    python experiments/backtest_eval.py --signal-date 2026-08-13 --eval-date 2026-09-11
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

PROJ = Path(__file__).resolve().parents[1]
RESULTS = PROJ / "experiments" / "results"

sys.path.insert(0, str(PROJ))

BULL = {"buy", "overweight", "strong buy", "增持", "买入"}
BEAR = {"sell", "underweight", "reduce", "减持", "卖出"}


def signal_direction(signal: str) -> str:
    s = (signal or "").strip().lower()
    if any(k in s for k in BULL):
        return "bullish"
    if any(k in s for k in BEAR):
        return "bearish"
    return "neutral"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal-date", default="2026-08-13")
    ap.add_argument("--eval-date", default="2026-09-11")
    args = ap.parse_args()
    signal_date, eval_date = args.signal_date, args.eval_date

    from tradingagents.dataflows.a_stock import _common as core

    # 同一标的取最新一次成功运行
    latest: dict[str, dict] = {}
    for f in sorted(RESULTS.glob("run_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("trade_date") != signal_date or d.get("error") is not None:
            continue
        if d.get("signal", "N/A") in ("N/A", ""):
            continue
        latest[d["ticker"]] = d

    out = []
    for ticker, r in sorted(latest.items()):
        code = core._normalize_ticker(ticker)
        df = core._load_ohlcv_astock(code, eval_date)
        if df.empty:
            print(f"skip {ticker}: no price data")
            continue
        d0, d1 = pd_timestamp(signal_date), pd_timestamp(eval_date)
        w = df[(df["Date"] >= d0) & (df["Date"] <= d1)].sort_values("Date")
        if len(w) < 2:
            print(f"skip {ticker}: insufficient window data")
            continue
        p0, p1 = float(w.iloc[0]["Close"]), float(w.iloc[-1]["Close"])
        chg = (p1 - p0) / p0 * 100
        direction = signal_direction(r["signal"])
        if direction == "bullish":
            hit = chg > 0
        elif direction == "bearish":
            hit = chg < 0
        else:
            hit = None  # 中性信号不参与方向命中
        out.append({
            "ticker": ticker,
            "signal": r["signal"],
            "direction": direction,
            "close_signal_day": round(p0, 2),
            "close_eval_day": round(p1, 2),
            "change_pct": round(chg, 2),
            "hit": hit,
            "wall_seconds": r["wall_seconds"],
        })

    active = [o for o in out if o["hit"] is not None]
    hits = sum(1 for o in active if o["hit"])
    summary = {
        "signal_date": signal_date,
        "eval_date": eval_date,
        "n_total": len(out),
        "n_directional": len(active),
        "n_hit": hits,
        "hit_rate_pct": round(hits / len(active) * 100, 1) if active else None,
        "runs": out,
    }
    out_path = RESULTS / f"backtest_eval_{datetime.now():%Y%m%d-%H%M%S}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n回测样本 {len(out)} 只，方向性信号 {len(active)} 条，命中 {hits} 条"
          f"（命中率 {summary['hit_rate_pct']}%）")
    print(f"{'股票':<8}{'信号':<12}{'方向':<9}{'区间涨跌%':<10}{'命中'}")
    for o in out:
        hit_s = {True: "✓", False: "✗", None: "—"}.get(o["hit"], "—")
        print(f"{o['ticker']:<8}{o['signal']:<12}{o['direction']:<9}{o['change_pct']:<10}{hit_s}")
    print(f"\nsaved -> {out_path}")


def pd_timestamp(s):
    import pandas as pd

    return pd.to_datetime(s)


if __name__ == "__main__":
    main()
