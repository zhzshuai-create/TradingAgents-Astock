"""E2E A01-A03: the launcher creates exactly one job and branches correctly.

Runs the real dev entry with ``--no-worker`` (queued jobs stay active) and a
temporary ticker fixture, then previews the built frontend with ``/api``
proxied to it.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/launcher_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p2/P2-08/.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-08"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

FIXTURE = {"300750": "宁德时代", "600519": "贵州茅台"}
JOB_URL = re.compile(r"/jobs/[^/]+$")

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


def api_ready(base: str, proc: subprocess.Popen[str], timeout: float = 90.0) -> dict:
    def probe() -> bool:
        if proc.poll() is not None:
            raise RuntimeError("dev entry exited early")
        try:
            body = get_json(f"{base}/api/v1/meta/options", timeout=2)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return False
        return isinstance(body.get("default_analysis_date"), str)

    wait_until(probe, timeout, "dev API")
    return get_json(f"{base}/api/v1/meta/options")


def preview_ready(url: str, proc: subprocess.Popen[str], timeout: float = 60.0) -> None:
    def probe() -> bool:
        if proc.poll() is not None:
            raise RuntimeError("vite preview exited early")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 200
        except (urllib.error.URLError, ConnectionError):
            return False

    wait_until(probe, timeout, "vite preview")


def job_ids(api: str) -> list[str]:
    body = get_json(f"{api}/api/v1/jobs?limit=100")
    return [str(item["job_id"]) for item in body["items"]]


class DevBackend:
    def __init__(self, root: Path, fixture: Path) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = os.environ.copy()
        env["TA_DEV_ROOT"] = str(root)
        env["TA_JOBS_DB"] = str(root / "jobs.db")
        env["TA_JOB_REPORTS_DIR"] = str(root / "reports")
        self.proc = subprocess.Popen(
            [
                str(PYTHON),
                "scripts/dev_backend.py",
                "--port",
                str(self.port),
                "--no-worker",
                "--ticker-fixture",
                str(fixture),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def __enter__(self) -> tuple[str, dict]:
        return self.base, api_ready(self.base, self.proc)

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
        preview_ready(f"{self.base}/workbench", self.proc)
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


def watch_posts(page: Page) -> dict:
    log: dict = {"count": 0, "statuses": [], "headers": []}

    def on_request(request) -> None:
        if request.method == "POST" and "/api/v1/jobs" in request.url:
            log["count"] += 1

    def on_response(response) -> None:
        if response.request.method == "POST" and "/api/v1/jobs" in response.url:
            log["statuses"].append(response.status)
            log["headers"].append(dict(response.headers))

    page.on("request", on_request)
    page.on("response", on_response)
    return log


def launcher(page: Page):
    return page.get_by_role("dialog", name="分析启动器")


def wait_enabled(page: Page, dialog, timeout: float = 15.0) -> None:
    button = dialog.get_by_role("button", name="开始分析")
    button.wait_for(state="visible")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if button.is_enabled():
            return
        time.sleep(0.1)
    raise RuntimeError("start button stayed disabled")


def open_prefilled(page: Page, base: str, ticker: str) -> None:
    page.goto(f"{base}/workbench?launch=1&ticker={ticker}")
    dialog = launcher(page)
    dialog.wait_for(state="visible")
    date = dialog.get_by_label("分析日期")
    wait_until(lambda: bool(date.input_value()), 15, "launcher defaults")


def a01_search_and_submit(
    browser: Browser, base: str, api: str, default_date: str
) -> str:
    before = job_ids(api)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page)
    posts = watch_posts(page)

    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for(state="visible")
    page.get_by_label("搜索要分析的股票").fill("宁德")
    option = page.get_by_role("option").filter(has_text="300750").first
    option.wait_for(state="visible")
    option.click()

    dialog = launcher(page)
    dialog.wait_for(state="visible")
    text = dialog.inner_text()
    check(
        "宁德时代" in text and "300750" in text,
        f"A01 picked ticker is shown as 名称+代码 ({text!r})",
    )
    date = dialog.get_by_label("分析日期")
    check(
        date.input_value() == default_date,
        f"A01 date comes from meta/options ({date.input_value()})",
    )
    page.screenshot(path=str(SHOTS / "launcher_1440_prefilled.png"), full_page=True)

    wait_enabled(page, dialog)
    dialog.get_by_role("button", name="开始分析").click()
    page.wait_for_url(JOB_URL, timeout=30_000)
    page.get_by_test_id("page-job-detail").wait_for(state="visible")
    new_id = page.url.rstrip("/").split("/")[-1]

    after = job_ids(api)
    check(new_id not in before, f"A01 URL carries the new job id ({new_id})")
    check(
        len(after) == len(before) + 1,
        f"A01 job count grows by exactly one ({len(before)} -> {len(after)})",
    )
    check(
        posts["count"] == 1 and posts["statuses"] == [201],
        f"A01 one POST with 201 ({posts['statuses']})",
    )
    page.screenshot(path=str(SHOTS / "launcher_1440_created.png"), full_page=True)
    check(not errors, f"A01 console/page errors: {errors}")
    context.close()
    return new_id


def a02_triple_click(browser: Browser, base: str, api: str) -> None:
    before = job_ids(api)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page)
    posts = watch_posts(page)

    def slow(route: Route) -> None:
        if route.request.method == "POST":
            time.sleep(0.6)
        route.continue_()

    page.route("**/api/v1/jobs", slow)
    open_prefilled(page, base, "600519")
    dialog = launcher(page)
    wait_enabled(page, dialog)

    dialog.get_by_role("button", name="开始分析").click()
    page.wait_for_function(
        "() => document.querySelector('button[form=\"launcher-form\"]')?.disabled === true"
    )
    check(True, "A02 button is disabled right after the first click")
    page.screenshot(path=str(SHOTS / "launcher_1440_submitting.png"), full_page=True)

    page.evaluate(
        """() => {
            const button = document.querySelector('button[form="launcher-form"]');
            if (button) {
                button.click();
                button.click();
            }
        }"""
    )
    page.wait_for_url(JOB_URL, timeout=30_000)
    wait_until(lambda: len(job_ids(api)) == len(before) + 1, 15, "single new job")

    check(posts["count"] == 1, f"A02 burst sends one POST ({posts['count']})")
    check(posts["statuses"] == [201], f"A02 status is 201 ({posts['statuses']})")
    check(
        len(job_ids(api)) == len(before) + 1,
        "A02 job count grows by exactly one",
    )
    check(not errors, f"A02 console/page errors: {errors}")
    page.unroute("**/api/v1/jobs")
    context.close()


def a03_existing_and_conflict(
    browser: Browser, base: str, api: str, active_id: str
) -> None:
    before = job_ids(api)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page)
    posts = watch_posts(page)

    open_prefilled(page, base, "300750")
    dialog = launcher(page)
    wait_enabled(page, dialog)
    dialog.get_by_role("button", name="开始分析").click()
    page.get_by_text("已有一个相同分析").wait_for(state="visible", timeout=10_000)
    page.wait_for_url(f"**/jobs/{active_id}", timeout=30_000)

    check(
        posts["statuses"] == [200],
        f"A03 same config answers 200 ({posts['statuses']})",
    )
    check(
        posts["headers"][0].get("x-existing-job") == active_id,
        f"A03 X-Existing-Job points at {active_id} "
        f"({posts['headers'][0].get('x-existing-job')})",
    )
    check(job_ids(api) == before, "A03 same-config submit creates no job")

    open_prefilled(page, base, "300750")
    dialog = launcher(page)
    wait_enabled(page, dialog)
    dialog.get_by_role("button", name=re.compile("阶段开关")).click()
    dialog.get_by_role("checkbox", name="政策分析").uncheck()
    dialog.get_by_role("button", name="开始分析").click()

    alert = dialog.get_by_role("alert")
    alert.wait_for(state="visible", timeout=10_000)
    link = alert.get_by_role("link", name="查看进行中的任务")
    check(
        link.get_attribute("href") == f"/jobs/{active_id}",
        f"A03 409 links to the active job ({link.get_attribute('href')})",
    )
    check(
        posts["statuses"] == [200, 409],
        f"A03 changed config answers 409 ({posts['statuses']})",
    )
    check(job_ids(api) == before, "A03 conflict submit creates no job")
    page.screenshot(path=str(SHOTS / "launcher_1440_conflict.png"), full_page=True)
    # The 409 itself is the assertion; only unrelated errors count here.
    unexpected = [item for item in errors if "Failed to load resource" not in item]
    check(not unexpected, f"A03 console/page errors: {unexpected}")
    context.close()


def mobile_flow(browser: Browser, base: str, ticker: str, width: int, height: int) -> None:
    context: BrowserContext = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    errors = watch_errors(page)
    posts = watch_posts(page)
    open_prefilled(page, base, ticker)
    dialog = launcher(page)

    box = dialog.bounding_box()
    check(
        box is not None
        and box["y"] <= 1
        and abs(box["width"] - width) <= 2
        and box["height"] >= height - 2,
        f"{width} launcher is fullscreen ({box})",
    )

    submit = dialog.get_by_role("button", name="开始分析")
    submit.wait_for(state="visible")
    button_box = submit.bounding_box()
    check(
        button_box is not None
        and button_box["height"] >= 44
        and button_box["y"] + button_box["height"] <= height + 1,
        f"{width} primary action is reachable and >=44px ({button_box})",
    )

    overflow = page.evaluate(
        "() => ({doc: document.documentElement.scrollWidth,"
        " body: document.body.scrollWidth, vw: window.innerWidth})"
    )
    check(
        overflow["doc"] <= overflow["vw"] and overflow["body"] <= overflow["vw"],
        f"{width} has no page-level horizontal scroll ({overflow})",
    )
    page.screenshot(path=str(SHOTS / f"launcher_{width}.png"), full_page=True)
    check(not errors, f"{width} console/page errors: {errors}")
    check(posts["count"] == 0, f"{width} opening the launcher never writes")
    context.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()

    with tempfile.TemporaryDirectory(
        prefix="astock-launcher-", ignore_cleanup_errors=True
    ) as temp:
        root = Path(temp)
        fixture = root / "tickers.json"
        fixture.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")
        with DevBackend(root / "backend", fixture) as (api, meta):
            print(f"dev api at {api}")
            with Preview(api) as base:
                print(f"preview at {base}")
                default_date = str(meta["default_analysis_date"])
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    active_id = a01_search_and_submit(
                        browser, base, api, default_date
                    )
                    a02_triple_click(browser, base, api)
                    a03_existing_and_conflict(browser, base, api, active_id)
                    mobile_flow(browser, base, "300750", 390, 844)
                    mobile_flow(browser, base, "300750", 360, 800)
                    browser.close()

    result = {
        "ticket": "A01-A03",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
