"""P5-08 AX-01 to AX-06: the nine core pages under axe-core WCAG 2.2 AA.

Builds the frontend, serves ``vite preview`` and stubs every API with
``context.route``. ``axe-core`` is injected from the local
``frontend/node_modules`` — no CDN, no network. Only the ``wcag2a``,
``wcag2aa``, ``wcag21aa`` and ``wcag22aa`` tags are run; critical and serious
violations fail the script, moderate and minor ones are recorded.

Nine routes run at 1440x900 and 390x844; the five key routes also run at
360x640. The journal page is scanned three times: unavailable, starting and
available. The available state uses a second local HTTP server as the iframe.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/a11y_e2e.py

Prints one JSON line and writes the combined P5-08 evidence file.
"""

from __future__ import annotations

import json
import re
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
AXE_PATH = FRONTEND / "node_modules" / "axe-core" / "axe.min.js"
PACKAGE_JSON = FRONTEND / "package.json"
EVIDENCE = (
    ROOT
    / "docs"
    / "upgrade"
    / "reviews"
    / "2026-11-07_P5-08可访问性与移动结果.json"
)

SERVER_TIME = "2026-11-05T09:30:00+08:00"
EMPTY_PAGE = {"items": [], "next_cursor": None}
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]
BLOCKING_IMPACTS = {"critical", "serious"}

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
<html lang="zh-CN"><head><meta charset="utf-8"><title>journal app</title></head>
<body><h1>journal app</h1></body></html>"""


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


AXE_RUN = """async (tags) => {
  const result = await axe.run(document, {
    runOnly: { type: "tag", values: tags },
    resultTypes: ["violations"],
  });
  return result.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact || "minor",
    help: violation.help,
    helpUrl: violation.helpUrl,
    nodes: violation.nodes.length,
    samples: violation.nodes.slice(0, 3).map((node) => ({
      target: (node.target || []).join(" "),
      html: (node.html || "").slice(0, 160),
    })),
  }));
}"""


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


def open_page(
    context: BrowserContext,
    base: str,
    path: str,
    test_id: str,
    state: str = "",
    errors: list[str] | None = None,
) -> Page:
    page = context.new_page()
    if errors is not None:
        errors.extend(watch(page))
    page.goto(f"{base}{path}")
    page.get_by_test_id(test_id).wait_for()
    page.wait_for_selector("h1", timeout=5000)
    page.wait_for_timeout(400)
    if state == "starting":
        page.get_by_role("button", name="已启动，重试").click()
        page.get_by_text("正在等待日志服务就绪…").wait_for()
        page.wait_for_timeout(300)
    elif state == "available":
        page.get_by_test_id("journal-new-window").wait_for()
        page.wait_for_timeout(400)
    return page


def summarise(path: str, state: str, width: int, violations: list[dict]) -> dict:
    counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    for violation in violations:
        impact = violation["impact"]
        counts[impact] = counts.get(impact, 0) + 1
    return {
        "path": path,
        "state": state,
        "width": width,
        "critical": counts["critical"],
        "serious": counts["serious"],
        "moderate": counts["moderate"],
        "minor": counts["minor"],
        "rules": [
            {
                "id": violation["id"],
                "impact": violation["impact"],
                "nodes": violation["nodes"],
                "help": violation["help"],
                "helpUrl": violation["helpUrl"],
                "samples": violation["samples"],
            }
            for violation in violations
        ],
    }


def scan(page: Page, path: str, state: str, width: int) -> list[dict]:
    violations = page.evaluate(AXE_RUN, AXE_TAGS)
    result = summarise(path, state, width, violations)
    page_results.append(result)
    label = f"{width} {path}{' (' + state + ')' if state else ''}"
    blocking = [
        f"{violation['impact']}:{violation['id']}"
        for violation in violations
        if violation["impact"] in BLOCKING_IMPACTS
    ]
    check(not blocking, f"AX-03 {label} has no critical/serious ({blocking})")
    if violations:
        detail = ", ".join(
            f"{violation['impact']}:{violation['id']}x{violation['nodes']}"
            for violation in violations
        )
        print(f"INFO {label} recorded violations: {detail}")
    return violations


def harness_self_test(browser: Browser, base: str) -> None:
    """Prove axe really reports: one alt-less image must be caught."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub_api(context)
    page = open_page(context, base, "/workbench", "page-workbench")
    page.add_script_tag(path=str(AXE_PATH))
    violations = page.evaluate(
        """async (tags) => {
          const image = document.createElement("img");
          image.id = "axe-self-test";
          image.src = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";
          const faint = document.createElement("p");
          faint.id = "axe-self-contrast";
          faint.style.cssText =
            "color:#dddddd;background:#ffffff;font-size:14px;margin:0";
          faint.textContent = "低对比度自检";
          document.body.appendChild(image);
          document.body.appendChild(faint);
          const result = await axe.run(document, {
            runOnly: { type: "tag", values: tags },
            resultTypes: ["violations"],
          });
          image.remove();
          faint.remove();
          return result.violations.map((violation) => violation.id);
        }""",
        AXE_TAGS,
    )
    check("image-alt" in violations, f"AX-02 harness catches an alt-less image ({violations})")
    check(
        "color-contrast" in violations,
        f"AX-02 harness catches low-contrast text ({violations})",
    )
    context.close()


def viewport_scan(
    browser: Browser,
    base: str,
    width: int,
    height: int,
    pages: list[tuple[str, str, str]],
    journal_base: str | None = None,
) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="Asia/Shanghai",
        is_mobile=width < 768,
        has_touch=width < 768,
    )
    stub_api(context)
    errors: list[str] = []
    for name, path, test_id in pages:
        states = [""]
        if name == "journal":
            states = ["", "starting"]
        for state in states:
            page = open_page(context, base, path, test_id, state, errors)
            page.add_script_tag(path=str(AXE_PATH))
            scan(page, path, state, width)
            page.close()

    # The available journal state needs its own meta payload and a local iframe.
    if journal_base is not None and any(name == "journal" for name, _p, _t in pages):
        context2 = browser.new_context(
            viewport={"width": width, "height": height},
            timezone_id="Asia/Shanghai",
            is_mobile=width < 768,
            has_touch=width < 768,
        )
        available_meta = json.loads(json.dumps(META))
        available_meta["journal"] = {
            "available": True,
            "entry_url": journal_base,
            "reason": None,
        }
        stub_api(context2, available_meta)
        page = open_page(
            context2, base, "/journal", "page-journal", "available", errors
        )
        page.add_script_tag(path=str(AXE_PATH))
        scan(page, "/journal", "available", width)
        page.close()
        context2.close()

    check(not errors, f"AX-02 {width} console/page errors ({errors[:3]})")
    context.close()


def audit_dependency() -> dict:
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    dev_version = package.get("devDependencies", {}).get("axe-core")
    runtime = package.get("dependencies", {}).get("axe-core")
    check(AXE_PATH.exists(), f"AX-01 axe.min.js exists ({AXE_PATH.name})")
    check(
        isinstance(dev_version, str) and re.fullmatch(r"\d+\.\d+\.\d+", dev_version) is not None,
        f"AX-01 axe-core is an exact devDependency ({dev_version})",
    )
    check(runtime is None, "AX-01 axe-core is not a runtime dependency")

    offenders: list[str] = []
    pattern = re.compile(r"\baxe(-core)?\b", re.IGNORECASE)
    for path in (FRONTEND / "src").rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx", ".css", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(str(path.relative_to(FRONTEND)))
    check(not offenders, f"AX-01 frontend/src never mentions axe ({offenders})")

    bundle_hits: list[str] = []
    for path in (FRONTEND / "dist").rglob("*.js"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "axe-core" in text or "axe.run" in text or "violations" in text and "runOnly" in text:
            bundle_hits.append(path.name)
    check(not bundle_hits, f"AX-01 bundle does not contain axe ({bundle_hits})")

    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node executable not found on PATH")
    out = ROOT / "docs" / "upgrade" / "reviews" / "_p5-08_bundle_tmp.json"
    subprocess.run(
        [node, "scripts/check_bundle.mjs", "--out", str(out)],
        cwd=FRONTEND,
        check=True,
        capture_output=True,
        text=True,
    )
    evidence = json.loads(out.read_text(encoding="utf-8"))
    out.unlink(missing_ok=True)
    entry_kb = evidence["entry"]["gzip_kb"]
    max_route = max(chunk["gzip_kb"] for chunk in evidence["route_chunks"])
    check(entry_kb <= 202.45, f"AX-01 entry gzip {entry_kb} kB <= 202.45")
    check(max_route <= 60, f"AX-01 largest route chunk {max_route} kB <= 60")
    return {
        "version": dev_version,
        "injection": "frontend/node_modules/axe-core/axe.min.js",
        "entry_gzip_kb": entry_kb,
        "entry_budget_kb": 202.45,
        "max_route_gzip_kb": max_route,
        "route_limit_kb": 60,
    }


def write_evidence(section: str, payload: dict) -> None:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if EVIDENCE.exists():
        try:
            existing = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing["ticket"] = "P5-08"
    existing[section] = payload
    EVIDENCE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("building frontend...")
    build()
    dependency = audit_dependency()

    with Server() as base, StaticServer(JOURNAL_PAGE) as journal:
        print(f"preview at {base}; journal iframe at {journal.base}")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                harness_self_test(browser, base)
                viewport_scan(browser, base, 1440, 900, CORE_PAGES, journal.base)
                viewport_scan(browser, base, 390, 844, CORE_PAGES, journal.base)
                viewport_scan(
                    browser,
                    base,
                    360,
                    640,
                    [page for page in CORE_PAGES if page[0] in KEY_360],
                    journal.base,
                )
            except Exception as error:  # noqa: BLE001 - reported as a check
                check(False, f"axe scan aborted: {error}")
            browser.close()

    total = len(page_results)
    check(total == 29, f"AX-02 scanned 29 page states ({total})")

    axe_payload = {
        "axe_version": dependency["version"],
        "injection": dependency["injection"],
        "tags": AXE_TAGS,
        "dependency": dependency,
        "pages": page_results,
        "exceptions": [],
        "blocking_impacts": sorted(BLOCKING_IMPACTS),
        "pages_scanned": total,
        "checks": checks,
        "failures": failures,
    }
    write_evidence("axe", axe_payload)

    result = {
        "ticket": "P5-08",
        "section": "axe",
        "axe_version": dependency["version"],
        "pages_scanned": total,
        "critical": sum(page["critical"] for page in page_results),
        "serious": sum(page["serious"] for page in page_results),
        "moderate": sum(page["moderate"] for page in page_results),
        "minor": sum(page["minor"] for page in page_results),
        "entry_gzip_kb": dependency["entry_gzip_kb"],
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
