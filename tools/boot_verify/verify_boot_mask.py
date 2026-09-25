"""阶段 4 验收: 遮罩是否真的盖住整个视口, 以及淡出后是否让位.

用法:
  python verify_boot_mask.py            # 自己起 8503 的服务
  python verify_boot_mask.py --no-server # 复用已在跑的服务
"""

from __future__ import annotations

import argparse
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

# 遮罩几何 + 命中测试. 命中测试是关键: position:fixed 只有在没有祖先带
# transform/filter/will-change 时才是相对视口的, 光看 getBoundingClientRect 不够.
PROBE = """
() => {
  const m = document.getElementById('boot-mask');
  if (!m) return {present: false};
  const r = m.getBoundingClientRect();
  const cs = getComputedStyle(m);
  const pts = [[innerWidth/2, innerHeight/2], [8, 8],
               [innerWidth-8, innerHeight-8], [innerWidth/2, 8],
               [innerWidth-40, 30]];
  const hits = pts.map(([x, y]) => {
    const el = document.elementFromPoint(x, y);
    return el ? (m.contains(el) ? 'mask' : (el.id || el.tagName + '.' + el.className)) : 'none';
  });
  return {
    present: true,
    rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
    viewport: [innerWidth, innerHeight],
    position: cs.position, zIndex: cs.zIndex,
    display: cs.display, opacity: cs.opacity,
    cls: m.className,
    hits,
    // 找出会劫持 fixed 定位的祖先
    badAncestor: (() => {
      let n = m.parentElement;
      while (n && n !== document.documentElement) {
        const s = getComputedStyle(n);
        if (s.transform !== 'none' || s.filter !== 'none' || s.willChange !== 'auto'
            || s.contain === 'paint' || s.contain === 'layout') {
          return n.tagName + '#' + n.id + '.' + n.className
                 + ' transform=' + s.transform + ' filter=' + s.filter
                 + ' willChange=' + s.willChange + ' contain=' + s.contain;
        }
        n = n.parentElement;
      }
      return null;
    })(),
  };
}
"""

results: dict = {}


def shoot(page, name: str, at_ms: int | None = None):
    if at_ms is not None:
        page.wait_for_timeout(at_ms)
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p))
    print(f"   shot -> {p.name}")


def run(page, label: str):
    page.goto(URL, wait_until="commit")

    # 遮罩刚上屏时
    page.wait_for_function(
        "() => !!document.getElementById('boot-mask')", timeout=15000
    )
    t_mask = page.evaluate(PROBE)
    results[f"{label}.mask"] = t_mask
    shoot(page, f"boot_{label}_mask")

    # 淡入完成后(约 360ms)再拍一张, 确认满不透明度时连 Streamlit 顶栏也盖住
    page.wait_for_timeout(700)
    t_settled = page.evaluate(PROBE)
    results[f"{label}.settled"] = t_settled
    shoot(page, f"boot_{label}_settled")

    # 内容就绪 + 最短可见时长之后
    page.wait_for_function(
        """() => {
          const b = window.__astockBoot;
          return b && b.hidden === true;
        }""",
        timeout=30000,
    )
    page.wait_for_timeout(600)
    t_after = page.evaluate(PROBE)
    results[f"{label}.after"] = t_after
    shoot(page, f"boot_{label}_after")

    # 淡出后主界面必须可点: 遮罩 pointer-events 恒为 none, 这里确认淡出后
    # 命中落在真实界面元素上(而不是还有一层 invisible 的东西挡着)
    results[f"{label}.after_hits"] = page.evaluate(
        """() => {
          const pts = [[innerWidth/2, innerHeight/2], [innerWidth/2, 24]];
          return pts.map(([x, y]) => {
            const els = document.elementsFromPoint(x, y);
            return els.length ? (els[0].id || els[0].tagName + '.' + (els[0].className || '')).slice(0, 60) : 'none';
          });
        }"""
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-server", action="store_true")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    proc = None
    if not args.no_server:
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
        print(f"server up on {PORT}")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.add_init_script("try { sessionStorage.clear(); } catch (e) {}")
            run(page, "light")

            # 暗色: 复用主题 JS 的入口(localStorage), 整页刷新
            page.evaluate("() => localStorage.setItem('astock-theme', 'dark')")
            page.reload(wait_until="commit")
            page.wait_for_function(
                "() => !!document.getElementById('boot-mask')", timeout=15000
            )
            page.wait_for_timeout(500)
            results["dark.mask"] = page.evaluate(PROBE)
            shoot(page, "boot_dark_mask")
            page.evaluate("() => localStorage.setItem('astock-theme', 'light')")

            browser.close()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    (OUT / "verify_boot_mask.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n=== light.mask ===")
    print(json.dumps(results["light.mask"], indent=2, ensure_ascii=False))
    print("\n=== light.after ===")
    print(json.dumps(results["light.after"], indent=2, ensure_ascii=False))
    print("\n=== light.after_hits ===", results["light.after_hits"])

    m = results["light.mask"]
    s = results["light.settled"]
    a = results["light.after"]

    # 覆盖证明改用像素: 遮罩 pointer-events 恒为 none(它从不接收点击),
    # elementFromPoint 会正确地穿透它, 命中测试不再是覆盖证据.
    from PIL import Image
    img = Image.open(OUT / "boot_light_settled.png").convert("RGB")
    px = {name: img.getpixel(xy) for name, xy in
          (("corner", (10, 500)), ("topcenter", (720, 140)),
           ("botcenter", (720, 780)), ("toolbar", (1360, 30)))}
    img_d = Image.open(OUT / "boot_dark_mask.png").convert("RGB")
    px_d = img_d.getpixel((1360, 30))

    checks = [
        ("遮罩存在", m["present"]),
        ("铺满视口", m["rect"][2] >= m["viewport"][0] and m["rect"][3] >= m["viewport"][1]
                    and abs(m["rect"][0]) < 2 and abs(m["rect"][1]) < 2),
        ("无祖先劫持 fixed 定位", m["badAncestor"] is None),
        ("淡入后不透明度为 1", s["opacity"] == "1"),
        ("亮色满屏为遮罩底色(含顶栏区域)",
         all(v == (255, 255, 255) for v in px.values())),
        ("暗色顶栏区域为遮罩底色", px_d == (14, 17, 23)),
        ("淡出后 display:none", a["display"] == "none"),
        ("淡出后命中不再是遮罩",
         all("boot-mask" not in h and "mask" != h for h in results["light.after_hits"])),
    ]
    print("\n=== gate ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and bool(passed)
    if m["badAncestor"]:
        print(f"  badAncestor: {m['badAncestor']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
