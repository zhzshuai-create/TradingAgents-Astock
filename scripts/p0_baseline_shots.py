"""P0 Day 1: 采集旧版界面截图与首屏/切换耗时基线。

只读，不改代码；使用免费行情源，不触发任何模型调用。

计时口径：点击后先等 400ms 让 Streamlit 进入重跑，再等 DOM 静默
（签名连续 1.5s 不变且无 spinner / 状态条不显示 Running）才算结束。
早先版本只查 spinner，会在重跑真正开始前就返回，测出 0.0x 秒的假数据。
"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8507/"
OUT = Path(r"C:\Users\zhzsh\TradingAgents-astock\docs\upgrade\baseline\shots")
OUT.mkdir(parents=True, exist_ok=True)

SIG_JS = """() => {
    const els = document.querySelectorAll('*').length;
    const txt = (document.body.innerText || '').length;
    const spin = document.querySelectorAll('[data-testid="stSpinner"]').length;
    const st = document.querySelector('[data-testid="stStatusWidget"]');
    const stt = st ? (st.innerText || '') : '';
    const mask = document.querySelector('#boot-mask');
    // offsetParent 对 position:fixed 恒为 null，不能用它判可见。
    // 遮罩的放行信号是 html[data-boot-gone="1"]（display:none）。
    const maskVisible = !!mask && document.documentElement.getAttribute('data-boot-gone') !== '1';
    return [els, txt, spin, stt, maskVisible ? 1 : 0].join('|');
}"""

results = {}


def wait_settled(page, quiet_ms=1500, timeout_ms=150000, label=""):
    deadline = time.perf_counter() + timeout_ms / 1000.0
    last = None
    last_change = time.perf_counter()
    while time.perf_counter() < deadline:
        sig = page.evaluate(SIG_JS)
        parts = sig.split("|")
        running = parts[2] != "0" or "Running" in parts[3] or "Connecting" in parts[3] or parts[4] == "1"
        if sig != last:
            last = sig
            last_change = time.perf_counter()
        elif not running and (time.perf_counter() - last_change) * 1000 >= quiet_ms:
            return
        page.wait_for_timeout(150)
    raise TimeoutError(f"not settled: {label} last={last}")


def act(page, fn, key, quiet_ms=1500, timeout_ms=150000):
    """执行一个交互并计时（含 400ms 重跑启动缓冲）。"""
    t0 = time.perf_counter()
    fn()
    page.wait_for_timeout(400)
    wait_settled(page, quiet_ms=quiet_ms, timeout_ms=timeout_ms, label=key)
    results[key] = round(time.perf_counter() - t0, 2)


def shot(page, name, full=False):
    page.screenshot(path=str(OUT / name), full_page=full)
    return name


with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # ── 桌面 1440x900 ────────────────────────────────────────────
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    t0 = time.perf_counter()
    page.goto(URL, wait_until="commit", timeout=180000)
    page.wait_for_selector("#boot-ready", state="attached", timeout=180000)
    results["desktop_boot_ready_s"] = round(time.perf_counter() - t0, 2)
    wait_settled(page, quiet_ms=2000, timeout_ms=180000, label="cold_first_screen")
    results["desktop_cold_first_screen_s"] = round(time.perf_counter() - t0, 2)
    results["desktop_analysis_shot"] = shot(page, "01_desktop_analysis.png")
    results["desktop_analysis_scroll_ok"] = page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )

    act(page, lambda: page.get_by_text("实时数据看板", exact=True).first.click(),
        "desktop_switch_to_data_s")
    results["desktop_market_overview_shot"] = shot(page, "02_desktop_market_overview.png")

    def _search():
        box = page.get_by_placeholder("搜索代码或名称，如 300750 / 宁德时代").first
        box.fill("000001")
        box.press("Enter")

    act(page, _search, "desktop_stock_valuation_s", quiet_ms=2000, timeout_ms=180000)
    results["desktop_stock_valuation_shot"] = shot(page, "03_desktop_stock_valuation.png")
    results["desktop_stock_valuation_full_shot"] = shot(
        page, "04_desktop_stock_valuation_full.png", full=True
    )

    act(page, lambda: page.get_by_text("交易日志", exact=True).first.click(),
        "desktop_switch_to_journal_s")
    results["desktop_journal_shot"] = shot(page, "05_desktop_journal.png")

    act(page, lambda: page.get_by_text("AI分析报告", exact=True).first.click(),
        "desktop_switch_back_to_analysis_s")

    # 暖切换：再切一次数据看板，看缓存命中后的耗时
    act(page, lambda: page.get_by_text("实时数据看板", exact=True).first.click(),
        "desktop_switch_to_data_warm_s")

    results["desktop_pageerrors"] = errors
    ctx.close()

    # ── 移动 390x844 ─────────────────────────────────────────────
    mctx = browser.new_context(
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
    )
    mpage = mctx.new_page()
    merrors = []
    mpage.on("pageerror", lambda e: merrors.append(str(e)))
    t0 = time.perf_counter()
    mpage.goto(URL, wait_until="commit", timeout=180000)
    mpage.wait_for_selector("#boot-ready", state="attached", timeout=180000)
    wait_settled(mpage, quiet_ms=2000, timeout_ms=180000, label="mobile_cold")
    results["mobile_cold_first_screen_s"] = round(time.perf_counter() - t0, 2)
    results["mobile_analysis_shot"] = shot(mpage, "11_mobile_analysis.png")
    results["mobile_analysis_scroll_ok"] = mpage.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    act(mpage, lambda: mpage.get_by_text("实时数据看板", exact=True).first.click(),
        "mobile_switch_to_data_s")
    results["mobile_market_overview_shot"] = shot(mpage, "12_mobile_market_overview.png")
    results["mobile_pageerrors"] = merrors
    mctx.close()

    browser.close()

print(json.dumps(results, ensure_ascii=True, indent=2))
