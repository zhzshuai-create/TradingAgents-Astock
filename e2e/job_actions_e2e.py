"""A07-A10: pause/resume, cancel, retry and resume-from-checkpoint.

Seeds the nine fixture states, starts the real dev entry (API + worker, fake
graph, slowed stage boundaries) against the same temporary root, previews the
built frontend with ``/api`` proxied to it, and drives the browser through the
four scenarios from ``contracts/interaction-checklist.md``.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/job_actions_e2e.py

A07 pauses a live job at a stage boundary, resumes it with the same job id and
checks the next stage runs. A08 dismisses the cancel dialog once (no request),
then confirms and waits for the terminal state without a report link. A09
retries a seeded failed job and double-clicks to prove one new job. A10 resumes
a seeded interrupted job from its checkpoint, then tampers the stored config
digest to see the 409 branch, restores it and resumes successfully.

Prints one JSON line; screenshots go to ui_shots_p2/P2-12/.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-12"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

STAGE_DELAY_MS = 5000
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
STAGE_IDS = [
    "market",
    "social",
    "news",
    "fundamentals",
    "policy",
    "hot_money",
    "lockup",
    "quality_gate",
    "debate",
    "trader",
    "risk",
    "pm",
]
STAGE_LABELS = {
    "pending": "等待中",
    "active": "执行中",
    "done": "已完成",
    "failed": "失败",
    "skipped": "已跳过",
}

UI_STATE = r"""
() => {
  const header = document.querySelector('[data-testid="job-header"]');
  const stages = {};
  for (const id of ["market", "social", "news", "fundamentals", "policy",
    "hot_money", "lockup", "quality_gate", "debate", "trader", "risk", "pm"]) {
    const button = document.querySelector('[data-testid="stage-' + id + '"]');
    const spans = button ? button.querySelectorAll("span") : [];
    stages[id] = spans.length >= 3 ? spans[2].textContent.trim() : "";
  }
  const buttons = Array.from(
    document.querySelectorAll("[data-testid^='job-action-']")
  ).filter((element) => element.tagName === "BUTTON");
  const dialog = document.querySelector('[data-testid="job-cancel-dialog"]');
  return {
    header: header ? header.innerText : "",
    actions: buttons.map((button) => button.getAttribute("data-testid")),
    stageLabels: stages,
    doneStages: Object.values(stages).filter((label) => label === "已完成").length,
    reportLink: Boolean(document.querySelector("[data-testid='job-open-report']")),
    dialogOpen: Boolean(dialog),
    dialogText: dialog ? dialog.innerText : "",
    noticeText: (document.querySelector("[data-testid='job-action-notice']")
      || {innerText: ""}).innerText,
    errorText: (document.querySelector("[data-testid='job-action-error']")
      || {innerText: ""}).innerText,
    focusedTestId: document.activeElement
      ? document.activeElement.getAttribute("data-testid")
      : null,
  };
}
"""

UI_LOG = r"""
(() => {
  window.__taUi = { headers: [], dialogTexts: [] };
  const remember = (list, value) => {
    if (!value || list[list.length - 1] === value) {
      return;
    }
    list.push(value);
  };
  const record = () => {
    const header = document.querySelector('[data-testid="job-header"]');
    if (header) {
      remember(window.__taUi.headers, header.innerText);
    }
    const dialog = document.querySelector('[data-testid="job-cancel-dialog"]');
    if (dialog) {
      remember(window.__taUi.dialogTexts, dialog.innerText);
    }
  };
  setInterval(record, 100);
  const start = () => {
    record();
    new MutationObserver(record).observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
    });
  };
  if (document.documentElement) {
    start();
  } else {
    document.addEventListener("DOMContentLoaded", start);
  }
})();
"""

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


def post_json(
    url: str, body: dict, headers: dict[str, str] | None = None
) -> tuple[int, dict[str, str], dict]:
    payload = json.dumps(body).encode("utf-8")
    merged = {"Content-Type": "application/json"}
    merged.update(headers or {})
    request = urllib.request.Request(
        url, data=payload, method="POST", headers=merged
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return (
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                json.loads(response.read().decode("utf-8")),
            )
    except urllib.error.HTTPError as error:
        body_text = error.read().decode("utf-8")
        return (
            error.code,
            {key.lower(): value for key, value in error.headers.items()},
            json.loads(body_text) if body_text else {},
        )


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
                "--stage-delay-ms",
                str(STAGE_DELAY_MS),
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
        preview_ready(f"{self.base}/workbench", self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def watch_errors(page: Page, *, ignore_network: bool = False) -> list[str]:
    errors: list[str] = []

    def on_console(message) -> None:
        if message.type != "error":
            return
        if ignore_network and message.text.startswith("Failed to load resource"):
            return
        errors.append(message.text)

    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", on_console)
    return errors


def watch_writes(page: Page) -> list[str]:
    writes: list[str] = []

    def on_request(request) -> None:
        if request.method != "GET" and "/api/v1/" in request.url:
            writes.append(f"{request.method} {request.url}")

    page.on("request", on_request)
    return writes


def create_job(api: str, ticker: str) -> str:
    status, _headers, body = post_json(
        f"{api}/api/v1/jobs",
        {
            "ticker": ticker,
            "analysis_date": datetime.now(timezone(timedelta(hours=8)))
            .date()
            .isoformat(),
            "config": {
                "llm_profile": "deepseek-default",
                "parallel_analysts": True,
                "stage_toggles": {
                    "policy": True,
                    "hot_money": True,
                    "lockup": True,
                },
            },
        },
        {"Idempotency-Key": str(uuid.uuid4())},
    )
    if status != 201:
        raise RuntimeError(f"create_job({ticker}) returned {status}: {body}")
    return str(body["job_id"])


def job_detail(api: str, job_id: str) -> dict:
    return get_json(f"{api}/api/v1/jobs/{job_id}")


def job_summaries(api: str) -> list[dict]:
    return get_json(f"{api}/api/v1/jobs?limit=50")["items"]


def cancel_job(api: str, job_id: str) -> None:
    status, _headers, body = post_json(
        f"{api}/api/v1/jobs/{job_id}/actions", {"action": "cancel"}
    )
    if status not in (200, 202):
        raise RuntimeError(f"cancel({job_id}) returned {status}: {body}")


def cancel_if_active(api: str, job_id: str) -> None:
    detail = job_detail(api, job_id)
    if detail["status"] in TERMINAL:
        return
    cancel_job(api, job_id)
    wait_for_status(api, job_id, "cancelled", timeout=30)


def wait_for_status(api: str, job_id: str, status: str, timeout: float = 90.0) -> dict:
    latest: dict = {}

    def reached() -> bool:
        nonlocal latest
        try:
            latest = job_detail(api, job_id)
        except (urllib.error.URLError, TimeoutError, OSError):
            return False
        return latest["status"] == status

    wait_until(reached, timeout, f"job {job_id} {status}")
    return latest


def wait_for_statuses(
    api: str, job_id: str, statuses: set[str], timeout: float = 90.0
) -> dict:
    latest: dict = {}

    def reached() -> bool:
        nonlocal latest
        try:
            latest = job_detail(api, job_id)
        except (urllib.error.URLError, TimeoutError, OSError):
            return False
        return latest["status"] in statuses

    wait_until(reached, timeout, f"job {job_id} in {sorted(statuses)}")
    return latest


def done_stages(detail: dict) -> int:
    return sum(1 for stage in detail["stages"] if stage["status"] == "done")


def ui_state(page: Page) -> dict:
    return page.evaluate(UI_STATE)


def wait_actions(page: Page, expected: list[str], timeout: float = 15.0) -> dict:
    """The terminal badge and its allowed actions arrive with the same job."""
    deadline = time.monotonic() + timeout
    state = ui_state(page)
    while state["actions"] != expected and time.monotonic() < deadline:
        page.wait_for_timeout(100)
        state = ui_state(page)
    return state


def wait_header(page: Page, label: str, timeout: float = 30_000) -> None:
    page.wait_for_function(
        "(label) => { const header = document.querySelector("
        "'[data-testid=\"job-header\"]'); "
        "return Boolean(header && header.innerText.includes(label)); }",
        arg=label,
        timeout=timeout,
    )


def wait_done_growth(page: Page, before: int, timeout: float = 30_000) -> None:
    page.wait_for_function(
        "(before) => Array.from(document.querySelectorAll("
        "'[data-testid=\"stage-group-analysis\"] button, "
        "[data-testid=\"stage-group-flow\"] button')).filter("
        "(button) => button.textContent.includes('已完成')).length > before",
        arg=before,
        timeout=timeout,
    )


def set_config_hash(db_path: Path, job_id: str, value: str) -> None:
    connection = sqlite3.connect(db_path, timeout=10)
    try:
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute(
            "UPDATE jobs SET config_hash = ? WHERE id = ?", (value, job_id)
        )
        connection.commit()
    finally:
        connection.close()


def a07_pause_resume(browser: Browser, base: str, api: str) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page)
    writes = watch_writes(page)

    job_id = create_job(api, "000629")
    wait_for_status(api, job_id, "running")
    page.goto(f"{base}/jobs/{job_id}")
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    wait_header(page, "运行中")
    wait_done_growth(page, 0)

    before = job_detail(api, job_id)
    page.get_by_test_id("job-action-pause").click()
    wait_header(page, "暂停中")
    page.get_by_test_id("job-notice").wait_for(state="visible", timeout=15_000)
    check(
        "已受理" in page.get_by_test_id("job-notice").inner_text()
        and "阶段结束后生效" in page.get_by_test_id("job-notice").inner_text(),
        "A07 pause notice explains the stage boundary",
    )
    accepted = job_detail(api, job_id)
    check(
        accepted["status"] == "pause_requested"
        and accepted["pending_action"] == "pause",
        f"A07 pause accepted without becoming paused "
        f"({accepted['status']}/{accepted['pending_action']})",
    )
    page.screenshot(path=str(SHOTS / "a07_pause_requested.png"), full_page=True)

    paused = wait_for_status(api, job_id, "paused")
    wait_header(page, "已暂停")
    page.get_by_test_id("job-action-resume").wait_for(
        state="visible", timeout=10_000
    )
    paused_done = done_stages(paused)
    check(
        paused_done >= done_stages(before),
        f"A07 pause keeps completed stages ({paused_done})",
    )
    paused_ui = ui_state(page)
    check(
        paused_ui["actions"] == ["job-action-resume", "job-action-cancel"],
        f"A07 paused actions come from the server ({paused_ui['actions']})",
    )
    page.screenshot(path=str(SHOTS / "a07_paused.png"), full_page=True)

    page.get_by_test_id("job-action-resume").click()
    resumed = wait_for_statuses(api, job_id, {"running", "succeeded"})
    check(resumed["job_id"] == job_id, "A07 resume keeps the same job id")
    check(
        resumed["resume_from_stage"] is not None,
        f"A07 resume records the checkpoint ({resumed['resume_from_stage']})",
    )
    page.wait_for_function(
        "(args) => { const header = document.querySelector("
        "'[data-testid=\"job-header\"]'); return Boolean(header && ("
        "header.innerText.includes(args[0]) || header.innerText.includes(args[1]))); }",
        arg=["运行中", "已完成"],
        timeout=30_000,
    )
    deadline = time.monotonic() + 40
    advanced = job_detail(api, job_id)
    while (
        time.monotonic() < deadline
        and advanced["status"] != "succeeded"
        and done_stages(advanced) <= paused_done
    ):
        time.sleep(0.1)
        advanced = job_detail(api, job_id)
    if time.monotonic() >= deadline:
        raise RuntimeError("timed out waiting for the resumed job to advance")
    check(
        advanced["status"] == "succeeded" or done_stages(advanced) > paused_done,
        f"A07 resumed job continues past the checkpoint "
        f"({paused_done} -> {done_stages(advanced)}, {advanced['status']})",
    )
    wait_done_growth(page, paused_done, timeout=40_000)
    resumed_ui = ui_state(page)
    check(
        resumed_ui["doneStages"] > paused_done,
        f"A07 UI shows the next completed stage "
        f"({resumed_ui['doneStages']} > {paused_done})",
    )
    check(
        sum(1 for entry in writes if entry.endswith("/actions")) == 2,
        f"A07 pause and resume use the actions endpoint ({writes})",
    )
    page.screenshot(path=str(SHOTS / "a07_resumed.png"), full_page=True)

    cancel_if_active(api, job_id)
    check(not errors, f"A07 console/page errors: {errors}")
    context.close()


def a08_cancel(browser: Browser, base: str, api: str) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.add_init_script(UI_LOG)
    errors = watch_errors(page)
    writes = watch_writes(page)

    job_id = create_job(api, "000630")
    wait_for_status(api, job_id, "running")
    page.goto(f"{base}/jobs/{job_id}")
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    wait_header(page, "运行中")
    wait_done_growth(page, 0)

    writes_before = len(writes)
    page.get_by_test_id("job-action-cancel").click()
    page.get_by_test_id("job-cancel-dialog").wait_for(
        state="visible", timeout=10_000
    )
    page.wait_for_function(
        "() => document.activeElement && "
        "document.activeElement.getAttribute('data-testid') === "
        "'job-cancel-dismiss'",
        timeout=5_000,
    )
    dialog = ui_state(page)
    check(
        "已产生的模型费用不退" in dialog["dialogText"]
        and "不会生成完整报告" in dialog["dialogText"],
        "A08 cancel dialog states the cost and report consequence",
    )
    check(
        dialog["focusedTestId"] == "job-cancel-dismiss",
        f"A08 dialog focuses the safe button ({dialog['focusedTestId']})",
    )
    check(
        len(writes) == writes_before,
        f"A08 opening the dialog sends no write ({writes})",
    )
    page.screenshot(path=str(SHOTS / "a08_cancel_dialog.png"), full_page=True)

    page.get_by_test_id("job-cancel-dismiss").click()
    page.get_by_test_id("job-cancel-dialog").wait_for(
        state="hidden", timeout=5_000
    )
    dismissed = job_detail(api, job_id)
    check(
        len(writes) == writes_before and dismissed["status"] == "running",
        f"A08 dismissing the dialog sends no write ({writes})",
    )

    page.get_by_test_id("job-action-cancel").click()
    page.get_by_test_id("job-cancel-confirm").click()
    page.wait_for_function(
        "() => { const header = document.querySelector("
        "'[data-testid=\"job-header\"]'); if (!header) return false; "
        "return header.innerText.includes('取消中') "
        "|| header.innerText.includes('已取消'); }",
        timeout=15_000,
    )
    accepted = job_detail(api, job_id)
    check(
        accepted["status"] in {"cancel_requested", "cancelled"},
        f"A08 cancel accepted without jumping to a report "
        f"({accepted['status']})",
    )
    log = page.evaluate("() => window.__taUi")
    check(
        any("取消中" in text for text in log["headers"]),
        "A08 the UI showed 取消中 before the terminal state",
    )
    page.screenshot(path=str(SHOTS / "a08_cancel_requested.png"), full_page=True)

    final = wait_for_status(api, job_id, "cancelled")
    wait_header(page, "已取消")
    final_ui = wait_actions(page, ["job-action-reanalyze"])
    check(final["report_id"] is None, "A08 cancelled job has no report id")
    # api-v1.md 1.6: cancelled allows reanalyze only, and never a report link.
    check(
        final_ui["actions"] == ["job-action-reanalyze"]
        and not final_ui["reportLink"],
        f"A08 cancelled detail only offers reanalyze and no report entry "
        f"({final_ui['actions']})",
    )
    check(
        len([entry for entry in writes if "/actions" in entry]) == 1,
        f"A08 confirmation sends exactly one cancel request ({writes})",
    )
    page.screenshot(path=str(SHOTS / "a08_cancelled.png"), full_page=True)
    check(not errors, f"A08 console/page errors: {errors}")
    context.close()


def a09_retry(browser: Browser, base: str, api: str, failed_id: str) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page)
    writes = watch_writes(page)

    before = job_detail(api, failed_id)
    page.goto(f"{base}/jobs/{failed_id}")
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    wait_header(page, "失败")
    initial = ui_state(page)
    check(
        initial["actions"]
        == ["job-action-retry", "job-action-reanalyze"],
        f"A09 failed job offers retry and reanalyze ({initial['actions']})",
    )
    page.screenshot(path=str(SHOTS / "a09_failed.png"), full_page=True)

    page.get_by_test_id("job-action-retry").dblclick()
    page.wait_for_function(
        "(oldId) => location.pathname !== '/jobs/' + oldId",
        arg=failed_id,
        timeout=30_000,
    )
    new_id = page.url.rstrip("/").rsplit("/", 1)[-1]
    check(new_id != failed_id, f"A09 retry opens a new job ({new_id})")
    created = job_detail(api, new_id)
    check(
        created["retry_of_job_id"] == failed_id,
        f"A09 new job records retry_of_job_id ({created['retry_of_job_id']})",
    )
    check(
        created["ticker_code"] == before["ticker_code"]
        and created["analysis_date"] == before["analysis_date"],
        "A09 new job inherits ticker and analysis date",
    )
    check(
        created["status"] in {"queued", "running", "succeeded"},
        f"A09 new job is runnable ({created['status']})",
    )
    retries = [
        job
        for job in job_summaries(api)
        if job["retry_of_job_id"] == failed_id
    ]
    check(
        len(retries) == 1,
        f"A09 a double click still creates one retry job ({len(retries)})",
    )
    after = job_detail(api, failed_id)
    check(
        after["status"] == before["status"]
        and after["updated_at"] == before["updated_at"]
        and after["error"] == before["error"]
        and after["stages"] == before["stages"],
        "A09 the failed job stays unchanged",
    )
    page.wait_for_function(
        "(label) => { const header = document.querySelector("
        "'[data-testid=\"job-header\"]'); "
        "return Boolean(header && header.innerText.includes(label)); }",
        arg="运行中",
        timeout=30_000,
    )
    check(
        len([entry for entry in writes if "/retry" in entry]) == 1,
        f"A09 a double click sends one retry request ({writes})",
    )
    page.screenshot(path=str(SHOTS / "a09_retry_running.png"), full_page=True)
    check(not errors, f"A09 console/page errors: {errors}")
    context.close()

    cancel_if_active(api, new_id)


def a10_resume(browser: Browser, base: str, api: str, interrupted_id: str, db_path: Path) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page, ignore_network=True)

    original = job_detail(api, interrupted_id)
    page.goto(f"{base}/jobs/{interrupted_id}")
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    wait_header(page, "等待人工处理")
    initial = ui_state(page)
    check(
        initial["actions"]
        == [
            "job-action-resume_from_checkpoint",
            "job-action-retry",
            "job-action-reanalyze",
        ],
        f"A10 interrupted job offers resume, retry and reanalyze ({initial['actions']})",
    )
    page.screenshot(path=str(SHOTS / "a10_interrupted.png"), full_page=True)

    set_config_hash(db_path, interrupted_id, "e2e-tampered-digest")
    page.reload()
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    with page.expect_response(
        lambda response: response.url.endswith(
            f"/api/v1/jobs/{interrupted_id}/retry"
        )
        and response.request.method == "POST",
        timeout=30_000,
    ) as mismatch_info:
        page.get_by_test_id("job-action-resume_from_checkpoint").click()
    check(
        mismatch_info.value.status == 409,
        f"A10 a tampered digest returns 409 ({mismatch_info.value.status})",
    )
    page.get_by_test_id("job-action-notice").wait_for(
        state="visible", timeout=15_000
    )
    mismatch_ui = ui_state(page)
    check(
        mismatch_ui["actions"] == ["job-action-reanalyze"],
        f"A10 fingerprint mismatch hides resume and retry "
        f"({mismatch_ui['actions']})",
    )
    check(
        "配置已变化" in mismatch_ui["noticeText"],
        f"A10 mismatch notice explains the limit ({mismatch_ui['noticeText']})",
    )
    check(
        "配置已变化" in mismatch_ui["errorText"],
        f"A10 mismatch shows the server message ({mismatch_ui['errorText']})",
    )
    page.screenshot(path=str(SHOTS / "a10_fingerprint_mismatch.png"), full_page=True)

    set_config_hash(db_path, interrupted_id, original["config_digest"])
    page.reload()
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    restored = ui_state(page)
    check(
        restored["actions"]
        == [
            "job-action-resume_from_checkpoint",
            "job-action-retry",
            "job-action-reanalyze",
        ],
        f"A10 restoring the digest brings the actions back ({restored['actions']})",
    )

    with page.expect_response(
        lambda response: response.url.endswith(
            f"/api/v1/jobs/{interrupted_id}/retry"
        )
        and response.request.method == "POST",
        timeout=30_000,
    ) as response_info:
        page.get_by_test_id("job-action-resume_from_checkpoint").click()
    response = response_info.value
    check(response.status == 201, f"A10 resume creates a new job ({response.status})")
    body = response.json()
    new_id = str(body["job_id"])
    check(
        body["resume_of_job_id"] == interrupted_id,
        f"A10 new job records resume_of_job_id ({body['resume_of_job_id']})",
    )
    check(
        body["resume_from_stage"] == original["resume_from_stage"],
        f"A10 new job starts at the checkpoint ({body['resume_from_stage']})",
    )
    check(
        body["retry_of_job_id"] is None,
        "A10 resumed job is not a same-config retry",
    )
    page.wait_for_function(
        "(oldId) => location.pathname !== '/jobs/' + oldId",
        arg=interrupted_id,
        timeout=30_000,
    )
    running = wait_for_statuses(api, new_id, {"running", "succeeded"}, timeout=60)
    check(
        running["job_id"] == new_id and running["resume_from_stage"] is not None,
        f"A10 the resumed job continues from the checkpoint ({running['status']})",
    )
    old_after = job_detail(api, interrupted_id)
    check(
        old_after["status"] == "interrupted",
        "A10 the interrupted job stays untouched",
    )
    page.screenshot(path=str(SHOTS / "a10_resumed.png"), full_page=True)
    check(not errors, f"A10 console/page errors (network filtered): {errors}")
    context.close()

    cancel_if_active(api, new_id)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()

    with tempfile.TemporaryDirectory(prefix="astock-actions-e2e-") as temp:
        root = Path(temp)
        db_path = root / "jobs.db"
        seeded = seed_jobs(root)
        print(f"seeded {len(seeded)} jobs")
        with DevBackend(root) as api:
            print(f"dev api at {api}")
            cancel_job(api, seeded["queued"]["job_id"])
            with Preview(api) as base:
                print(f"preview at {base}")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    a07_pause_resume(browser, base, api)
                    a08_cancel(browser, base, api)
                    a09_retry(browser, base, api, seeded["failed"]["job_id"])
                    a10_resume(
                        browser,
                        base,
                        api,
                        seeded["interrupted"]["job_id"],
                        db_path,
                    )
                    browser.close()

    result = {
        "ticket": "A07-A10",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
