"""轮 4 走查: 8502 冷态下进平台日志页, 验证懒加载自动拉起 + iframe 接入.

预检 8502/平台端口必须空闲; 测试结束 terminate 平台进程, 但被拉起的日志进程
按"留着下次秒开"策略不带走 —— 收尾时自行清理 8502.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(os.environ.get("ASTOCK_REPO") or Path(__file__).resolve().parents[2])
OUT = Path.cwd()  # 证据截图落运行目录, 不污染仓库
PORT = 8503
PLATFORM = f"http://localhost:{PORT}/"
HEALTH_8502 = "http://localhost:8502/_stcore/health"


def listening(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    assert not listening(8502), "预检失败: 8502 已有服务, 无法验证冷启动拉起"
    assert not listening(PORT), f"预检失败: {PORT} 被占用"

    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(REPO / "web" / "app.py"),
         "--server.port", str(PORT), "--server.headless", "true"],
        cwd=str(REPO),
    )
    deadline = time.time() + 60
    while time.time() < deadline and not listening(PORT):
        time.sleep(0.5)
    assert listening(PORT), f"平台 {PORT} 未就绪"
    print(f"platform up on {PORT}")

    results: dict = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.goto(PLATFORM + "?noboot=1", wait_until="domcontentloaded")
            pg.wait_for_selector("text=交易日志", timeout=30000)
            t0 = time.time()
            pg.click("text=交易日志")
            # 自动拉起: spinner -> iframe[src*='8502']
            pg.wait_for_selector("iframe[src*='8502']", timeout=30000)
            results["iframe_after_s"] = round(time.time() - t0, 2)
            # iframe 内真的渲染出日志应用, 而非连接错误页
            pg.wait_for_timeout(4000)
            pg.screenshot(path=str(OUT / "journal_autostart.png"), full_page=False)
            results["health_8502"] = listening(8502)
            b.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    print(results)
    ok = results.get("health_8502") and results.get("iframe_after_s", 99) < 30
    print("VERIFY", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
