"""UI 现状截图：亮/暗 × AI首页/数据看板，供前端优化前后对比。"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8501"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "ui_shots_before")
OUT.mkdir(exist_ok=True)


def shoot(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("saved", name)


def click_segmented(page, label):
    sel = '[data-testid^="stBaseButton-segmented_control"]'
    try:
        page.locator(sel, has_text=label).first.click(timeout=4000)
    except Exception:
        page.get_by_text(label, exact=True).first.click(timeout=4000)


def toggle_theme(page):
    """rope 主题切换（#rope-root 在 srcdoc 组件 iframe 内，同源可直点）。"""
    page.evaluate(
        """() => {
        for (const f of document.querySelectorAll('iframe')) {
          try {
            const r = f.contentDocument && f.contentDocument.getElementById('rope-root');
            if (r) { r.click(); return true; }
          } catch (e) {}
        }
        return false;
      }"""
    )


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1920, "height": 1000})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)  # splash + 首屏
    shoot(page, "home_light")

    # 数据看板
    click_segmented(page, "实时数据看板")
    page.wait_for_timeout(9000)
    shoot(page, "dash_light")

    # 历史报告
    click_segmented(page, "AI分析报告")
    page.wait_for_timeout(2000)

    # 暗色模式（页面级 rope 按钮）
    toggle_theme(page)
    page.wait_for_timeout(2500)
    page.evaluate("() => { window.scrollTo(0, 0); }")
    shoot(page, "home_dark")

    click_segmented(page, "实时数据看板")
    page.wait_for_timeout(6000)
    shoot(page, "dash_dark")

    browser.close()
print("done ->", OUT.resolve())
