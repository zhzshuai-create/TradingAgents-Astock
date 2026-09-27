"""trade-journal 服务的路径解析/探活/启动/等就绪 — launch.py 与交易日志页共用的单一知识点.

约定两仓库为同级目录: <parent>/TradingAgents-astock* 与 <parent>/trade-journal.
日志仓库改入口或端口时只改这里.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

JOURNAL_DIR = Path(__file__).resolve().parent.parent.parent / "trade-journal"
JOURNAL_HOST = "localhost"
JOURNAL_PORT = 8502
JOURNAL_URL = f"http://{JOURNAL_HOST}:{JOURNAL_PORT}"


def journal_alive() -> bool:
    """探测 8502 上的交易日志是否在跑 (先 TCP 再取健康端点, 短超时)."""
    try:
        with socket.create_connection((JOURNAL_HOST, JOURNAL_PORT), timeout=0.5):
            pass
    except OSError:
        return False
    # M3: DEV_LOG:553 记录过本机 loopback 假 200/假失败怪象 — 健康端点异常时
    # 间隔复测一次再下结论, 单探宽判会跳过启动直接嵌 iframe 得白屏
    for _ in range(2):
        try:
            with urllib.request.urlopen(f"{JOURNAL_URL}/_stcore/health", timeout=1.0) as r:
                return r.status == 200
        except Exception:
            time.sleep(1.5)
    # 两次都拿不到 200: TCP 却通 — 进程在但服务未就绪, 让调用方走拉起/等待路径
    return False


def start_journal() -> subprocess.Popen | None:
    """拉起 trade-journal 子进程; 仓库不存在时返回 None, 由调用方决定提示方式."""
    app = JOURNAL_DIR / "app.py"
    if not app.exists():
        return None
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(app),
         "--server.headless", "true", "--server.port", str(JOURNAL_PORT)],
        cwd=str(JOURNAL_DIR),
    )


def wait_ready(timeout: float = 12.0, poll: float = 0.3) -> bool:
    """等健康端点就绪. 轮 2 教训: 本机 loopback 会出现伪单次 200, 须两次且间隔 >=150ms."""
    deadline = time.monotonic() + timeout
    first_ok = -1.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{JOURNAL_URL}/_stcore/health", timeout=1.0) as r:
                if r.status == 200:
                    now = time.monotonic()
                    if first_ok >= 0 and now - first_ok >= 0.15:
                        return True
                    first_ok = now
        except Exception:
            first_ok = -1.0
        time.sleep(poll)
    return False
