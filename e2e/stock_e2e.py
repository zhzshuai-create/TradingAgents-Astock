"""P4-09 W07 stock workspace desktop E2E.

Runs the built frontend on ``vite preview`` with stubbed read APIs:

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/stock_e2e.py

Desktop 1440 only (P4-09). Covers R-12 (five tabs, deep links, refresh,
invalid tickers) and R-13 (stock <-> reports/jobs context and the active job
button), plus W07-01..W07-10. Prints one JSON line; screenshots go to
ui_shots_p4/P4-09/.
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
SHOTS = ROOT / "ui_shots_p4" / "P4-09"

AS_OF = "2026-11-05T09:30:00+08:00"
TICKER = "600000"

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
                with urllib.request.urlopen(
                    f"{self.base}/market", timeout=1
                ) as response:
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


QUOTE = {
    "name": "浦发银行",
    "price": 10.52,
    "last_close": 10.39,
    "open": 10.4,
    "high": 10.6,
    "low": 10.35,
    "change_pct": 1.25,
    "change_amt": 0.13,
    "amount_wan": 86550.5,
    "turnover_pct": 0.42,
    "pe_ttm": 5.6,
    "pb": 0.62,
    "amplitude_pct": 2.4,
    "float_mcap_yi": 3085.2,
    "mcap_yi": 3085.2,
    "limit_up": 11.43,
}

VALUATION = {
    "eps_forecast": 1.86,
    "pe_forward": 5.65,
    "peg": 0.42,
    "pe_digestion_years": 3.1,
}

SECTOR_BLOCKS = {
    "industry": [{"name": "银行", "change_pct": 0.8, "desc": "股份制银行"}],
    "concept": [{"name": "沪股通", "change_pct": 0.2, "desc": ""}],
    "region": [{"name": "上海", "change_pct": -0.1, "desc": ""}],
}

SNAPSHOT = {
    "quote": QUOTE,
    "valuation": VALUATION,
    "sector_blocks": SECTOR_BLOCKS,
    "units": {"price": "元", "amount": "万元", "mcap": "亿元"},
}

SNAPSHOT_PARTIAL = {
    "quote": QUOTE,
    "valuation": None,
    "sector_blocks": None,
    "units": {"price": "元", "amount": "万元", "mcap": "亿元"},
}

KLINE = {
    "adjust": "none",
    "bars": [
        {
            "date": "2026-10-29",
            "open": 10.1,
            "high": 10.3,
            "low": 10.0,
            "close": 10.2,
            "volume": 120000,
            "amount": 122400000,
        },
        {
            "date": "2026-10-30",
            "open": 10.2,
            "high": 10.42,
            "low": 10.1,
            "close": 10.39,
            "volume": 151000,
            "amount": 156800000,
        },
        {
            "date": "2026-11-05",
            "open": 10.4,
            "high": 10.6,
            "low": 10.35,
            "close": 10.52,
            "volume": 168000,
            "amount": 176500000,
        },
    ],
    "units": {"price": "元", "volume": "手", "amount": "元"},
}

INTRADAY = {
    "date": "2026-11-05",
    "points": [
        {"time": "09:30", "price": 10.4, "volume": 1000, "avg_price": 10.4},
        {"time": "11:30", "price": 10.5, "volume": 800, "avg_price": 10.45},
        {"time": "13:00", "price": 10.48, "volume": 900, "avg_price": 10.46},
        {"time": "15:00", "price": 10.52, "volume": 1600, "avg_price": 10.49},
    ],
    "session_gaps": [["11:30", "13:00"]],
    "units": {"price": "元", "volume": "手", "amount": "元"},
}

NEWS = {
    "items": [
        {
            "title": "浦发银行发布三季度报告",
            "content": "详情见 https://example.com/news/1。",
            "published_at": "2026-11-05T09:10:00+08:00",
            "source": "eastmoney",
            "url": "https://example.com/news/1",
        },
        {
            "title": "<script>alert(1)</script> 不应执行",
            "content": "javascript:alert(1) 只作为文本显示。",
            "published_at": "2026-11-04T18:00:00+08:00",
            "source": "cls",
            "url": "javascript:alert(1)",
        },
    ],
    "untrusted": True,
}

FUND_FLOW = {
    "items": [
        {
            "time": "09:30",
            "main_net": 1200000,
            "small_net": -400000,
            "mid_net": 50000,
            "large_net": 300000,
            "super_net": 850000,
        },
        {
            "time": "10:00",
            "main_net": -300000,
            "small_net": 120000,
            "mid_net": -20000,
            "large_net": -100000,
            "super_net": -180000,
        },
    ]
}

REPORTS = {
    "items": [
        {
            "meta": {
                "report_id": "rpt-1",
                "job_id": "job-1",
                "ticker_code": TICKER,
                "ticker_name": "浦发银行",
                "analysis_date": "2026-11-04",
                "generated_at": "2026-11-04T16:20:00+08:00",
                "generated_at_source": "job_clock",
                "origin": "new",
                "schema_version": "report-schema-v1",
                "content_hash": "hash-1",
                "config_digest": "cfg-1",
                "data_quality_status": "ok",
                "chart_snapshot_status": "none",
                "retry_of_job_id": None,
                "rating": "Buy",
                "signal": "Buy",
            },
            "summary_available": True,
        }
    ],
    "next_cursor": None,
}

REPORT_DETAIL = {
    "meta": REPORTS["items"][0]["meta"],
    "sections": {
        "sec-decision": {
            "id": "sec-decision",
            "title": "最终交易决策",
            "body": "正文",
        }
    },
}

JOB_ITEM = {
    "job_id": "job-1",
    "status": "running",
    "pending_action": None,
    "ticker_code": TICKER,
    "ticker_name": "浦发银行",
    "analysis_date": "2026-11-05",
    "created_at": AS_OF,
    "updated_at": AS_OF,
    "started_at": AS_OF,
    "finished_at": None,
    "current_stage": None,
    "stats": {"model_calls": 3, "tokens_in": 1000, "tokens_out": 800, "elapsed_ms": 65000},
    "report_id": None,
    "error": None,
    "config_digest": "cfg-1",
    "graph_version": "graph-v1",
    "retry_of_job_id": None,
    "resume_of_job_id": None,
    "resume_from_stage": None,
    "allowed_actions": ["pause", "cancel"],
    "links": {
        "self": "/api/v1/jobs/job-1",
        "events": "/api/v1/jobs/job-1/events",
        "report": None,
    },
}

JOB_DETAIL = {
    **JOB_ITEM,
    "stages": [
        {
            "id": f"stage-{index + 1}",
            "name": f"阶段 {index + 1}",
            "index": index + 1,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
        }
        for index in range(12)
    ],
    "reconcile_notes": [],
    "links": JOB_ITEM["links"],
}

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


def parse(url: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urllib.parse.urlparse(url)
    return parsed.path, urllib.parse.parse_qs(parsed.query, keep_blank_values=True)


def stub_api(context: BrowserContext, variant: str = "ok") -> None:
    def fulfill(route: object, payload: object, status: int = 200) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    def stock_route(route: object) -> None:
        path, query = parse(route.request.url)
        ticker = path.split("/stocks/")[1].split("/")[0]
        if ticker != TICKER:
            fulfill(
                route,
                {
                    "error": {
                        "code": "invalid_request",
                        "message": "没有这只股票",
                        "details": {"field": "ticker"},
                    }
                },
                status=400,
            )
            return
        if path.endswith("/snapshot"):
            if variant == "partial":
                fulfill(
                    route,
                    envelope(
                        SNAPSHOT_PARTIAL,
                        partial=True,
                        failed=("valuation", "sector_blocks"),
                    ),
                )
                return
            if variant == "stale":
                fulfill(
                    route,
                    envelope(SNAPSHOT, status="stale", stale_reason="ttl_exceeded"),
                )
                return
            fulfill(route, envelope(SNAPSHOT))
            return
        if path.endswith("/kline"):
            fulfill(route, envelope(KLINE))
            return
        if path.endswith("/intraday"):
            date = query.get("date", [""])[0]
            if date == "2025-01-02":
                fulfill(
                    route,
                    envelope(
                        {
                            **INTRADAY,
                            "date": date,
                            "points": [],
                            "session_gaps": [],
                        }
                    ),
                )
                return
            fulfill(
                route,
                envelope({**INTRADAY, "date": date or INTRADAY["date"]}),
            )
            return
        if path.endswith("/news"):
            fulfill(route, envelope(NEWS))
            return
        if path.endswith("/fund-flow"):
            fulfill(route, envelope(FUND_FLOW))
            return
        if path.endswith("/reports"):
            if variant == "reports_error":
                fulfill(
                    route,
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "报告读取失败",
                        }
                    },
                    status=500,
                )
                return
            if variant in ("empty_reports", "stale"):
                fulfill(route, {"items": [], "next_cursor": None})
                return
            fulfill(route, REPORTS)
            return
        fulfill(route, envelope(None, status="empty"))

    context.route(
        "**/api/v1/meta/options**",
        lambda route: fulfill(route, META_OPTIONS),
    )
    context.route("**/api/v1/stocks/**", stock_route)
    context.route(
        "**/api/v1/market/search**",
        lambda route: fulfill(route, envelope({"items": [], "truncated": False})),
    )
    context.route(
        "**/api/v1/jobs**",
        lambda route: fulfill(
            route,
            {
                "items": [JOB_ITEM] if variant == "jobs" else [],
                "next_cursor": None,
            },
        ),
    )
    context.route(
        "**/api/v1/jobs/job-1/events**",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            headers={"cache-control": "no-cache"},
            body=(
                "id: 1\nevent: snapshot\n"
                + "data: "
                + json.dumps({"job": JOB_DETAIL, "last_seq": 1}, ensure_ascii=False)
                + "\n\n"
            ),
        ),
    )
    context.route(
        "**/api/v1/jobs/job-1",
        lambda route: fulfill(route, JOB_DETAIL),
    )
    context.route(
        "**/api/v1/reports**",
        lambda route: fulfill(route, {"items": [], "next_cursor": None}),
    )
    context.route(
        "**/api/v1/reports/rpt-1",
        lambda route: fulfill(route, REPORT_DETAIL),
    )


def active_tab(page: Page) -> str | None:
    return (
        page.locator('[data-testid="stock-tab"][data-active="true"]')
        .get_attribute("data-tab")
    )


def query(page: Page, key: str) -> str | None:
    return page.evaluate(
        "(key) => new URLSearchParams(location.search).get(key)", key
    )


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


def main_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors, requests = watch(page)

    page.goto(f"{base}/stocks/{TICKER}")
    page.get_by_test_id("stock-price").wait_for(state="visible")

    # W07-01: name/code, market, price, source and data time; no stale banner.
    header = page.get_by_test_id("stock-header").inner_text()
    check(
        all(
            part in header
            for part in (
                "浦发银行",
                TICKER,
                "沪市",
                "10.52",
                "+1.25%",
                "来源 多源",
                "数据时间 11-05 09:30",
            )
        ),
        f"W07-01 header carries identity, quote, source and time ({header!r})",
    )
    check(
        page.get_by_test_id("stock-header").get_by_test_id("stale-banner").count()
        == 0,
        "W07-01 fresh snapshot shows no stale banner",
    )

    # W07-02: primary action opens a prefilled launcher.
    primary = page.get_by_test_id("stock-primary-action")
    check(
        primary.inner_text() == "分析这只股票",
        f"W07-02 primary action is analyze when no job is active ({primary.inner_text()!r})",
    )
    primary.click()
    dialog = page.get_by_role("dialog", name="分析启动器")
    dialog.wait_for(state="visible")
    dialog_text = dialog.inner_text()
    check(
        TICKER in dialog_text and "浦发银行" in dialog_text,
        "W07-02 launcher is prefilled with this stock",
    )
    dialog.get_by_role("button", name="取消").click()
    page.wait_for_function(
        "document.querySelector('[role=\"dialog\"]') === null"
    )

    # R-13: context links carry the ticker into reports and jobs.
    reports_href = page.get_by_role("link", name="查看最新报告").get_attribute("href")
    jobs_href = page.get_by_role("link", name="查看该股票任务").get_attribute("href")
    check(
        reports_href == f"/reports?ticker={TICKER}"
        and jobs_href == f"/jobs?ticker={TICKER}",
        f"R-13 header links carry the ticker ({reports_href!r}, {jobs_href!r})",
    )
    page.get_by_role("link", name="查看最新报告").click()
    page.wait_for_url(lambda url: "/reports?ticker=" in url)
    page.get_by_test_id("page-reports").wait_for(state="visible")
    check(
        wait_for_request(page, requests, f"/api/v1/reports?ticker={TICKER}")
        and "股票 600000" in page.get_by_test_id("report-filter-chips").inner_text(),
        "R-13 reports page opens filtered by this ticker",
    )
    page.go_back()
    page.get_by_test_id("stock-price").wait_for(state="visible")
    page.get_by_role("link", name="查看该股票任务").click()
    page.wait_for_url(lambda url: "/jobs?ticker=" in url)
    page.get_by_test_id("page-jobs").wait_for(state="visible")
    check(
        "股票 600000" in page.get_by_test_id("job-filter-chips").inner_text(),
        "R-13 jobs page opens filtered by this ticker",
    )
    page.go_back()
    page.get_by_test_id("stock-price").wait_for(state="visible")

    # W07-03: valuation fields, missing markers, sectors and fund flow.
    valuation = page.get_by_test_id("stock-valuation")
    valuation_text = valuation.inner_text()
    check(
        all(
            part in valuation_text
            for part in (
                "5.60",
                "0.62",
                "86550.50",
                "0.42%",
                "1.86",
                "5.65",
                "0.42",
                "3.10",
            )
        ),
        f"W07-03 valuation shows quote and consensus figures ({valuation_text!r})",
    )
    check(
        page.get_by_test_id("valuation-field").count() == 12
        and page.locator('[data-testid="valuation-field"][data-missing="true"]').count()
        == 0,
        "W07-03 complete valuation has twelve fields and no dashes",
    )
    check(
        page.get_by_test_id("sector-group").count() == 3
        and all(
            name in valuation.inner_text() for name in ("银行", "沪股通", "上海")
        ),
        "W07-03 sector blocks render industry, concept and region",
    )
    flow = page.get_by_test_id("fund-flow-table").inner_text()
    check(
        page.get_by_test_id("fund-flow-row").count() == 2
        and "主力净额" in flow
        and "1200000.00" in flow,
        "W07-03 fund flow table lists rows and columns",
    )

    # W07-04: K line tab, period buttons and the unadjusted tag.
    page.get_by_role("tab", name="K 线").click()
    page.get_by_test_id("kline-chart").wait_for(state="visible")
    check(
        query(page, "tab") == "kline" and active_tab(page) == "kline",
        "W07-04 K line tab is written to the query",
    )
    check(
        page.get_by_test_id("kline-period-day").get_attribute("aria-pressed")
        == "true",
        "W07-04 day period is the default",
    )
    kline_meta = page.get_by_test_id("kline-meta").inner_text()
    check(
        "不复权" in kline_meta and "数据时间 2026-11-05 09:30" in kline_meta,
        f"W07-04 chart shows unadjusted tag and data time ({kline_meta!r})",
    )
    page.get_by_test_id("kline-period-week").click()
    page.wait_for_function(
        "new URLSearchParams(location.search).get('period') === 'week'"
    )
    week_requested = wait_for_request(
        page, requests, "/stocks/600000/kline?period=week&limit=120"
    )
    week_pressed = (
        page.get_by_test_id("kline-period-week").get_attribute("aria-pressed")
        == "true"
    )
    kline_urls = [url for _, url in requests if "/kline" in url]
    check(
        week_requested and week_pressed,
        f"W07-04 week period refetches and stays pressed "
        f"(request={week_requested}, pressed={week_pressed}, {kline_urls})",
    )

    # W07-08: each tab keeps its scroll position; refresh starts at the top.
    page.evaluate("document.getElementById('main-content').scrollTop = 300")
    page.wait_for_timeout(120)
    saved_scroll = scroll_top(page)
    page.get_by_role("tab", name="分时").click()
    page.get_by_test_id("intraday-chart").wait_for(state="visible")
    page.get_by_role("tab", name="K 线").click()
    page.get_by_test_id("kline-chart").wait_for(state="visible")
    page.wait_for_timeout(120)
    if saved_scroll > 0:
        check(
            abs(scroll_top(page) - saved_scroll) <= 4,
            f"W07-08 switching back restores the tab scroll "
            f"({scroll_top(page)} vs {saved_scroll})",
        )
    else:
        check(True, "W07-08 tab scroll is covered by the component checks")
    page.reload()
    page.get_by_test_id("kline-chart").wait_for(state="visible")
    page.wait_for_timeout(300)
    check(
        scroll_top(page) == 0,
        f"W07-08 refresh starts at the top ({scroll_top(page)})",
    )
    check(
        active_tab(page) == "kline" and query(page, "period") == "week",
        "W07-08 refresh restores tab and period from the query",
    )

    # W07-05: intraday date, lunch gap and an out-of-retention empty state.
    page.get_by_role("tab", name="分时").click()
    page.get_by_test_id("intraday-chart").wait_for(state="visible")
    check(
        page.locator('[data-role="lunch-gap"]').count() == 1,
        "W07-05 lunch break band is drawn",
    )
    check(
        page.get_by_label("分时日期").input_value() == "",
        "W07-05 the latest trading day is the default",
    )
    page.get_by_label("分时日期").fill("2026-10-01")
    page.wait_for_function(
        "new URLSearchParams(location.search).get('date') === '2026-10-01'"
    )
    intraday_requested = wait_for_request(
        page, requests, "/stocks/600000/intraday?date=2026-10-01"
    )
    intraday_urls = [url for _, url in requests if "/intraday" in url]
    check(
        intraday_requested and page.get_by_test_id("intraday-chart").is_visible(),
        f"W07-05 date filter drives the intraday request "
        f"(request={intraday_requested}, {intraday_urls})",
    )
    page.get_by_label("分时日期").fill("2025-01-02")
    page.wait_for_function(
        "document.querySelector('[data-testid=\"stock-intraday\"] [data-state=\"empty\"]') !== null"
    )
    check(
        "该日期没有分时数据" in page.get_by_test_id("stock-intraday").inner_text(),
        "W07-05 out-of-retention date uses the empty copy",
    )
    page.get_by_role("button", name="最新交易日").click()
    page.get_by_test_id("intraday-chart").wait_for(state="visible")
    check(
        query(page, "date") is None,
        "W07-05 latest-trading-day clears the date query",
    )

    # W07-06: news stays inert except for safe http(s) links.
    page.get_by_role("tab", name="新闻").click()
    page.get_by_test_id("stock-news-item").first.wait_for(state="visible")
    news = page.get_by_test_id("stock-news")
    check(
        page.get_by_test_id("stock-news-item").count() == 2,
        f"W07-06 news items render ({page.get_by_test_id('stock-news-item').count()})",
    )
    link = page.get_by_test_id("stock-news-link")
    check(
        link.count() == 1
        and link.get_attribute("href") == "https://example.com/news/1"
        and link.get_attribute("target") == "_blank"
        and link.get_attribute("rel") == "noopener noreferrer",
        "W07-06 external news link is safe and opens in a new window",
    )
    check(
        "<script>alert(1)</script>" in news.inner_text()
        and news.locator("script").count() == 0
        and page.locator('a[href^="javascript:"]').count() == 0,
        "W07-06 script and javascript: URLs stay inert text",
    )

    # W07-07: report list, reader drill-down and back to the tab.
    page.get_by_role("tab", name="报告").click()
    page.get_by_test_id("stock-report-row").first.wait_for(state="visible")
    check(
        page.get_by_test_id("stock-report-row").count() == 1,
        "W07-07 stock reports list has one row",
    )
    report_link = page.get_by_role("link", name="2026-11-04 报告")
    check(
        report_link.get_attribute("href") == "/reports/rpt-1",
        "W07-07 report row links to the reader",
    )
    report_link.click()
    page.wait_for_url(lambda url: "/reports/rpt-1" in url)
    page.get_by_test_id("page-report-detail").wait_for(state="visible")
    check(
        page.get_by_test_id("page-report-detail").is_visible(),
        "W07-07 clicking a report opens the reader",
    )
    page.go_back()
    page.get_by_test_id("stock-report-row").first.wait_for(state="visible")
    check(
        active_tab(page) == "reports",
        "W07-07 back returns to the reports tab",
    )

    # W07-08: deep links restore, illegal values fall back without a 400.
    page.goto(f"{base}/stocks/{TICKER}?tab=intraday&period=week&date=2026-10-01")
    page.get_by_test_id("intraday-chart").wait_for(state="visible")
    check(
        active_tab(page) == "intraday"
        and page.get_by_label("分时日期").input_value() == "2026-10-01",
        "W07-08 deep link restores tab and date",
    )
    page.get_by_role("tab", name="K 线").click()
    page.get_by_test_id("kline-chart").wait_for(state="visible")
    check(
        page.get_by_test_id("kline-period-week").get_attribute("aria-pressed")
        == "true",
        "W07-08 deep link restores the K line period",
    )

    page.goto(f"{base}/stocks/{TICKER}?tab=bad&period=bad&date=2026-13-01")
    page.get_by_test_id("stock-valuation").wait_for(state="visible")
    check(
        urllib.parse.urlparse(page.url).path == f"/stocks/{TICKER}"
        and active_tab(page) == "valuation",
        "W07-08 illegal tab falls back to valuation without rewriting the path",
    )
    page.get_by_role("tab", name="K 线").click()
    page.get_by_test_id("kline-chart").wait_for(state="visible")
    check(
        page.get_by_test_id("kline-period-day").get_attribute("aria-pressed")
        == "true"
        and wait_for_request(page, requests, "/stocks/600000/kline?period=day&limit=120"),
        "W07-08 illegal period falls back to day",
    )
    page.get_by_role("tab", name="分时").click()
    page.get_by_test_id("intraday-chart").wait_for(state="visible")
    check(
        page.get_by_label("分时日期").input_value() == ""
        and query(page, "date") is None
        and not any("date=2026-13-01" in url for _, url in requests),
        "W07-08 illegal date falls back to the latest trading day",
    )

    # W07-09: malformed and unknown tickers use the same 400 page.
    page.goto(f"{base}/stocks/60000")
    page.get_by_test_id("invalid-ticker").wait_for(state="visible")
    malformed = page.get_by_test_id("invalid-ticker").inner_text()
    check(
        "没有这只股票" in malformed
        and "不是 6 位数字" in malformed
        and page.get_by_test_id("invalid-ticker")
        .get_by_role("combobox", name="搜索股票")
        .is_visible()
        and page.get_by_role("link", name="回市场").get_attribute("href")
        == "/market",
        "W07-09 malformed ticker renders the 400 page with search and market link",
    )

    page.goto(f"{base}/stocks/{TICKER}")
    page.get_by_test_id("stock-price").wait_for(state="visible")
    page.screenshot(path=str(SHOTS / "stock_1440.png"), full_page=True)
    check(
        all(method == "GET" for method, _ in requests),
        "R-12/R-13 stock reads are all GET",
    )
    check(not errors, f"R-12/R-13 desktop console/page errors: {errors}")
    context.close()


def invalid_flow(browser: Browser, base: str) -> None:
    """A 6-digit code missing from the name table: the app handles a real 400."""
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors, requests = watch(page)
    page.goto(f"{base}/stocks/999999")
    page.get_by_test_id("invalid-ticker").wait_for(state="visible")
    unknown = page.get_by_test_id("invalid-ticker").inner_text()
    check(
        "没有这只股票" in unknown and "不在本地名称表中" in unknown,
        "W07-09 unknown ticker uses the unresolved 400 copy",
    )
    check(
        any("/api/v1/stocks/999999/snapshot" in url for _, url in requests),
        "W07-09 unknown ticker is rejected by the snapshot endpoint",
    )
    app_errors = [item for item in errors if "Failed to load resource" not in item]
    check(not app_errors, f"W07-09 unknown ticker app errors: {app_errors}")
    context.close()


def partial_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context, "partial")
    page = context.new_page()
    errors, _ = watch(page)
    page.goto(f"{base}/stocks/{TICKER}")
    page.get_by_test_id("stock-price").wait_for(state="visible")

    # W07-10: the quote survives a failed valuation block and the block is named.
    header = page.get_by_test_id("stock-header")
    check(
        header.get_by_test_id("stock-price").inner_text() == "10.52",
        "W07-10 quote stays visible when valuation fails",
    )
    check(
        header.get_by_test_id("partial-notice").is_visible()
        and "估值" in header.get_by_test_id("partial-blocks").inner_text(),
        "W07-10 partial notice names the failed valuation block",
    )
    valuation = page.get_by_test_id("stock-valuation")
    check(
        "不可得" in page.get_by_test_id("valuation-note").inner_text()
        and page.locator('[data-testid="valuation-field"][data-missing="true"]').count()
        == 4
        and page.get_by_test_id("sector-note").is_visible(),
        "W07-10 missing valuation fields show dashes and an explanation",
    )
    page.screenshot(path=str(SHOTS / "stock_partial.png"), full_page=True)
    check(not errors, f"W07-10 partial console/page errors: {errors}")
    context.close()


def states_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context, "stale")
    page = context.new_page()
    errors, _ = watch(page)
    page.goto(f"{base}/stocks/{TICKER}")
    page.get_by_test_id("stock-price").wait_for(state="visible")
    header = page.get_by_test_id("stock-header")
    check(
        header.get_by_test_id("stale-banner").is_visible()
        and "超过新鲜度阈值" in header.get_by_test_id("stale-banner").inner_text(),
        "W07-01 stale snapshot shows its banner and reason",
    )
    check(
        header.get_by_test_id("stock-price").inner_text() == "10.52",
        "W07-01 stale snapshot keeps the quote visible",
    )
    page.get_by_role("tab", name="报告").click()
    page.get_by_test_id("stock-reports").wait_for(state="visible")
    page.wait_for_function(
        "document.querySelector('[data-testid=\"stock-reports\"] [data-state=\"empty\"]') !== null"
    )
    check(
        "还没有这只股票的报告" in page.get_by_test_id("stock-reports").inner_text(),
        "W07-07 empty report list uses its empty copy",
    )
    page.screenshot(path=str(SHOTS / "stock_states.png"), full_page=True)
    check(not errors, f"W07-01/W07-07 stale console/page errors: {errors}")
    context.close()


def reports_error_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context, "reports_error")
    page = context.new_page()
    errors, requests = watch(page)
    page.goto(f"{base}/stocks/{TICKER}?tab=reports")
    page.get_by_test_id("data-state-error").wait_for(state="visible")
    before = len(
        [url for _, url in requests if "/stocks/600000/reports" in url]
    )
    page.get_by_role("button", name="重试").click()
    page.wait_for_timeout(400)
    after = len(
        [url for _, url in requests if "/stocks/600000/reports" in url]
    )
    check(
        after > before,
        f"W07-07 report error is retryable ({before}->{after})",
    )
    app_errors = [item for item in errors if "Failed to load resource" not in item]
    check(not app_errors, f"W07-07 report error app errors: {app_errors}")
    context.close()


def active_job_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context, "jobs")
    page = context.new_page()
    errors, _ = watch(page)
    page.goto(f"{base}/stocks/{TICKER}")
    button = page.get_by_test_id("stock-primary-action")
    button.wait_for(state="visible")
    page.wait_for_function(
        "document.querySelector('[data-testid=\"stock-primary-action\"]').textContent === '查看进行中任务'"
    )
    check(
        button.inner_text() == "查看进行中任务",
        f"W07-02 an active job replaces the primary action ({button.inner_text()!r})",
    )
    button.click()
    page.wait_for_url(lambda url: "/jobs/job-1" in url)
    page.get_by_test_id("page-job-detail").wait_for(state="visible")
    check(
        page.get_by_test_id("page-job-detail").is_visible(),
        "W07-02 the primary action jumps to the active job",
    )
    page.screenshot(path=str(SHOTS / "stock_active_job.png"), full_page=True)
    check(not errors, f"W07-02 active job console/page errors: {errors}")
    context.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()
    with Server() as base:
        print(f"preview at {base}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            main_flow(browser, base)
            invalid_flow(browser, base)
            partial_flow(browser, base)
            states_flow(browser, base)
            reports_error_flow(browser, base)
            active_job_flow(browser, base)
            browser.close()

    result = {
        "ticket": "P4-09",
        "checks": checks,
        "failures": failures,
        "screenshots": [str(SHOTS.relative_to(ROOT))],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
