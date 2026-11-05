"""E2E-05 and M02/M03/M05/M07: the job detail page in a real browser.

Seeds one job per status through ``scripts/seed_e2e_jobs.py`` (fake graph,
temporary DB and report root), starts the dev API with ``--no-worker`` so the
rows keep their seeded states, previews the built frontend with ``/api``
proxied to it, and lets the browser read only.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/job_detail_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p2/P2-10/.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-10"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "pause_requested": "暂停中",
    "paused": "已暂停",
    "cancel_requested": "取消中",
    "cancelled": "已取消",
    "succeeded": "已完成",
    "failed": "失败",
    "interrupted": "等待人工处理",
}
NOTICE_STATUSES = {
    "queued",
    "pause_requested",
    "cancel_requested",
    "failed",
    "interrupted",
}
HIGHLIGHTED = {"running", "pause_requested", "cancel_requested"}

failures: list[str] = []
checks = 0
writes: list[str] = []


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


def get_json(url: str, timeout: float = 5.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_until(predicate, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {label}")


def api_ready(base: str, proc: subprocess.Popen[str], timeout: float = 60.0) -> None:
    url = f"{base}/api/v1/jobs/not-ready-probe"

    def probe() -> bool:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"dev entry exited early:\n{output}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 404
        except urllib.error.HTTPError as error:
            return error.code == 404
        except (urllib.error.URLError, ConnectionError):
            return False

    wait_until(probe, timeout, "dev API")


def preview_ready(url: str, proc: subprocess.Popen[str], timeout: float = 30.0) -> None:
    def probe() -> bool:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"vite preview exited early:\n{output}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 200
        except (urllib.error.URLError, ConnectionError):
            return False

    wait_until(probe, timeout, "vite preview")


def seed_jobs(root: Path) -> dict[str, dict[str, str]]:
    env = os.environ.copy()
    env.update(
        {
            "TA_E2E": "1",
            "TA_JOBS_DB": str(root / "jobs.db"),
            "TA_JOB_REPORTS_DIR": str(root / "reports"),
            "PYTHONIOENCODING": "utf-8",
        }
    )
    proc = subprocess.run(
        [str(PYTHON), "scripts/seed_e2e_jobs.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"seed failed:\n{proc.stdout}\n{proc.stderr}")
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError(f"seed produced no JSON:\n{proc.stdout}")
    return json.loads(lines[-1])["jobs"]


class DevBackend:
    def __init__(self, root: Path) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = os.environ.copy()
        env["TA_DEV_ROOT"] = str(root)
        self.proc = subprocess.Popen(
            [
                str(PYTHON),
                "scripts/dev_backend.py",
                "--port",
                str(self.port),
                "--no-worker",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def __enter__(self) -> str:
        api_ready(self.base, self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


class Preview:
    def __init__(self, api: str) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("node executable not found on PATH")
        env = os.environ.copy()
        env["VITE_API_PROXY_TARGET"] = api
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
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def __enter__(self) -> str:
        preview_ready(f"{self.base}/jobs", self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def watch_errors(page: Page, *, ignore_not_found: bool = False) -> list[str]:
    errors: list[str] = []

    def on_console(message) -> None:
        if message.type != "error":
            return
        text = message.text
        if ignore_not_found and text.startswith("Failed to load resource"):
            return
        errors.append(text)

    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", on_console)
    return errors


def record_network(page: Page) -> tuple[list[str], list[str]]:
    page_writes: list[str] = []
    stage_requests: list[str] = []

    def on_request(request) -> None:
        if request.method != "GET" and "/api/v1/" in request.url:
            page_writes.append(f"{request.method} {request.url}")
            writes.append(f"{request.method} {request.url}")
        if request.method == "GET" and "/stages/" in request.url:
            stage_requests.append(request.url)

    page.on("request", on_request)
    return page_writes, stage_requests


def wait_detail(page: Page) -> None:
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=15_000)


def check_actions(page: Page, detail: dict) -> None:
    actions = detail["allowed_actions"]
    group = page.get_by_test_id("job-actions")
    if not actions:
        check(group.count() == 0, "no action group when allowed_actions is empty")
        return
    check(group.count() == 1, "action group is rendered")
    check(
        group.locator("button").count() == len(actions),
        f"action button count matches allowed_actions ({len(actions)})",
    )
    for action in actions:
        button = page.get_by_test_id(f"job-action-{action}")
        check(button.is_visible(), f"{action} button is visible")
        check(button.is_enabled(), f"{action} button is enabled after P2-12")


def check_stats(page: Page, detail: dict) -> None:
    stats = detail["stats"]
    for key, test_id in (
        ("model_calls", "stat-model-calls"),
        ("tokens_in", "stat-tokens-in"),
        ("tokens_out", "stat-tokens-out"),
    ):
        text = page.get_by_test_id(test_id).inner_text().replace(",", "").strip()
        check(text == str(stats[key]), f"{test_id} matches the API value {stats[key]}")
    elapsed = page.get_by_test_id("stat-elapsed").inner_text().strip()
    if stats["elapsed_ms"] == 0:
        check(elapsed == "—", "zero elapsed time renders as a dash")
    else:
        check(elapsed not in ("", "—"), f"elapsed time renders ({elapsed})")


def check_no_horizontal_scroll(page: Page, label: str) -> None:
    root_ok = page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
    )
    check(root_ok, f"{label}: no page-level horizontal scroll")
    main_ok = page.evaluate(
        "() => { const main = document.getElementById('main-content');"
        " return main === null || main.scrollWidth <= main.clientWidth + 1; }"
    )
    check(main_ok, f"{label}: no horizontal scroll inside the content area")


def check_mobile_touch_targets(page: Page, label: str) -> None:
    boxes = page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'[data-testid=\"stage-group-analysis\"] button, "
        "[data-testid=\"stage-group-flow\"] button'"
        ")).map((button) => { const box = button.getBoundingClientRect();"
        " return {x: box.x, width: box.width, height: box.height}; })"
    )
    check(len(boxes) == 12, f"{label}: 12 stage rows are rendered")
    check(
        all(box["height"] >= 44 for box in boxes),
        f"{label}: stage rows are at least 44px tall ({[round(b['height']) for b in boxes]})",
    )
    xs = sorted({round(box["x"]) for box in boxes})
    check(len(xs) == 1, f"{label}: stage timeline is one column (x={xs})")
    check(page.locator("table").count() == 0, f"{label}: no table is rendered")
    actions = page.locator("[data-testid^='job-action-']")
    if actions.count() > 0:
        heights = [
            actions.nth(index).bounding_box()["height"]
            for index in range(actions.count())
        ]
        check(
            all(height >= 44 for height in heights),
            f"{label}: action buttons are at least 44px tall ({heights})",
        )


def status_flow(
    browser: Browser, base: str, api: str, jobs: dict[str, dict[str, str]]
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page)
    _page_writes, stage_requests = record_network(page)

    for status, entry in jobs.items():
        job_id = entry["job_id"]
        detail = get_json(f"{api}/api/v1/jobs/{job_id}")
        stage_requests.clear()
        page.goto(f"{base}/jobs/{job_id}")
        wait_detail(page)

        header_text = page.get_by_test_id("job-header").inner_text()
        check(
            STATUS_LABELS[status] in header_text,
            f"{status}: header badge shows {STATUS_LABELS[status]}",
        )
        page_text = page.get_by_test_id("page-job-detail").inner_text()
        check("进行中" not in page_text, f"{status}: never uses 进行中")
        if status == "interrupted":
            check("运行中" not in page_text, "interrupted is never labelled running")

        notice = page.get_by_test_id("job-notice")
        if status in NOTICE_STATUSES:
            check(notice.count() == 1, f"{status}: status notice is rendered")
            check(
                notice.get_attribute("data-kind") == status,
                f"{status}: notice kind matches the status",
            )
        else:
            check(notice.count() == 0, f"{status}: no extra notice")

        check(
            page.get_by_test_id("stage-group-analysis").locator("button").count() == 7,
            f"{status}: 7 analysis stages",
        )
        check(
            page.get_by_test_id("stage-group-flow").locator("button").count() == 5,
            f"{status}: 5 flow stages",
        )
        current = detail["current_stage"]
        highlighted = page.locator("[aria-current='step']")
        if status in HIGHLIGHTED:
            check(highlighted.count() == 1, f"{status}: exactly one current stage")
            if current is not None:
                check(
                    page.get_by_test_id(f"stage-{current['id']}").get_attribute(
                        "aria-current"
                    )
                    == "step",
                    f"{status}: current stage {current['id']} is highlighted",
                )
        else:
            check(highlighted.count() == 0, f"{status}: no current stage highlight")

        check_actions(page, detail)
        check_stats(page, detail)

        if status == "succeeded":
            check(
                detail["report_id"] is not None,
                "succeeded has a committed report id",
            )
            page.get_by_test_id("stage-report-body").wait_for(
                state="visible", timeout=15_000
            )
            check(
                len(stage_requests) == 1,
                f"succeeded: only the auto-expanded report is requested ({stage_requests})",
            )
            check(
                stage_requests[-1].endswith("/stages/pm"),
                "succeeded: the latest completed stage (pm) auto-expands",
            )
            check(
                page.get_by_test_id("stage-report-toggle-pm").get_attribute(
                    "aria-expanded"
                )
                == "true",
                "succeeded: pm report row is expanded",
            )
            link = page.get_by_test_id("job-open-report")
            check(link.count() == 1, "succeeded: 打开报告 is visible")
            check(
                link.get_attribute("href") == f"/reports/{detail['report_id']}",
                "succeeded: 打开报告 points at /reports/:reportId",
            )
            page.screenshot(
                path=str(SHOTS / "detail_succeeded.png"), full_page=True
            )

        if status == "failed":
            check(
                "失败" in page.get_by_test_id("stage-fundamentals").inner_text(),
                "failed: the failed stage is marked 失败",
            )
            check(
                "数据源超时" in notice.inner_text(),
                "failed: notice shows the safe error message",
            )
            page.get_by_test_id("stage-report-toggle-market").click()
            page.get_by_test_id("stage-report-body").wait_for(
                state="visible", timeout=15_000
            )
            body = page.get_by_test_id("stage-report-body")
            before = len(body.inner_text())
            check("600008" in body.inner_text(), "failed: completed report is readable")
            expand = page.get_by_test_id("stage-report-expand")
            check(expand.count() == 1, "failed: long report offers 展开全文")
            expand.click()
            expand.wait_for(state="detached")
            after = len(body.inner_text())
            check(after > before, f"failed: 展开全文 reveals more text ({before} -> {after})")
            link = body.locator("a").first
            check(link.get_attribute("target") == "_blank", "report link opens a new tab")
            rel = (link.get_attribute("rel") or "").split()
            check(
                "noopener" in rel and "noreferrer" in rel,
                f"report link keeps noopener noreferrer ({rel})",
            )
            page.screenshot(path=str(SHOTS / "detail_failed.png"), full_page=True)

        if status not in {"succeeded", "failed"}:
            page.screenshot(
                path=str(SHOTS / f"detail_{status}.png"), full_page=True
            )

    check(_page_writes == [], f"desktop detail pages never write ({_page_writes})")
    check(not errors, f"desktop console/page errors: {errors}")
    context.close()


def not_found_flow(browser: Browser, base: str, api: str) -> None:
    before = len(get_json(f"{api}/api/v1/jobs?limit=100")["items"])
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page, ignore_not_found=True)
    page_writes, _stage_requests = record_network(page)

    page.goto(f"{base}/jobs/does-not-exist")
    page.get_by_test_id("job-not-found").wait_for(state="visible", timeout=15_000)
    panel = page.get_by_test_id("job-not-found")
    check("没有找到这个任务" in panel.inner_text(), "404 page explains the missing job")
    check(panel.locator("a").count() == 1, "404 page offers one exit")
    check(
        (panel.locator("a").first.get_attribute("href") or "").endswith("/jobs"),
        "404 page only goes back to the task list",
    )
    after = len(get_json(f"{api}/api/v1/jobs?limit=100")["items"])
    check(before == after, f"404 page creates no jobs ({before} -> {after})")
    check(page_writes == [], "404 page never writes")
    page.screenshot(path=str(SHOTS / "detail_404.png"), full_page=True)
    check(not errors, f"404 console/page errors: {errors}")
    context.close()


def mobile_flow(
    browser: Browser,
    base: str,
    api: str,
    jobs: dict[str, dict[str, str]],
    width: int,
    height: int,
) -> None:
    label = f"{width}x{height}"
    entry = jobs["running"]
    job_id = entry["job_id"]
    detail = get_json(f"{api}/api/v1/jobs/{job_id}")
    context: BrowserContext = browser.new_context(
        viewport={"width": width, "height": height},
        is_mobile=True,
        has_touch=True,
        device_scale_factor=2,
    )
    page = context.new_page()
    errors = watch_errors(page)
    page_writes, stage_requests = record_network(page)

    page.goto(f"{base}/jobs/{job_id}")
    wait_detail(page)
    check_mobile_touch_targets(page, label)
    current = detail["current_stage"]
    check(current is not None, f"{label}: running job has a current stage")
    if current is not None:
        check(
            page.get_by_test_id(f"stage-{current['id']}").get_attribute(
                "aria-current"
            )
            == "step",
            f"{label}: current stage is highlighted in the single column",
        )
    check(
        page.get_by_test_id("stage-report-list").is_visible() is False,
        f"{label}: inline report list is hidden on mobile",
    )
    check_no_horizontal_scroll(page, label)
    page.screenshot(path=str(SHOTS / f"detail_{label}.png"), full_page=True)

    stage_requests.clear()
    page.get_by_test_id("stage-market").click()
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible", timeout=10_000)
    check("技术分析" in dialog.inner_text(), f"{label}: stage report opens in a drawer")
    check(
        any(url.endswith("/stages/market") for url in stage_requests),
        f"{label}: the drawer fetches exactly the selected stage report",
    )
    body = page.get_by_test_id("drawer-body")
    body.get_by_test_id("stage-report-body").wait_for(
        state="visible", timeout=15_000
    )
    expand = body.get_by_test_id("stage-report-expand")
    if expand.count() == 1:
        expand.click()
        expand.wait_for(state="detached")
    check(
        body.evaluate("el => el.scrollHeight > el.clientHeight"),
        f"{label}: the drawer body scrolls independently",
    )
    body.evaluate("el => { el.scrollTop = 200; }")
    check(
        body.evaluate("el => el.scrollTop") > 0,
        f"{label}: the drawer body actually scrolled",
    )
    check(
        page.evaluate("() => getComputedStyle(document.body).overflow") == "hidden",
        f"{label}: body scroll is locked while the drawer is open",
    )
    check(
        page.evaluate(
            "() => getComputedStyle(document.getElementById('main-content')).overflowY"
        )
        == "hidden",
        f"{label}: content scroll is locked while the drawer is open",
    )
    page.screenshot(path=str(SHOTS / f"detail_{label}_drawer.png"), full_page=True)

    page.get_by_role("button", name="关闭抽屉").click()
    dialog.wait_for(state="hidden", timeout=10_000)
    check(
        page.evaluate("() => getComputedStyle(document.body).overflow") != "hidden",
        f"{label}: body scroll is restored after closing",
    )
    check(
        page.evaluate(
            "() => getComputedStyle(document.getElementById('main-content')).overflowY"
        )
        != "hidden",
        f"{label}: content scroll is restored after closing",
    )
    check_no_horizontal_scroll(page, label)
    check(page_writes == [], f"{label}: mobile detail never writes ({page_writes})")
    check(not errors, f"{label}: console/page errors: {errors}")
    context.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()

    with tempfile.TemporaryDirectory(prefix="astock-e2e-") as temp:
        root = Path(temp)
        print("seeding nine statuses...")
        jobs = seed_jobs(root)
        missing = set(STATUS_LABELS) - set(jobs)
        if missing:
            raise RuntimeError(f"seed missed statuses: {sorted(missing)}")
        with DevBackend(root) as api:
            print(f"dev api at {api}")
            with Preview(api) as base:
                print(f"preview at {base}")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    status_flow(browser, base, api, jobs)
                    not_found_flow(browser, base, api)
                    mobile_flow(browser, base, api, jobs, 390, 844)
                    mobile_flow(browser, base, api, jobs, 360, 800)
                    browser.close()

    check(writes == [], f"the browser never sent a write request ({writes})")
    result = {
        "ticket": "E2E-05",
        "checks": checks,
        "failures": failures,
        "jobs": {status: entry["job_id"] for status, entry in jobs.items()},
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
