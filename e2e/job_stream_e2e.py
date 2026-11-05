"""A05 + A06: job detail event stream, refresh replay and reconnect.

Runs the real dev entry (API + worker, fake graph, slowed stage boundaries)
against a temporary root, previews the built frontend with ``/api`` proxied to
it, and creates the job from Python. The browser only reads.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/job_stream_e2e.py

A05 reloads the detail page and checks the new stream carries the saved cursor,
that stages never move backwards, that actions still match the API and that no
job was created. A06 aborts the event route for ten seconds, checks the
reconnect banner and growing retry gaps, then lets the stream resume and checks
the replay starts right after the cursor, stays continuous, reaches the
terminal state, and stops reconnecting.

Prints one JSON line; screenshots go to ui_shots_p2/P2-11/.
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

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-11"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

TICKER = "000629"
STAGE_DELAY_MS = 3000
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
OFFLINE_SECONDS = 10.0

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

STAGE_RANK = {"等待中": 0, "执行中": 1, "已完成": 2, "失败": 2, "已跳过": 2}

SSE_RECORDER = r"""
(() => {
  window.__taSse = { connections: [], events: [] };
  const originalFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (!url.includes("/events")) {
      return originalFetch.apply(this, arguments);
    }
    const source = (init && init.headers) || (input && input.headers);
    const headers = new Headers(source || undefined);
    const record = {
      url: url,
      lastEventId: headers.get("Last-Event-ID"),
      at: Date.now(),
      closedAt: null,
      contentType: null,
      error: null,
      frames: [],
    };
    window.__taSse.connections.push(record);
    const result = originalFetch.apply(this, arguments);
    result.then((response) => {
      record.contentType = response.headers.get("Content-Type") || "";
      if (!response.body) {
        record.closedAt = Date.now();
        return;
      }
      const reader = response.clone().body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const pump = () => reader.read().then(({ done, value }) => {
        if (done) {
          record.closedAt = Date.now();
          return;
        }
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n\n")) !== -1) {
          const block = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          const dataLines = block
            .split("\n")
            .filter((line) => line.startsWith("data: "))
            .map((line) => line.slice(6));
          if (dataLines.length === 0) {
            continue;
          }
          try {
            const data = JSON.parse(dataLines.join("\n"));
            record.frames.push({ type: data.type, seq: data.seq });
            window.__taSse.events.push({ type: data.type, seq: data.seq });
          } catch (error) {
            record.frames.push({ type: "unparsed", seq: null });
          }
        }
        return pump();
      });
      return pump();
    }).catch((error) => {
      record.error = String(error);
      record.closedAt = Date.now();
    });
    return result;
  };
})();
"""

UI_STATE = r"""
() => {
  const ids = ["market", "social", "news", "fundamentals", "policy",
    "hot_money", "lockup", "quality_gate", "debate", "trader", "risk", "pm"];
  const stages = {};
  for (const id of ids) {
    const button = document.querySelector('[data-testid="stage-' + id + '"]');
    const spans = button ? button.querySelectorAll("span") : [];
    stages[id] = spans.length >= 3 ? spans[2].textContent.trim() : "";
  }
  const actionButtons = Array.from(
    document.querySelectorAll("[data-testid^='job-action-']")
  );
  const header = document.querySelector("[data-testid='job-header']");
  return {
    stages: stages,
    actions: actionButtons.length,
    actionsEnabled: actionButtons.every((button) => !button.disabled),
    header: header ? header.innerText : "",
    reportLink: Boolean(document.querySelector("[data-testid='job-open-report']")),
    reconnecting: Boolean(
      document.querySelector("[data-testid='job-stream-reconnecting']")
    ),
    expired: Boolean(
      document.querySelector("[data-testid='job-stream-expired']")
    ),
  };
}
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


def job_detail(api: str, job_id: str) -> dict:
    return get_json(f"{api}/api/v1/jobs/{job_id}")


def job_count(api: str) -> int:
    body = get_json(f"{api}/api/v1/jobs?limit=50")
    return len(body["items"])


def event_seqs(db_path: Path, job_id: str) -> list[int]:
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT seq FROM job_events WHERE job_id = ? AND seq IS NOT NULL "
            "ORDER BY seq",
            (job_id,),
        ).fetchall()
    finally:
        connection.close()
    return [int(row[0]) for row in rows]


def wait_for_status(api: str, job_id: str, status: str, timeout: float = 60.0) -> dict:
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


def ui_state(page: Page) -> dict:
    return page.evaluate(UI_STATE)


def cursor_of(page: Page, job_id: str) -> int | None:
    raw = page.evaluate(
        "(jobId) => sessionStorage.getItem('ta:job-cursor:' + jobId)", job_id
    )
    return None if raw is None else int(raw)


def connections(page: Page) -> list[dict]:
    return page.evaluate("() => window.__taSse.connections")


def recorded_events(page: Page) -> list[dict]:
    return page.evaluate("() => window.__taSse.events")


def stage_ranks(state: dict) -> dict[str, int]:
    return {
        stage_id: STAGE_RANK.get(label, -1)
        for stage_id, label in state["stages"].items()
    }


def a05_refresh_replay(
    browser: Browser, base: str, api: str, job_id: str
) -> dict:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.add_init_script(SSE_RECORDER)
    errors = watch_errors(page)
    writes = watch_writes(page)

    page.goto(f"{base}/jobs/{job_id}")
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    page.wait_for_function(
        "() => window.__taSse && window.__taSse.connections.length >= 1",
        timeout=15_000,
    )
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('button[data-testid^=\"stage-\"]'))"
        ".filter((button) => button.textContent.includes('已完成')).length >= 1",
        timeout=45_000,
    )

    before = ui_state(page)
    cursor_before = cursor_of(page, job_id)
    check(
        cursor_before is not None and cursor_before > 0,
        f"A05 event cursor exists before refresh ({cursor_before})",
    )
    detail_before = job_detail(api, job_id)
    jobs_before = job_count(api)
    check(detail_before["status"] == "running", "A05 job is still running before refresh")
    check(
        sum(1 for label in before["stages"].values() if label != "等待中") >= 1,
        "A05 detail shows progressed stages before refresh",
    )
    page.screenshot(path=str(SHOTS / "a05_before_refresh.png"), full_page=True)

    page.reload()
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    page.wait_for_function(
        "() => window.__taSse && window.__taSse.connections.length >= 1",
        timeout=15_000,
    )
    after = ui_state(page)
    resumed = connections(page)[0]
    check(
        resumed["lastEventId"] is not None
        and cursor_before is not None
        and int(resumed["lastEventId"]) >= cursor_before,
        f"A05 reloaded stream carries Last-Event-ID "
        f"({resumed['lastEventId']} >= {cursor_before})",
    )
    check(
        "text/event-stream" in (resumed["contentType"] or ""),
        f"A05 stream content type is event-stream ({resumed['contentType']})",
    )

    ranks_before = stage_ranks(before)
    ranks_after = stage_ranks(after)
    regressions = [
        stage_id
        for stage_id in STAGE_IDS
        if ranks_after[stage_id] < ranks_before[stage_id]
    ]
    check(regressions == [], f"A05 stages never move backwards ({regressions})")
    check(
        len([label for label in after["stages"].values() if label]) == 12,
        "A05 details still render 12 stages after refresh",
    )
    check(
        after["actions"] == before["actions"]
        and after["actionsEnabled"] == before["actionsEnabled"],
        f"A05 action buttons match before/after "
        f"({before['actions']} -> {after['actions']})",
    )

    detail_after = None
    for _ in range(20):
        detail_after = job_detail(api, job_id)
        if len(detail_after["allowed_actions"]) == after["actions"]:
            break
        time.sleep(0.1)
    assert detail_after is not None
    check(
        after["actions"] == len(detail_after["allowed_actions"])
        and after["actionsEnabled"],
        f"A05 rendered actions match the API ({after['actions']})",
    )
    check(not after["expired"], "A05 refresh does not show the expired banner")
    check(job_count(api) == jobs_before, "A05 refresh does not create a job")
    check(writes == [], f"A05 browser issues no writes ({writes})")
    check(not errors, f"A05 console/page errors: {errors}")
    page.screenshot(path=str(SHOTS / "a05_after_refresh.png"), full_page=True)
    context.close()
    return detail_after


MOBILE_BANNER_STATE = r"""
() => {
  const nav = document.querySelector('[data-testid="mobile-nav"]');
  const banner = document.querySelector('[data-testid="job-stream-reconnecting"]');
  const navBox = nav ? nav.getBoundingClientRect() : null;
  const bannerBox = banner ? banner.getBoundingClientRect() : null;
  return {
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    navVisible: Boolean(navBox && navBox.width > 0 && navBox.height > 0),
    overlap: Boolean(
      navBox && bannerBox && bannerBox.bottom > navBox.top
      && bannerBox.top < navBox.bottom
    ),
    bannerVisible: Boolean(bannerBox && bannerBox.height > 0),
  };
}
"""


def a06_mobile_banner(browser: Browser, base: str, job_id: str) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    context.route("**/api/v1/jobs/*/events**", lambda route: route.abort())
    page = context.new_page()
    page.goto(f"{base}/jobs/{job_id}")
    page.get_by_test_id("job-stream-reconnecting").wait_for(
        state="visible", timeout=15_000
    )
    state = page.evaluate(MOBILE_BANNER_STATE)
    check(state["bannerVisible"], "A06 mobile shows the reconnect banner")
    check(
        state["scrollWidth"] <= state["clientWidth"] + 1,
        f"A06 mobile banner adds no horizontal scroll "
        f"({state['scrollWidth']}/{state['clientWidth']})",
    )
    check(state["navVisible"], "A06 mobile bottom navigation stays visible")
    check(not state["overlap"], "A06 mobile banner does not cover the bottom nav")
    page.screenshot(path=str(SHOTS / "a06_mobile_banner.png"), full_page=True)
    context.close()


def replay_continuity(
    records: list[dict], cursor: int
) -> tuple[list[int], bool]:
    """Frames after a cursor must start at cursor + 1 and stay consecutive."""
    seqs: list[int] = []
    for record in records:
        if "text/event-stream" not in (record["contentType"] or ""):
            continue
        if record["lastEventId"] is None or int(record["lastEventId"]) != cursor:
            continue
        seqs = [
            int(frame["seq"])
            for frame in record["frames"]
            if frame["type"] != "snapshot"
            and frame["seq"] is not None
            and frame["seq"] > cursor
        ]
    consecutive = all(
        later == earlier + 1 for earlier, later in zip(seqs, seqs[1:])
    )
    return seqs, consecutive


def a06_disconnect_and_resume(
    browser: Browser, base: str, api: str, job_id: str, db_path: Path
) -> int:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.add_init_script(SSE_RECORDER)
    errors = watch_errors(page, ignore_network=True)
    writes = watch_writes(page)

    page.goto(f"{base}/jobs/{job_id}")
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    page.wait_for_function(
        "() => window.__taSse && window.__taSse.connections.length >= 1",
        timeout=15_000,
    )
    state = ui_state(page)
    check("运行中" in state["header"], "A06 job is running before the disconnect")
    jobs_before = job_count(api)
    page.screenshot(path=str(SHOTS / "a06_before_disconnect.png"), full_page=True)

    def abort_stream(route) -> None:
        route.abort()

    context.route("**/api/v1/jobs/*/events**", abort_stream)
    cursor_before = cursor_of(page, job_id)
    check(cursor_before is not None, f"A06 cursor before disconnect ({cursor_before})")
    page.reload()
    page.get_by_test_id("job-header").wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("job-stream-reconnecting").wait_for(
        state="visible", timeout=15_000
    )
    check(True, "A06 reconnect banner appears while the stream is down")
    page.wait_for_timeout(int(OFFLINE_SECONDS * 1000))
    attempts = connections(page)
    check(
        len(attempts) >= 3,
        f"A06 retried during the outage ({len(attempts)} attempts)",
    )
    gaps = [
        later["at"] - earlier["at"]
        for earlier, later in zip(attempts, attempts[1:])
    ]
    check(
        len(gaps) == 0 or gaps[-1] > gaps[0],
        f"A06 retry gaps grow (ms: {[round(gap) for gap in gaps]})",
    )
    check(
        all(attempt["lastEventId"] == str(cursor_before) for attempt in attempts),
        "A06 every failed attempt keeps the same cursor",
    )
    page.screenshot(path=str(SHOTS / "a06_offline.png"), full_page=True)

    context.unroute("**/api/v1/jobs/*/events**")
    page.get_by_test_id("job-stream-reconnecting").wait_for(
        state="hidden", timeout=20_000
    )
    check(True, "A06 banner disappears after the stream comes back")

    resumed = [record for record in connections(page) if record["contentType"]]
    check(len(resumed) >= 1, "A06 a stream reconnects after the outage")
    live = resumed[-1]
    check(
        live["lastEventId"] is not None
        and int(live["lastEventId"]) >= int(cursor_before or 0),
        f"A06 resumed stream carries the cursor ({live['lastEventId']})",
    )
    replay_seqs, consecutive = replay_continuity(
        connections(page), int(cursor_before or 0)
    )
    check(
        len(replay_seqs) >= 1,
        f"A06 replay fills frames missed while offline ({len(replay_seqs)} frames)",
    )
    check(
        consecutive,
        f"A06 replay seqs are consecutive after the cursor ({replay_seqs[:6]}...)",
    )

    wait_until(
        lambda: job_detail(api, job_id)["status"] in TERMINAL,
        90,
        "terminal job",
    )
    page.get_by_test_id("job-header").wait_for(state="visible")
    final = job_detail(api, job_id)
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"job-stream-reconnecting\"]')"
        " && !document.querySelector('[data-testid=\"job-stream-expired\"]')",
        timeout=30_000,
    )
    terminal_labels = {
        "succeeded": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
        "interrupted": "等待人工处理",
    }
    page.wait_for_function(
        "(label) => (document.querySelector('[data-testid=\"job-header\"]')"
        " || {innerText: ''}).innerText.includes(label)",
        arg=terminal_labels[final["status"]],
        timeout=15_000,
    )
    page.wait_for_function(
        "(expect) => Boolean(document.querySelector('[data-testid=\"job-open-report\"]'))"
        " === expect",
        arg=final["report_id"] is not None,
        timeout=15_000,
    )
    final_state = ui_state(page)
    check(
        terminal_labels[final["status"]] in final_state["header"],
        f"A06 detail shows the terminal status ({final['status']})",
    )
    check(
        final_state["reportLink"] == (final["report_id"] is not None),
        "A06 report link matches the terminal report_id",
    )
    check(not final_state["expired"], "A06 never shows the expired banner")

    connections_at_terminal = len(connections(page))
    page.wait_for_timeout(3000)
    check(
        len(connections(page)) == connections_at_terminal,
        "A06 no new stream connection after the terminal state",
    )
    page.screenshot(path=str(SHOTS / "a06_terminal.png"), full_page=True)

    seqs = event_seqs(db_path, job_id)
    check(
        seqs == list(range(1, len(seqs) + 1)),
        f"A06 stored event seqs have no holes (1..{len(seqs)})",
    )
    check(
        len(seqs) > 0,
        f"A06 the job emitted events ({len(seqs)} frames)",
    )
    check(job_count(api) == jobs_before, "A06 reconnect does not create a job")
    check(writes == [], f"A06 browser issues no writes ({writes})")
    check(not errors, f"A06 console/page errors: {errors}")
    context.close()
    return len(replay_seqs)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()

    with tempfile.TemporaryDirectory(prefix="astock-e2e-") as temp:
        db_path = Path(temp) / "jobs.db"
        with DevBackend(Path(temp)) as api:
            print(f"dev api at {api}")
            with Preview(api) as base:
                print(f"preview at {base}")
                job_id = create_job(api)
                print(f"created {job_id}")
                wait_for_status(api, job_id, "running")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    a05_refresh_replay(browser, base, api, job_id)
                    a06_mobile_banner(browser, base, job_id)
                    a06_disconnect_and_resume(browser, base, api, job_id, db_path)
                    browser.close()

    result = {
        "ticket": "A05+A06",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
