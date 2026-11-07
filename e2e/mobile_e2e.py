"""P5-08 MOB-01 to MOB-06: mobile overflow and 44px touch targets.

Builds the frontend, serves ``vite preview`` and stubs every API with
``context.route``. At 390x844 and 360x640 it visits the nine core pages and
measures ``document.documentElement.scrollWidth`` against ``clientWidth`` — the
page itself must never scroll sideways (``body { overflow-x: hidden }`` does not
count). Every visible control's short edge must reach 44px; inline prose links
are listed one by one with the WCAG 2.5.8 exception as their reason.

The settings page is walked group by group at 360; the journal page is checked
in its unavailable, starting and available states. Screenshots land in
``ui_shots_p5/P5-08/`` (git-ignored) and the numbers go into the combined P5-08
evidence file.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/mobile_e2e.py

Prints one JSON line; exits non-zero on any failed check.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p5" / "P5-08"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
EVIDENCE = (
    ROOT
    / "docs"
    / "upgrade"
    / "reviews"
    / "2026-11-07_P5-08可访问性与移动结果.json"
)

SERVER_TIME = "2026-11-05T09:30:00+08:00"
EMPTY_PAGE = {"items": [], "next_cursor": None}
TOUCH_MIN = 44

META = {
    "app_version": "0.9.0",
    "server_time": SERVER_TIME,
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

JOB = {
    "job_id": "job-1",
    "status": "succeeded",
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
    "report_id": "r-long",
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
        "report": "/api/v1/reports/r-long",
    },
    "stages": [],
    "reconcile_notes": [],
}

failures: list[str] = []
checks = 0
page_results: list[dict] = []
exceptions: list[dict] = []
screenshots: list[str] = []


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if condition:
        print(f"PASS {message}")
        return
    failures.append(message)
    print(f"FAIL {message}")


def envelope(data: object, status: str = "ok") -> dict:
    return {
        "schema_version": "market-envelope-v1",
        "status": status,
        "source": "static",
        "as_of": None,
        "fetched_at": "2026-11-05T09:00:00+08:00",
        "is_stale": False,
        "stale_reason": None,
        "error_code": None,
        "error_message": None,
        "partial": False,
        "failed_blocks": [],
        "data": data,
    }


EMPTY_ENVELOPE = envelope(None, status="empty")
SEARCH_EMPTY = envelope({"items": [], "truncated": False})


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
                    f"{self.base}/workbench", timeout=1
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


JOURNAL_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>journal app</title>
<style>body{margin:0;font:16px/1.5 sans-serif}</style></head>
<body><h1>journal app</h1><p>交易日志独立应用</p></body></html>"""


class StaticServer:
    def __init__(self, body: str) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server naming
                payload = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: object) -> None:
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self.httpd.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "StaticServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def report_fixture() -> dict:
    report = json.loads(
        (FIXTURES / "long_report.json").read_text(encoding="utf-8")
    )
    report["meta"]["report_id"] = "r-long"
    return report


def json_route(payload: object, status: int = 200) -> Callable[[object], None]:
    def handler(route: object) -> None:
        route.fulfill(  # type: ignore[attr-defined]
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    return handler


def sse_route(route: object) -> None:
    route.fulfill(  # type: ignore[attr-defined]
        status=200,
        headers={"content-type": "text/event-stream", "cache-control": "no-store"},
        body=": connected\n\n",
    )


def jobs_route(route: object) -> None:
    request = route.request  # type: ignore[attr-defined]
    if request.method == "POST":
        json_route(JOB, status=201)(route)
        return
    json_route(EMPTY_PAGE)(route)


def stub_api(context: BrowserContext, meta: dict | None = None) -> None:
    """Broad patterns first; the narrower ones registered later win."""
    report = report_fixture()
    context.route("**/api/v1/jobs**", jobs_route)
    context.route("**/api/v1/meta/options**", json_route(meta or META))
    context.route("**/api/v1/market/search**", json_route(SEARCH_EMPTY))
    context.route("**/api/v1/market/overview**", json_route(EMPTY_ENVELOPE))
    context.route("**/api/v1/market/industries**", json_route(EMPTY_ENVELOPE))
    context.route("**/api/v1/market/strong-stocks**", json_route(EMPTY_ENVELOPE))
    context.route("**/api/v1/market/newsflash**", json_route(EMPTY_ENVELOPE))
    context.route("**/api/v1/stocks/**", json_route(EMPTY_ENVELOPE))
    context.route("**/api/v1/reports**", json_route(EMPTY_PAGE))
    context.route("**/api/v1/reports/r-long", json_route(report))
    context.route("**/api/v1/jobs/job-1/events", sse_route)
    context.route("**/api/v1/jobs/job-1", json_route(JOB))


def watch(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text) if message.type == "error" else None
        ),
    )
    return errors


CORE_PAGES = [
    ("workbench", "/workbench", "page-workbench"),
    ("market", "/market", "page-market"),
    ("stock", "/stocks/600519", "page-stock"),
    ("jobs", "/jobs", "page-jobs"),
    ("job-detail", "/jobs/job-1", "page-job-detail"),
    ("reports", "/reports", "page-reports"),
    ("report-detail", "/reports/r-long", "page-report-detail"),
    ("journal", "/journal", "page-journal"),
    ("settings", "/settings", "page-settings"),
]
KEY_360 = {"workbench", "market", "stock", "journal", "settings"}

OVERFLOW = """() => {
  const doc = document.documentElement;
  return {
    scroll_width: doc.scrollWidth,
    client_width: doc.clientWidth,
    body_scroll_width: document.body.scrollWidth,
    body_overflow_x: getComputedStyle(document.body).overflowX,
  };
}"""

TOUCH = """(minSize) => {
  const selector = "button, a[href], input, select, textarea, [role=button]";
  const found = [];
  for (const el of document.querySelectorAll(selector)) {
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") continue;
    if (el.closest("[hidden]")) continue;
    let box = el;
    // A checkbox or radio is tapped through its label, so the label box is
    // the effective target when it is larger.
    if (el.tagName === "INPUT" && /^(checkbox|radio)$/.test(el.type)) {
      const label = (el.labels && el.labels[0]) || el.closest("label");
      if (label && label.getBoundingClientRect().width > 0) box = label;
    }
    const rect = box.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    // Off-canvas controls (skip link parked above the viewport, closed
    // drawers) are not visible targets.
    if (rect.bottom <= 0 || rect.right <= 0 || rect.left >= window.innerWidth) continue;
    const name = (
      el.getAttribute("aria-label") ||
      el.textContent ||
      el.getAttribute("title") ||
      el.getAttribute("placeholder") ||
      ""
    ).replace(/\\s+/g, " ").trim().slice(0, 40);
    const inline_prose =
      el.tagName === "A" &&
      style.display === "inline" &&
      el.closest("p, li, td, dd, blockquote, h1, h2, h3, h4, h5, h6, figcaption") !== null;
    found.push({
      tag: el.tagName,
      name,
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      short: Math.round(Math.min(rect.width, rect.height)),
      inline_prose,
      passed: Math.min(rect.width, rect.height) >= minSize,
    });
  }
  return found;
}"""


def open_page(
    context: BrowserContext,
    base: str,
    path: str,
    test_id: str,
    errors: list[str] | None = None,
) -> Page:
    page = context.new_page()
    if errors is not None:
        errors.extend(watch(page))
    page.goto(f"{base}{path}")
    page.get_by_test_id(test_id).wait_for()
    page.wait_for_selector("h1", timeout=5000)
    page.wait_for_timeout(400)
    return page


def shot(page: Page, width: int, name: str) -> str:
    target = SHOTS / f"{width}-{name}.png"
    page.screenshot(path=str(target), full_page=False)
    screenshots.append(target.name)
    return target.name


def measure(page: Page, path: str, width: int, name: str) -> dict:
    overflow = page.evaluate(OVERFLOW)
    check(
        overflow["scroll_width"] <= overflow["client_width"],
        f"MOB-01 {width} {path} no page-level overflow ({overflow})",
    )
    controls = page.evaluate(TOUCH, TOUCH_MIN)
    small = [control for control in controls if not control["passed"] and not control["inline_prose"]]
    exempt = [control for control in controls if not control["passed"] and control["inline_prose"]]
    for control in exempt:
        exceptions.append(
            {
                "width": width,
                "path": path,
                "name": control["name"],
                "tag": control["tag"],
                "short_edge": control["short"],
                "reason": "正文内联链接，WCAG 2.5.8 行内文本例外",
            }
        )
    check(
        not small,
        f"MOB-02 {width} {path} controls reach {TOUCH_MIN}px "
        f"({[(c['name'], c['short']) for c in small]})",
    )
    page_results.append(
        {
            "width": width,
            "path": path,
            "state": "",
            "scroll_width": overflow["scroll_width"],
            "client_width": overflow["client_width"],
            "body_overflow_x": overflow["body_overflow_x"],
            "controls": len(controls),
            "undersized": [
                {"name": c["name"], "tag": c["tag"], "short": c["short"]}
                for c in small
            ],
            "inline_exemptions": [
                {"name": c["name"], "short": c["short"]} for c in exempt
            ],
            "screenshot": shot(page, width, name),
        }
    )
    return overflow


def scan_viewport(
    browser: Browser,
    base: str,
    width: int,
    height: int,
    pages: list[tuple[str, str, str]],
    journal_base: str,
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context)
    errors: list[str] = []
    for name, path, test_id in pages:
        page = open_page(context, base, path, test_id, errors)
        measure(page, path, width, name)
        page.close()
    check(not errors, f"MOB-01 {width} console/page errors ({errors[:3]})")
    context.close()

    journal_states(browser, base, journal_base, width, height)
    settings_flow(browser, base, width, height)


def journal_states(
    browser: Browser, base: str, journal_base: str, width: int, height: int
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context)
    errors: list[str] = []

    page = open_page(context, base, "/journal", "page-journal", errors)
    check(
        page.locator("[data-testid=page-journal]").get_attribute("data-view")
        == "unavailable",
        f"MOB-04 {width} journal unavailable state renders",
    )
    overflow = measure(page, "/journal", width, "journal")
    check(
        page.get_by_role("button", name="已启动，重试").bounding_box()["height"] >= TOUCH_MIN,
        f"MOB-04 {width} journal retry button is tall enough",
    )
    shot(page, width, "journal-unavailable")

    page.get_by_role("button", name="已启动，重试").click()
    page.get_by_text("正在等待日志服务就绪…").wait_for()
    check(
        page.locator("[data-testid=page-journal]").get_attribute("data-view")
        == "starting",
        f"MOB-04 {width} journal starting state renders",
    )
    starting_overflow = page.evaluate(OVERFLOW)
    check(
        starting_overflow["scroll_width"] <= starting_overflow["client_width"],
        f"MOB-04 {width} journal starting has no overflow ({starting_overflow})",
    )
    page_results.append(
        {
            "width": width,
            "path": "/journal",
            "state": "starting",
            "scroll_width": starting_overflow["scroll_width"],
            "client_width": starting_overflow["client_width"],
            "screenshot": shot(page, width, "journal-starting"),
        }
    )
    page.close()

    available_meta = json.loads(json.dumps(META))
    available_meta["journal"] = {
        "available": True,
        "entry_url": journal_base,
        "reason": None,
    }
    context2 = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context2, available_meta)
    page = open_page(context2, base, "/journal", "page-journal", errors)
    page.get_by_test_id("journal-new-window").wait_for()
    check(
        page.locator("[data-testid=page-journal]").get_attribute("data-view")
        == "available",
        f"MOB-04 {width} journal available state renders",
    )
    available_overflow = page.evaluate(OVERFLOW)
    check(
        available_overflow["scroll_width"] <= available_overflow["client_width"],
        f"MOB-04 {width} journal available has no overflow ({available_overflow})",
    )
    check(
        page.locator("[data-testid=page-journal] iframe").count() == 1,
        f"MOB-04 {width} journal keeps a single iframe",
    )
    page_results.append(
        {
            "width": width,
            "path": "/journal",
            "state": "available",
            "scroll_width": available_overflow["scroll_width"],
            "client_width": available_overflow["client_width"],
            "screenshot": shot(page, width, "journal-available"),
        }
    )
    page.close()
    context2.close()
    check(not errors, f"MOB-04 {width} journal console/page errors ({errors[:3]})")
    context.close()
    print(f"INFO {width} journal unavailable overflow {overflow['scroll_width']}/"
          f"{overflow['client_width']}")


def settings_flow(browser: Browser, base: str, width: int, height: int) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context)
    errors: list[str] = []
    page = open_page(context, base, "/settings", "page-settings", errors)

    rows = page.locator("nav[aria-label='设置分组'] button")
    check(rows.count() == 4, f"MOB-03 {width} settings lists four groups")
    boxes = [rows.nth(index).bounding_box() for index in range(rows.count())]
    check(
        all(box is not None and box["height"] >= TOUCH_MIN for box in boxes),
        f"MOB-03 {width} every settings row is a 44px target "
        f"({[round(box['height']) for box in boxes if box]})",
    )
    shot(page, width, "settings")

    top_overflow = page.evaluate(OVERFLOW)
    check(
        top_overflow["scroll_width"] <= top_overflow["client_width"],
        f"MOB-03 {width} settings list has no overflow ({top_overflow})",
    )

    for group in ("basic", "model", "data", "about"):
        rows.nth(
            ["basic", "model", "data", "about"].index(group)
        ).click()
        page.wait_for_function(f"location.hash === '#group-{group}'")
        heading = page.locator(f"h2[id='group-{group}']")
        heading.wait_for()
        detail_overflow = page.evaluate(OVERFLOW)
        check(
            detail_overflow["scroll_width"] <= detail_overflow["client_width"],
            f"MOB-03 {width} settings {group} has no overflow ({detail_overflow})",
        )
        controls = page.evaluate(TOUCH, TOUCH_MIN)
        small = [
            control
            for control in controls
            if not control["passed"] and not control["inline_prose"]
        ]
        check(
            not small,
            f"MOB-03 {width} settings {group} controls reach {TOUCH_MIN}px "
            f"({[(c['name'], c['short']) for c in small]})",
        )
        page.get_by_role("button", name="返回设置").click()
        page.wait_for_function("location.hash === ''")
        rows.nth(0).wait_for()

    check(
        page.get_by_role("status").first.text_content() is not None,
        f"MOB-03 {width} settings keeps its save status region",
    )
    shot(page, width, "settings-groups")
    check(not errors, f"MOB-03 {width} settings console/page errors ({errors[:3]})")
    context.close()


def write_evidence(payload: dict) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if EVIDENCE.exists():
        try:
            existing = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing["ticket"] = "P5-08"
    existing["mobile"] = payload
    EVIDENCE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()

    with Server() as base, StaticServer(JOURNAL_PAGE) as journal:
        print(f"preview at {base}; journal iframe at {journal.base}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                scan_viewport(browser, base, 390, 844, CORE_PAGES, journal.base)
                scan_viewport(browser, base, 360, 640, CORE_PAGES, journal.base)
            except Exception as error:  # noqa: BLE001 - reported as a check
                check(False, f"mobile scan aborted: {error}")
            browser.close()

    expected = len(CORE_PAGES) * 2 + 5
    check(len(screenshots) >= expected, f"MOB-05 screenshots {len(screenshots)} >= {expected}")

    payload = {
        "touch_min_px": TOUCH_MIN,
        "pages": page_results,
        "exceptions": exceptions,
        "screenshots": sorted(set(screenshots)),
        "checks": checks,
        "failures": failures,
    }
    write_evidence(payload)

    result = {
        "ticket": "P5-08",
        "section": "mobile",
        "pages_measured": len(page_results),
        "undersized": sum(len(page["undersized"]) for page in page_results if "undersized" in page),
        "exceptions": len(exceptions),
        "screenshots": len(set(screenshots)),
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
