# -*- coding: utf-8 -*-
"""T3 阶段4: 跨窗口对照汇总（论文 T3 表的数据源）.

输入: results/baselines_rule_{signal_date}.json（阶段3a 规则基线, 含 TA 信号）
      results/b4_ml_{signal_date}.json（阶段3b 机器学习基线, 存在即并入, 缺则跳过）
输出: results/compare_t3.json + compare_t3.md（分窗口 + 跨窗聚合 + 成本敏感性）

口径: 方向化收益 = 多头取 ret / 空头取 -ret; 中性不占样本不扣成本;
净收益 = 方向化收益 - 2×单边费（一次开平仓）。
"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
STRATEGIES = ["ta", "b1_buyhold", "b2_ma", "b3_mom20", "b4_ml"]
LABELS = {
    "ta": "TradingAgents", "b1_buyhold": "B1 买入持有", "b2_ma": "B2 均线",
    "b3_mom20": "B3 动量", "b4_ml": "B4 LGBM+Alpha158",
}
FEES = (0.001, 0.0025)  # 单边费两档


def _agg(rows: list[dict]) -> dict:
    out = {}
    for s in STRATEGIES:
        scored = [r for r in rows if r.get(s) in ("bullish", "bearish")]
        if not scored:
            out[s] = {"scored": 0, "hits": 0, "hit_rate": None,
                      "avg_directed_ret": None}
            continue
        hits = [r for r in scored
                if (r[s] == "bullish" and r["ret"] > 0)
                or (r[s] == "bearish" and r["ret"] < 0)]
        avg = sum(r["ret"] if r[s] == "bullish" else -r["ret"]
                  for r in scored) / len(scored)
        out[s] = {
            "scored": len(scored), "hits": len(hits),
            "hit_rate": round(len(hits) / len(scored), 4),
            "avg_directed_ret": round(avg, 6),
            "avg_net_f001": round(avg - 2 * FEES[0], 6),
            "avg_net_f025": round(avg - 2 * FEES[1], 6),
        }
    return out


def main() -> None:
    windows: dict[str, list[dict]] = {}
    for f in sorted(RESULTS.glob("baselines_rule_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        key = f"{d['signal_date']}→{d['eval_date']}"
        rows = list(d["rows"])
        b4 = RESULTS / f"b4_ml_{d['signal_date']}.json"
        if b4.exists():  # B4 落地后自动并入
            b4d = json.loads(b4.read_text(encoding="utf-8"))
            by_t = {r["ticker"]: r for r in b4d["rows"]}
            for r in rows:
                if r["ticker"] in by_t:
                    r["b4_ml"] = by_t[r["ticker"]]["b4_ml"]
        windows[key] = rows

    if not windows:
        raise SystemExit("没有 baselines_rule_*.json, 先跑 baselines_rule.py")

    per_window = {k: _agg(v) for k, v in windows.items()}
    all_rows = [r for v in windows.values() for r in v]
    total = _agg(all_rows)

    lines = ["# T3 基线对照汇总", "",
             f"窗口数 {len(windows)} · 方向样本池 {sum(len(v) for v in windows.values())} 标的次 · "
             "hfq 后复权同源 · 方向判定与 T2 同口径", ""]
    for k, agg in per_window.items():
        lines.append(f"## 窗口 {k}")
        lines.append("")
        lines.append("| 策略 | 方向样本 | 命中 | 命中率 | 方向化均收益 | 净(费0.1%) | 净(费0.25%) |")
        lines.append("|---|---|---|---|---|---|---|")
        for s in STRATEGIES:
            a = agg[s]
            if a["scored"] == 0:
                lines.append(f"| {LABELS[s]} | 0 | - | - | - | - | - |")
                continue
            lines.append(
                f"| {LABELS[s]} | {a['scored']} | {a['hits']} | {a['hit_rate']:.0%} "
                f"| {a['avg_directed_ret']:+.2%} | {a['avg_net_f001']:+.2%} "
                f"| {a['avg_net_f025']:+.2%} |")
        lines.append("")
    lines.append("## 跨窗口聚合")
    lines.append("")
    lines.append("| 策略 | 方向样本 | 命中 | 命中率 | 方向化均收益 | 净(费0.1%) | 净(费0.25%) |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in STRATEGIES:
        a = total[s]
        if a["scored"] == 0:
            lines.append(f"| {LABELS[s]} | 0 | - | - | - | - | - |")
            continue
        lines.append(
            f"| {LABELS[s]} | {a['scored']} | {a['hits']} | {a['hit_rate']:.0%} "
            f"| {a['avg_directed_ret']:+.2%} | {a['avg_net_f001']:+.2%} "
            f"| {a['avg_net_f025']:+.2%} |")
    lines += ["", "> 样本量小（个位数方向样本），结论表述必须带 n；Hold 等中性信号不计入方向样本。", ""]

    md = "\n".join(lines)
    (RESULTS / "compare_t3.md").write_text(md, encoding="utf-8")
    (RESULTS / "compare_t3.json").write_text(
        json.dumps({"per_window": per_window, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)
    print(f"-> {RESULTS / 'compare_t3.md'}")


if __name__ == "__main__":
    main()
