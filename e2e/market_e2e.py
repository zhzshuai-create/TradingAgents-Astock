"""P4-06/P4-07/P4-11 W08 market dashboard E2E.

Runs the built frontend on ``vite preview`` with stubbed read APIs:

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/market_e2e.py

Desktop 1440 (P4-06) covers R-10 and R-11: session bar, index cards,
industries, strong stocks, newsflash, per-block states, no-write reads, and
industry -> constituents -> stock -> back with industry, topN, date, drawer
and scroll restored. Mobile 390x844 and 360x800 (P4-07) covers W08M-01..04:
index strip scrolls inside its container, cards replace tables, the
full-screen board drills and restores, and touch targets reach 44px without
page-level horizontal overflow. P4-11 adds R-15: the visible 10s overview
poll, the 60s floor while hidden, an immediate refetch on returning to the
foreground, a 500ms debounced manual refresh that issues one request group,
and timers cleared when the page is left. Prints one JSON line; desktop
screenshots go to ui_shots_p4/P4-06/, mobile ones to ui_shots_p4/P4-07/.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p4" / "P4-06"
SHOTS_MOBILE = ROOT / "ui_shots_p4" / "P4-07"

AS_OF = "2026-11-05T09:30:00+08:00"

failures: list[str] = []
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if condition:
        print(f"PASS {message}")
        return
    failures.append(message)
    print(f"FAIL {message}")


def run_node(script: str, *args: str) -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node executable not found on PATH")
    subprocess.run([node, script, *args], cwd=FRONTEND, check=True)


def build() -> None:
    run_node("node_modules/typescript/bin/tsc", "--noEmit")
    run_node("node_modules/vite/bin/vite.js", "build")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    def __init__(self) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("node executable not found on PATH")
        self.proc = subprocess.Popen(
            [
                node,
                "node_modules/vite/bin/vite.js",
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--strictPort",
            ],
            cwd=FRONTEND,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def __enter__(self) -> str:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                output = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"vite preview exited early:\n{output}")
            try:
                with urllib.request.urlopen(f"{self.base}/market", timeout=1) as response:
                    if response.status == 200:
                        return self.base
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.2)
        raise RuntimeError("vite preview did not answer")

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def watch(page: Page) -> tuple[list[str], list[tuple[str, str]]]:
    errors: list[str] = []
    requests: list[tuple[str, str]] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on(
        "request",
        lambda request: (
            requests.append((request.method, request.url))
            if "/api/" in request.url
            else None
        ),
    )
    return errors, requests


def envelope(
    data: object | None,
    *,
    status: str = "ok",
    source: str = "mixed",
    partial: bool = False,
    failed: tuple[str, ...] = (),
    stale_reason: str | None = None,
    error_code: str | None = None,
) -> dict:
    return {
        "schema_version": "market-envelope-v1",
        "status": status,
        "source": source,
        "as_of": AS_OF,
        "fetched_at": AS_OF,
        "is_stale": status == "stale",
        "stale_reason": stale_reason,
        "error_code": error_code,
        "error_message": "上游暂不可用" if error_code else None,
        "partial": partial,
        "failed_blocks": list(failed),
        "data": data,
    }


OVERVIEW = envelope(
    {
        "market_session": "trading",
        "indices": [
            {
                "code": "000001.SH",
                "name": "上证指数",
                "price": 3345.12,
                "change_pct": 0.42,
                "change_amt": 13.98,
            },
            {
                "code": "399001.SZ",
                "name": "深证成指",
                "price": 10880.5,
                "change_pct": -0.31,
                "change_amt": -33.8,
            },
            {
                "code": "399006.SZ",
                "name": "创业板指",
                "price": 2210.4,
                "change_pct": 0.08,
                "change_amt": 1.77,
            },
        ],
        "northbound": None,
    }
)

INDUSTRY_ROWS = [
    {
        "rank": index + 1,
        "name": f"行业{index + 1:02d}",
        "code": f"BK{1000 + index}",
        "change_pct": round(4.5 - index * 0.2, 2),
        "up_count": 40 - index,
        "down_count": 2 + index,
        "leader": f"龙头{index + 1:02d}",
        "leader_change": round(9.0 - index * 0.15, 2),
    }
    for index in range(30)
]


def industries(top: int) -> dict:
    return envelope(
        {
            "top": INDUSTRY_ROWS[:top],
            "bottom": INDUSTRY_ROWS[-5:],
            "total": len(INDUSTRY_ROWS),
        }
    )


def constituents(board: str) -> dict:
    return envelope(
        {
            "board_code": board,
            "items": [
                {
                    "code": f"6000{index:02d}",
                    "name": f"成分{index + 1:02d}",
                    "price": round(10 + index * 1.5, 2),
                    "change_pct": round(2.0 - index * 0.1, 2),
                    "change_amt": None,
                }
                for index in range(10)
            ],
        }
    )


STRONG_ITEMS = [
    {
        "ticker_code": "000001",
        "name": "平安银行",
        "reason": "算力",
        "market": "sz",
        "change_pct": 6.2,
        "change_amt": 0.7,
        "close": 12.34,
        "turnover_pct": 3.4,
    },
    {
        "ticker_code": "000002",
        "name": "万科A",
        "reason": "算力",
        "market": "sz",
        "change_pct": 5.1,
        "change_amt": 0.4,
        "close": 9.1,
        "turnover_pct": 2.1,
    },
    {
        "ticker_code": "000063",
        "name": "中兴通讯",
        "reason": "算力",
        "market": "sz",
        "change_pct": 4.8,
        "change_amt": 1.2,
        "close": 26.2,
        "turnover_pct": 4.0,
    },
    {
        "ticker_code": "300750",
        "name": "宁德时代",
        "reason": "储能",
        "market": "sz",
        "change_pct": 4.2,
        "change_amt": 9.1,
        "close": 225.5,
        "turnover_pct": 3.4,
    },
    {
        "ticker_code": "300274",
        "name": "阳光电源",
        "reason": "储能",
        "market": "sz",
        "change_pct": 3.9,
        "change_amt": 2.8,
        "close": 74.0,
        "turnover_pct": 2.8,
    },
    {
        "ticker_code": "600519",
        "name": "贵州茅台",
        "reason": "白酒",
        "market": "sh",
        "change_pct": 3.1,
        "change_amt": 45.0,
        "close": 1500.0,
        "turnover_pct": 0.6,
    },
    {
        "ticker_code": "000858",
        "name": "五粮液",
        "reason": "白酒",
        "market": "sz",
        "change_pct": 2.7,
        "change_amt": 3.2,
        "close": 121.4,
        "turnover_pct": 1.1,
    },
    {
        "ticker_code": "300024",
        "name": "机器人",
        "reason": "机器人",
        "market": "sz",
        "change_pct": 2.4,
        "change_amt": 0.3,
        "close": 12.8,
        "turnover_pct": 5.2,
    },
    {
        "ticker_code": "600111",
        "name": "北方稀土",
        "reason": "稀土",
        "market": "sh",
        "change_pct": 2.1,
        "change_amt": 0.5,
        "close": 24.3,
        "turnover_pct": 1.9,
    },
    {
        "ticker_code": "688981",
        "name": "中芯国际",
        "reason": "半导体",
        "market": "sh",
        "change_pct": 1.8,
        "change_amt": 1.1,
        "close": 62.5,
        "turnover_pct": 2.2,
    },
    {
        "ticker_code": "601012",
        "name": "隆基绿能",
        "reason": "光伏",
        "market": "sh",
        "change_pct": 1.5,
        "change_amt": 0.3,
        "close": 20.2,
        "turnover_pct": 1.4,
    },
    {
        "ticker_code": "600760",
        "name": "中航沈飞",
        "reason": "军工",
        "market": "sh",
        "change_pct": 1.2,
        "change_amt": 0.6,
        "close": 50.4,
        "turnover_pct": 0.9,
    },
]

NEWS_ITEMS = [
    {
        "published_at": "2026-11-05T09:28:00+08:00",
        "title": "央行公开市场净投放 2000 亿元",
        "content": "详见 https://example.com/news?id=1。",
        "source": "cls",
        "url": "https://example.com/news?id=1",
    },
    {
        "published_at": "2026-11-05T09:20:00+08:00",
        "title": "<script>alert(1)</script> 不应执行",
        "content": "javascript:alert(1) 只作为文本显示。",
        "source": "cls",
        "url": None,
    },
    {
        "published_at": "2026-11-05T09:10:00+08:00",
        "title": "北向资金半日净流入 32 亿元",
        "content": "",
        "source": "eastmoney",
        "url": None,
    },
]

META_OPTIONS = {
    "app_version": "0.9.0",
    "server_time": AS_OF,
    "default_analysis_date": "2026-11-05",
    "llm_profiles": [{"id": "deepseek-default", "label": "DeepSeek 默认"}],
    "stage_toggles": [{"id": "policy", "label": "政策分析", "default": True}],
    "limits": {"max_active_jobs": 1, "max_date_ahead_days": 0},
    "journal": {
        "available": False,
        "entry_url": "http://127.0.0.1:8502",
        "reason": "not_running",
    },
    "contract_version": "api-v1",
}


def stub_api(context: BrowserContext, variant: str = "ok") -> None:
    def fulfill(route: object, payload: dict) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    def top_param(url: str) -> int:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        try:
            return int(query.get("top", ["20"])[0])
        except ValueError:
            return 20

    context.route(
        "**/api/v1/meta/options**",
        lambda route: fulfill(route, META_OPTIONS),
    )
    context.route(
        "**/api/v1/jobs**",
        lambda route: fulfill(route, {"items": [], "next_cursor": None}),
    )
    context.route(
        "**/api/v1/market/search**",
        lambda route: fulfill(route, envelope({"items": [], "truncated": False})),
    )
    # P4-09 wired the stock workspace into the constituent drill-down; these
    # reads are outside W08's scope, so serve the contract's empty state.
    context.route(
        "**/api/v1/stocks/**",
        lambda route: fulfill(route, envelope(None, status="empty")),
    )

    def overview_route(route: object) -> None:
        if variant == "states":
            fulfill(
                route,
                envelope(
                    OVERVIEW["data"],
                    status="stale",
                    partial=True,
                    failed=("indices",),
                    stale_reason="ttl_exceeded",
                ),
            )
            return
        fulfill(route, OVERVIEW)

    def industries_route(route: object) -> None:
        if variant == "states":
            fulfill(route, envelope(None, status="error", error_code="upstream"))
            return
        fulfill(route, industries(top_param(route.request.url)))

    def strong_route(route: object) -> None:
        if variant == "states":
            fulfill(route, envelope({"items": []}))
            return
        fulfill(route, envelope({"items": STRONG_ITEMS}))

    def news_route(route: object) -> None:
        if variant == "states":
            fulfill(
                route,
                envelope(
                    {"items": NEWS_ITEMS},
                    status="stale",
                    stale_reason="upstream_fallback",
                ),
            )
            return
        fulfill(route, envelope({"items": NEWS_ITEMS}))

    context.route("**/api/v1/market/overview**", overview_route)
    context.route("**/api/v1/market/industries**", industries_route)
    # Registered after the industries wildcard so the nested path wins.
    context.route(
        "**/api/v1/market/industries/*/stocks**",
        lambda route: fulfill(
            route,
            constituents(
                route.request.url.split("/industries/")[1].split("/stocks")[0]
            ),
        ),
    )
    context.route("**/api/v1/market/strong-stocks**", strong_route)
    context.route("**/api/v1/market/newsflash**", news_route)


def section(page: Page, name: str):
    return page.locator(f"section[aria-labelledby='market-{name}']")


def scroll_top(page: Page) -> float:
    return page.evaluate("document.getElementById('main-content').scrollTop")


def wait_for_request(
    page: Page,
    requests: list[tuple[str, str]],
    needle: str,
    timeout: float = 3.0,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(needle in url for _, url in requests):
            return True
        # Pump the sync Playwright event loop; time.sleep would block it.
        page.wait_for_timeout(50)
    return False


def count_requests(requests: list[tuple[str, str]], needle: str) -> int:
    return sum(1 for _method, url in requests if needle in url)


def wait_for_count(
    page: Page,
    requests: list[tuple[str, str]],
    needle: str,
    minimum: int,
    timeout: float,
) -> bool:
    """Pump the sync Playwright event loop while polling the request log."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if count_requests(requests, needle) >= minimum:
            return True
        page.wait_for_timeout(50)
    return count_requests(requests, needle) >= minimum


def set_visibility(page: Page, state: str) -> None:
    page.evaluate(
        """(state) => {
          Object.defineProperty(document, 'visibilityState', {
            configurable: true,
            get: () => state,
          });
          Object.defineProperty(document, 'hidden', {
            configurable: true,
            get: () => state === 'hidden',
          });
          document.dispatchEvent(new Event('visibilitychange'));
        }""",
        state,
    )


def main_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors, requests = watch(page)

    # W08-07: illegal or out-of-range query values fall back to defaults and
    # the path is left alone.
    page.goto(f"{base}/market?top=999&date=2026-13-01&board=bad&theme=none")
    page.get_by_test_id("market-session").wait_for(state="visible")
    page.get_by_test_id("industry-table").wait_for(state="visible")
    check(
        urllib.parse.urlparse(page.url).path == "/market",
        "W08-07 illegal query keeps the /market path",
    )
    select = page.get_by_label("显示条数")
    check(select.input_value() == "20", "W08-07 illegal top falls back to 20")
    check(
        page.get_by_label("强势股日期").input_value() == "",
        "W08-07 illegal date falls back to latest",
    )
    check(page.get_by_role("dialog").count() == 0, "W08-07 illegal board keeps drawer closed")
    check(
        page.get_by_test_id("theme-chip").count() == 9,
        "W08-07 illegal theme falls back to all themes",
    )

    # W08-01: session bar and three index cards with time and source.
    session = page.get_by_test_id("market-session").inner_text()
    check(
        "交易中" in session
        and "最近更新 11-05 09:30" in session
        and "来源 多源" in session,
        f"W08-01 session bar shows session, update time and source ({session!r})",
    )
    cards = page.get_by_test_id("index-card")
    check(cards.count() == 3, f"W08-01 three index cards ({cards.count()})")
    first_card = cards.nth(0).inner_text()
    check(
        all(
            part in first_card
            for part in ("上证指数", "000001.SH", "3345.12", "+0.42%", "+13.98")
        ),
        f"W08-01 index card carries price/change ({first_card!r})",
    )
    check(
        "11-05 09:30" in first_card and "多源" in first_card,
        "W08-01 index card carries data time and source",
    )

    # W08-02: top 20, bottom group, leader and up/down counts.
    top_rows = page.locator('[data-testid="industry-row"][data-variant="top"]')
    bottom_rows = page.locator('[data-testid="industry-row"][data-variant="bottom"]')
    check(top_rows.count() == 20, f"W08-02 industry top 20 ({top_rows.count()})")
    check(bottom_rows.count() == 5, f"W08-02 industry bottom 5 ({bottom_rows.count()})")
    first_row = top_rows.nth(0).inner_text()
    check(
        all(part in first_row for part in ("行业01", "+4.50%", "40", "2", "龙头01")),
        f"W08-02 industry row shows leader and breadth ({first_row!r})",
    )
    check(
        section(page, "industries").get_by_text("涨幅末位").is_visible(),
        "W08-02 bottom group has its own label",
    )

    # W08-04: themes aggregate from reason and filter the current list.
    strong_rows = page.get_by_test_id("strong-row")
    check(strong_rows.count() == 12, f"W08-04 strong table has all rows ({strong_rows.count()})")
    chips = page.get_by_test_id("theme-chip")
    check(chips.count() == 9, f"W08-04 theme chips are TOP8 plus 全部 ({chips.count()})")
    page.get_by_test_id("theme-chips").get_by_role("button", name="算力", exact=True).click()
    page.wait_for_function("document.querySelectorAll('[data-testid=\"strong-row\"]').length === 3")
    check(
        "theme=" in page.url and strong_rows.count() == 3,
        "W08-04 theme filter keeps only the current list's matches",
    )
    check(
        page.get_by_role("button", name="算力", exact=True).get_attribute("aria-pressed")
        == "true",
        "W08-04 active theme chip is pressed",
    )
    page.get_by_role("button", name="全部", exact=True).click()
    page.wait_for_function("document.querySelectorAll('[data-testid=\"strong-row\"]').length === 12")
    check("theme=" not in page.url, "W08-04 全部 clears the theme query")
    check(
        page.get_by_test_id("strong-row").nth(3).inner_text().find("225.50") >= 0,
        "W08-04 strong rows show price",
    )

    # W08-05: plain text with only http(s) links, opened safely.
    items = page.get_by_test_id("newsflash-item")
    check(items.count() == 3, f"W08-05 newsflash items ({items.count()})")
    link = page.get_by_test_id("newsflash-link")
    check(link.count() == 1, f"W08-05 only one http text link ({link.count()})")
    check(
        link.get_attribute("href") == "https://example.com/news?id=1",
        "W08-05 trailing CJK punctuation is not part of the href",
    )
    check(
        link.get_attribute("target") == "_blank"
        and link.get_attribute("rel") == "noopener noreferrer",
        "W08-05 external link opens in a new window without an opener",
    )
    news_text = section(page, "newsflash").inner_text()
    check(
        "<script>alert(1)</script>" in news_text,
        "W08-05 script tag stays visible text",
    )
    check(
        section(page, "newsflash").locator("script").count() == 0
        and page.locator('a[href^="javascript:"]').count() == 0,
        "W08-05 script and javascript: links stay inert",
    )

    # W08-07: controls write canonical query values.
    select.select_option("10")
    page.wait_for_function(
        "new URLSearchParams(location.search).get('top') === '10'"
    )
    page.wait_for_function("document.querySelectorAll('[data-testid=\"industry-row\"]').length === 15")
    check(
        page.locator('[data-testid="industry-row"][data-variant="top"]').count() == 10,
        "W08-07 top control refetches and renders Top 10",
    )
    check(
        any("/api/v1/market/industries?top=10" in url for _, url in requests),
        "W08-07 top control sends top=10",
    )
    page.get_by_label("强势股日期").fill("2026-11-04")
    page.wait_for_function(
        "new URLSearchParams(location.search).get('date') === '2026-11-04'"
    )
    check(
        wait_for_request(page, requests, "date=2026-11-04"),
        "W08-07 date control sends date=2026-11-04",
    )
    page.screenshot(path=str(SHOTS / "market_1440.png"), full_page=True)

    # R-11: industry -> constituents -> stock -> back restores five things.
    page.evaluate("document.getElementById('main-content').scrollTop = 620")
    row = page.locator('[data-code="BK1006"]')
    row.click()
    drawer = page.get_by_role("dialog")
    drawer.wait_for(state="visible")
    page.wait_for_function(
        "document.querySelectorAll('[data-testid=\"constituent-row\"]').length === 10"
    )
    check(
        "行业07 · 成分股" in drawer.inner_text(),
        "R-11 drawer names the selected industry",
    )
    check(
        drawer.get_by_test_id("constituent-row").count() == 10,
        "R-11 drawer lists the top 10 constituents",
    )
    check(
        "board=BK1006" in page.url and row.get_attribute("data-active") == "true",
        "R-11 selected industry is written to the query and highlighted",
    )
    saved_scroll = scroll_top(page)
    drawer.get_by_test_id("constituent-row").nth(0).click()
    page.wait_for_url(
        lambda url: "/stocks/600000" in url and "tab=valuation" in url
    )
    page.get_by_test_id("page-stock").wait_for(state="visible")
    check(
        "tab=valuation" in page.url and page.get_by_test_id("page-stock").is_visible(),
        "R-11 constituent drills into /stocks/:ticker?tab=valuation",
    )

    page.go_back()
    page.get_by_test_id("page-market").wait_for(state="visible")
    page.get_by_test_id("industry-table").wait_for(state="visible")
    drawer = page.get_by_role("dialog")
    drawer.wait_for(state="visible")
    check(
        page.get_by_label("显示条数").input_value() == "10",
        "W08-08 back restores topN",
    )
    check(
        page.get_by_label("强势股日期").input_value() == "2026-11-04",
        "W08-08 back restores the strong-stock date",
    )
    check(
        page.locator('[data-code="BK1006"]').get_attribute("data-active") == "true",
        "W08-08 back restores the selected industry",
    )
    check(
        drawer.get_by_test_id("constituent-row").count() == 10,
        "W08-08 back reopens the constituent drawer",
    )
    try:
        page.wait_for_function(
            f"document.getElementById('main-content').scrollTop >= {max(saved_scroll - 4, 0)}",
            timeout=5000,
        )
        restored = scroll_top(page)
    except Exception:  # noqa: BLE001 - reported as a failed check below
        restored = scroll_top(page)
    check(
        saved_scroll > 0 and abs(restored - saved_scroll) <= 4,
        f"W08-08 back restores scroll ({restored} vs {saved_scroll})",
    )
    page.screenshot(path=str(SHOTS / "market_returned.png"))

    # Refresh is not a back navigation: it starts at the top.
    page.reload()
    page.get_by_test_id("industry-table").wait_for(state="visible")
    page.wait_for_timeout(400)
    check(scroll_top(page) == 0, f"W08-08 refresh starts at the top ({scroll_top(page)})")

    check(
        all(method == "GET" for method, _ in requests),
        "R-10 market reads are all GET",
    )
    check(not errors, f"R-10/R-11 desktop console/page errors: {errors}")
    context.close()


def states_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context, "states")
    page = context.new_page()
    errors, requests = watch(page)
    page.goto(f"{base}/market")
    page.get_by_test_id("market-session").wait_for(state="visible")

    overview = section(page, "overview")
    check(
        overview.get_by_test_id("stale-banner").is_visible()
        and "超过新鲜度阈值" in overview.get_by_test_id("stale-banner").inner_text(),
        "W08-06 stale block shows its banner and reason",
    )
    check(
        overview.get_by_test_id("partial-notice").is_visible()
        and overview.get_by_test_id("partial-blocks").inner_text() == "指数",
        "W08-06 partial notice names the failed block",
    )

    industries_section = section(page, "industries")
    check(
        industries_section.get_by_test_id("data-state-error").is_visible(),
        "W08-06 industries error keeps the other blocks alive",
    )
    before = len([url for _, url in requests if "/market/industries?" in url])
    industries_section.get_by_role("button", name="重试").click()
    page.wait_for_function(
        "document.querySelector('section[aria-labelledby=\"market-industries\"] [data-state=\"error\"]') !== null"
    )
    page.wait_for_timeout(300)
    after = len([url for _, url in requests if "/market/industries?" in url])
    check(after > before, f"W08-06 block retry refetches only that block ({before}->{after})")

    strong_section = section(page, "strong")
    check(
        strong_section.get_by_test_id("data-state-empty").is_visible()
        and "非交易日或盘后未更新" in strong_section.inner_text(),
        "W08-04 empty strong stocks use the non-trading copy",
    )
    news_section = section(page, "newsflash")
    check(
        news_section.get_by_test_id("stale-banner").is_visible()
        and "已使用备用数据源" in news_section.inner_text()
        and news_section.get_by_test_id("newsflash-item").count() == 3,
        "W08-06 newsflash stale keeps its content",
    )
    page.screenshot(path=str(SHOTS / "market_states.png"), full_page=True)
    check(not errors, f"R-10 states console/page errors: {errors}")
    context.close()


def refresh_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors, requests = watch(page)
    overview = "/api/v1/market/overview"
    blocks = {
        overview: "overview",
        "/api/v1/market/industries?": "industries",
        "/api/v1/market/strong-stocks": "strong stocks",
        "/api/v1/market/newsflash": "newsflash",
    }

    page.goto(f"{base}/market")
    page.get_by_test_id("industry-table").wait_for(state="visible")

    # R-15: while visible the overview polls on its contract interval (10s).
    before = count_requests(requests, overview)
    started = time.monotonic()
    polled = wait_for_count(page, requests, overview, before + 1, timeout=15.0)
    elapsed = time.monotonic() - started
    check(
        polled and 8.5 <= elapsed <= 15.0,
        f"R-15 visible tab polls overview on the 10s interval ({elapsed:.1f}s)",
    )

    # R-15: hidden tabs fall back to the 60s floor, so 12s stays quiet.
    before = count_requests(requests, overview)
    set_visibility(page, "hidden")
    page.wait_for_timeout(12_000)
    hidden_delta = count_requests(requests, overview) - before
    check(
        hidden_delta == 0,
        f"R-15 hidden tab drops the 10s poll to the 60s floor ({hidden_delta} reads)",
    )

    # R-15: returning to the foreground refetches at once, not on the next tick.
    foreground = {needle: count_requests(requests, needle) for needle in blocks}
    set_visibility(page, "visible")
    check(
        wait_for_count(
            page, requests, overview, foreground[overview] + 1, timeout=3.0
        ),
        "R-15 returning to the foreground refetches immediately",
    )
    # The same foreground group refetches the other blocks too; let all four
    # land before sampling the burst baseline, or a late request from this
    # group is counted as part of the next one.
    for needle in blocks:
        wait_for_count(page, requests, needle, foreground[needle] + 1, timeout=3.0)

    # R-15: a click burst is one 500ms debounced request group.
    before = {needle: count_requests(requests, needle) for needle in blocks}
    for _ in range(3):
        page.get_by_test_id("market-refresh").click()
    page.wait_for_timeout(250)
    early = {
        name: count_requests(requests, needle) - before[needle]
        for needle, name in blocks.items()
    }
    check(
        all(delta == 0 for delta in early.values()),
        f"R-15 refresh holds the burst inside the debounce window ({early})",
    )
    wait_for_count(page, requests, overview, before[overview] + 1, timeout=3.0)
    page.wait_for_timeout(700)
    after = {
        name: count_requests(requests, needle) - before[needle]
        for needle, name in blocks.items()
    }
    check(
        all(delta == 1 for delta in after.values()),
        f"R-15 one refresh group reads every block once ({after})",
    )

    # R-15: leaving the page clears the interval instead of polling in the
    # background.
    page.locator('aside[aria-label="主导航"]').get_by_role(
        "link", name="任务", exact=True
    ).click()
    page.wait_for_url(lambda url: url.rstrip("/").endswith("/jobs"))
    page.get_by_test_id("page-jobs").wait_for(state="visible")
    before = count_requests(requests, overview)
    page.wait_for_timeout(12_000)
    left_delta = count_requests(requests, overview) - before
    check(
        left_delta == 0,
        f"R-15 leaving the market page clears its poll timer ({left_delta} reads)",
    )

    check(
        all(method == "GET" for method, _ in requests),
        "R-15 refresh and polling stay read-only",
    )
    check(not errors, f"R-15 console/page errors: {errors}")
    context.close()


def touch_violations(page: Page, selectors: list[str]) -> list[str]:
    script = """
    (selectors) => selectors.flatMap((selector) =>
      Array.from(document.querySelectorAll(selector))
        .map((node) => ({ selector, rect: node.getBoundingClientRect() }))
        .filter(({ rect }) => rect.width > 0 && rect.height > 0)
        .filter(({ rect }) => rect.height < 43.5)
        .map(({ selector, rect }) =>
          selector + ":" + Math.round(rect.width) + "x" + Math.round(rect.height))
    )
    """
    return page.evaluate(script, selectors)


PAGE_TOUCH_SELECTORS = [
    '[data-testid="industry-card"]',
    '[data-testid="strong-card"] a',
    '[data-testid="theme-chip"]',
    "select",
    'input[type="date"]',
    'section[aria-labelledby="market-strong"] button',
]

BOARD_TOUCH_SELECTORS = [
    '[data-testid="board-stock-row"]',
    '[aria-label="关闭成分股"]',
]


def mobile_flow(
    browser: Browser,
    base: str,
    width: int,
    height: int,
    tag: str,
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors, requests = watch(page)
    page.goto(f"{base}/market")
    page.get_by_test_id("market-session").wait_for(state="visible")
    page.get_by_test_id("index-strip").wait_for(state="visible")
    page.get_by_test_id("industry-cards").wait_for(state="visible")
    page.wait_for_function(
        "document.querySelectorAll('[data-testid=\"strong-card\"]').length === 12"
    )

    # W08M-01: the index strip scrolls inside its own container; the page
    # itself never gains a horizontal scrollbar.
    metrics = page.evaluate(
        """() => {
          const strip = document.querySelector('[data-testid="index-strip"]');
          const main = document.getElementById('main-content');
          return {
            stripScroll: strip.scrollWidth,
            stripClient: strip.clientWidth,
            docScroll: document.documentElement.scrollWidth,
            docClient: document.documentElement.clientWidth,
            mainScroll: main.scrollWidth,
            mainClient: main.clientWidth,
          };
        }"""
    )
    check(
        metrics["stripScroll"] > metrics["stripClient"],
        f"{tag} W08M-01 index strip overflows horizontally "
        f"({metrics['stripScroll']} > {metrics['stripClient']})",
    )
    check(
        metrics["docScroll"] == metrics["docClient"],
        f"{tag} W08M-01 document width fits the viewport "
        f"({metrics['docScroll']} vs {metrics['docClient']})",
    )
    check(
        metrics["mainScroll"] == metrics["mainClient"],
        f"{tag} W08M-01 scroll container width fits "
        f"({metrics['mainScroll']} vs {metrics['mainClient']})",
    )
    page.screenshot(path=str(SHOTS_MOBILE / f"market_{tag}.png"), full_page=True)

    # W08M-02: industries and strong stocks are cards; no table reaches the DOM.
    top_cards = page.locator('[data-testid="industry-card"][data-variant="top"]')
    bottom_cards = page.locator(
        '[data-testid="industry-card"][data-variant="bottom"]'
    )
    check(top_cards.count() == 20, f"{tag} W08M-02 top 20 industry cards ({top_cards.count()})")
    check(
        bottom_cards.count() == 5,
        f"{tag} W08M-02 bottom 5 industry cards ({bottom_cards.count()})",
    )
    first_card_text = top_cards.nth(0).inner_text()
    check(
        all(
            part in first_card_text
            for part in ("行业01", "+4.50%", "上涨 40", "下跌 2", "龙头01")
        ),
        f"{tag} W08M-02 industry card shows rank, change and breadth "
        f"({first_card_text!r})",
    )
    check(
        page.get_by_test_id("strong-card").count() == 12,
        f"{tag} W08M-02 all 12 strong stocks render as cards "
        f"({page.get_by_test_id('strong-card').count()})",
    )
    check(
        page.get_by_test_id("theme-chip").count() == 9,
        f"{tag} W08M-02 theme chips survive on mobile "
        f"({page.get_by_test_id('theme-chip').count()})",
    )
    check(
        page.locator("table").count() == 0,
        f"{tag} W08M-02 no table element in the DOM ({page.locator('table').count()})",
    )
    check(
        page.get_by_test_id("industry-table").count() == 0
        and page.get_by_test_id("strong-table").count() == 0,
        f"{tag} W08M-02 desktop table components are not mounted",
    )

    # W08M-04: controls and cards meet the 44px touch target.
    page_violations = touch_violations(page, PAGE_TOUCH_SELECTORS)
    check(
        not page_violations,
        f"{tag} W08M-04 page controls are at least 44px tall ({page_violations})",
    )

    # W08M-03: tapping an industry opens the full-screen board; closing or
    # coming back restores the original scroll position.
    page.evaluate("document.getElementById('main-content').scrollTop = 500")
    page.wait_for_function(
        "document.getElementById('main-content').scrollTop === 500"
    )
    first = page.locator('[data-code="BK1003"]')
    first.click()
    saved_scroll = scroll_top(page)
    dialog = page.get_by_test_id("board-stocks-dialog")
    dialog.wait_for(state="visible")
    page.wait_for_function(
        "document.querySelectorAll('[data-testid=\"board-stock-row\"]').length === 10"
    )
    check(
        "行业04 · 成分股" in dialog.inner_text(),
        f"{tag} W08M-03 board layer names the selected industry",
    )
    check(
        "board=BK1003" in page.url,
        f"{tag} W08M-03 board query drives the layer ({page.url})",
    )
    check(
        page.get_by_test_id("board-stock-row").count() == 10,
        f"{tag} W08M-03 board lists 10 constituents "
        f"({page.get_by_test_id('board-stock-row').count()})",
    )
    box = dialog.bounding_box()
    check(
        box is not None
        and abs(box["x"]) <= 1
        and abs(box["y"]) <= 1
        and abs(box["width"] - width) <= 1
        and abs(box["height"] - height) <= 1,
        f"{tag} W08M-03 board fills the viewport ({box})",
    )
    check(
        dialog.evaluate("(node) => node.scrollWidth === node.clientWidth"),
        f"{tag} W08M-03 board layer has no horizontal overflow",
    )
    board_violations = touch_violations(page, BOARD_TOUCH_SELECTORS)
    check(
        not board_violations,
        f"{tag} W08M-04 board targets are at least 44px tall ({board_violations})",
    )
    page.screenshot(path=str(SHOTS_MOBILE / f"market_{tag}_dialog.png"))

    dialog.get_by_role("button", name="关闭成分股").click()
    page.wait_for_function(
        "document.querySelector('[data-testid=\"board-stocks-dialog\"]') === null"
    )
    check(
        "board=" not in page.url,
        f"{tag} W08M-03 closing clears the board query ({page.url})",
    )
    check(
        abs(scroll_top(page) - saved_scroll) <= 4,
        f"{tag} W08M-03 closing keeps the scroll position "
        f"({scroll_top(page)} vs {saved_scroll})",
    )

    first.click()
    page.get_by_test_id("board-stocks-dialog").wait_for(state="visible")
    page.wait_for_function(
        "document.querySelectorAll('[data-testid=\"board-stock-row\"]').length === 10"
    )
    page.get_by_test_id("board-stock-row").first.click()
    page.wait_for_url(lambda url: "/stocks/600000" in url and "tab=valuation" in url)
    page.get_by_test_id("page-stock").wait_for(state="visible")
    check(
        "tab=valuation" in page.url,
        f"{tag} W08M-03 a constituent drills into /stocks/:ticker?tab=valuation",
    )

    page.go_back()
    page.get_by_test_id("page-market").wait_for(state="visible")
    page.get_by_test_id("board-stocks-dialog").wait_for(state="visible")
    page.wait_for_function(
        "document.querySelectorAll('[data-testid=\"board-stock-row\"]').length === 10"
    )
    check(
        "board=BK1003" in page.url,
        f"{tag} W08M-03 back reopens the board from the query ({page.url})",
    )
    try:
        page.wait_for_function(
            f"Math.abs(document.getElementById('main-content').scrollTop - {saved_scroll}) <= 4",
            timeout=5000,
        )
        restored = scroll_top(page)
    except Exception:  # noqa: BLE001 - reported as a failed check below
        restored = scroll_top(page)
    check(
        saved_scroll > 0 and abs(restored - saved_scroll) <= 4,
        f"{tag} W08M-03 back restores scroll ({restored} vs {saved_scroll})",
    )

    check(
        all(method == "GET" for method, _ in requests),
        f"{tag} W08M-04 mobile reads are all GET",
    )
    check(not errors, f"{tag} W08M-01..04 console/page errors: {errors}")
    context.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    SHOTS_MOBILE.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()
    with Server() as base:
        print(f"preview at {base}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            main_flow(browser, base)
            states_flow(browser, base)
            refresh_flow(browser, base)
            mobile_flow(browser, base, 390, 844, "390")
            mobile_flow(browser, base, 360, 800, "360")
            browser.close()

    result = {
        "ticket": "P4-11",
        "checks": checks,
        "failures": failures,
        "screenshots": [
            str(SHOTS.relative_to(ROOT)),
            str(SHOTS_MOBILE.relative_to(ROOT)),
        ],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())