# -*- coding: utf-8 -*-
"""自动化录制 AStock Web UI 演示 GIF（Playwright 逐帧截图 + PIL 合成）.

前提：Web 已在本地运行（streamlit run web/app.py），或加 --launch 自动拉起。
脚本按"分镜"执行：boot 动画 → AI 分析页 → 实时数据看板 → 强势股归因 →
资金流 → 主题切换 → 侧边栏；每一步都是 best-effort，单个控件失败不中断
录制，结束时打印每步成败报告。

个股 K 线周期切换依赖页面顶部搜索框（自定义组件，Playwright 无法触达），
自动化路线覆盖不到；需要 K 线镜头请走人工录制路线（docs/demo-script.md）。

用法：
    python scripts/make_demo_gif.py                          # 默认 http://localhost:8501
    python scripts/make_demo_gif.py --launch                 # 自动拉起 streamlit
    python scripts/make_demo_gif.py --out assets/demo.gif --scale 0.5
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))

BOOT_MASK_SELECTOR = "#boot-mask"
APP_READY_SELECTOR = ".index-bar"


def grab(page, frames: list, interval: float, n: int) -> None:
    for _ in range(n):
        frames.append(page.screenshot(type="png"))
        time.sleep(interval)


def click_radio(page, label: str) -> bool:
    """点击顶部 segmented control 的某个模式（Streamlit 1.57: 按钮而非 radio）"""
    for how in (
        lambda: page.locator(
            "[data-testid^=stBaseButton-segmented_control]", has_text=label
        ).first.click(timeout=3000),
        lambda: page.get_by_text(label, exact=True).first.click(timeout=3000),
    ):
        try:
            how()
            return True
        except Exception:
            continue
    return False


def click_zone_radio(page, label: str, wait_s: float = 8.0) -> bool:
    """看板分区 radio（个股估值/强势股归因/资金流/资讯）。
    注意：个股 K 线区块由"顶部搜索框"（自定义组件，Playwright 无法触达）驱动，
    自动化路线到不了 K 线周期切换，人工录制路线可以。"""
    for how in (
        lambda: page.get_by_role("radio", name=label).first.click(timeout=3000),
        lambda: page.locator("label", has_text=label).first.click(timeout=3000),
    ):
        try:
            how()
            time.sleep(wait_s)
            return True
        except Exception:
            continue
    return False


def toggle_theme(page) -> bool:
    """主题开关是自定义组件（#rope-root），在 components.html 的 iframe 里"""
    for fr in page.frames:
        try:
            rope = fr.locator("#rope-root")
            if rope.count() and rope.first.is_visible():
                rope.first.click()
                return True
        except Exception:
            continue
    return False


def open_sidebar(page) -> bool:
    """Streamlit 1.57 侧边栏默认展开：可见即成功，否则点收起/展开按钮"""
    try:
        if page.get_by_test_id("stSidebar").first.is_visible():
            return True
    except Exception:
        pass
    for testid in ("stSidebarCollapseButton", "stSidebarCollapsedControl"):
        try:
            page.get_by_test_id(testid).first.click(timeout=2000)
            return True
        except Exception:
            continue
    return False


def wait_app_ready(page, timeout_s: float = 40.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if page.locator(APP_READY_SELECTOR).first.is_visible():
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def launch_streamlit(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "web/app.py",
         "--server.headless", "true", "--server.port", str(port)],
        cwd=str(PROJ),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import urllib.request
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/_stcore/health", timeout=2) as r:
                if r.status == 200:
                    return proc
        except Exception:
            time.sleep(1)
    proc.terminate()
    raise RuntimeError("streamlit 启动超时")


def build_gif(frames: list, out: Path, scale: float, interval: float) -> int:
    from PIL import Image

    imgs = [Image.open(io.BytesIO(b)).convert("RGB") for b in frames]
    if scale != 1.0:
        size = (int(imgs[0].width * scale), int(imgs[0].height * scale))
        imgs = [im.resize(size, Image.LANCZOS) for im in imgs]
    # 合并连续相同帧（时长累加）。不能用 PIL optimize=True：它会丢弃重复帧
    # 但不合并时长，导致动画整体被压缩变快
    uniq: list = []
    durs: list = []
    for im in imgs:
        if uniq and im.tobytes() == uniq[-1].tobytes():
            durs[-1] += interval * 1000
        else:
            uniq.append(im)
            durs.append(interval * 1000)
    out.parent.mkdir(parents=True, exist_ok=True)
    uniq[0].save(
        out, save_all=True, append_images=uniq[1:], duration=durs,
        loop=0, optimize=False,
    )
    return out.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--launch", action="store_true", help="自动拉起 streamlit（结束时关闭）")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--out", default="assets/demo.gif")
    ap.add_argument("--interval", type=float, default=0.7, help="帧间隔秒")
    ap.add_argument("--scale", type=float, default=0.5, help="输出宽度缩放（1920*0.5=960）")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    proc = launch_streamlit(args.port) if args.launch else None
    report: list[tuple[str, bool]] = []
    frames: list = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(args.url, wait_until="domcontentloaded")
            time.sleep(1.2)                      # 让 boot 遮罩先出现
            grab(page, frames, args.interval, 4)  # 分镜1: boot 动画

            ready = wait_app_ready(page)
            report.append(("app ready", ready))
            grab(page, frames, args.interval, 3)  # 分镜2: AI 分析报告首页

            ok = click_radio(page, "实时数据看板")
            report.append(("切换到数据看板", ok))
            time.sleep(7 if ok else 2)           # 等看板数据（K线/指标）渲染
            grab(page, frames, args.interval, 4)  # 分镜3: 实时数据看板

            ok_z1 = click_zone_radio(page, "强势股归因", wait_s=4)
            report.append(("分区切强势股归因", ok_z1))
            grab(page, frames, args.interval, 3)  # 分镜4: 强势股归因

            ok_z2 = click_zone_radio(page, "资金流", wait_s=3)
            report.append(("分区切资金流", ok_z2))
            grab(page, frames, args.interval, 2)  # 分镜5: 资金流

            ok_t = toggle_theme(page)
            report.append(("主题切换", ok_t))
            time.sleep(1.5)
            grab(page, frames, args.interval, 3)  # 分镜6: 暗色主题

            ok_s = open_sidebar(page)
            report.append(("侧边栏可见", ok_s))
            time.sleep(1.5)
            grab(page, frames, args.interval, 2)  # 分镜7: 侧边栏

            browser.close()
    finally:
        if proc:
            proc.terminate()

    out = PROJ / args.out
    size = build_gif(frames, out, args.scale, args.interval)
    print(f"\n帧数 {len(frames)}  时长约 {len(frames) * args.interval:.0f}s")
    for name, ok in report:
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"GIF -> {out}  {size / 1024 / 1024:.1f} MB")
    if size > 10 * 1024 * 1024:
        print("⚠ 超过 10MB，建议减小 --scale 或加长 --interval")
    return 0 if frames else 1


if __name__ == "__main__":
    sys.exit(main())
