"""P5-04 W09 journal shell E2E.

Runs the built frontend on ``vite preview`` and serves the journal itself from
a second local HTTP server:

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/journal_e2e.py

Desktop 1440 covers JRN-01/02/03/04/05/06/07/08/10: the three states, the
three reason branches, the 2s retry poll that stops once available, the 30s
timeout, the theme message target origin, the triple-checked receipt, the
single scroll container and the data isolation line. The journal iframe
records every message it receives; a same-origin second frame and a
different-origin frame prove that only the journal window gets theme
messages. Mobile 390x844 and 360x800 cover JRN-09: no page-level horizontal
overflow, the page itself never scrolls, and touch targets reach 44px.
Prints one JSON line; screenshots go to ``ui_shots_p5/P5-04/``.
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

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p5" / "P5-04"

SERVER_TIME = "2026-11-05T09:30:00+08:00"
ISOLATION = "本系统不会读取或修改交易日志的数据。"
THEME_TYPE = "astock-theme-request"

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


class PreviewServer:
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
                with urllib.request.urlopen(f"{self.base}/journal", timeout=1) as response:
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
<html><head><meta charset="utf-8"><title>journal app</title></head>
<body><h1>journal app</h1>
<script>
window.__messages = [];
window.addEventListener('message', function (event) {
  window.__messages.push({
    origin: event.origin,
    type: event.data && event.data.type,
    theme: event.data && event.data.theme
  });
});
</script></body></html>"""

EVIL_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>evil frame</title></head>
<body><h1>evil frame</h1>
<script>
window.__messages = [];
window.addEventListener('message', function (event) {
  window.__messages.push({origin: event.origin, theme: event.data && event.data.theme});
});
parent.postMessage({type: 'astock-theme-request', theme: 'evil'}, '*');
</script></body></html>"""

RECORDER_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>recorder</title></head>
<body><h1>recorder</h1>
<script>
window.__messages = [];
window.addEventListener('message', function (event) {
  window.__messages.push({origin: event.origin, theme: event.data && event.data.theme});
});
</script></body></html>"""


def make_handler(pages: dict[str, str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            body = pages.get(self.path.split("?")[0], pages["/"]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    return Handler


class StaticServer:
    def __init__(self, pages: dict[str, str]) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(pages))
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


META_BASE = {
    "app_version": "0.9.0",
    "server_time": SERVER_TIME,
    "default_analysis_date": "2026-11-05",
    "llm_profiles": [{"id": "deepseek-default", "label": "DeepSeek 默认"}],
    "stage_toggles": [],
    "limits": {"max_active_jobs": 1, "max_date_ahead_days": 0},
    "contract_version": "api-v1",
}

MARKET_ENVELOPE = {
    "schema_version": "market-envelope-v1",
    "status": "error",
    "source": "mixed",
    "as_of": SERVER_TIME,
    "fetched_at": SERVER_TIME,
    "is_stale": False,
    "stale_reason": None,
    "error_code": "upstream_error",
    "error_message": "上游暂不可用",
    "partial": False,
    "failed_blocks": ["overview"],
    "data": None,
}


def meta(journal: dict) -> dict:
    return {**META_BASE, "journal": journal}


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


def json_route(route: object, payload: dict) -> None:
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


def stub_meta(
    context: BrowserContext,
    journal: dict,
    entry_url: str,
    *,
    available_after: int | None = None,
) -> dict[str, int]:
    """Serve one journal state; ``available_after`` flips to available by call."""
    state = {"calls": 0}
    ok = {"available": True, "entry_url": entry_url, "reason": None}

    def handler(route: object) -> None:
        state["calls"] += 1
        current = journal
        if available_after is not None and state["calls"] >= available_after:
            current = ok
        json_route(route, meta(current))

    context.route("**/api/v1/meta/options**", handler)
    return state


def stub_rest(context: BrowserContext) -> None:
    context.route(
        "**/api/v1/jobs**",
        lambda route: json_route(route, {"items": [], "next_cursor": None}),
    )
    context.route(
        "**/api/v1/reports**",
        lambda route: json_route(route, {"items": [], "next_cursor": None}),
    )
    context.route(
        "**/api/v1/market/**",
        lambda route: json_route(route, MARKET_ENVELOPE),
    )


def frame_for(page: Page, url_prefix: str) -> object:
    for frame in page.frames:
        if frame.url.startswith(url_prefix):
            return frame
    return None


def journal_frame(page: Page, journal_base: str) -> object:
    """The app lives at ``/``; ``/evil`` shares the origin and must not match."""
    expected = journal_base.rstrip("/")
    for frame in page.frames:
        if frame.url.split("?")[0].rstrip("/") == expected:
            return frame
    return None


def wait_for_messages(frame: object, page: Page, at_least: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    messages: list[dict] = []
    while time.monotonic() < deadline:
        messages = frame.evaluate("window.__messages || []")
        if len(messages) >= at_least:
            return messages
        page.wait_for_timeout(50)
    return messages


def layout_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const main = document.getElementById('main-content');
          const mainRect = main.getBoundingClientRect();
          const style = getComputedStyle(main);
          const head = document.querySelector('[data-testid="journal-frame-head"]');
          const frame = document.querySelector('iframe[title="交易日志"]');
          const frameRect = frame.getBoundingClientRect();
          const headRect = head.getBoundingClientRect();
          return {
            frameWidth: frameRect.width,
            frameHeight: frameRect.height,
            frameTop: frameRect.top,
            frameBottom: frameRect.bottom,
            headBottom: headRect.bottom,
            contentTop: mainRect.top + parseFloat(style.paddingTop),
            contentBottom: mainRect.bottom - parseFloat(style.paddingBottom),
            contentWidth: main.clientWidth
              - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
            gap: frameRect.top - headRect.bottom,
            overflowY: style.overflowY,
            mainScrollHeight: main.scrollHeight,
            mainClientHeight: main.clientHeight,
            mainScrollTop: main.scrollTop,
            docScroll: document.documentElement.scrollWidth,
            docClient: document.documentElement.clientWidth,
            theme: document.documentElement.dataset.theme || '',
          };
        }"""
    )


def touch_violations(page: Page) -> list[str]:
    return page.evaluate(
        """() => {
          const out = [];
          for (const node of document.querySelectorAll('#main-content a, #main-content button')) {
            const box = node.getBoundingClientRect();
            if (box.height < 44) {
              out.push(`${node.tagName}:${node.textContent.trim()}:${Math.round(box.height)}`);
            }
          }
          return out;
        }"""
    )


def available_flow(
    browser: Browser, base: str, journal: StaticServer, evil: StaticServer
) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_rest(context)
    stub_meta(
        context,
        {"available": True, "entry_url": journal.base, "reason": None},
        journal.base,
    )
    page = context.new_page()
    errors, requests = watch(page)

    page.goto(f"{base}/journal")
    page.get_by_text("日志服务运行中").wait_for()
    check(
        page.get_by_role("heading", level=1, name="交易日志").is_visible(),
        "available JRN-01 keeps the page heading",
    )

    iframe = page.locator("iframe[title='交易日志']")
    check(iframe.count() == 1, "available JRN-01 renders one journal iframe")
    check(
        iframe.get_attribute("src") == journal.base,
        f"available JRN-01 iframe src is entry_url ({iframe.get_attribute('src')})",
    )
    link = page.get_by_role("link", name="新窗口打开")
    check(link.get_attribute("href") == journal.base, "available JRN-01 new window href")
    check(link.get_attribute("target") == "_blank", "available JRN-01 new window target")
    check(
        link.get_attribute("rel") == "noreferrer",
        "available JRN-01 new window rel is noreferrer",
    )
    check(
        page.get_by_role("button", name="刷新").is_visible(),
        "available JRN-01 offers a refresh control",
    )

    # JRN-06: load message carries the current theme and a concrete origin.
    frame = journal_frame(page, journal.base)
    check(frame is not None, "available JRN-06 journal frame is reachable")
    if frame is None:
        context.close()
        return
    messages = wait_for_messages(frame, page, 1)
    theme = page.evaluate("document.documentElement.dataset.theme")
    check(
        len(messages) >= 1
        and messages[0]["type"] == THEME_TYPE
        and messages[0]["theme"] == theme,
        f"available JRN-06 iframe receives the initial theme ({messages})",
    )
    check(
        messages[0]["origin"] == base,
        f"available JRN-06 message origin is the app origin ({messages[0]['origin']})",
    )

    # Theme change in the shell reaches the frame.
    page.get_by_role("button", name="切换到深色主题").first.click()
    messages = wait_for_messages(frame, page, 2)
    check(
        any(item["theme"] == "dark" and item["origin"] == base for item in messages),
        f"available JRN-06 theme change is pushed to the journal ({messages})",
    )

    # JRN-07: a valid receipt is echoed, foreign origin/window/type are ignored.
    frame.evaluate(
        "window.parent.postMessage({type: 'astock-theme-request', theme: 'ignored'}, '*')"
    )
    messages = wait_for_messages(frame, page, len(messages) + 1)
    echoed = messages[-1]
    check(
        echoed["type"] == THEME_TYPE and echoed["theme"] == "dark",
        f"available JRN-07 valid receipt is echoed with the live theme ({echoed})",
    )

    before = len(messages)
    page.evaluate(
        """(src) => {
          const node = document.createElement('iframe');
          node.id = 'same-origin-evil';
          node.src = src;
          document.body.appendChild(node);
        }""",
        f"{journal.base}/evil",
    )
    page.wait_for_timeout(700)
    after = frame.evaluate("window.__messages || []")
    check(
        len(after) == before,
        f"available JRN-07 foreign window is ignored ({before} -> {len(after)})",
    )

    page.evaluate(
        """(src) => {
          const node = document.createElement('iframe');
          node.id = 'foreign-origin';
          node.src = src;
          document.body.appendChild(node);
        }""",
        f"{evil.base}/",
    )
    page.wait_for_timeout(700)
    foreign = frame_for(page, evil.base)
    check(foreign is not None, "available JRN-06 foreign frame is mounted")
    if foreign is not None:
        received = foreign.evaluate("window.__messages || []")
        check(
            received == [],
            f"available JRN-06 theme never goes to '*' ({received})",
        )

    # JRN-08: iframe fills the content box and stays the only scroller.
    metrics = layout_metrics(page)
    expected_height = (
        metrics["contentBottom"]
        - metrics["contentTop"]
        - (metrics["headBottom"] - metrics["contentTop"])
        - metrics["gap"]
    )
    check(
        abs(metrics["frameBottom"] - metrics["contentBottom"]) <= 2,
        f"available JRN-08 iframe reaches the content bottom ({metrics})",
    )
    check(
        abs(metrics["frameHeight"] - expected_height) <= 2,
        f"available JRN-08 iframe height fills the viewport ({metrics})",
    )
    check(
        metrics["frameWidth"] <= metrics["contentWidth"] + 1,
        f"available JRN-08 iframe width fits the content box ({metrics})",
    )
    check(
        metrics["overflowY"] == "hidden"
        and metrics["mainScrollHeight"] <= metrics["mainClientHeight"] + 1,
        f"available JRN-08 the page has no second scrollbar ({metrics})",
    )
    check(
        metrics["docScroll"] == metrics["docClient"],
        f"available JRN-08 no page-level horizontal overflow ({metrics})",
    )

    # Refresh remounts the iframe and re-sends the theme. The reloaded
    # document starts with exactly one recorded message.
    page.get_by_role("button", name="刷新").click()
    reloaded: list[dict] = []
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        for candidate in page.frames:
            if candidate.url.split("?")[0].rstrip("/") != journal.base.rstrip("/"):
                continue
            try:
                messages = candidate.evaluate("window.__messages || []")
            except Exception:  # noqa: BLE001 - a navigating frame may detach
                continue
            if len(messages) == 1:
                reloaded = messages
                break
        if reloaded:
            break
        page.wait_for_timeout(100)
    check(
        len(reloaded) == 1 and reloaded[0]["theme"] == "dark",
        f"available JRN-01 refresh reloads and re-sends the theme ({reloaded})",
    )

    check(
        all(method == "GET" for method, _url in requests),
        f"available reads are all GET ({requests})",
    )
    page.screenshot(path=str(SHOTS / "journal_available.png"))
    check(not errors, f"available console/page errors: {errors}")
    context.close()


def starting_flow(browser: Browser, base: str, journal: StaticServer) -> None:
    """JRN-04: 2s polling starts on demand and stops once available."""
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_rest(context)
    state = stub_meta(
        context,
        {"available": False, "entry_url": journal.base, "reason": "not_running"},
        journal.base,
        available_after=4,
    )
    page = context.new_page()
    errors, _requests = watch(page)

    page.goto(f"{base}/journal")
    page.get_by_text("交易日志是独立应用，当前没有在运行。").wait_for()
    check(state["calls"] == 1, f"starting JRN-04 one meta read on entry ({state['calls']})")

    page.get_by_role("button", name="已启动，重试").click()
    page.get_by_text("正在等待日志服务就绪…").wait_for()
    check(True, "starting JRN-04 retry enters the waiting state")
    page.wait_for_timeout(1_200)
    check(
        state["calls"] == 2,
        f"starting JRN-04 the immediate refetch is one request ({state['calls']})",
    )
    page.get_by_text("已等待 2 秒").wait_for(timeout=3_000)
    check(True, "starting JRN-04 shows the elapsed seconds")

    page.get_by_text("日志服务运行中").wait_for(timeout=6_000)
    check(
        state["calls"] == 4,
        f"starting JRN-04 polls every 2s until available ({state['calls']})",
    )
    page.wait_for_timeout(5_000)
    check(
        state["calls"] == 4,
        f"starting JRN-04 polling stops once available ({state['calls']})",
    )
    check(
        page.locator("iframe[title='交易日志']").count() == 1,
        "starting JRN-04 the frame appears after the service comes up",
    )
    check(not errors, f"starting console/page errors: {errors}")
    context.close()


def timeout_flow(browser: Browser, base: str, journal: StaticServer) -> None:
    """JRN-05: 30s without success returns to unavailable and stops asking."""
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_rest(context)
    state = stub_meta(
        context,
        {"available": False, "entry_url": journal.base, "reason": "probe_failed"},
        journal.base,
    )
    page = context.new_page()
    errors, _requests = watch(page)

    page.goto(f"{base}/journal")
    page.get_by_text("交易日志是独立应用，当前没有在运行。").wait_for()
    page.get_by_role("button", name="重新检测").click()
    page.get_by_text("正在等待日志服务就绪…").wait_for()
    page.wait_for_timeout(31_000)
    check(
        page.get_by_text("交易日志是独立应用，当前没有在运行。").is_visible(),
        "timeout JRN-05 returns to unavailable after 30s",
    )
    check(
        page.get_by_text("正在等待日志服务就绪…").count() == 0,
        "timeout JRN-05 the waiting state is gone",
    )
    check(
        page.get_by_text("8502 端口是否被其他服务占用。").is_visible(),
        "timeout JRN-05 keeps the last reason (probe_failed)",
    )
    calls = state["calls"]
    page.wait_for_timeout(5_000)
    check(
        state["calls"] == calls,
        f"timeout JRN-05 no meta request after the deadline ({calls} -> {state['calls']})",
    )
    check(not errors, f"timeout console/page errors: {errors}")
    context.close()


def reason_flow(
    browser: Browser, base: str, journal: StaticServer, reason: str
) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        timezone_id="Asia/Shanghai",
    )
    stub_rest(context)
    stub_meta(
        context,
        {"available": False, "entry_url": journal.base, "reason": reason},
        journal.base,
    )
    page = context.new_page()
    errors, _requests = watch(page)

    page.goto(f"{base}/journal")
    page.get_by_text("交易日志是独立应用，当前没有在运行。").wait_for()
    body = page.locator("body").inner_text()
    check(ISOLATION in body, f"{reason} JRN-02/03/10 shows the isolation line")
    check(
        page.locator("iframe[title='交易日志']").count() == 0
        and page.get_by_role("link", name="新窗口打开").count() == 0,
        f"{reason} renders no frame and no new-window link",
    )

    if reason == "not_running":
        check("trade-journal/run.bat" in body, "not_running JRN-02 offers run.bat")
        check(
            page.get_by_role("button", name="已启动，重试").is_visible(),
            "not_running JRN-02 offers the manual retry",
        )
        check(
            "安装说明" not in body and "端口" not in body,
            "not_running JRN-02 shows neither install nor port copy",
        )
    elif reason == "not_installed":
        check("安装说明" in body, "not_installed JRN-03 explains installation")
        check(
            "run.bat" not in body and "8502 端口" not in body,
            "not_installed JRN-03 shows no start command and no port copy",
        )
    else:
        check("8502 端口" in body, "probe_failed JRN-03 points at the port")
        check("代理" in body, "probe_failed JRN-03 points at the proxy")
        check("run.bat" not in body, "probe_failed JRN-03 shows no start command")

    # JRN-10: a broken journal never blocks the other routes.
    for path, test_id in (
        ("/market", "page-market"),
        ("/jobs", "page-jobs"),
        ("/reports", "page-reports"),
    ):
        page.goto(f"{base}{path}")
        region = page.get_by_test_id(test_id)
        region.wait_for(timeout=5_000)
        check(region.is_visible(), f"{reason} JRN-10 {path} still opens")

    check(not errors, f"{reason} console/page errors: {errors}")
    context.close()


def mobile_flow(
    browser: Browser,
    base: str,
    journal: StaticServer,
    width: int,
    height: int,
    tag: str,
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_rest(context)
    stub_meta(
        context,
        {"available": True, "entry_url": journal.base, "reason": None},
        journal.base,
    )
    page = context.new_page()
    errors, _requests = watch(page)

    page.goto(f"{base}/journal")
    page.get_by_text("日志服务运行中").wait_for()
    page.wait_for_timeout(500)

    metrics = layout_metrics(page)
    check(
        metrics["docScroll"] == metrics["docClient"],
        f"{tag} JRN-09 no horizontal overflow ({metrics})",
    )
    check(
        metrics["mainScrollTop"] == 0
        and metrics["mainScrollHeight"] <= metrics["mainClientHeight"] + 1,
        f"{tag} JRN-09 the page itself does not scroll ({metrics})",
    )
    check(
        abs(metrics["frameBottom"] - metrics["contentBottom"]) <= 2,
        f"{tag} JRN-09 the iframe fills the viewport height ({metrics})",
    )
    violations = touch_violations(page)
    check(not violations, f"{tag} JRN-09 controls reach 44px ({violations})")
    page.screenshot(path=str(SHOTS / f"journal_mobile_{tag}.png"))
    check(not errors, f"{tag} console/page errors: {errors}")
    context.close()

    # The unavailable branch stays a normal scrolling page at the same width.
    offline_context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=True,
        has_touch=True,
    )
    stub_rest(offline_context)
    stub_meta(
        offline_context,
        {"available": False, "entry_url": journal.base, "reason": "not_running"},
        journal.base,
    )
    offline_page = offline_context.new_page()
    offline_errors, _offline_requests = watch(offline_page)
    offline_page.goto(f"{base}/journal")
    offline_page.get_by_text("交易日志是独立应用，当前没有在运行。").wait_for()
    offline = offline_page.evaluate(
        """() => ({
          docScroll: document.documentElement.scrollWidth,
          docClient: document.documentElement.clientWidth,
          isolation: document.body.innerText.includes('本系统不会读取或修改交易日志的数据。'),
        })"""
    )
    check(
        offline["docScroll"] == offline["docClient"],
        f"{tag} JRN-09 unavailable page has no horizontal overflow ({offline})",
    )
    check(offline["isolation"], f"{tag} JRN-09 unavailable page keeps the isolation line")
    retry_violations = touch_violations(offline_page)
    check(
        not retry_violations,
        f"{tag} JRN-09 unavailable controls reach 44px ({retry_violations})",
    )
    offline_page.screenshot(path=str(SHOTS / f"journal_mobile_{tag}_unavailable.png"))
    check(not offline_errors, f"{tag} unavailable console/page errors: {offline_errors}")
    offline_context.close()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()
    with PreviewServer() as base, StaticServer({"/": JOURNAL_PAGE, "/evil": EVIL_PAGE}) as journal:
        with StaticServer({"/": RECORDER_PAGE}) as evil:
            print(f"preview at {base}; journal at {journal.base}; evil at {evil.base}")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                available_flow(browser, base, journal, evil)
                starting_flow(browser, base, journal)
                timeout_flow(browser, base, journal)
                for reason in ("not_running", "not_installed", "probe_failed"):
                    reason_flow(browser, base, journal, reason)
                mobile_flow(browser, base, journal, 390, 844, "390")
                mobile_flow(browser, base, journal, 360, 800, "360")
                browser.close()

    result = {
        "ticket": "P5-04",
        "checks": checks,
        "failures": failures,
        "screenshots": [str(SHOTS.relative_to(ROOT))],
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
