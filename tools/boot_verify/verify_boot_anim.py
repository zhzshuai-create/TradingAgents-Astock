"""阶段 5 验收: 节点点亮时间线是否真的逐个推进, 以及汇聚/决策节点是否到位.

在遮罩上屏后的 0.3 / 0.9 / 1.8 / 2.6s 各截一张, 同时记录 7 个节点与决策节点的
计算不透明度, 用数值证明"逐个点亮"而不是"一起出现".
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(os.environ.get("ASTOCK_REPO") or Path(__file__).resolve().parents[2])
OUT = Path.cwd()  # 证据截图/JSON 落到运行目录, 不污染仓库
PORT = 8503
URL = f"http://localhost:{PORT}/"

OPACITIES = """
() => {
  const op = (e) => Math.round(+getComputedStyle(e).opacity * 100) / 100;
  return {
    nodes: [...document.querySelectorAll('#boot-mask .boot-node')].map(op),
    decision: op(document.querySelector('#boot-mask .boot-decision')),
    mask: op(document.getElementById('boot-mask')),
  };
}
"""

SHOTS = [(300, "anim_t03"), (600, "anim_t09"), (800, "anim_t17"), (1000, "anim_t27")]


def capture(page, label: str):
    page.goto(URL, wait_until="commit")
    page.wait_for_function("() => !!document.getElementById('boot-mask')", timeout=15000)
    timeline = []
    acc = 0
    for delta, name in SHOTS:
        page.wait_for_timeout(delta)
        acc += delta
        page.screenshot(path=str(OUT / f"{label}_{name}.png"))
        timeline.append({"t_ms": acc, "name": name, **page.evaluate(OPACITIES)})
    page.wait_for_function(
        "() => window.__astockBoot && window.__astockBoot.hidden === true", timeout=30000
    )
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / f"{label}_after.png"))
    return timeline


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(REPO / "web" / "app.py"),
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

    result = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script("try { sessionStorage.clear(); } catch (e) {}")
            result["light"] = capture(page, "light")

            page.evaluate("() => localStorage.setItem('astock-theme', 'dark')")
            result["dark"] = capture(page, "dark")
            page.evaluate("() => localStorage.setItem('astock-theme', 'light')")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    (OUT / "verify_boot_anim.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for mode in ("light", "dark"):
        print(f"=== {mode} ===")
        for row in result[mode]:
            print(f"  t={row['t_ms']:>4}ms nodes={row['nodes']} decision={row['decision']}")

    tl = result["light"]
    checks = [
        ("0.3s 时遮罩已淡入、节点尚未开始(时间线起点 0.55s)",
         tl[0]["mask"] > 0.5 and all(v < 0.1 for v in tl[0]["nodes"])),
        ("0.9s 时前段已亮、末位未亮(逐个而非同时)",
         tl[1]["nodes"][0] > 0.9 and tl[1]["nodes"][2] > 0.3 and tl[1]["nodes"][6] < 0.1),
        ("1.7s 时 7 个节点全亮、决策未出现",
         all(v > 0.9 for v in tl[2]["nodes"]) and tl[2]["decision"] < 0.1),
        ("2.7s 时节点已汇聚消失、决策已出现",
         all(v < 0.1 for v in tl[3]["nodes"]) and tl[3]["decision"] > 0.9),
    ]
    print("\n=== gate ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and bool(passed)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
