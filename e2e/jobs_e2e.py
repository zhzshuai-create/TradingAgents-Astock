"""E2E-04 and M06: job list filters, cursor links, table and mobile cards.

Runs the built frontend on ``vite preview`` with a read-only jobs API. Every
non-GET request is recorded and must stay empty.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/jobs_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p2/P2-09/.
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
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-09"

failures: list[str] = []
checks = 0

ListRequest = dict[str, str]


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
                with urllib.request.urlopen(f"{self.base}/jobs", timeout=1) as response:
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


def job(
    job_id: str,
    status: str,
    *,
    name: str,
    code: str,
    analysis_date: str,
    stage: dict | None = None,
    error: dict | None = None,
    elapsed_ms: int = 1000,
) -> dict:
    return {
        "job_id": job_id,
        "status": status,
        "pending_action": None,
        "ticker_code": code,
        "ticker_name": name,
        "analysis_date": analysis_date,
        "created_at": f"{analysis_date}T09:03:00+08:00",
        "updated_at": f"{analysis_date}T09:04:00+08:00",
        "started_at": f"{analysis_date}T09:03:01+08:00",
        "finished_at": None,
        "current_stage": stage,
        "stats": {
            "model_calls": 3,
            "tokens_in": 100,
            "tokens_out": 50,
            "elapsed_ms": elapsed_ms,
        },
        "report_id": None,
        "error": error,
        "config_digest": "hash",
        "graph_version": "graph-v1",
        "retry_of_job_id": None,
        "resume_of_job_id": None,
        "resume_from_stage": None,
        "allowed_actions": ["pause", "cancel"],
        "links": {
            "self": f"/api/v1/jobs/{job_id}",
            "events": f"/api/v1/jobs/{job_id}/events",
            "report": None,
        },
    }


FAILED = job(
    "job-fail",
    "failed",
    name="钒钛股份",
    code="000629",
    analysis_date="2026-11-05",
    error={"code": "model_error", "message": "模型调用失败"},
    elapsed_ms=1234,
)
RUNNING = job(
    "job-run",
    "running",
    name="贵州茅台",
    code="600519",
    analysis_date="2026-11-04",
    stage={"id": "market", "name": "技术分析", "index": 3, "total": 12, "status": "active"},
    elapsed_ms=45000,
)
SUCCEEDED = job(
    "job-done",
    "succeeded",
    name="宁德时代",
    code="300750",
    analysis_date="2026-10-30",
    elapsed_ms=3_723_000,
)
JOBS = [FAILED, RUNNING, SUCCEEDED]

ACTIVE_STATUSES = {
    "queued",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
}

ALL_STATUSES = [
    "queued",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
    "interrupted",
]

META = {
    "app_version": "0.9.0",
    "server_time": "2026-11-05T09:30:00+08:00",
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

SEARCH = {
    "schema_version": "market-envelope-v1",
    "status": "ok",
    "source": "static",
    "as_of": "2026-11-05T09:00:00+08:00",
    "fetched_at": "2026-11-05T09:00:00+08:00",
    "is_stale": False,
    "stale_reason": None,
    "error_code": None,
    "error_message": None,
    "partial": False,
    "failed_blocks": [],
    "data": {"items": [], "truncated": False},
}


def filter_jobs(params: dict[str, str]) -> list[dict]:
    items = JOBS
    if params.get("active") == "true":
        items = [item for item in items if item["status"] in ACTIVE_STATUSES]
    else:
        statuses = [value for value in params.get("status", "").split(",") if value]
        if statuses:
            items = [item for item in items if item["status"] in statuses]
    ticker = params.get("ticker")
    if ticker:
        items = [item for item in items if item["ticker_code"] == ticker]
    date_from = params.get("date_from")
    if date_from:
        items = [item for item in items if item["analysis_date"] >= date_from]
    date_to = params.get("date_to")
    if date_to:
        items = [item for item in items if item["analysis_date"] <= date_to]
    return items


class ApiStub:
    """Read-only jobs API; every write attempt is recorded as a failure."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.requests: list[ListRequest] = []
        self.raw_queries: list[str] = []

    def install(self, context: BrowserContext) -> None:
        context.route("**/api/v1/jobs**", self._jobs)
        context.route("**/api/v1/meta/options**", self._json(META))
        context.route("**/api/v1/market/search**", self._json(SEARCH))

    @staticmethod
    def _json(payload: dict):
        def fulfill(route: object, *args: object) -> None:
            route.fulfill(  # type: ignore[attr-defined]
                status=200,
                content_type="application/json",
                body=json.dumps(payload),
            )

        return fulfill

    def _jobs(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        if request.method != "GET":
            self.writes.append(f"{request.method} {request.url}")
            route.fulfill(  # type: ignore[attr-defined]
                status=201,
                content_type="application/json",
                body="{}",
            )
            return
        parsed = urllib.parse.urlparse(request.url)
        raw = urllib.parse.parse_qs(parsed.query)
        params = {key: values[0] for key, values in raw.items()}
        self.requests.append(params)
        self.raw_queries.append(parsed.query)
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"items": filter_jobs(params), "next_cursor": None}
            ),
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


def scroll_content_to_top(page: Page) -> None:
    page.evaluate(
        "document.getElementById('main-content')?.scrollTo({top: 0, left: 0})"
    )
    page.wait_for_timeout(150)


def wait_rows(page: Page, count: int) -> None:
    rows = page.get_by_test_id("job-row")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if rows.count() == count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected {count} rows, saw {rows.count()}")


def wait_cards(page: Page, count: int) -> None:
    cards = page.get_by_test_id("job-card")
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if cards.count() == count:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected {count} cards, saw {cards.count()}")


def deep_link_flow(browser: Browser, base: str) -> None:
    stub = ApiStub()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/jobs?status=failed&ticker=000629")
    page.get_by_test_id("page-jobs").wait_for(state="visible")
    page.get_by_test_id("job-table").wait_for(state="visible")
    wait_rows(page, 1)

    params = wait_for_list_request(
        page, stub, lambda item: item.get("status") == "failed"
    )
    check(params.get("status") == "failed", f"deep link sends status=failed ({params})")
    check(params.get("ticker") == "000629", f"deep link sends ticker=000629 ({params})")
    check(params.get("limit") == "20", f"deep link sends limit=20 ({params})")
    check(
        page.get_by_role("checkbox", name="失败").is_checked(),
        "deep link checks 失败",
    )
    check(
        not page.get_by_role("checkbox", name="运行中").is_checked(),
        "deep link leaves 运行中 unchecked",
    )
    check(
        page.get_by_label("股票代码").input_value() == "000629",
        "deep link fills the ticker field",
    )
    row = page.get_by_test_id("job-row").first
    row_text = row.inner_text()
    check(
        "钒钛股份" in row_text and "失败" in row_text,
        f"deep link row shows the failed stock ({row_text})",
    )
    check(
        "模型调用失败" in row_text,
        f"failed row shows the safe message ({row_text})",
    )
    check(
        row.get_by_role("link", name="查看").get_attribute("href") == "/jobs/job-fail",
        "查看 points at the job detail route",
    )
    check(
        page.url == f"{base}/jobs?status=failed&ticker=000629",
        f"deep link URL is unchanged ({page.url})",
    )
    page.screenshot(path=str(SHOTS / "jobs_1440_deep_link.png"), full_page=True)

    page.get_by_role("button", name="重置").click()
    page.wait_for_url(lambda url: url.endswith("/jobs"))
    wait_rows(page, 3)
    wait_for_list_request(
        page,
        stub,
        lambda item: "status" not in item
        and "ticker" not in item
        and "date_from" not in item
        and "date_to" not in item,
        minimum=1,
    )
    check(page.url == f"{base}/jobs", f"reset returns to the bare /jobs URL ({page.url})")

    expected_statuses = ",".join(
        status for status in ALL_STATUSES if status != "succeeded"
    )
    page.get_by_role("checkbox", name="已完成").click()
    wait_rows(page, 2)
    status_params = wait_for_list_request(
        page, stub, lambda item: item.get("status") == expected_statuses
    )
    check(
        status_params.get("status") == expected_statuses,
        "unchecking 已完成 requests the eight remaining statuses",
    )

    ticker = page.get_by_label("股票代码")
    ticker.fill("000629")
    ticker.press("Enter")
    ticker_params = wait_for_list_request(
        page,
        stub,
        lambda item: item.get("status") == expected_statuses
        and item.get("ticker") == "000629",
    )
    check(
        ticker_params.get("ticker") == "000629",
        "committing the ticker requests ticker=000629",
    )

    page.get_by_label("开始日期").fill("2026-11-01")
    page.get_by_label("结束日期").fill("2026-11-05")
    date_params = wait_for_list_request(
        page,
        stub,
        lambda item: item.get("date_from") == "2026-11-01"
        and item.get("date_to") == "2026-11-05",
    )
    check(
        date_params.get("status") == expected_statuses
        and date_params.get("ticker") == "000629",
        "date change keeps the other filters",
    )

    url_query = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
    last = list_requests(stub)[-1]
    for key in ("status", "ticker", "date_from", "date_to"):
        check(
            url_query.get(key, [None])[0] == last.get(key),
            f"URL and request agree on {key} ({url_query.get(key)} vs {last.get(key)})",
        )
    check(
        "status=&" not in page.url and not page.url.endswith("status="),
        f"URL never writes an empty status ({page.url})",
    )
    page.screenshot(path=str(SHOTS / "jobs_1440_filtered.png"), full_page=True)

    def fully_filtered(item: ListRequest) -> bool:
        return (
            item.get("status") == expected_statuses
            and item.get("ticker") == "000629"
            and item.get("date_from") == "2026-11-01"
            and item.get("date_to") == "2026-11-05"
        )

    before = len([item for item in list_requests(stub) if fully_filtered(item)])
    page.reload()
    page.get_by_test_id("job-table").wait_for(state="visible")
    wait_rows(page, 1)
    wait_for_list_request(page, stub, fully_filtered, minimum=before + 1)
    check(
        page.get_by_role("checkbox", name="已完成").is_checked() is False,
        "refresh keeps the status filter",
    )
    check(
        page.get_by_label("股票代码").input_value() == "000629",
        "refresh keeps the ticker filter",
    )
    check(
        page.get_by_label("开始日期").input_value() == "2026-11-01"
        and page.get_by_label("结束日期").input_value() == "2026-11-05",
        "refresh keeps the date range",
    )

    check(stub.writes == [], f"desktop filters never write ({stub.writes})")
    check(
        not any(
            params.get("active") == "true" and "status" in params
            for params in stub.requests
        ),
        "active=true and status never travel together",
    )
    check(
        not any(
            part == "status=" for raw in stub.raw_queries for part in raw.split("&")
        ),
        "no request carries an empty status",
    )
    scroll_content_to_top(page)
    check(not errors, f"desktop console/page errors: {errors}")
    context.close()


def desktop_table_flow(browser: Browser, base: str) -> None:
    stub = ApiStub()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/jobs")
    page.get_by_test_id("job-table").wait_for(state="visible")
    wait_rows(page, 3)

    header = page.get_by_test_id("job-table").locator("thead").inner_text()
    for label in ("股票", "分析日期", "状态", "当前阶段", "耗时", "创建时间", "操作"):
        check(label in header, f"1440 table header contains {label}")

    rows = page.get_by_test_id("job-row")
    check(
        all(
            (rows.nth(index).get_by_role("link", name="查看").get_attribute("href") or "").startswith(
                "/jobs/"
            )
            for index in range(rows.count())
        ),
        "1440 every row has a 查看 link to /jobs/:id",
    )
    check(
        rows.nth(1).get_by_test_id("stage-progress").count() == 1,
        "1440 running row draws a stage progress bar",
    )
    check(
        rows.nth(2).get_by_test_id("stage-progress").count() == 0,
        "1440 succeeded row has no stage progress bar",
    )
    check(
        "模型调用失败" in rows.nth(0).inner_text(),
        "1440 failed row shows the safe error copy",
    )
    check(stub.writes == [], f"1440 table never writes ({stub.writes})")
    page.screenshot(path=str(SHOTS / "jobs_1440.png"), full_page=True)
    scroll_content_to_top(page)
    check(not errors, f"1440 console/page errors: {errors}")
    context.close()


def mobile_flow(
    browser: Browser,
    base: str,
    width: int,
    height: int,
    label: str,
    *,
    exercise_filters: bool,
) -> None:
    stub = ApiStub()
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/jobs")
    page.get_by_test_id("page-jobs").wait_for(state="visible")
    wait_cards(page, 3)

    check(
        not page.locator("table").is_visible(),
        f"{label} does not show the desktop table",
    )
    first_card = page.get_by_test_id("job-card").first
    text = first_card.inner_text()
    check(
        "钒钛股份" in text and "失败" in text,
        f"{label} card starts with stock and status ({text})",
    )
    check("2026-11-05" in text, f"{label} card shows the analysis date")
    check("耗时" in text, f"{label} card shows the duration")
    check(
        first_card.get_attribute("href") == "/jobs/job-fail",
        f"{label} whole card links to the job detail",
    )
    check(
        page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ),
        f"{label} has no page-level horizontal scroll",
    )
    page.screenshot(path=str(SHOTS / f"jobs_{width}.png"), full_page=True)

    if exercise_filters:
        page.get_by_test_id("job-filter-open").get_by_role(
            "button", name="筛选"
        ).click()
        dialog = page.get_by_role("dialog", name="筛选任务")
        dialog.wait_for(state="visible")
        # Let the pop-in scale animation finish before measuring targets.
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
        status_label = dialog.get_by_test_id("filter-status-failed").bounding_box()
        check(
            status_label is not None and status_label["height"] >= 44,
            f"{label} status rows are at least 44px tall ({status_label})",
        )
        page.screenshot(path=str(SHOTS / f"jobs_{width}_filters.png"))

        ticker = dialog.get_by_label("股票代码")
        ticker.fill("600519")
        ticker.press("Enter")
        wait_for_list_request(
            page, stub, lambda item: item.get("ticker") == "600519"
        )

        active = dialog.get_by_role("checkbox", name="只看活动任务")
        active.click()
        active_params = wait_for_list_request(
            page, stub, lambda item: item.get("active") == "true"
        )
        check(
            "status" not in active_params,
            f"{label} active switch omits status ({active_params})",
        )
        check(
            dialog.get_by_role("checkbox", name="失败").is_disabled(),
            f"{label} status boxes disable while active is on",
        )
        dialog.get_by_role("button", name="应用筛选").click()
        dialog.wait_for(state="detached")
        wait_cards(page, 1)

        chips = page.get_by_test_id("job-filter-chip")
        chip_text = " ".join(chips.all_inner_texts())
        check(
            "股票 600519" in chip_text and "只看活动任务" in chip_text,
            f"{label} chips show the applied conditions ({chip_text})",
        )
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
        page.screenshot(path=str(SHOTS / f"jobs_{width}_filtered.png"), full_page=True)

    check(stub.writes == [], f"{label} never writes ({stub.writes})")
    check(
        not any(
            params.get("active") == "true" and "status" in params
            for params in stub.requests
        ),
        f"{label} active=true and status never travel together",
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
            desktop_table_flow(browser, base)
            mobile_flow(browser, base, 390, 844, "390", exercise_filters=True)
            mobile_flow(browser, base, 360, 800, "360", exercise_filters=False)
            browser.close()

    result = {
        "ticket": "E2E-04 + M06",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
