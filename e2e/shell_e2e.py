"""P2-02 shell E2E: deep links, navigation, 404, invalid ticker, responsive.

Run with the system Python that has playwright + chromium (not .venv):

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/shell_e2e.py

The script builds the frontend, starts `vite preview` on a free port, checks
E2E-01 (1440 desktop, 390 mobile) and E2E-02 (390/360 overflow, 44px targets,
safe-area), writes screenshots to ui_shots_p2/P2-02/, and prints one JSON line.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-02"

ROUTES: dict[str, tuple[str, str]] = {
    "/workbench": ("page-workbench", "工作台"),
    "/market": ("page-market", "市场"),
    "/stocks/600519": ("page-stock", "600519 股票工作区"),
    "/jobs": ("page-jobs", "任务"),
    "/jobs/job-1": ("page-job-detail", "600519"),
    "/reports": ("page-reports", "报告"),
    "/reports/report-1": ("page-report-detail", "报告 report-1"),
    "/journal": ("page-journal", "交易日志"),
    "/settings": ("page-settings", "设置"),
}

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


def wait_for_server(
    url: str, proc: subprocess.Popen[str], timeout: float = 30.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"vite preview exited early:\n{output}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError(f"vite preview did not answer on {url}")


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
        wait_for_server(f"{self.base}/workbench", self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


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


META_OPTIONS = {
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

SEARCH_EMPTY = {
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

JOB_STAGES = [
    ("market", "技术分析"),
    ("social", "情绪分析"),
    ("news", "新闻舆情"),
    ("fundamentals", "基本面"),
    ("policy", "政策分析"),
    ("hot_money", "游资追踪"),
    ("lockup", "解禁监控"),
    ("quality_gate", "质量门控"),
    ("debate", "多空辩论"),
    ("trader", "交易决策"),
    ("risk", "风控评估"),
    ("pm", "最终决策"),
]

JOB_DETAIL = {
    "job_id": "job-1",
    "status": "queued",
    "pending_action": None,
    "ticker_code": "600519",
    "ticker_name": None,
    "analysis_date": "2026-11-05",
    "created_at": "2026-11-05T09:00:00+08:00",
    "updated_at": "2026-11-05T09:00:00+08:00",
    "started_at": None,
    "finished_at": None,
    "current_stage": None,
    "stages": [
        {
            "id": stage_id,
            "name": name,
            "index": index,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
        }
        for index, (stage_id, name) in enumerate(JOB_STAGES, 1)
    ],
    "stats": {
        "model_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "elapsed_ms": 0,
    },
    "report_id": None,
    "error": None,
    "config_digest": "0" * 64,
    "graph_version": "graph-v1",
    "retry_of_job_id": None,
    "resume_of_job_id": None,
    "resume_from_stage": None,
    "allowed_actions": ["cancel"],
    "links": {
        "self": "/api/v1/jobs/job-1",
        "events": "/api/v1/jobs/job-1/events",
        "report": None,
    },
    "reconcile_notes": [],
}


def stub_api(context: BrowserContext) -> None:
    """Keep shell E2E offline: the shell now polls jobs and meta on mount."""

    def fulfill(route: object, payload: dict) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    context.route(
        "**/api/v1/jobs**",
        lambda route: fulfill(route, {"items": [], "next_cursor": None}),
    )
    # Registered after the wildcard so the detail route wins for /jobs/job-1.
    context.route(
        "**/api/v1/jobs/job-1",
        lambda route: fulfill(route, JOB_DETAIL),
    )
    # Registered after the detail route: the wildcard above also matches
    # /events, and a JSON 200 there would be a protocol error in the client.
    context.route(
        "**/api/v1/jobs/job-1/events",
        lambda route: route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=(
                "retry: 3000\n\n"
                "id: 0\n"
                "event: snapshot\n"
                "data: "
                + json.dumps(
                    {
                        "seq": 0,
                        "job_id": "job-1",
                        "type": "snapshot",
                        "at": "2026-11-05T09:00:00+08:00",
                        "payload": {"job": JOB_DETAIL, "last_seq": 0},
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            ),
        ),
    )
    context.route(
        "**/api/v1/meta/options**",
        lambda route: fulfill(route, META_OPTIONS),
    )
    context.route(
        "**/api/v1/market/search**",
        lambda route: fulfill(route, SEARCH_EMPTY),
    )


def assert_route(page: Page, base: str, path: str) -> None:
    test_id, heading = ROUTES[path]
    page.goto(f"{base}{path}")
    page.get_by_test_id(test_id).wait_for(state="visible")
    text = page.locator("h1").first.inner_text()
    check(heading in text, f"deep link {path} renders {test_id} ({text})")


def desktop_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub_api(context)
    page = context.new_page()
    errors = watch_errors(page)

    for path in ROUTES:
        assert_route(page, base, path)

    nav = page.get_by_role("complementary", name="主导航")
    page.goto(f"{base}/workbench")
    page.get_by_test_id("service-status").get_by_text("服务正常").wait_for()
    check(
        page.get_by_test_id("active-job-bar").count() == 0,
        "desktop has no bar without active jobs",
    )
    sidebar = page.locator("aside")
    expanded_width = sidebar.bounding_box()
    page.get_by_role("button", name="收起侧栏").click()
    page.wait_for_timeout(250)
    collapsed_width = sidebar.bounding_box()
    check(
        expanded_width is not None
        and collapsed_width is not None
        and abs(expanded_width["width"] - 232) < 1
        and abs(collapsed_width["width"] - 72) < 1,
        "desktop sidebar collapses 232 -> 72",
    )
    page.get_by_role("button", name="展开侧栏").click()
    page.wait_for_timeout(250)

    for label, path, test_id in (
        ("市场", "/market", "page-market"),
        ("任务", "/jobs", "page-jobs"),
        ("报告", "/reports", "page-reports"),
        ("工作台", "/workbench", "page-workbench"),
    ):
        nav.get_by_role("link", name=label, exact=True).click()
        page.wait_for_url(f"**{path}")
        page.get_by_test_id(test_id).wait_for(state="visible")
        check(page.url.endswith(path), f"desktop sidebar nav -> {path}")
    page.screenshot(path=str(SHOTS / "desktop_workbench.png"), full_page=True)

    page.goto(f"{base}/no-such-page")
    page.get_by_role("heading", name="页面不存在").wait_for()
    check(
        page.get_by_role("link", name="回工作台").is_visible()
        and page.get_by_role("link", name="回任务列表").is_visible(),
        "desktop 404 exposes two exits",
    )
    page.screenshot(path=str(SHOTS / "desktop_404.png"), full_page=True)
    page.get_by_role("link", name="回工作台").click()
    page.wait_for_url("**/workbench")
    check(page.url.endswith("/workbench"), "404 exit 回工作台")

    page.goto(f"{base}/no-such-page")
    page.get_by_role("link", name="回任务列表").click()
    page.wait_for_url("**/jobs")
    check(page.url.endswith("/jobs"), "404 exit 回任务列表")

    page.goto(f"{base}/stocks/abc")
    page.get_by_role("heading", name="没有这只股票").wait_for()
    invalid = page.get_by_test_id("invalid-ticker")
    check(
        invalid.get_by_label("搜索股票").is_visible()
        and invalid.get_by_role("link", name="回市场").is_visible(),
        "invalid ticker has search and 回市场",
    )
    invalid.get_by_role("link", name="回市场").click()
    page.wait_for_url("**/market")
    check(page.url.endswith("/market"), "invalid ticker exit 回市场")

    check(not errors, f"desktop console/page errors: {errors}")
    context.close()


def mobile_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context)
    page = context.new_page()
    errors = watch_errors(page)
    page.goto(f"{base}/workbench")
    page.get_by_test_id("mobile-nav").wait_for(state="visible")

    nav = page.get_by_test_id("mobile-nav")
    items = nav.locator("a, button")
    check(items.count() == 5, f"mobile bottom nav has five items ({items.count()})")
    for index in range(items.count()):
        box = items.nth(index).bounding_box()
        check(
            box is not None and box["height"] >= 44,
            f"mobile nav item {index} height >= 44 ({box and box['height']})",
        )

    primary = page.get_by_test_id("workbench-primary").bounding_box()
    check(
        primary is not None and primary["height"] >= 44,
        f"mobile primary button height >= 44 ({primary and primary['height']})",
    )

    for label, path, test_id in (
        ("市场", "/market", "page-market"),
        ("任务", "/jobs", "page-jobs"),
        ("报告", "/reports", "page-reports"),
        ("工作台", "/workbench", "page-workbench"),
    ):
        nav.get_by_role("link", name=label, exact=True).click()
        page.wait_for_url(f"**{path}")
        page.get_by_test_id(test_id).wait_for(state="visible")
        check(page.url.endswith(path), f"mobile bottom nav -> {path}")

    nav.get_by_role("button", name="更多").click()
    drawer = page.get_by_role("dialog", name="更多")
    drawer.wait_for(state="visible")
    check(
        drawer.get_by_role("link", name="交易日志").is_visible()
        and drawer.get_by_role("link", name="设置").is_visible()
        and drawer.get_by_role("link", name="旧版入口").is_visible(),
        "mobile more drawer lists 日志/设置/旧版入口",
    )
    legacy_href = drawer.get_by_role("link", name="旧版入口").get_attribute("href")
    check(legacy_href == "http://localhost:8501", "legacy entry points at 8501")
    page.wait_for_timeout(400)
    page.screenshot(path=str(SHOTS / "mobile_more.png"))

    drawer.get_by_role("link", name="设置").click()
    page.wait_for_url("**/settings")
    check(page.url.endswith("/settings"), "mobile more -> 设置")

    nav.get_by_role("button", name="更多").click()
    page.get_by_role("dialog", name="更多").get_by_role("link", name="交易日志").click()
    page.wait_for_url("**/journal")
    check(page.url.endswith("/journal"), "mobile more -> 交易日志")
    page.screenshot(path=str(SHOTS / "mobile_journal.png"), full_page=True)

    page.goto(f"{base}/workbench")
    page.get_by_role("button", name="打开搜索").click()
    search = page.locator('header input[type="search"]:visible')
    search.fill("600519")
    search.press("Enter")
    page.wait_for_url(lambda url: "launch=1" in url and "ticker=600519" in url)
    dialog = page.get_by_role("dialog", name="分析启动器")
    dialog.wait_for(state="visible")
    check(
        "600519" in dialog.inner_text(),
        "mobile header search opens the workbench launcher",
    )

    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for(state="visible")
    page.screenshot(path=str(SHOTS / "mobile_workbench.png"), full_page=True)

    check(not errors, f"mobile console/page errors: {errors}")
    context.close()


def overflow_flow(browser: Browser, base: str, width: int, height: int) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context)
    page = context.new_page()
    errors = watch_errors(page)
    for path in [*ROUTES, "/no-such-page", "/stocks/abc", "/stocks"]:
        page.goto(f"{base}{path}")
        page.wait_for_load_state("load")
        scroll_width = page.evaluate("document.documentElement.scrollWidth")
        client_width = page.evaluate("document.documentElement.clientWidth")
        check(
            scroll_width == client_width,
            f"{width}px {path} has no horizontal overflow "
            f"({scroll_width}/{client_width})",
        )
    viewport = page.get_attribute('meta[name="viewport"]', "content")
    check(
        viewport is not None and "viewport-fit=cover" in viewport,
        f"{width}px viewport meta enables safe areas",
    )
    page.goto(f"{base}/workbench")
    page.wait_for_load_state("load")
    page.screenshot(path=str(SHOTS / f"mobile_{width}_workbench.png"), full_page=True)
    check(not errors, f"{width}px console/page errors: {errors}")
    context.close()


def safe_area_css() -> None:
    css = "".join(
        path.read_text(encoding="utf-8")
        for path in (FRONTEND / "dist" / "assets").glob("*.css")
    )
    check(
        "env(safe-area-inset-bottom)" in css,
        "built CSS reserves env(safe-area-inset-bottom)",
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()
    safe_area_css()
    with Server() as base:
        print(f"preview at {base}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            desktop_flow(browser, base)
            mobile_flow(browser, base)
            overflow_flow(browser, base, 390, 844)
            overflow_flow(browser, base, 360, 780)
            browser.close()

    result = {
        "ticket": "P2-02",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
