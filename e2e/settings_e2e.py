"""P5-03 W10 settings E2E.

Runs the built frontend on ``vite preview`` with a stubbed ``meta/options``:

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/settings_e2e.py

Desktop 1440 covers SET-01/02/04/05/06/07: the four groups and their ids,
``#group-*`` deep links (scroll into view, unknown hash stays at the top), the
read-only contract values, local preference persistence across a reload,
no secret input, no write request and an unchanged job config snapshot.
Mobile 390x844 and 360x800 cover SET-08: the group list drills into a detail
page through the hash, reload restores it, back clears it, and neither width
overflows horizontally. Prints one JSON line; screenshots go to
``ui_shots_p5/P5-03/``.
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
SHOTS = ROOT / "ui_shots_p5" / "P5-03"

SERVER_TIME = "2026-11-05T09:30:00+08:00"

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
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                output = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"vite preview exited early:\n{output}")
            try:
                with urllib.request.urlopen(
                    f"{self.base}/settings", timeout=1
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


META_OPTIONS = {
    "app_version": "0.9.0",
    "server_time": SERVER_TIME,
    "default_analysis_date": "2026-11-05",
    "llm_profiles": [
        {"id": "deepseek-default", "label": "DeepSeek 默认"},
        {"id": "fast", "label": "快速模型"},
    ],
    "stage_toggles": [{"id": "policy", "label": "政策分析", "default": True}],
    "limits": {"max_active_jobs": 1, "max_date_ahead_days": 0},
    "journal": {
        "available": False,
        "entry_url": "http://127.0.0.1:8502",
        "reason": "not_running",
    },
    "contract_version": "api-v1",
}

JOB = {
    "job_id": "job-1",
    "status": "completed",
    "pending_action": None,
    "ticker_code": "600519",
    "ticker_name": "贵州茅台",
    "analysis_date": "2026-11-05",
    "created_at": "2026-11-05T09:00:00+08:00",
    "updated_at": "2026-11-05T09:10:00+08:00",
    "started_at": "2026-11-05T09:00:01+08:00",
    "finished_at": "2026-11-05T09:10:00+08:00",
    "current_stage": None,
    "stats": {
        "model_calls": 12,
        "tokens_in": 1200,
        "tokens_out": 800,
        "elapsed_ms": 600000,
    },
    "report_id": None,
    "error": None,
    "config_digest": "cfg-snapshot-1",
    "graph_version": "graph-v1",
    "retry_of_job_id": None,
    "resume_of_job_id": None,
    "resume_from_stage": None,
    "allowed_actions": [],
    "links": {
        "self": "/api/v1/jobs/job-1",
        "events": "/api/v1/jobs/job-1/events",
        "report": None,
    },
    "stages": [],
    "reconcile_notes": [],
}


def watch(page: Page) -> tuple[list[str], list[tuple[str, str]]]:
    errors: list[str] = []
    requests: list[tuple[str, str]] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    page.on(
        "request",
        lambda request: (
            requests.append((request.method, request.url))
            if "/api/" in request.url
            else None
        ),
    )
    return errors, requests


def stub_api(context: BrowserContext) -> None:
    def json_route(route: object, payload: dict) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    context.route(
        "**/api/v1/meta/options**",
        lambda route: json_route(route, META_OPTIONS),
    )
    context.route(
        "**/api/v1/jobs**",
        lambda route: json_route(route, {"items": [], "next_cursor": None}),
    )
    # Registered last so the detail path wins over the list wildcard.
    context.route(
        "**/api/v1/jobs/job-1",
        lambda route: json_route(route, JOB),
    )


def wait_for_count(
    requests: list[tuple[str, str]], needle: str, expected: int, page: Page
) -> bool:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        current = sum(1 for _method, url in requests if needle in url)
        if current >= expected:
            return True
        page.wait_for_timeout(50)
    return sum(1 for _method, url in requests if needle in url) >= expected


def group_metrics(page: Page, group: str) -> dict:
    return page.evaluate(
        """(group) => {
          const node = document.getElementById(group);
          const rect = node.getBoundingClientRect();
          return {
            top: rect.top,
            bottom: rect.bottom,
            scroll: document.getElementById('main-content').scrollTop,
            viewport: window.innerHeight,
          };
        }""",
        f"group-{group}",
    )


def page_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const main = document.getElementById('main-content');
          return {
            docScroll: document.documentElement.scrollWidth,
            docClient: document.documentElement.clientWidth,
            mainScroll: main.scrollWidth,
            mainClient: main.clientWidth,
          };
        }"""
    )


def touch_violations(page: Page, selector: str) -> list[str]:
    return page.evaluate(
        """(selector) => {
          const out = [];
          for (const node of document.querySelectorAll(selector)) {
            const box = node.getBoundingClientRect();
            if (box.height < 44) {
              out.push(`${node.tagName}:${Math.round(box.height)}`);
            }
          }
          return out;
        }""",
        selector,
    )


def stored_preferences(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const raw = localStorage.getItem('astock.prefs.v1');
          return raw === null ? null : JSON.parse(raw);
        }"""
    )


def desktop_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors, requests = watch(page)

    # SET-01: four groups, stable ids, no fallback scroll on entry.
    page.goto(f"{base}/settings")
    page.get_by_role("heading", level=1, name="设置").wait_for()
    headings = page.locator("h2[id^='group-']")
    check(headings.count() == 4, f"desktop SET-01 four group headings ({headings.count()})")
    ids = headings.evaluate_all("(nodes) => nodes.map((node) => node.id)")
    check(
        ids == ["group-basic", "group-model", "group-data", "group-about"],
        f"desktop SET-01 group ids in order ({ids})",
    )
    titles = headings.evaluate_all("(nodes) => nodes.map((node) => node.textContent)")
    check(
        titles == ["基本", "模型", "数据源", "关于"],
        f"desktop SET-01 group titles ({titles})",
    )
    sections = page.locator("section[aria-labelledby^='group-']")
    check(sections.count() == 4, f"desktop SET-01 labelled sections ({sections.count()})")
    check(
        page.evaluate("document.getElementById('main-content').scrollTop") == 0,
        "desktop SET-01 entry without a hash stays at the top",
    )

    # SET-02: read-only values come straight from the contract.
    body = page.locator("body").inner_text()
    for value in (
        "接口可达",
        "0.9.0",
        "api-v1",
        SERVER_TIME,
        "http://127.0.0.1:8502",
        "DeepSeek 默认",
        "deepseek-default",
        "未连接",
    ):
        check(value in body, f"desktop SET-02 shows {value!r}")
    check(
        SERVER_TIME.endswith("+08:00") and "+08:00" in body,
        "desktop SET-02 keeps the server time offset (+08:00)",
    )
    check(
        wait_for_count(requests, "/api/v1/meta/options", 1, page),
        "desktop SET-02 requests meta/options",
    )
    page.wait_for_timeout(300)
    meta_calls = sum(1 for _m, url in requests if "/api/v1/meta/options" in url)
    check(meta_calls == 1, f"desktop SET-02 reuses one meta cache key ({meta_calls})")

    # SET-04: no secret input, no secret pattern in the DOM.
    check(
        page.locator("input[type='password']").count() == 0,
        "desktop SET-04 no password input",
    )
    identities = page.evaluate(
        """() => Array.from(document.querySelectorAll('input, textarea, select'))
            .map((node) => [
              node.id, node.getAttribute('name'), node.getAttribute('type')
            ].join(' ').toLowerCase())"""
    )
    check(
        not any(
            token in identity
            for identity in identities
            for token in ("password", "api_key", "base_url", "authorization")
        ),
        f"desktop SET-04 no secret field identity ({identities})",
    )
    check(
        "api_key" not in body.lower()
        and "authorization" not in body.lower()
        and "sk-" not in body,
        "desktop SET-04 no secret pattern in the DOM",
    )

    # SET-06: every change saves immediately and announces itself.
    page.select_option("#settings-density", "compact")
    check("已保存" in page.get_by_role("status").inner_text(), "desktop SET-06 announces the save")
    page.select_option("#settings-refresh", "manual")
    page.select_option("#settings-export", "markdown")
    page.select_option("#settings-default-model", "fast")
    page.get_by_label("默认并行分析师").check()
    stored = stored_preferences(page)
    check(
        stored == {
            "density": "compact",
            "refresh": "manual",
            "export": "markdown",
            "launcher": {"llm_profile": "fast", "parallel_analysts": True},
        },
        f"desktop SET-06 preference payload ({stored})",
    )

    page.reload()
    page.get_by_role("heading", level=1, name="设置").wait_for()
    check(
        page.locator("#settings-density").input_value() == "compact",
        "desktop SET-06 density survives a reload",
    )
    check(
        page.locator("#settings-refresh").input_value() == "manual",
        "desktop SET-06 refresh survives a reload",
    )
    check(
        page.locator("#settings-export").input_value() == "markdown",
        "desktop SET-06 export survives a reload",
    )
    check(
        page.locator("#settings-default-model").input_value() == "fast",
        "desktop SET-06 default model survives a reload",
    )
    check(
        page.get_by_label("默认并行分析师").is_checked(),
        "desktop SET-06 parallel analysts survive a reload",
    )

    # SET-01: deep links scroll to the group.
    page.goto(f"{base}/settings#group-data")
    page.get_by_role("heading", level=2, name="数据源").wait_for()
    page.wait_for_timeout(250)
    data_metrics = group_metrics(page, "data")
    check(
        0 <= data_metrics["top"] < data_metrics["viewport"],
        f"desktop SET-01 deep link brings the data group into view ({data_metrics})",
    )
    check(
        data_metrics["scroll"] > 0,
        f"desktop SET-01 deep link scrolls the page ({data_metrics['scroll']})",
    )

    # SET-07: an unknown hash is ignored and writes nothing. The query string
    # forces a full load so the previous deep-link scroll does not carry over.
    page.goto(f"{base}/settings?entry=top#group-nope")
    page.get_by_role("heading", level=1, name="设置").wait_for()
    page.wait_for_timeout(250)
    check(
        page.evaluate("document.getElementById('main-content').scrollTop") == 0,
        "desktop SET-07 unknown hash stays at the top",
    )
    check(
        page.locator("h2[id^='group-']").count() == 4
        and "#group-nope" in page.url,
        "desktop SET-07 unknown hash keeps the hash and the four groups",
    )

    page.screenshot(path=str(SHOTS / "settings_desktop.png"), full_page=True)
    check(not errors, f"desktop console/page errors: {errors}")
    context.close()


def snapshot_flow(browser: Browser, base: str) -> None:
    """SET-05: settings writes nothing; a job snapshot never changes."""
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors, requests = watch(page)

    page.goto(f"{base}/settings")
    page.get_by_role("heading", level=1, name="设置").wait_for()
    page.get_by_text("接口可达").wait_for()
    before_keys = set(page.evaluate("Object.keys(localStorage)"))
    before_job = page.evaluate(
        "fetch('/api/v1/jobs/job-1').then((response) => response.json())"
    )

    page.select_option("#settings-density", "compact")
    page.select_option("#settings-refresh", "manual")
    page.select_option("#settings-export", "markdown")
    page.select_option("#settings-default-model", "fast")
    page.get_by_label("默认并行分析师").check()

    after_job = page.evaluate(
        "fetch('/api/v1/jobs/job-1').then((response) => response.json())"
    )
    check(
        before_job["config_digest"] == after_job["config_digest"]
        and before_job["graph_version"] == after_job["graph_version"],
        "desktop SET-05 job config snapshot is unchanged",
    )
    after_keys = set(page.evaluate("Object.keys(localStorage)"))
    check(
        after_keys - before_keys <= {"astock.prefs.v1", "astock.theme"},
        f"desktop SET-05 only preference keys were added ({sorted(after_keys)})",
    )
    check(
        all(method == "GET" for method, _url in requests),
        f"desktop SET-05 settings reads are all GET ({requests})",
    )
    detail_calls = sum(
        1
        for _m, url in requests
        if url.split("?")[0].rstrip("/").endswith("/api/v1/jobs/job-1")
    )
    check(
        detail_calls == 2,
        f"desktop SET-05 settings never writes to a job ({detail_calls})",
    )
    check(not errors, f"desktop SET-05 console/page errors: {errors}")
    context.close()


def mobile_flow(
    browser: Browser, base: str, width: int, height: int, tag: str
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context)
    page = context.new_page()
    errors, _requests = watch(page)

    page.goto(f"{base}/settings")
    page.get_by_role("heading", level=1, name="设置").wait_for()
    nav = page.locator("nav[aria-label='设置分组']")
    nav.wait_for()
    rows = nav.locator("button")
    check(rows.count() == 4, f"{tag} SET-08 group list has four rows ({rows.count()})")
    check(
        page.locator("h2[id^='group-']").count() == 0,
        f"{tag} SET-08 the list page renders no group section",
    )

    # SET-08: drill in, reload restores, back clears the hash.
    rows.nth(1).click()
    page.wait_for_function("location.hash === '#group-model'")
    page.get_by_role("heading", level=2, name="模型").wait_for()
    check(
        page.get_by_role("button", name="返回设置").is_visible(),
        f"{tag} SET-08 detail page offers a back button",
    )
    check(
        nav.count() == 0,
        f"{tag} SET-08 the detail page replaces the group list",
    )

    page.reload()
    page.get_by_role("heading", level=2, name="模型").wait_for()
    check(
        page.evaluate("location.hash") == "#group-model",
        f"{tag} SET-08 reload restores the deep-linked group",
    )

    page.get_by_role("button", name="返回设置").click()
    page.wait_for_function("location.hash === ''")
    nav.wait_for()
    check(
        page.locator("h2[id^='group-']").count() == 0,
        f"{tag} SET-08 back returns to the group list",
    )

    metrics = page_metrics(page)
    check(
        metrics["docScroll"] == metrics["docClient"],
        f"{tag} SET-08 document width fits ({metrics['docScroll']} vs {metrics['docClient']})",
    )
    check(
        metrics["mainScroll"] == metrics["mainClient"],
        f"{tag} SET-08 scroll container width fits "
        f"({metrics['mainScroll']} vs {metrics['mainClient']})",
    )
    violations = touch_violations(
        page, "#main-content nav[aria-label='设置分组'] button"
    )
    check(not violations, f"{tag} SET-08 group rows reach 44px ({violations})")
    page.screenshot(path=str(SHOTS / f"settings_mobile_{tag}.png"), full_page=True)

    rows.nth(2).click()
    page.get_by_role("heading", level=2, name="数据源").wait_for()
    detail_violations = touch_violations(
        page, "#main-content button, #main-content a, #main-content select"
    )
    check(
        not detail_violations,
        f"{tag} SET-08 detail controls reach 44px ({detail_violations})",
    )
    page.screenshot(path=str(SHOTS / f"settings_mobile_{tag}_detail.png"))
    detail_metrics = page_metrics(page)
    check(
        detail_metrics["docScroll"] == detail_metrics["docClient"],
        f"{tag} SET-08 detail page has no horizontal overflow",
    )

    # SET-07 mobile: an unknown hash falls back to the list, quietly.
    page.goto(f"{base}/settings#group-nope")
    nav.wait_for()
    check(
        page.locator("h2[id^='group-']").count() == 0
        and page.evaluate("location.hash") == "#group-nope",
        f"{tag} SET-07 unknown hash shows the group list",
    )
    check(not errors, f"{tag} console/page errors: {errors}")
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
            desktop_flow(browser, base)
            snapshot_flow(browser, base)
            mobile_flow(browser, base, 390, 844, "390")
            mobile_flow(browser, base, 360, 800, "360")
            browser.close()

    result = {
        "ticket": "P5-03",
        "checks": checks,
        "failures": failures,
        "screenshots": [str(SHOTS.relative_to(ROOT))],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
