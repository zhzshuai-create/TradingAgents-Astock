"""阶段 6 验收: 门控语义 — 每个标签页只播一次.

场景:
  1 新标签页首次加载            -> 播
  2 同页 F5                     -> 不播
  3 连续 5 次模式切换(st.rerun) -> 不播, 且不闪
  4 location.reload()(重连同款) -> 不播
  5 新标签页                    -> 播(sessionStorage 按标签页)
  6 ?noboot=1                   -> 不播
  7 prefers-reduced-motion      -> 不播
"""

from __future__ import annotations

import subprocess
import sys
import time
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(os.environ.get("ASTOCK_REPO") or Path(__file__).resolve().parents[2])
PORT = 8503
URL = f"http://localhost:{PORT}/"

MASK_STATE = """
() => {
  const m = document.getElementById('boot-mask');
  const h = document.documentElement;
  return { cls: [h.getAttribute('data-boot'), h.getAttribute('data-boot-done'),
                 h.getAttribute('data-boot-gone')].join(','),
           op: m ? +getComputedStyle(m).opacity : 0,
           disp: m ? getComputedStyle(m).display : 'gone' };
}
"""

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def wait_played(page, timeout=8000) -> bool:
    try:
        page.wait_for_function(
            "() => document.documentElement.getAttribute('data-boot') === 'play'",
            timeout=timeout,
        )
        return True
    except Exception as exc:
        try:
            print("    wait_played miss:", str(exc)[:80],
                  page.evaluate(MASK_STATE),
                  page.evaluate("() => { const B = window.__astockBoot || {};"
                                " return { decided: !!B.decided, hidden: !!B.hidden,"
                                " ready: !!B.ready }; }"))
        except Exception:
            pass
        return False


def watch_no_play(page, seconds: float):
    """轮询: 播一次至少持续 2.8s, 100ms 轮询不可能漏看."""
    deadline = time.monotonic() + seconds
    state = {"cls": "", "op": 0, "disp": ""}
    while time.monotonic() < deadline:
        try:
            state = page.evaluate(MASK_STATE)
        except Exception:
            # 导航瞬间执行上下文会被销毁, 跳过这一拍继续看
            time.sleep(0.1)
            continue
        if "boot-play" in state["cls"] or state["op"] > 0.05:
            return False, state
        time.sleep(0.1)
    return True, state


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

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})

            # 1 首次加载 -> 播
            p1 = ctx.new_page()
            p1.goto(URL, wait_until="commit")
            played = wait_played(p1)
            record("新标签页首次加载播放", played)
            p1.wait_for_function(
                "() => window.__astockBoot && window.__astockBoot.hidden === true",
                timeout=30000,
            )

            # 2 F5 -> 不播
            p1.reload(wait_until="commit")
            ok, st = watch_no_play(p1, 3.0)
            record("F5 后不重播", ok, f"cls={st['cls']!r} op={st['op']}")
            p1.wait_for_selector(".model-badge", timeout=30000)

            # 3 连续 5 次模式切换 -> 不播
            ok = True
            detail = ""
            for i, label in enumerate(["实时数据看板", "AI分析报告"] * 3):
                p1.get_by_role("button", name=label).first.click()
                passed_i, st = watch_no_play(p1, 1.5)
                ok = ok and passed_i
                if not passed_i:
                    detail = f"第 {i + 1} 次切换后重播 cls={st['cls']!r}"
                    break
            record("连续 5 次模式切换不重播", ok, detail)

            # 4 location.reload() -> 不播
            p1.evaluate("() => location.reload()")
            ok, st = watch_no_play(p1, 3.0)
            record("location.reload() 后不重播", ok, f"cls={st['cls']!r} op={st['op']}")

            # 5 新标签页 -> 播
            p2 = ctx.new_page()
            p2.goto(URL, wait_until="commit")
            record("新标签页重新播放", wait_played(p2))
            p2.close()

            # 6 ?noboot=1 -> 不播
            p3 = ctx.new_page()
            p3.goto(URL + "?noboot=1", wait_until="commit")
            ok, st = watch_no_play(p3, 3.0)
            record("?noboot=1 不播放", ok, f"cls={st['cls']!r} op={st['op']}")
            p3.close()

            # 7 reduced motion -> 不播
            ctx_rm = browser.new_context(viewport={"width": 1440, "height": 900},
                                         reduced_motion="reduce")
            p4 = ctx_rm.new_page()
            p4.goto(URL, wait_until="commit")
            ok, st = watch_no_play(p4, 3.0)
            record("prefers-reduced-motion 不播放", ok, f"cls={st['cls']!r} op={st['op']}")
            p4.close()
            ctx_rm.close()

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n=== gate ===")
    bad = [n for n, ok, _ in results if not ok]
    print(f"  {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
