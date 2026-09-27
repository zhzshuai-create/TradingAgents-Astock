"""单次分析实验脚本 — 串行 vs 并行性能对比 & 回测数据采集.

铁律：
1. 对项目仓库只读：运行前后各做一次 git HEAD + 工作区状态校验，
   任何变更立即报错并写日志。
2. 结果文件带时间戳命名，绝不覆盖；每次运行追加登记到 manifest.csv。
3. 结果 JSON 自带完整元数据（配置/模型/git 版本），保证可复现。

模型配置从仓库根目录 .env 读取（LLM_PROVIDER / DEEP_THINK_LLM /
QUICK_THINK_LLM / BACKEND_URL），与 Web UI 使用同一套配置入口。

用法：
    python experiments/run_analysis_once.py --ticker 000858 --date 2026-09-11 --mode serial
    python experiments/run_analysis_once.py --ticker 000858 --date 2026-09-11 --mode parallel
    TA_PARALLEL_ANALYSTS=1 python experiments/run_analysis_once.py ...   # 与 --mode parallel 等效
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
RESULTS = PROJ / "experiments" / "results"
MANIFEST = RESULTS / "manifest.csv"
RUN_LOG = RESULTS / "experiment_log.md"

sys.path.insert(0, str(PROJ))

FIELDS = ["ticker", "date", "mode", "wall_seconds", "llm_calls", "tool_calls",
          "tokens_in", "tokens_out", "signal", "git_head", "result_file", "ran_at"]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(PROJ), *args], capture_output=True, text=True
    ).stdout.strip()


def repo_state() -> dict:
    return {"head": git("rev-parse", "HEAD"), "dirty": git("status", "--porcelain")}


def log(level: str, msg: str) -> None:
    line = f"- [{datetime.now():%Y-%m-%d %H:%M}] [{level}] {msg}"
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--date", required=True, help="交易日 YYYY-MM-DD")
    ap.add_argument("--mode", choices=["serial", "parallel"], required=True)
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv(PROJ / ".env")

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from cli.stats_handler import StatsCallbackHandler

    before = repo_state()

    config = {
        **DEFAULT_CONFIG,
        "parallel_analysts": args.mode == "parallel",
        "llm_provider": os.getenv("LLM_PROVIDER", "deepseek"),
        "deep_think_llm": os.getenv("DEEP_THINK_LLM", "deepseek-chat"),
        "quick_think_llm": os.getenv("QUICK_THINK_LLM", "deepseek-chat"),
        "backend_url": os.getenv("BACKEND_URL") or None,
    }

    stats = StatsCallbackHandler()
    t0 = time.perf_counter()
    signal = "N/A"
    error = None
    node_seq: list[str] = []
    try:
        graph = TradingAgentsGraph(debug=False, config=config, callbacks=[stats])
        init_state, stream_args, _ = graph.prepare_graph_run(
            args.ticker, args.date, callbacks=[stats]
        )
        # 推理型模型的分析师工具循环步数多于常规对话模型，默认 100 步可能不够用。
        # 注意 recursion_limit 嵌套在 args["config"] 内（LangGraph 运行时配置）
        stream_args["config"]["recursion_limit"] = int(
            os.getenv("RECURSION_LIMIT", "300")
        )
        last_chunk = {}
        # 双通道: updates 记录节点执行序列(诊断), values 保留完整终态给 finalize
        stream_args["stream_mode"] = ["updates", "values"]
        for mode, payload in graph.graph.stream(init_state, **stream_args):
            if mode == "updates":
                for node_name in payload:
                    node_seq.append(node_name)
            elif mode == "values":
                last_chunk = payload
        if not last_chunk:
            raise RuntimeError("分析没有返回任何结果")
        signal = graph.finalize_graph_run(args.ticker, args.date, last_chunk)
    except Exception as exc:  # noqa: BLE001 — 实验脚本需要捕获一切以记录日志
        import traceback

        error = f"{type(exc).__name__}: {exc}"
        log(
            "ERROR",
            f"{args.ticker} {args.date} {args.mode} 运行失败：{error}\n"
            f"节点执行序列(最后15个)：{node_seq[-15:]}\n"
            f"TRACEBACK:\n{traceback.format_exc()}",
        )
    wall = time.perf_counter() - t0
    after = repo_state()

    # ── 源代码保护校验 ──
    if before != after:
        log("ERROR", f"项目仓库在运行期间发生变化！before={before} after={after}")
        return 2
    if after["dirty"]:
        log("WARN", f"项目仓库工作区不干净（非本次运行造成？）：\n{after['dirty']}")

    s = stats.get_stats()
    ran_at = f"{datetime.now():%Y%m%d-%H%M%S}"
    result_file = f"run_{ran_at}_{args.ticker}_{args.mode}.json"
    result = {
        "ticker": args.ticker,
        "trade_date": args.date,
        "mode": args.mode,
        "wall_seconds": round(wall, 1),
        "llm_calls": s.get("llm_calls"),
        "tool_calls": s.get("tool_calls"),
        "tokens_in": s.get("tokens_in"),
        "tokens_out": s.get("tokens_out"),
        "signal": signal,
        "error": error,
        "git_head": after["head"],
        "repo_dirty_after": bool(after["dirty"]),
        "ran_at": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "models": {
            "provider": config.get("llm_provider"),
            "deep_think_llm": config.get("deep_think_llm"),
            "quick_think_llm": config.get("quick_think_llm"),
        },
        "parallel_analysts": config["parallel_analysts"],
    }
    out = RESULTS / result_file
    assert not out.exists(), "结果文件重名——时间戳碰撞，检查时钟"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if not MANIFEST.exists():
        MANIFEST.write_text(",".join(FIELDS) + "\n", encoding="utf-8")
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            args.ticker, args.date, args.mode, result["wall_seconds"],
            s.get("llm_calls"), s.get("tool_calls"), s.get("tokens_in"),
            s.get("tokens_out"), signal, after["head"], result_file, result["ran_at"],
        ])

    log(
        "ERROR" if error else "INFO",
        f"{args.ticker} {args.date} {args.mode}: wall={wall:.0f}s "
        f"llm={s.get('llm_calls')} signal={signal} -> {result_file}"
        + (f" ERROR={error}" if error else ""),
    )
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())
