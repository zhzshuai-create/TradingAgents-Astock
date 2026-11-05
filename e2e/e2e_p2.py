"""P2-13: one entry point for the P2 exit walkthrough.

Runs the eight verified suites once each, then the checks P2-13 owns: the A04
return paths and the "还有 N 个" jump, A14 filter + scroll restore, and the
mobile measurements M01/M02/M03/M06/M07 at 1440x900, 390x844 and 360x800.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/e2e_p2.py
    ... e2e/e2e_p2.py --new-only      # skip the eight suites while iterating
    ... e2e/e2e_p2.py --phase a14     # only the A14 + mobile backend

The suites are reused as subprocesses instead of being re-implemented: they own
their fake data, temporary roots and stubs, and each prints one JSON line.
Every backend runs from a temporary root with the fake graph; the browser never
creates a job except in the launcher suite where that is the scenario.

Screenshots and suite logs go to ui_shots_p2/P2-13/ (not committed).
"""

from __future__ import annotations

import argparse
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
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-13"
LOGS = SHOTS / "logs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

A04_TICKERS = ("600519", "600520")
A14_TICKER = "600519"
A14_JOBS = 21
A04_STAGE_DELAY_MS = 3000
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
MOBILE_SIZES = ((390, 844), (360, 800))
DESKTOP = {"width": 1440, "height": 900}

SUITES = (
    ("E2E-01/02", "shell_e2e.py"),
    ("E2E-03", "workbench_e2e.py"),
    ("E2E-07", "active_job_e2e.py"),
    ("A01-A03", "launcher_e2e.py"),
    ("E2E-04/M06", "jobs_e2e.py"),
    ("E2E-05/M02/M03/M05/M07", "job_detail_e2e.py"),
    ("A05/A06", "job_stream_e2e.py"),
    ("A07-A10", "job_actions_e2e.py"),
)

failures: list[str] = []
checks = 0
suites: list[dict[str, Any]] = []


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


def wait_until(predicate, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {label}")


def wait_count(locator, count: int, label: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if locator.count() >= count:
            return
        time.sleep(0.05)
    raise AssertionError(f"{label}: expected {count}, saw {locator.count()}")


def wait_url_param(
    page: Page, name: str, value: str | None = None, timeout: float = 10.0
) -> None:
    def probe() -> bool:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
        if name not in params:
            return False
        return value is None or params[name][0] == value

    wait_until(probe, timeout, f"URL parameter {name}")


def wait_chip(page: Page, needle: str, timeout: float = 10.0) -> None:
    """Wait until the rendered filter state (the chips) shows ``needle``.

    The URL changes before React re-renders the page with the new state, so
    the chips are the signal that the next filter change will build on it.
    """

    def probe() -> bool:
        chips = page.get_by_test_id("job-filter-chips")
        return chips.count() > 0 and needle in chips.inner_text()

    wait_until(probe, timeout, f"filter chip {needle!r}")


def get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any], timeout: float = 10.0) -> tuple[int, dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return int(response.status), body, dict(response.headers)
    except urllib.error.HTTPError as error:
        body = json.loads(error.read().decode("utf-8") or "{}")
        return int(error.code), body, dict(error.headers)


def api_ready(base: str, proc: subprocess.Popen[str], timeout: float = 60.0) -> None:
    url = f"{base}/api/v1/jobs/not-ready-probe"

    def probe() -> bool:
        if proc.poll() is not None:
            raise RuntimeError("dev entry exited early")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.status == 404
        except urllib.error.HTTPError as error:
            return error.code == 404
        except (urllib.error.URLError, ConnectionError):
            return False

    wait_until(probe, timeout, "dev API")


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


class DevBackend:
    def __init__(
        self, root: Path, *, worker: bool = True, stage_delay_ms: int = 0
    ) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = os.environ.copy()
        env["TA_DEV_ROOT"] = str(root)
        command = [str(PYTHON), "scripts/dev_backend.py", "--port", str(self.port)]
        if not worker:
            command.append("--no-worker")
        command.extend(["--stage-delay-ms", str(stage_delay_ms)])
        self.proc = subprocess.Popen(
            command,
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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


def watch_posts(page: Page) -> list[str]:
    posts: list[str] = []
    page.on(
        "request",
        lambda request: (
            posts.append(f"{request.method} {request.url}")
            if request.method == "POST" and "/api/v1/jobs" in request.url
            else None
        ),
    )
    return posts


def create_job(api: str, ticker: str) -> tuple[int, str | None]:
    status, body, headers = post_json(
        f"{api}/api/v1/jobs",
        {
            "ticker": ticker,
            "analysis_date": datetime.now(timezone(timedelta(hours=8)))
            .date()
            .isoformat(),
            "config": {
                "llm_profile": "deepseek-default",
                "parallel_analysts": True,
                "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
            },
        },
    )
    job_id = body.get("job_id") if isinstance(body, dict) else None
    return status, None if job_id is None else str(job_id)


def job_status(api: str, job_id: str) -> str | None:
    try:
        return str(get_json(f"{api}/api/v1/jobs/{job_id}")["status"])
    except Exception:  # noqa: BLE001 - best-effort poll
        return None


def run_suites() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    for ticket, name in SUITES:
        log = LOGS / f"{name[:-3]}.log"
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(ROOT / "e2e" / name)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
        log.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
        result: dict[str, Any] = {}
        for line in reversed(proc.stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    continue
                break
        seconds = round(time.monotonic() - started, 1)
        passed = proc.returncode == 0 and not result.get("failures")
        check(
            passed,
            f"{ticket} ({name}): {result.get('checks', '?')} checks, "
            f"{len(result.get('failures', []))} failures, {seconds}s",
        )
        if not passed:
            failures.extend(
                f"{name}: {item}" for item in result.get("failures", ["见日志"])
            )
        suites.append(
            {
                "ticket": ticket,
                "script": f"e2e/{name}",
                "checks": result.get("checks"),
                "failures": result.get("failures", []),
                "exit_code": proc.returncode,
                "seconds": seconds,
                "log": str(log.relative_to(ROOT)).replace("\\", "/"),
            }
        )


def wait_terminal(api: str, job_id: str, timeout: float) -> None:
    wait_until(
        lambda: job_status(api, job_id) in TERMINAL, timeout, f"job {job_id} terminal"
    )


def a04_flow(browser: Browser, base: str, api: str, job_ids: list[str]) -> None:
    context = browser.new_context(viewport=DESKTOP)
    page = context.new_page()
    errors = watch_errors(page)
    posts = watch_posts(page)

    for entry in ("/market", "/reports", f"/stocks/{A04_TICKERS[0]}"):
        page.goto(f"{base}{entry}")
        bar = page.get_by_test_id("active-job-bar")
        bar.wait_for(state="visible", timeout=30_000)
        identity = bar.get_by_role("link").first.inner_text()
        codes = re.findall(r"\d{6}", identity)
        check(len(codes) == 1, f"A04 {entry} bar shows one ticker ({identity!r})")
        code = codes[0] if codes else ""

        target = bar.get_by_role("link", name="查看").get_attribute("href")
        check(
            target in [f"/jobs/{job_id}" for job_id in job_ids],
            f"A04 {entry} bar links to one of the created jobs ({target})",
        )
        page.screenshot(path=str(SHOTS / f"a04_{entry.strip('/').replace('/', '_')}.png"), full_page=True)

        bar.get_by_role("link", name="查看").click()
        page.wait_for_url(f"**{target}")
        page.get_by_test_id("page-job-detail").wait_for(state="visible", timeout=30_000)
        header = page.get_by_test_id("job-header").inner_text()
        check(code in header, f"A04 {entry} detail belongs to {code} ({header!r})")

        page.go_back()
        page.wait_for_url(f"**{entry}")
        check(
            page.url == f"{base}{entry}",
            f"A04 {entry} back returns to the entry page ({page.url})",
        )

    page.goto(f"{base}/market")
    bar = page.get_by_test_id("active-job-bar")
    bar.wait_for(state="visible", timeout=30_000)
    more = bar.get_by_role("link", name=re.compile("还有"))
    check(more.count() == 1, f"A04 the bar shows 还有 N 个 with two active jobs")
    more_text = more.inner_text()
    check("还有 1 个" in more_text, f"A04 the bar counts the extra job ({more_text!r})")
    more.click()
    page.wait_for_url("**/jobs?active=true")
    page.get_by_test_id("page-jobs").wait_for(state="visible", timeout=30_000)
    chips = page.get_by_test_id("job-filter-chips").inner_text()
    check("只看活动任务" in chips, f"A04 还有 N 个 lands on the active filter ({chips!r})")
    wait_count(page.get_by_test_id("job-row"), len(job_ids), "A04 active list rows")
    check(
        page.get_by_test_id("job-row").count() == len(job_ids),
        "A04 the active list shows both active jobs",
    )
    page.screenshot(path=str(SHOTS / "a04_active_list.png"), full_page=True)

    for job_id in job_ids:
        wait_terminal(api, job_id, 180)
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"active-job-bar\"]')",
        timeout=60_000,
    )
    check(True, "A04 the bar disappears after the jobs reach terminal states")

    check(posts == [], f"A04 the browser never POSTs /jobs ({posts})")
    check(not errors, f"A04 console/page errors: {errors}")
    context.close()


def seed_terminal_jobs(api: str, count: int) -> list[str]:
    job_ids: list[str] = []
    for index in range(count):
        status, job_id = create_job(api, A14_TICKER)
        if status != 201 or job_id is None:
            raise RuntimeError(f"create_job returned {status} at {index}")
        job_ids.append(job_id)
        wait_terminal(api, job_id, 60)
    return job_ids


def a14_flow(browser: Browser, base: str, api: str, job_ids: list[str]) -> None:
    context = browser.new_context(viewport=DESKTOP)
    page = context.new_page()
    errors = watch_errors(page)
    posts = watch_posts(page)

    page.goto(f"{base}/jobs")
    page.get_by_test_id("page-jobs").wait_for(state="visible")
    page.get_by_test_id("job-table").wait_for(state="visible")
    wait_count(page.get_by_test_id("job-row"), min(20, len(job_ids)), "A14 first page")

    # Each change replaces the URL, and applyFilters builds on the state of the
    # render it belongs to. Settle one step before starting the next, otherwise
    # a later change can overwrite the URL with the previous state.
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    page.get_by_role("checkbox", name="失败").click()
    wait_url_param(page, "status")
    wait_chip(page, "已完成")
    ticker = page.get_by_label("股票代码")
    ticker.fill(A14_TICKER)
    ticker.press("Enter")
    wait_url_param(page, "ticker", A14_TICKER)
    wait_chip(page, f"股票 {A14_TICKER}")
    page.get_by_label("开始日期").fill(today)
    wait_url_param(page, "date_from", today)
    wait_chip(page, "起")
    page.get_by_label("结束日期").fill(today)
    wait_url_param(page, "date_to", today)
    wait_chip(page, "至")
    # The chips strip is display:none at 1440 (it is a mobile affordance), so
    # presence means "a filter is active"; text is read without layout.
    chips = page.get_by_test_id("job-filter-chips")
    chips.wait_for(state="attached", timeout=15_000)
    chip_text = chips.inner_text()
    check(
        f"股票 {A14_TICKER}" in chip_text,
        f"A14 the chips describe the ticker filter ({chip_text!r})",
    )
    wait_count(page.get_by_test_id("job-row"), 20, "A14 filtered first page")

    page.get_by_role("button", name="加载更多").click()
    wait_count(page.get_by_test_id("job-row"), len(job_ids), "A14 second page")
    wait_url_param(page, "cursor")
    list_url = page.url
    list_query = urllib.parse.urlparse(list_url).query
    list_key = f"ta:jobs-scroll:{urllib.parse.urlparse(list_url).path}?{list_query}"

    page.evaluate(
        "() => { const main = document.getElementById('main-content');"
        " if (main) main.scrollTop = 400; }"
    )
    page.wait_for_timeout(200)
    before = page.evaluate(
        "() => { const main = document.getElementById('main-content');"
        " return main ? main.scrollTop : -1; }"
    )
    check(before > 0, f"A14 the list is scrolled before leaving ({before})")
    page.screenshot(path=str(SHOTS / "a14_filtered_scrolled.png"), full_page=True)

    page.get_by_test_id("job-row").last.get_by_role("link", name="查看").click()
    page.wait_for_url(re.compile(r".*/jobs/[0-9a-f-]+$"))
    page.get_by_test_id("page-job-detail").wait_for(state="visible", timeout=30_000)
    detail_url = page.url
    saved = page.evaluate("(key) => sessionStorage.getItem(key)", list_key)
    check(
        saved is not None and int(saved) > 0,
        f"A14 leaving the list stores the scroll under the list URL ({list_key!r} -> {saved})",
    )

    page.go_back()
    page.wait_for_url(re.compile(r".*/jobs\?.*"))
    page.get_by_test_id("job-table").wait_for(state="visible", timeout=30_000)
    wait_count(page.get_by_test_id("job-row"), len(job_ids), "A14 restored rows")

    check(page.url == list_url, f"A14 back returns to the exact list URL ({page.url})")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
    check("status" in params, "A14 the status filter survives the round trip")
    check(
        params.get("ticker") == [A14_TICKER],
        f"A14 the ticker survives ({params.get('ticker')})",
    )
    check(
        params.get("date_from") == [today] and params.get("date_to") == [today],
        "A14 the date range survives the round trip",
    )
    check("cursor" in params, "A14 the cursor survives the round trip")
    check(
        page.get_by_role("checkbox", name="失败").is_checked() is False,
        "A14 the unchecked status stays unchecked",
    )
    check(
        page.get_by_label("股票代码").input_value() == A14_TICKER,
        "A14 the ticker field is restored",
    )
    check(
        page.get_by_label("开始日期").input_value() != ""
        and page.get_by_label("结束日期").input_value() != "",
        "A14 the date fields are restored",
    )
    check(
        page.get_by_test_id("job-row").count() == len(job_ids),
        "A14 the loaded page count is unchanged after returning",
    )
    restored = page.evaluate(
        "() => { const main = document.getElementById('main-content');"
        " return main ? main.scrollTop : -1; }"
    )
    expected = int(saved or 0)
    check(
        abs(restored - expected) <= 2,
        f"A14 scroll position is restored within 2px (saved {expected}, restored {restored})",
    )
    check(
        page.evaluate("(key) => sessionStorage.getItem(key)", list_key) is None,
        "A14 the scroll key is cleared after a single restore",
    )

    fresh = browser.new_context(viewport=DESKTOP)
    fresh_page = fresh.new_page()
    fresh_page.goto(detail_url)
    fresh_page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    fresh_page.get_by_test_id("job-header").get_by_role("link", name="任务").click()
    fresh_page.wait_for_url(re.compile(r".*/jobs/?$"), timeout=30_000)
    check(
        fresh_page.url.rstrip("/") == f"{base}/jobs",
        f"A14 a fresh tab returns to the default list ({fresh_page.url})",
    )
    check(
        fresh_page.get_by_test_id("job-filter-chips").count() == 0,
        "A14 a fresh tab restores no filters",
    )
    check(
        fresh_page.get_by_label("股票代码").input_value() == "",
        "A14 a fresh tab keeps the ticker field empty",
    )
    fresh.close()

    check(posts == [], f"A14 the browser never POSTs /jobs ({posts})")
    check(not errors, f"A14 console/page errors: {errors}")
    context.close()


def mobile_flow(browser: Browser, base: str, job_id: str, width: int, height: int) -> None:
    label = f"{width}x{height}"
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    errors = watch_errors(page)

    # M07: page-level horizontal scroll on every route.
    for path in (
        "/workbench",
        "/jobs",
        f"/jobs/{job_id}",
        "/market",
        "/reports",
        f"/stocks/{A14_TICKER}",
    ):
        page.goto(f"{base}{path}")
        page.wait_for_timeout(700)
        dims = page.evaluate(
            "() => ({ doc: document.documentElement.scrollWidth,"
            " body: document.body.scrollWidth,"
            " client: document.documentElement.clientWidth })"
        )
        check(
            dims["doc"] <= dims["client"] + 1,
            f"{label} M07 {path} documentElement does not scroll horizontally ({dims})",
        )
        check(
            dims["body"] <= dims["client"] + 1,
            f"{label} M07 {path} body does not overflow ({dims})",
        )

    # M01: the workbench primary action sits in the first screen.
    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for(state="visible")
    primary = page.get_by_test_id("workbench-primary").bounding_box()
    check(
        primary is not None
        and primary["height"] >= 44
        and primary["y"] >= 0
        and primary["y"] + primary["height"] <= height,
        f"{label} M01 primary action is visible without scrolling ({primary})",
    )
    page.screenshot(path=str(SHOTS / f"mobile_{label}_workbench.png"), full_page=True)

    # M02 + M03: the launcher footer is fully visible and not covered.
    page.get_by_test_id("workbench-primary").click()
    dialog = page.get_by_role("dialog", name="分析启动器")
    dialog.wait_for(state="visible", timeout=15_000)
    # The fullscreen sheet opens with a scale animation; measure after it.
    page.wait_for_timeout(400)
    submit = dialog.get_by_role("button", name="开始分析")
    submit.wait_for(state="visible")
    box = submit.bounding_box()
    check(
        box is not None
        and box["height"] >= 44
        and box["y"] >= 0
        and box["y"] + box["height"] <= height + 1,
        f"{label} M02 launcher submit is fully visible ({box})",
    )
    covered = page.evaluate(
        """([x, y]) => {
            const element = document.elementFromPoint(x, y);
            const button = element && element.closest("button");
            return button ? button.textContent.trim().includes("开始分析") : false;
        }""",
        [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2] if box else [0, 0],
    )
    check(covered, f"{label} M02 launcher submit is not covered by the bottom nav")
    panel = dialog.bounding_box()
    check(
        panel is not None
        and panel["y"] <= 1
        and abs(panel["width"] - width) <= 2
        and panel["height"] >= height - 2,
        f"{label} M02 the launcher covers the viewport ({panel})",
    )
    page.screenshot(path=str(SHOTS / f"mobile_{label}_launcher.png"))
    dialog.get_by_role("button", name="取消").click()
    dialog.wait_for(state="hidden", timeout=15_000)

    nav_heights = page.evaluate(
        """() => Array.from(
            document.querySelectorAll('[data-testid="mobile-nav"] a, [data-testid="mobile-nav"] button')
        ).filter((item) => item.offsetParent !== null)
         .map((item) => item.getBoundingClientRect().height)"""
    )
    check(
        len(nav_heights) == 5 and all(value >= 44 for value in nav_heights),
        f"{label} M03 the five nav items are at least 44px ({[round(v) for v in nav_heights]})",
    )
    # M03 counts the primary/secondary Button component (and its danger/small
    # sizes), matching the wireframe audit selectors; an inline submit inside
    # the search field is part of that field, not a standalone touch target.
    content_heights = page.evaluate(
        """() => Array.from(
            document.querySelectorAll("#main-content button[class*='_button_']")
        )
            .filter((item) => item.offsetParent !== null)
            .map((item) => ({ text: item.textContent.trim().slice(0, 12),
                              height: item.getBoundingClientRect().height }))"""
    )
    short = [item for item in content_heights if item["height"] < 44]
    check(
        len(content_heights) > 0 and not short,
        f"{label} M03 every app button is at least 44px ({short})",
    )

    # M06: the job list renders cards, not a table.
    page.goto(f"{base}/jobs")
    page.get_by_test_id("page-jobs").wait_for(state="visible")
    page.get_by_test_id("job-card").first.wait_for(state="visible", timeout=15_000)
    visible_tables = page.evaluate(
        """() => Array.from(document.querySelectorAll("table"))
            .filter((table) => table.offsetParent !== null).length"""
    )
    check(
        visible_tables == 0,
        f"{label} M06 the job list shows no table ({visible_tables})",
    )
    check(
        page.get_by_test_id("job-card").count() >= 1,
        f"{label} M06 the job list renders cards",
    )
    page.screenshot(path=str(SHOTS / f"mobile_{label}_jobs.png"), full_page=True)

    # M02 + M05 + M06 on the detail page: the nav never covers the content.
    page.goto(f"{base}/jobs/{job_id}")
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    actions = page.locator("[data-testid^='job-action-']")
    boxes = [actions.nth(index).bounding_box() for index in range(actions.count())]
    boxes = [box for box in boxes if box is not None]
    check(len(boxes) > 0, f"{label} M03 the detail page shows action buttons ({len(boxes)})")
    check(
        all(box["height"] >= 44 for box in boxes),
        f"{label} M03 action buttons are at least 44px ({[round(b['height']) for b in boxes]})",
    )
    page.evaluate(
        "() => { const main = document.getElementById('main-content');"
        " if (main) main.scrollTop = main.scrollHeight; }"
    )
    page.wait_for_timeout(400)
    edge = page.evaluate(
        """() => {
            const nav = document.querySelector('[data-testid="mobile-nav"]');
            const main = document.getElementById('main-content');
            const bottoms = Array.from(main.querySelectorAll('*'))
                .map((element) => element.getBoundingClientRect())
                .filter((rect) => rect.height > 0 && rect.width > 0 && rect.top >= 0 && rect.bottom > 0)
                .map((rect) => rect.bottom);
            return {
                navTop: nav ? nav.getBoundingClientRect().top : null,
                navHeight: nav ? nav.getBoundingClientRect().height : 0,
                maxBottom: bottoms.length === 0 ? null : Math.max(...bottoms),
                paddingBottom: parseFloat(getComputedStyle(main).paddingBottom),
                atBottom: Math.abs(main.scrollHeight - main.scrollTop - main.clientHeight) <= 1,
            };
        }"""
    )
    check(
        edge["atBottom"] is True,
        f"{label} M02 the detail page scrolls to its end ({edge})",
    )
    check(
        edge["maxBottom"] is not None
        and edge["navTop"] is not None
        and edge["maxBottom"] <= edge["navTop"] + 1,
        f"{label} M02 no visible content is hidden under the bottom nav ({edge})",
    )
    check(
        edge["paddingBottom"] + 1 >= edge["navHeight"],
        f"{label} M02 content padding reserves the nav height ({edge})",
    )
    stage_buttons = page.locator(
        "[data-testid='stage-group-analysis'] button, [data-testid='stage-group-flow'] button"
    )
    heights = [
        stage_buttons.nth(index).bounding_box()["height"]
        for index in range(stage_buttons.count())
    ]
    check(
        len(heights) == 12 and all(value >= 44 for value in heights),
        f"{label} M05/M03 the 12 stage rows are single-column and at least 44px",
    )
    check(
        page.locator("table").count() == 0,
        f"{label} M06 the detail page renders no table",
    )
    page.screenshot(path=str(SHOTS / f"mobile_{label}_detail.png"), full_page=True)

    check(not errors, f"{label} console/page errors: {errors}")
    context.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P2-13 P2 出口验收")
    parser.add_argument(
        "--new-only", action="store_true", help="skip the eight existing suites"
    )
    parser.add_argument(
        "--phase",
        choices=("all", "suites", "a04", "a14"),
        default="all",
        help="a14 includes the mobile measurements",
    )
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "Python313" not in sys.executable and "Python31" not in sys.executable:
        print(f"warning: run with the system Python 3.13 (current: {sys.executable})")
    SHOTS.mkdir(parents=True, exist_ok=True)

    if not args.new_only and args.phase in ("all", "suites"):
        print("running the eight verified suites...")
        run_suites()

    if args.skip_build:
        print("skipping build")
    else:
        print("building frontend...")
        build()

    if args.phase in ("all", "a04"):
        run_a04()

    if args.phase in ("all", "a14"):
        run_a14()

    result = {
        "ticket": "P2-13",
        "checks": checks,
        "failures": failures,
        "suites": suites,
        "screenshots": str(SHOTS.relative_to(ROOT)).replace("\\", "/"),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


def run_a04() -> None:
    with tempfile.TemporaryDirectory(prefix="astock-p2-a04-", ignore_cleanup_errors=True) as temp:
        with DevBackend(Path(temp), worker=True, stage_delay_ms=A04_STAGE_DELAY_MS) as api:
            with Preview(api) as base:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        job_ids = []
                        for ticker in A04_TICKERS:
                            status, job_id = create_job(api, ticker)
                            if status != 201 or job_id is None:
                                raise RuntimeError(f"create_job({ticker}) -> {status}")
                            job_ids.append(job_id)
                        print(f"A04 jobs: {job_ids}")
                        a04_flow(browser, base, api, job_ids)
                    finally:
                        browser.close()

def run_a14() -> None:
    with tempfile.TemporaryDirectory(prefix="astock-p2-a14-", ignore_cleanup_errors=True) as temp:
        with DevBackend(Path(temp), worker=True, stage_delay_ms=0) as api:
            print(f"seeding {A14_JOBS} terminal jobs...")
            job_ids = seed_terminal_jobs(api, A14_JOBS)
            with Preview(api) as base:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    try:
                        a14_flow(browser, base, api, job_ids)
                        for width, height in MOBILE_SIZES:
                            mobile_flow(browser, base, job_ids[0], width, height)
                    finally:
                        browser.close()


if __name__ == "__main__":
    sys.exit(main())
