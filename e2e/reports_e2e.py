"""P3-04 / A14 / M06: report library filters, paging, table and mobile cards.

Runs the built frontend on ``vite preview`` with a read-only reports API. Every
non-GET request and every non-reports API call is recorded and must stay empty.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/reports_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p3/P3-04/.
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
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p3" / "P3-04"
YEAR = datetime.now().year

failures: list[str] = []
checks = 0

ListRequest = dict[str, str]

RATINGS = ["Buy", "Overweight", "Hold", "Underweight", "Sell", "unknown"]

META = {
    "app_version": "0.9.0",
    "server_time": "2026-11-06T09:30:00+08:00",
    "default_analysis_date": "2026-11-06",
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
        end = time.monotonic() + 30.0
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                output = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"vite preview exited early:\n{output}")
            try:
                with urllib.request.urlopen(
                    f"{self.base}/reports", timeout=1
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


def report(
    report_id: str,
    rating: str,
    signal: str,
    name: str,
    code: str,
    analysis_date: str,
    origin: str,
    generated_at: str | None,
) -> dict:
    return {
        "meta": {
            "report_id": report_id,
            "job_id": "job-1" if origin == "new" else None,
            "ticker_code": code,
            "ticker_name": name,
            "analysis_date": analysis_date,
            "generated_at": generated_at,
            "generated_at_source": "unknown" if generated_at is None else "job_clock",
            "origin": origin,
            "schema_version": "report-v1",
            "content_hash": f"hash-{report_id}",
            "config_digest": "cfg-1",
            "data_quality_status": "absent" if origin == "legacy_import" else "ok",
            "chart_snapshot_status": (
                "none" if origin == "legacy_import" else "frozen"
            ),
            "retry_of_job_id": None,
            "rating": rating,
            "signal": signal,
        },
        "summary_available": True,
    }


REPORTS = [
    report(
        "r-overweight",
        "Overweight",
        "Buy",
        "贵州茅台",
        "600519",
        "2026-10-28",
        "new",
        f"{YEAR}-10-28T11:41:00+08:00",
    ),
    report(
        "r-hold",
        "Hold",
        "Hold",
        "比亚迪",
        "002594",
        "2026-10-27",
        "new",
        f"{YEAR}-10-27T15:02:00+08:00",
    ),
    report(
        "r-buy",
        "Buy",
        "Buy",
        "中芯国际",
        "688981",
        "2026-10-24",
        "new",
        f"{YEAR}-10-24T10:18:00+08:00",
    ),
    report(
        "r-legacy",
        "Sell",
        "Sell",
        "中国平安",
        "601318",
        "2026-10-20",
        "legacy_import",
        None,
    ),
    report(
        "r-unknown",
        "unknown",
        "unknown",
        "隆基绿能",
        "601012",
        "2026-10-18",
        "legacy_import",
        None,
    ),
]

MANY_REPORTS = [
    report(
        f"r-many-{index:02d}",
        "Buy",
        "Buy",
        f"测试股票 {index:02d}",
        f"{600000 + index:06d}",
        "2026-10-28",
        "new",
        f"{YEAR}-10-28T{9 + index // 12:02d}:{index % 60:02d}:00+08:00",
    )
    for index in range(22)
]


def filter_reports(items: list[dict], params: dict[str, str]) -> list[dict]:
    ratings = [value for value in params.get("rating", "").split(",") if value]
    if ratings:
        items = [item for item in items if item["meta"]["rating"] in ratings]
    ticker = params.get("ticker")
    if ticker:
        items = [item for item in items if item["meta"]["ticker_code"] == ticker]
    date_from = params.get("date_from")
    if date_from:
        items = [
            item
            for item in items
            if item["meta"]["analysis_date"] >= date_from
        ]
    date_to = params.get("date_to")
    if date_to:
        items = [item for item in items if item["meta"]["analysis_date"] <= date_to]
    return items


class ApiStub:
    """Read-only reports API; writes and unrelated APIs are failures."""

    def __init__(self, items: list[dict], page_size: int | None = None) -> None:
        self.items = items
        self.page_size = page_size
        self.writes: list[str] = []
        self.unexpected: list[str] = []
        self.requests: list[ListRequest] = []

    def install(self, context: BrowserContext) -> None:
        # LIFO: the specific handlers registered last win over the catch-all.
        context.route("**/api/**", self._other)
        context.route("**/api/v1/jobs**", self._jobs)
        context.route("**/api/v1/meta/options**", self._json(META))
        context.route("**/api/v1/reports**", self._reports)
        # `**/api/v1/reports**` also matches `/reports/<id>`; the single-segment
        # detail glob must come last so opening a row returns a ReportDTO.
        context.route("**/api/v1/reports/*", self._detail)

    @staticmethod
    def _json(payload: dict):
        def fulfill(route: object, *args: object) -> None:
            route.fulfill(  # type: ignore[attr-defined]
                status=200,
                content_type="application/json",
                body=json.dumps(payload),
            )

        return fulfill

    def _other(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        self.unexpected.append(f"{request.method} {request.url}")
        route.fulfill(  # type: ignore[attr-defined]
            status=404,
            content_type="application/json",
            body=json.dumps(
                {"error": {"code": "not_found", "message": "not found"}}
            ),
        )

    def _jobs(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        if request.method != "GET":
            self.writes.append(f"{request.method} {request.url}")
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps({"items": [], "next_cursor": None}),
        )

    def _reports(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        if request.method != "GET":
            self.writes.append(f"{request.method} {request.url}")
            route.fulfill(  # type: ignore[attr-defined]
                status=202,
                content_type="application/json",
                body="{}",
            )
            return
        parsed = urllib.parse.urlparse(request.url)
        raw = urllib.parse.parse_qs(parsed.query)
        params = {key: values[0] for key, values in raw.items()}
        self.requests.append(params)
        items = filter_reports(self.items, params)
        next_cursor = None
        if self.page_size is not None:
            start = int(params.get("cursor") or 0)
            end = start + self.page_size
            next_cursor = str(end) if end < len(items) else None
            items = items[start:end]
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps({"items": items, "next_cursor": next_cursor}),
        )

    def _detail(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        if request.method != "GET":
            self.writes.append(f"{request.method} {request.url}")
            route.fulfill(  # type: ignore[attr-defined]
                status=202,
                content_type="application/json",
                body="{}",
            )
            return
        parsed = urllib.parse.urlparse(request.url)
        report_id = parsed.path.rsplit("/", 1)[-1]
        item = next(
            (
                candidate
                for candidate in self.items
                if candidate["meta"]["report_id"] == report_id
            ),
            None,
        )
        if item is None:
            route.fulfill(  # type: ignore[attr-defined]
                status=404,
                content_type="application/json",
                body=json.dumps(
                    {"error": {"code": "report_not_found", "message": "not found"}}
                ),
            )
            return
        detail = {
            "meta": item["meta"],
            "sections": {
                "sec-decision": {
                    "id": "sec-decision",
                    "title": "最终交易决策",
                    "body": "测试正文",
                }
            },
        }
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps(detail),
        )


def list_requests(stub: ApiStub) -> list[ListRequest]:
    return [params for params in stub.requests if params.get("limit") == "20"]


def wait_for_list_request(
    page: Page,
    stub: ApiStub,
    predicate: Callable[[ListRequest], bool],
    *,
    minimum: int = 1,
    timeout_ms: int = 5000,
) -> ListRequest:
    end = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < end:
        matching = [params for params in list_requests(stub) if predicate(params)]
        if len(matching) >= minimum:
            return matching[-1]
        page.wait_for_timeout(50)
    raise AssertionError(f"no list request matched after {timeout_ms} ms")


def watch_errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    return errors


def wait_rows(page: Page, count: int, timeout_ms: int = 5000) -> None:
    rows = page.get_by_test_id("report-row")
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if rows.count() == count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected {count} rows, saw {rows.count()}")


def wait_cards(page: Page, count: int, timeout_ms: int = 5000) -> None:
    cards = page.get_by_test_id("report-card")
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if cards.count() == count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected {count} cards, saw {cards.count()}")


def scroll_content_to_top(page: Page) -> None:
    page.evaluate(
        "document.getElementById('main-content')?.scrollTo({top: 0, left: 0})"
    )
    page.wait_for_timeout(150)


def deep_link_flow(browser: Browser, base: str) -> None:
    stub = ApiStub(REPORTS)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(
        f"{base}/reports?ticker=601318&date_from=2026-10-01"
        "&date_to=2026-10-31&rating=Sell"
    )
    page.get_by_test_id("page-reports").wait_for(state="visible")
    page.get_by_test_id("report-table").wait_for(state="visible")
    wait_rows(page, 1)

    params = wait_for_list_request(
        page, stub, lambda item: item.get("rating") == "Sell"
    )
    check(params.get("ticker") == "601318", f"deep link sends ticker ({params})")
    check(
        params.get("date_from") == "2026-10-01"
        and params.get("date_to") == "2026-10-31",
        f"deep link sends the date range ({params})",
    )
    check(params.get("rating") == "Sell", f"deep link sends rating ({params})")
    check(params.get("limit") == "20", f"deep link sends limit=20 ({params})")
    check(
        page.get_by_label("股票代码").input_value() == "601318",
        "deep link fills the ticker field",
    )
    check(
        page.get_by_label("开始日期").input_value() == "2026-10-01"
        and page.get_by_label("结束日期").input_value() == "2026-10-31",
        "deep link fills both dates",
    )
    check(
        page.get_by_role("checkbox", name="卖出").is_checked(),
        "deep link checks 卖出",
    )
    check(
        not page.get_by_role("checkbox", name="中性").is_checked(),
        "deep link leaves 中性 unchecked",
    )
    row_text = page.get_by_test_id("report-row").first.inner_text()
    check(
        "中国平安" in row_text
        and "历史导入" in row_text
        and "生成时间未知" in row_text,
        f"legacy row is honest about origin and time ({row_text})",
    )
    page.screenshot(
        path=str(SHOTS / "reports_1440_deep_link.png"), full_page=True
    )

    page.get_by_role("button", name="重置").click()
    page.wait_for_url(lambda url: url.endswith("/reports"))
    wait_rows(page, 5)
    wait_for_list_request(
        page,
        stub,
        lambda item: "rating" not in item
        and "ticker" not in item
        and "date_from" not in item
        and "date_to" not in item,
    )
    check(page.url == f"{base}/reports", f"reset returns to /reports ({page.url})")

    expected = ",".join(rating for rating in RATINGS if rating != "Hold")
    page.get_by_role("checkbox", name="中性").click()
    wait_rows(page, 4)
    rating_params = wait_for_list_request(
        page, stub, lambda item: item.get("rating") == expected
    )
    check(
        rating_params.get("rating") == expected,
        "unchecking 中性 requests the other five ratings",
    )
    page.wait_for_url(lambda url: "rating=" in url)

    ticker = page.get_by_label("股票代码")
    ticker.fill("601318")
    ticker.press("Enter")
    wait_rows(page, 1)
    wait_for_list_request(
        page,
        stub,
        lambda item: item.get("ticker") == "601318"
        and item.get("rating") == expected,
    )
    page.wait_for_url(lambda url: "ticker=601318" in url)

    page.get_by_label("开始日期").fill("2026-10-01")
    page.get_by_label("结束日期").fill("2026-10-31")
    # The first date fill already sends a request, so require every filter the
    # page should still be carrying; matching on dates alone accepts the stale
    # pre-ticker/deep-link requests.
    date_params = wait_for_list_request(
        page,
        stub,
        lambda item: item.get("date_from") == "2026-10-01"
        and item.get("date_to") == "2026-10-31"
        and item.get("ticker") == "601318"
        and item.get("rating") == expected,
    )
    page.wait_for_url(lambda url: "date_to=2026-10-31" in url)
    check(
        date_params.get("rating") == expected
        and date_params.get("ticker") == "601318",
        f"date change keeps the other filters ({date_params})",
    )

    url_query = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
    last = list_requests(stub)[-1]
    for key in ("rating", "ticker", "date_from", "date_to"):
        check(
            url_query.get(key, [None])[0] == last.get(key),
            f"URL and request agree on {key}",
        )
    page.screenshot(
        path=str(SHOTS / "reports_1440_filtered.png"), full_page=True
    )

    def fully_filtered(item: ListRequest) -> bool:
        return (
            item.get("rating") == expected
            and item.get("ticker") == "601318"
            and item.get("date_from") == "2026-10-01"
            and item.get("date_to") == "2026-10-31"
        )

    before = len([item for item in list_requests(stub) if fully_filtered(item)])
    page.reload()
    page.get_by_test_id("report-table").wait_for(state="visible")
    wait_rows(page, 1)
    wait_for_list_request(page, stub, fully_filtered, minimum=before + 1)
    check(
        page.get_by_role("checkbox", name="卖出").is_checked()
        and not page.get_by_role("checkbox", name="中性").is_checked(),
        "refresh keeps the rating filter",
    )
    check(
        page.get_by_label("股票代码").input_value() == "601318",
        "refresh keeps the ticker filter",
    )

    check(stub.writes == [], f"desktop filters never write ({stub.writes})")
    scroll_content_to_top(page)
    check(not errors, f"desktop console/page errors: {errors}")
    context.close()


def table_flow(browser: Browser, base: str) -> None:
    stub = ApiStub(REPORTS)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/reports")
    page.get_by_test_id("report-table").wait_for(state="visible")
    wait_rows(page, 5)

    header = page.get_by_test_id("report-table").locator("thead").inner_text()
    for label in ("评级", "股票", "分析日期", "来源", "生成时间", "信号", "摘要"):
        check(label in header, f"1440 table header contains {label}")

    rows = page.get_by_test_id("report-row")
    first = rows.nth(0).inner_text()
    check(
        "增持" in first and "贵州茅台" in first and "600519" in first,
        f"1440 first row shows rating and identity ({first})",
    )
    check(
        "AI 分析" in first and "10-28" in first and "Buy" in first,
        f"1440 new report shows origin, time and signal ({first})",
    )
    legacy = rows.nth(3).inner_text()
    check(
        "历史导入" in legacy and "生成时间未知" in legacy,
        f"1440 legacy row shows unknown time ({legacy})",
    )
    unknown = rows.nth(4).inner_text()
    check(
        "未知" in unknown and "unknown" in unknown,
        f"1440 unknown rating and signal stay literal ({unknown})",
    )
    check(
        rows.nth(0)
        .get_by_role("link", name="贵州茅台")
        .get_attribute("href")
        == "/reports/r-overweight",
        "1440 report name links to the reader route",
    )
    check(stub.writes == [], f"1440 table never writes ({stub.writes})")
    page.screenshot(path=str(SHOTS / "reports_1440.png"), full_page=True)
    scroll_content_to_top(page)
    check(not errors, f"1440 console/page errors: {errors}")
    context.close()


def return_context_flow(browser: Browser, base: str) -> None:
    stub = ApiStub(MANY_REPORTS, page_size=20)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/reports?rating=Buy")
    page.get_by_test_id("report-table").wait_for(state="visible")
    wait_rows(page, 20)

    page.get_by_role("button", name="加载更多").click()
    wait_rows(page, 22)
    wait_for_list_request(
        page, stub, lambda item: item.get("cursor") == "20"
    )
    check("cursor=20" in page.url, f"load more writes the cursor ({page.url})")

    target = page.evaluate(
        "() => {"
        "  const el = document.getElementById('main-content');"
        "  if (!el) return 0;"
        "  const top = Math.min(400, el.scrollHeight - el.clientHeight);"
        "  el.scrollTo({top});"
        "  return top;"
        "}"
    )
    page.wait_for_timeout(200)
    check(target > 100, f"the table is tall enough to scroll (target={target})")
    # Playwright scrolls a click target into view, which would destroy the
    # position under test; pick a row that is already on screen after scrolling.
    href = page.evaluate(
        "() => {"
        "  const links = [...document.querySelectorAll("
        "    '[data-testid=\"report-row\"] a'"
        "  )];"
        "  const visible = links.find((link) => {"
        "    const rect = link.getBoundingClientRect();"
        "    return rect.top > 120 && rect.bottom < window.innerHeight - 120;"
        "  });"
        "  return visible ? visible.getAttribute('href') : null;"
        "}"
    )
    check(href is not None, f"a row stays visible after scrolling (href={href})")
    before_click = page.evaluate(
        "document.getElementById('main-content').scrollTop"
    )
    check(
        abs(before_click - target) <= 5,
        f"scrolling kept the position before opening a row ({before_click})",
    )
    page.get_by_test_id("report-row").locator(f'a[href="{href}"]').click()
    page.get_by_test_id("page-report-detail").wait_for(state="visible")
    check(
        page.get_by_test_id("reader-header").is_visible(),
        "opening a row renders the report reader",
    )
    page.go_back()

    page.get_by_test_id("report-table").wait_for(state="visible")
    wait_rows(page, 22)
    check(
        "rating=Buy" in page.url and "cursor=20" in page.url,
        f"back restores filters and loaded pages ({page.url})",
    )
    end = time.monotonic() + 3.0
    top = 0.0
    while time.monotonic() < end:
        top = page.evaluate(
            "document.getElementById('main-content')?.scrollTop ?? 0"
        )
        if abs(top - target) <= 60:
            break
        page.wait_for_timeout(50)
    check(
        abs(top - target) <= 60,
        f"back restores the scroll position (scrollTop={top}, target={target})",
    )
    check(
        page.get_by_role("checkbox", name="买入").is_checked(),
        "back keeps the rating checkbox checked",
    )
    check(stub.writes == [], f"return flow never writes ({stub.writes})")
    scroll_content_to_top(page)
    check(not errors, f"return flow console/page errors: {errors}")
    context.close()


def mobile_flow(
    browser: Browser,
    base: str,
    width: int,
    height: int,
    *,
    exercise_filters: bool,
) -> None:
    label = str(width)
    stub = ApiStub(REPORTS)
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/reports")
    page.get_by_test_id("page-reports").wait_for(state="visible")
    wait_cards(page, 5)

    check(
        not page.locator("table").is_visible(),
        f"{label} does not show the desktop table",
    )
    first_card = page.get_by_test_id("report-card").first
    text = first_card.inner_text()
    check(
        "增持" in text and "贵州茅台" in text and "2026-10-28" in text,
        f"{label} card starts with rating, stock and date ({text})",
    )
    check(
        "AI 分析" in text and "生成于" in text and "Buy" in text,
        f"{label} card shows origin, generation time and signal ({text})",
    )
    legacy = page.get_by_test_id("report-card").nth(3).inner_text()
    check(
        "历史导入" in legacy and "生成时间未知" in legacy,
        f"{label} legacy card is honest about time ({legacy})",
    )
    check(
        first_card.get_attribute("href") == "/reports/r-overweight",
        f"{label} whole card links to the reader",
    )
    check(
        page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ),
        f"{label} has no page-level horizontal scroll",
    )
    page.screenshot(path=str(SHOTS / f"reports_{width}.png"), full_page=True)

    if exercise_filters:
        page.get_by_test_id("report-filter-open").get_by_role(
            "button", name="筛选"
        ).click()
        dialog = page.get_by_role("dialog", name="筛选报告")
        dialog.wait_for(state="visible")
        page.wait_for_timeout(300)
        panel = dialog.bounding_box()
        check(
            panel is not None
            and panel["width"] >= width - 1
            and panel["height"] >= height - 1,
            f"{label} filter dialog fills the viewport ({panel})",
        )
        apply_button = dialog.get_by_role("button", name="应用筛选").bounding_box()
        check(
            apply_button is not None and apply_button["height"] >= 44,
            f"{label} 应用筛选 is at least 44px tall ({apply_button})",
        )
        rating_label = dialog.get_by_test_id("filter-rating-Overweight").bounding_box()
        check(
            rating_label is not None and rating_label["height"] >= 44,
            f"{label} rating rows are at least 44px tall ({rating_label})",
        )
        dialog.get_by_role("checkbox", name="增持").click()
        dialog.get_by_role("button", name="应用筛选").click()
        dialog.wait_for(state="detached")
        wait_cards(page, 4)

        chips = page.get_by_test_id("report-filter-chip")
        chip_text = " ".join(chips.all_inner_texts())
        check("评级" in chip_text, f"{label} chips show the rating filter ({chip_text})")
        check(
            not page.locator("table").is_visible(),
            f"{label} cards remain after applying filters",
        )
        check(
            page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            ),
            f"{label} stays free of horizontal scroll after filtering",
        )
        page.screenshot(
            path=str(SHOTS / f"reports_{width}_filtered.png"), full_page=True
        )

    check(stub.writes == [], f"{label} never writes ({stub.writes})")
    check(
        stub.unexpected == [],
        f"{label} only calls the reports API ({stub.unexpected})",
    )
    scroll_content_to_top(page)
    check(not errors, f"{label} console/page errors: {errors}")
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
            deep_link_flow(browser, base)
            table_flow(browser, base)
            return_context_flow(browser, base)
            mobile_flow(browser, base, 390, 844, exercise_filters=True)
            mobile_flow(browser, base, 360, 800, exercise_filters=False)
            browser.close()

    result = {
        "ticket": "P3-04 + A14 + M06",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
