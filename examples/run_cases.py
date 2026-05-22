"""Batch runner: analyse multiple A-stock tickers and save results to examples/cases/.

Usage:
    uv run python examples/run_cases.py          # run all cases
    uv run python examples/run_cases.py 688017   # run a single ticker
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# ── Config ───────────────────────────────────────────────────────────────────

CASES_DIR = Path(__file__).parent / "cases"
CASES_DIR.mkdir(parents=True, exist_ok=True)

TRADE_DATE = "2026-05-12"

# 10 tickers across different sectors
# fmt: off
TICKERS = {
    "688017": "绿的谐波 (科创板·谐波减速器)",
    "300750": "宁德时代 (创业板·动力电池)",
    "600519": "贵州茅台 (主板·白酒龙头)",
    "000858": "五粮液 (主板·白酒)",
    "300059": "东方财富 (创业板·互联网券商)",
    "601012": "隆基绿能 (主板·光伏)",
    "300760": "迈瑞医疗 (创业板·医疗器械)",
    "688981": "中芯国际 (科创板·芯片代工)",
    "002594": "比亚迪 (主板·新能源汽车)",
    "300124": "汇川技术 (创业板·工业自动化)",
}
# fmt: on


def build_config() -> dict:
    """Build the TradingAgents config for case runs."""
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "minimax"
    config["deep_think_llm"] = "MiniMax-M2.7"
    config["quick_think_llm"] = "MiniMax-M2.7-highspeed"
    config["data_vendors"] = {
        "core_stock_apis": "a_stock",
        "technical_indicators": "a_stock",
        "fundamental_data": "a_stock",
        "news_data": "a_stock",
        "signal_data": "a_stock",
    }
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"
    return config


def run_single(ticker: str, label: str, config: dict) -> None:
    """Run one ticker and save the decision to a markdown file."""
    print(f"\n{'=' * 60}")
    print(f"Analysing {ticker} — {label}")
    print(f"Trade date: {TRADE_DATE}")
    print(f"{'=' * 60}\n")

    start_time = time.time()
    ta = TradingAgentsGraph(debug=True, config=config)

    full_decision = ""
    try:
        final_state, decision = ta.propagate(ticker, TRADE_DATE)
        full_decision = final_state.get("final_trade_decision", "")
    except Exception as e:
        decision = f"ERROR: {e}"

    elapsed = time.time() - start_time

    # Save result — full decision + short signal
    out_path = CASES_DIR / f"{ticker}_{label.split('(')[0].strip()}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# {ticker} {label}\n\n")
        f.write(f"- **Trade Date**: {TRADE_DATE}\n")
        f.write(f"- **Run Time**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"- **Duration**: {elapsed:.0f}s ({elapsed / 60:.1f} min)\n")
        f.write(f"- **LLM**: MiniMax-M2.7 / M2.7-highspeed\n\n")
        f.write(f"## Signal: {decision}\n\n")
        if full_decision and full_decision != decision:
            f.write(f"## Full Analysis\n\n{full_decision}\n")

    print(f"\n✅ Saved to {out_path} ({elapsed:.0f}s)")

    # Also save a JSON summary for programmatic use
    summary_path = CASES_DIR / f"{ticker}_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "ticker": ticker,
                "label": label,
                "trade_date": TRADE_DATE,
                "run_time": datetime.now().isoformat(),
                "duration_seconds": round(elapsed),
                "signal": decision,
                "decision_preview": (full_decision or decision)[:2000],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def main() -> None:
    config = build_config()

    # Allow single ticker override from CLI
    if len(sys.argv) > 1:
        ticker = sys.argv[1]
        label = TICKERS.get(ticker, ticker)
        run_single(ticker, label, config)
        return

    # Run all
    print(f"Running {len(TICKERS)} cases...")
    for ticker, label in TICKERS.items():
        run_single(ticker, label, config)
        print(f"\n{'─' * 40}")

    print(f"\n{'=' * 60}")
    print(f"All {len(TICKERS)} cases complete. Results in {CASES_DIR}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
