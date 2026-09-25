"""看门狗兜底的变异测试: 脚本在遮罩之后抛异常, 遮罩必须在 FALLBACK_MS 后自行放行.

起一个临时 streamlit 应用(只复用 boot_splash, 不复用 app.py), 渲染遮罩+看门狗后
立刻 raise. 若 6s 后遮罩仍未隐藏, 说明兜底失效.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(os.environ.get("ASTOCK_REPO") or Path(__file__).resolve().parents[2])
PORT = 8504
URL = f"http://localhost:{PORT}/"

APP_SRC = '''
import sys
sys.path.insert(0, r"{repo}")
import streamlit as st
from web.components.boot_splash import render_boot_mask, start_boot_watchdog

st.set_page_config(page_title="boom", layout="wide")
render_boot_mask()
start_boot_watchdog()
raise RuntimeError("simulated mid-render crash")
'''.format(repo=str(REPO))


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        app = Path(td) / "boom_app.py"
        app.write_text(APP_SRC, encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(app),
             "--server.port", str(PORT), "--server.headless", "true"],
            cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import urllib.request
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://localhost:{PORT}/_stcore/health", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1000, "height": 700})
                page.add_init_script("try { sessionStorage.clear(); } catch (e) {}")
                t0 = time.monotonic()
                page.goto(URL, wait_until="commit")
                page.wait_for_function(
                    "() => !!document.getElementById('boot-mask')", timeout=15000
                )
                # 确认脚本真的炸了
                page.wait_for_selector('[data-testid="stException"]', timeout=15000)
                print("exception banner: present")

                hidden_at = None
                try:
                    page.wait_for_function(
                        "() => window.__astockBoot && window.__astockBoot.hidden === true",
                        timeout=15000,
                    )
                    hidden_at = time.monotonic() - t0
                except Exception:
                    pass
                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    if hidden_at is None:
        print("FAIL: mask never released on crash path")
        return 1
    print(f"mask released at {hidden_at:.1f}s after navigation (fallback ~6.5s)")
    ok = 5.0 <= hidden_at <= 9.0
    print("PASS" if ok else "FAIL", "fallback window")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
