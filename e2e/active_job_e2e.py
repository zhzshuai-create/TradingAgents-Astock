"""E2E-07: the active job bar navigates, never creates, and disappears.

Runs the real dev entry (API + worker, fake graph) against a temporary root and
previews the built frontend with ``/api`` proxied to it. The job is created from
Python; the browser may only read.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/active_job_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p2/P2-06/.
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
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-06"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

TICKER = "000629"
STAGE_DELAY_MS = 1200
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
PAGES = ["/workbench", "/jobs", "/reports"]

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


def get_json(url: str, timeout: float = 2.0) -> dict:
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


def create_job(api: str) -> str:
    payload = json.dumps(
        {
            "ticker": TICKER,
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
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api}/api/v1/jobs",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = json.loads(response.read().decode("utf-8"))
    return str(body["job_id"])


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


def job_status(api: str, job_id: str) -> str | None:
    try:
        return str(get_json(f"{api}/api/v1/jobs/{job_id}", timeout=5)["status"])
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def wait_for_running(api: str, job_id: str, timeout: float = 60.0) -> None:
    def running() -> bool:
        try:
            body = get_json(f"{api}/api/v1/jobs/{job_id}", timeout=5)
        except (urllib.error.URLError, TimeoutError, OSError):
            return False
        return body["status"] == "running"

    wait_until(running, timeout, "job running")


def active_bar_flow(browser: Browser, base: str, api: str, job_id: str) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = watch_errors(page)
    posts: list[str] = []
    page.on(
        "request",
        lambda request: (
            posts.append(request.url)
            if request.method == "POST" and "/api/v1/jobs" in request.url
            else None
        ),
    )

    for name, path in zip(("workbench", "jobs", "reports"), PAGES):
        page.goto(f"{base}{path}")
        bar = page.get_by_test_id("active-job-bar")
        bar.wait_for(state="visible")
        text = bar.inner_text()
        check(TICKER in text, f"{path} bar shows the ticker ({text})")
        page.screenshot(path=str(SHOTS / f"active_bar_{name}.png"), full_page=True)

        bar.get_by_role("link", name="查看").click()
        page.wait_for_url(f"**/jobs/{job_id}")
        check(
            page.url.endswith(f"/jobs/{job_id}"),
            f"{path} bar navigates to /jobs/{job_id}",
        )

    check(posts == [], f"browser never POSTs /jobs ({posts})")

    wait_until(lambda: job_status(api, job_id) in TERMINAL, 90, "terminal job")
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"active-job-bar\"]')",
        timeout=30_000,
    )
    check(True, "bar disappears after the job reaches a terminal state")
    page.get_by_test_id("page-job-detail").wait_for(state="visible")
    page.screenshot(path=str(SHOTS / "active_bar_after_terminal.png"), full_page=True)

    check(not errors, f"browser console/page errors: {errors}")
    context.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()

    with tempfile.TemporaryDirectory(prefix="astock-e2e-") as temp:
        with DevBackend(Path(temp)) as api:
            print(f"dev api at {api}")
            with Preview(api) as base:
                print(f"preview at {base}")
                job_id = create_job(api)
                print(f"created {job_id}")
                wait_for_running(api, job_id)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    active_bar_flow(browser, base, api, job_id)
                    browser.close()

    result = {
        "ticket": "E2E-07",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
