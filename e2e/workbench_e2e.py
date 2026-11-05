"""E2E-03: workbench first screen, active card, recent jobs, launcher.

Runs the built frontend on ``vite preview`` with stubbed read APIs. The browser
may only read: opening and closing the launcher must not send a single write.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/workbench_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p2/P2-07/.
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
SHOTS = ROOT / "ui_shots_p2" / "P2-07"

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
        end = time.monotonic() + 30.0
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                output = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"vite preview exited early:\n{output}")
            try:
                with urllib.request.urlopen(f"{self.base}/workbench", timeout=1) as response:
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
    name: str = "钒钛股份",
    code: str = "000629",
    stage: dict | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "status": status,
        "pending_action": None,
        "ticker_code": code,
        "ticker_name": name,
        "analysis_date": "2026-11-05",
        "created_at": "2026-11-05T09:03:00+08:00",
        "updated_at": "2026-11-05T09:04:00+08:00",
        "started_at": "2026-11-05T09:03:01+08:00",
        "finished_at": None,
        "current_stage": stage,
        "stats": {"model_calls": 3, "tokens_in": 100, "tokens_out": 50, "elapsed_ms": 1000},
        "report_id": None,
        "error": None,
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


RUNNING = job(
    "job-run",
    "running",
    stage={"id": "market", "name": "技术分析", "index": 3, "total": 12, "status": "active"},
)
ACTIVE = [RUNNING, job("job-queue", "queued", name="贵州茅台", code="600519", stage=None)]
RECENT = [
    RUNNING,
    job("job-fail", "failed", name="宁德时代", code="300750", stage=None),
    job("job-interrupt", "interrupted", name="中际旭创", code="300308", stage=None),
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


class ApiStub:
    """Read-only jobs API; every write attempt is recorded as a failure."""

    def __init__(self) -> None:
        self.writes: list[str] = []

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
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.url).query)
        items = ACTIVE if query.get("active") == ["true"] else RECENT
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps({"items": items, "next_cursor": None}),
        )


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


def open_launcher(page: Page) -> None:
    page.get_by_test_id("workbench-primary").click()
    dialog = page.get_by_role("dialog", name="分析启动器")
    dialog.wait_for(state="visible")
    page.wait_for_url(lambda url: "launch=1" in url)


def close_launcher(page: Page) -> None:
    page.get_by_role("button", name="知道了").click()
    page.get_by_role("dialog", name="分析启动器").wait_for(state="detached")
    page.wait_for_url(lambda url: "launch" not in url and "ticker" not in url)


def scroll_content_to_top(page: Page) -> None:
    page.evaluate(
        "document.getElementById('main-content')?.scrollTo({top: 0, left: 0})"
    )
    page.wait_for_timeout(150)


def mobile_flow(browser: Browser, base: str, stub: ApiStub) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)
    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for(state="visible")

    primary = page.get_by_test_id("workbench-primary").bounding_box()
    check(
        primary is not None
        and primary["height"] >= 44
        and primary["y"] + primary["height"] <= 844,
        f"390 primary action sits in the first screen ({primary})",
    )

    card = page.get_by_test_id("workbench-active-card")
    card.wait_for(state="visible")
    card_text = card.inner_text()
    check(
        "钒钛股份" in card_text and "3/12" in card_text,
        f"390 active card is visible without expanding ({card_text})",
    )

    rows = page.get_by_test_id("recent-job")
    check(rows.count() == 3, f"390 recent jobs shows three rows ({rows.count()})")
    for index in range(rows.count()):
        check(rows.nth(index).is_visible(), f"390 recent row {index} is visible")

    reports = page.get_by_test_id("recent-reports")
    body = reports.get_by_text("报告库将在 P3 开放。")
    check(
        page.get_by_role("button", name="查看全部").is_visible(),
        "390 recent reports collapse into 查看全部",
    )
    check(not body.is_visible(), "390 report body is hidden before expanding")
    page.get_by_role("button", name="查看全部").click()
    check(body.is_visible(), "390 查看全部 reveals only the P3 copy")
    page.screenshot(path=str(SHOTS / "workbench_390_reports.png"), full_page=True)

    market = page.get_by_test_id("market-summary").inner_text()
    check(
        "P4" in market and "指数" in market,
        f"390 market placeholder names P4 without fake numbers ({market})",
    )

    open_launcher(page)
    page.screenshot(path=str(SHOTS / "workbench_390_launcher.png"))
    close_launcher(page)
    check(stub.writes == [], f"390 open/close launcher never writes ({stub.writes})")
    check(
        rows.count() == 3,
        "390 recent job count is unchanged after the launcher round trip",
    )

    scroll_content_to_top(page)
    page.screenshot(path=str(SHOTS / "workbench_390.png"), full_page=True)
    check(not errors, f"390 console/page errors: {errors}")
    context.close()

def desktop_flow(browser: Browser, base: str, stub: ApiStub) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)
    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for(state="visible")
    page.get_by_test_id("recent-job").first.wait_for(state="visible")

    boxes = {
        "activity": page.get_by_test_id("workbench-active-card").bounding_box(),
        "primary": page.get_by_test_id("workbench-primary").bounding_box(),
        "recent": page.get_by_test_id("recent-jobs").bounding_box(),
        "reports": page.get_by_test_id("recent-reports").bounding_box(),
        "market": page.get_by_test_id("market-summary").bounding_box(),
    }
    ordered = [
        boxes[name]["y"]
        for name in ("activity", "primary", "recent", "reports", "market")
        if boxes[name] is not None
    ]
    check(
        len(ordered) == 5 and ordered == sorted(ordered),
        f"1440 content order is activity, start, recent, reports, market ({ordered})",
    )
    check(
        page.get_by_text("报告库将在 P3 开放。").is_visible(),
        "1440 recent reports placeholder is visible without expanding",
    )
    check(
        page.get_by_test_id("active-job-bar").count() == 1,
        "1440 keeps exactly one active-job block on the workbench",
    )
    page.screenshot(path=str(SHOTS / "workbench_1440.png"), full_page=True)

    open_launcher(page)
    close_launcher(page)
    check(stub.writes == [], f"1440 open/close launcher never writes ({stub.writes})")
    scroll_content_to_top(page)
    check(not errors, f"1440 console/page errors: {errors}")
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
            mobile_flow(browser, base, ApiStub())
            desktop_flow(browser, base, ApiStub())
            browser.close()

    result = {
        "ticket": "E2E-03",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
