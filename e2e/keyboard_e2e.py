"""P5-06 KB-01 to KB-08: the main journey with the keyboard only.

Builds the frontend, serves ``vite preview`` and stubs every API with
``context.route``. Nothing is clicked: the script only sends
``page.keyboard.press`` / ``page.keyboard.type`` and walks focus with Tab,
Shift+Tab, Enter and Escape.

Desktop 1440 covers skip link -> navigation -> search -> launcher -> job
detail -> report reader -> settings -> journal retry, plus the desktop tab
order and the visible focus ring. Mobile 390 covers the search panel Escape,
the "more" drawer (focus trap and return), and the settings group list with
its hash deep link and back button. A final sweep audits every visible
control on the nine core routes for an empty accessible name at both widths.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/keyboard_e2e.py

Prints one JSON line; screenshots go to ``ui_shots_p5/P5-06/``.
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
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p5" / "P5-06"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"

SERVER_TIME = "2026-11-05T09:30:00+08:00"
EMPTY_PAGE = {"items": [], "next_cursor": None}

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


def stub_api(context: BrowserContext) -> None:
    """Broad patterns first; the narrower ones registered later win."""
    report = report_fixture()
    context.route("**/api/v1/jobs**", jobs_route)
    context.route("**/api/v1/meta/options**", json_route(META))
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


FOCUS_INFO = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) {
    return { tag: "BODY", name: "", id: "", ring: "none", width: "0px" };
  }
  let name = (el.getAttribute("aria-label") || "").trim();
  if (!name && el.labels && el.labels.length) {
    name = (el.labels[0].textContent || "").trim();
  }
  if (!name) {
    name = (el.textContent || "").trim();
  }
  if (!name) {
    name = (el.getAttribute("title") || "").trim();
  }
  const style = getComputedStyle(el);
  return {
    tag: el.tagName,
    name: name.replace(/\\s+/g, " "),
    id: el.id || "",
    ring: style.outlineStyle,
    width: style.outlineWidth,
  };
}"""


def focus_info(page: Page) -> dict:
    return page.evaluate(FOCUS_INFO)


def tab_to(
    page: Page,
    match: Callable[[dict], bool],
    label: str,
    steps: int = 90,
    backwards: bool = False,
) -> dict:
    key = "Shift+Tab" if backwards else "Tab"
    for _ in range(steps):
        page.keyboard.press(key)
        info = focus_info(page)
        if match(info):
            return info
    raise AssertionError(f"{label}: never reached; focus is {focus_info(page)}")


def main_focus(page: Page) -> bool:
    return page.evaluate("document.activeElement && document.activeElement.id === 'main-content'")


def ring_visible(info: dict) -> bool:
    return info["ring"] == "solid" and info["width"] not in {"0px", ""}


UNNAMED = """() => Array.from(
  document.querySelectorAll("button, a, input, select, textarea")
).filter((el) => {
  const box = el.getBoundingClientRect();
  if (box.width === 0 && box.height === 0) return false;
  if ((el.getAttribute("aria-label") || "").trim()) return false;
  if (el.labels && el.labels.length && (el.labels[0].textContent || "").trim()) {
    return false;
  }
  if ((el.textContent || "").trim()) return false;
  if ((el.getAttribute("title") || "").trim()) return false;
  return true;
}).map((el) => el.outerHTML.slice(0, 120))"""


CORE_ROUTES = [
    ("/workbench", "page-workbench"),
    ("/market", "page-market"),
    ("/stocks/600519", "page-stock"),
    ("/jobs", "page-jobs"),
    ("/jobs/job-1", "page-job-detail"),
    ("/reports", "page-reports"),
    ("/reports/r-long", "page-report-detail"),
    ("/journal", "page-journal"),
    ("/settings", "page-settings"),
]


def desktop_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_api(context)
    page = context.new_page()
    errors = watch(page)
    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for()

    check(page.title() == "工作台 · AStock Pro", f"KB-02 tab title ({page.title()})")
    check(
        page.evaluate("document.activeElement === document.body"),
        "KB-01 first paint does not take focus",
    )

    # KB-04: skip link, brand, primary and secondary navigation, then the top bar.
    page.keyboard.press("Tab")
    first = focus_info(page)
    check(
        first["name"] == "跳到主要内容" and first["tag"] == "A",
        f"KB-03 skip link is the first stop ({first})",
    )
    check(ring_visible(first), f"KB-04 skip link shows a focus ring ({first['ring']})")

    order: list[str] = []
    for _ in range(9):
        page.keyboard.press("Tab")
        order.append(focus_info(page)["name"])
    expected = [
        "AStock Pro 工作台",
        "工作台",
        "市场",
        "任务",
        "报告",
        "交易日志",
        "设置",
        "旧版入口",
        "收起侧栏",
    ]
    check(order == expected, f"KB-04 desktop tab order ({order})")

    for _ in range(9):
        page.keyboard.press("Shift+Tab")
    check(
        focus_info(page)["name"] == "跳到主要内容",
        "KB-04 Shift+Tab walks back to the skip link",
    )
    page.keyboard.press("Enter")
    page.wait_for_timeout(100)
    check(main_focus(page), "KB-03 Enter on the skip link focuses #main-content")

    # KB-05: search from the top bar opens the launcher with the typed code.
    search = tab_to(
        page,
        lambda info: info["tag"] == "INPUT" and info["name"] == "搜索股票",
        "KB-05 search input",
        backwards=True,
    )
    check(ring_visible(search), "KB-04 focused search input keeps a visible ring")
    page.keyboard.type("600519")
    page.keyboard.press("Enter")

    dialog = page.get_by_role("dialog", name="分析启动器")
    dialog.wait_for()
    check(
        page.evaluate(
            """() => {
              const dialog = document.querySelector("[role=dialog]");
              return dialog !== null && dialog.contains(document.activeElement);
            }"""
        ),
        "KB-05 the launcher takes focus inside the dialog",
    )
    check("ticker=600519" in page.url, f"KB-05 search entered the launcher ({page.url})")
    page.wait_for_selector("button[form=launcher-form]:not([disabled])", timeout=5000)

    submit = tab_to(
        page,
        lambda info: info["name"] == "开始分析" and info["tag"] == "BUTTON",
        "launcher submit",
    )
    check(submit["tag"] == "BUTTON", "KB-05 launcher submit is keyboard reachable")
    page.keyboard.press("Enter")

    page.wait_for_url("**/jobs/job-1", timeout=10000)
    page.get_by_test_id("job-header").wait_for()
    check(main_focus(page), "KB-01 route change moves focus to #main-content")
    check(page.title() == "任务 · AStock Pro", f"KB-02 job title ({page.title()})")

    # Dialog focus is returned to the shell before the detail page appears.
    report = tab_to(
        page,
        lambda info: info["name"] == "打开报告" and info["tag"] == "A",
        "job report link",
    )
    check(ring_visible(report), "KB-04 the report link shows a focus ring")
    page.keyboard.press("Enter")
    page.wait_for_url("**/reports/r-long", timeout=10000)
    page.get_by_test_id("page-report-detail").wait_for()
    check(main_focus(page), "KB-01 report route moves focus to the main region")
    check(page.title() == "报告 · AStock Pro", f"KB-02 report title ({page.title()})")

    # Back through the shell to settings, then to the journal.
    tab_to(
        page,
        lambda info: info["name"] == "设置" and info["tag"] == "A",
        "sidebar settings link",
        backwards=True,
    )
    page.keyboard.press("Enter")
    page.get_by_test_id("page-settings").wait_for()
    check(main_focus(page), "KB-01 settings route moves focus to the main region")
    check(page.title() == "设置 · AStock Pro", f"KB-02 settings title ({page.title()})")

    density = tab_to(page, lambda info: info["id"] == "settings-density", "density select")
    check(density["tag"] == "SELECT", "KB-05 the first settings control is keyboard reachable")
    check(ring_visible(density), "KB-04 the settings control shows a focus ring")
    check(
        page.locator("h2[id^='group-']").count() == 4,
        "KB-04 the keyboard path lands in a settings page with four groups",
    )
    page.screenshot(path=str(SHOTS / "settings_keyboard_desktop.png"))

    tab_to(
        page,
        lambda info: info["name"] == "交易日志" and info["tag"] == "A",
        "sidebar journal link",
        backwards=True,
    )
    page.keyboard.press("Enter")
    page.get_by_test_id("page-journal").wait_for()
    check(page.title() == "交易日志 · AStock Pro", f"KB-02 journal title ({page.title()})")

    retry = tab_to(page, lambda info: info["name"] == "已启动，重试", "journal retry")
    check(retry["tag"] == "BUTTON", "KB-04 the journal retry button is keyboard reachable")
    page.keyboard.press("Enter")
    page.get_by_text("正在等待日志服务就绪…").wait_for()
    check(True, "KB-04 Enter on the retry button starts the local waiting state")
    page.screenshot(path=str(SHOTS / "journal_retry_keyboard.png"))

    # KB-08: no trap — 30 tabs keep moving through distinct controls.
    seen: list[str] = []
    for _ in range(30):
        page.keyboard.press("Tab")
        seen.append(focus_info(page)["id"] + focus_info(page)["name"])
    check(
        all(left != right for left, right in zip(seen, seen[1:])),
        "KB-08 Tab never sticks on one control (no keyboard trap)",
    )
    check(len(set(seen)) >= 10, f"KB-08 Tab reaches {len(set(seen))} distinct controls")

    check(not errors, f"desktop console/page errors: {errors}")
    context.close()


def mobile_flow(browser: Browser, base: str) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_api(context)
    page = context.new_page()
    errors = watch(page)
    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for()

    page.keyboard.press("Tab")
    check(
        focus_info(page)["name"] == "跳到主要内容",
        "mobile KB-03 skip link is still first",
    )
    page.keyboard.press("Enter")
    page.wait_for_timeout(100)
    check(main_focus(page), "mobile KB-03 skip link focuses the main region")

    # KB-05 mobile: Escape closes the search panel and returns to its button.
    tab_to(page, lambda info: info["name"] == "打开搜索", "mobile search button")
    page.keyboard.press("Enter")
    page.wait_for_timeout(150)
    check(
        focus_info(page)["tag"] == "INPUT",
        f"mobile KB-05 opening search moves focus into the input ({focus_info(page)})",
    )
    page.keyboard.type("600519")
    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    after = focus_info(page)
    check(
        after["name"] == "打开搜索" and after["tag"] == "BUTTON",
        f"mobile KB-05 Escape restores the search button ({after})",
    )
    check(
        page.evaluate(
            """() => {
              const button = document.querySelector(
                "button[aria-label='打开搜索'], button[aria-label='关闭搜索']"
              );
              const header = button && button.closest("header");
              return header !== null
                && header.querySelectorAll("input[type=search]").length === 0;
            }"""
        ),
        "mobile KB-05 Escape closes the search panel",
    )

    # KB-07: the more drawer traps focus, closes on Escape and gives focus back.
    tab_to(page, lambda info: info["name"] == "更多", "mobile more button")
    page.keyboard.press("Enter")
    drawer = page.get_by_role("dialog", name="更多")
    drawer.wait_for()
    check(
        page.evaluate(
            """() => {
              const dialog = document.querySelector("[role=dialog]");
              return dialog !== null && dialog.contains(document.activeElement);
            }"""
        ),
        "mobile KB-07 the drawer receives focus",
    )
    inner: list[str] = []
    for _ in range(4):
        page.keyboard.press("Tab")
        inner.append(focus_info(page)["name"])
    inside = page.evaluate(
        """() => {
          const dialog = document.querySelector("[role=dialog]");
          return dialog !== null && dialog.contains(document.activeElement);
        }"""
    )
    check(inside, f"mobile KB-07 Tab stays inside the drawer ({inner})")
    page.keyboard.press("Escape")
    drawer.wait_for(state="detached")
    page.wait_for_timeout(150)
    check(
        focus_info(page)["name"] == "更多",
        f"mobile KB-07 Escape returns focus to the more button ({focus_info(page)})",
    )

    # KB-04/KB-08: settings group list, hash deep link and back button.
    page.goto(f"{base}/settings")
    page.get_by_role("heading", name="设置", level=1).wait_for()
    tab_to(
        page,
        lambda info: info["name"].startswith("模型"),
        "mobile settings 模型 group",
    )
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash === '#group-model'")
    page.get_by_role("heading", name="模型", level=2).wait_for()
    check(True, "mobile KB-04 Enter opens the 模型 group from the list")

    tab_to(page, lambda info: info["name"] == "返回设置", "mobile settings back")
    page.keyboard.press("Enter")
    page.wait_for_function("location.hash === ''")
    check(
        page.locator("nav[aria-label='设置分组'] button").count() == 4,
        "mobile KB-04 the back button restores the four-row list",
    )

    overflow = page.evaluate(
        """() => ({
          doc: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
        })"""
    )
    check(
        overflow["doc"] == overflow["client"],
        f"mobile KB-04 no horizontal overflow ({overflow})",
    )
    page.screenshot(path=str(SHOTS / "settings_keyboard_mobile.png"))

    check(not errors, f"mobile console/page errors: {errors}")
    context.close()


def audit_flow(browser: Browser, base: str, width: int, height: int, tag: str) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=width < 768,
        has_touch=width < 768,
    )
    stub_api(context)
    page = context.new_page()
    for path, test_id in CORE_ROUTES:
        page.goto(f"{base}{path}")
        page.get_by_test_id(test_id).wait_for()
        page.wait_for_timeout(300)
        unnamed = page.evaluate(UNNAMED)
        check(not unnamed, f"{tag} KB-08 {path} controls have names ({unnamed})")
    page.goto(f"{base}/no-such-page")
    page.get_by_test_id("not-found").wait_for()
    check(
        page.title() == "AStock Pro",
        f"{tag} KB-02 unknown route keeps one product name ({page.title()})",
    )
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
            try:
                desktop_flow(browser, base)
            except Exception as error:  # noqa: BLE001 - reported as a check
                check(False, f"desktop keyboard flow aborted: {error}")
            try:
                mobile_flow(browser, base)
            except Exception as error:  # noqa: BLE001
                check(False, f"mobile keyboard flow aborted: {error}")
            try:
                audit_flow(browser, base, 1440, 900, "1440")
                audit_flow(browser, base, 390, 844, "390")
            except Exception as error:  # noqa: BLE001
                check(False, f"accessible-name audit aborted: {error}")
            browser.close()

    result = {
        "ticket": "P5-06",
        "checks": checks,
        "failures": failures,
        "screenshots": [str(SHOTS.relative_to(ROOT))],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
