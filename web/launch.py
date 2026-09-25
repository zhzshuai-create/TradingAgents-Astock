"""Launch the TradingAgents web UI via `tradingagents-web` command.

加 --with-journal 可同时拉起被 iframe 嵌入的 trade-journal (localhost:8502)。
两者约定为同级目录: <parent>/TradingAgents-astock 与 <parent>/trade-journal。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

JOURNAL_DIR = Path(__file__).resolve().parent.parent.parent / "trade-journal"
JOURNAL_PORT = 8502


def _start_journal() -> subprocess.Popen | None:
    app = JOURNAL_DIR / "app.py"
    if not app.exists():
        print(f"[warn] 未找到交易日志: {app}")
        print("       跳过。平台内『交易日志』页会给出手动启动引导。")
        return None
    print(f"[journal] 启动交易日志 -> http://localhost:{JOURNAL_PORT}")
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(app), "--server.headless", "true"],
        cwd=str(JOURNAL_DIR),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 A股多智能体平台 Web UI")
    parser.add_argument("--with-journal", action="store_true",
                        help="同时启动被 iframe 嵌入的交易日志 (8502)")
    args = parser.parse_args()

    journal_proc = _start_journal() if args.with_journal else None
    # 不串行等日志: 实测两服务自举各 ~1.0s, 并行拉起后平台首帧(点击后 ~2s)探活时
    # 日志早已监听; 即便探空也有 warning 引导 + iframe 重连兜底, 下次 rerun 自愈.
    app_path = Path(__file__).parent / "app.py"
    try:
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])
    finally:
        if journal_proc and journal_proc.poll() is None:
            journal_proc.terminate()


if __name__ == "__main__":
    main()
