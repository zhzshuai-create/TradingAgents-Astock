"""Launch the TradingAgents web UI via `tradingagents-web` command.

加 --with-journal 可同时拉起被 iframe 嵌入的 trade-journal (localhost:8502)。
启动/探活逻辑在 web/journal_service.py, 与平台内交易日志页的懒加载共用。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from web.journal_service import JOURNAL_DIR, JOURNAL_PORT, start_journal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 A股多智能体平台 Web UI")
    parser.add_argument("--with-journal", action="store_true",
                        help="同时启动被 iframe 嵌入的交易日志 (8502)")
    args = parser.parse_args()

    journal_proc = None
    if args.with_journal:
        print(f"[journal] 启动交易日志 -> http://localhost:{JOURNAL_PORT}")
        journal_proc = start_journal()
        if journal_proc is None:
            print(f"[warn] 未找到交易日志: {JOURNAL_DIR / 'app.py'}")
            print("       跳过。平台内『交易日志』页会给出手动启动引导。")
    # 不串行等日志: 实测两服务自举各 ~1.0s, 并行拉起后平台首帧(点击后 ~2s)探活时
    # 日志早已监听; 即便探空也有 warning 引导 + iframe 重连兜底, 下次 rerun 自愈.
    app_path = Path(__file__).parent / "app.py"
    try:
        # M4: 显式固定 8501 — 不传端口时 Streamlit 遇占用会顺延到 8502, 撞上同命令刚拉起的日志服务
        subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path), "--server.port", "8501"])
    finally:
        if journal_proc and journal_proc.poll() is None:
            journal_proc.terminate()


if __name__ == "__main__":
    main()
