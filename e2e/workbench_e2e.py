"""E2E-03: workbench first screen, active card, recent jobs, launcher.

Runs the built frontend on ``vite preview`` with stubbed read APIs. The browser
may only read: opening and closing the launcher must not send a single write.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/workbench_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p2/P2-07/.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SHOTS = ROOT / "ui_shots_p2" / "P2-07"

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
        end = time.monotonic() + 30.0
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                output = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"vite preview exited early:\n{output}")
            try:
                with urllib.request.urlopen(f"{self.base}/workbench", timeout=1) as response:
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


def job(
    job_id: str,
    status: str,
    *,
    name: str = "钒钛股份",
    code: str = "000629",
    stage: dict | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "status": status,
        "pending_action": None,
        "ticker_code": code,
        "ticker_name": name,
        "analysis_date": "2026-11-05",
        "created_at": "2026-11-05T09:03:00+08:00",
        "updated_at": "2026-11-05T09:04:00+08:00",
        "started_at": "2026-11-05T09:03:01+08:00",
        "finished_at": None,
        "current_stage": stage,
        "stats": {"model_calls": 3, "tokens_in": 100, "tokens_out": 50, "elapsed_ms": 1000},
        "report_id": None,
        "error": None,
        "config_digest": "hash",
        "graph_version": "graph-v1",
        "retry_of_job_id": None,
        "resume_of_job_id": None,
        "resume_from_stage": None,
        "allowed_actions": ["pause", "cancel"],
        "links": {
            "self": f"/api/v1/jobs/{job_id}",
            "events": f"/api/v1/jobs/{job_id}/events",
            "report": None,
        },
    }


RUNNING = job(
    "job-run",
    "running",
    stage={"id": "market", "name": "技术分析", "index": 3, "total": 12, "status": "active"},
)
ACTIVE = [RUNNING, job("job-queue", "queued", name="贵州茅台", code="600519", stage=None)]
RECENT = [
    RUNNING,
    job("job-fail", "failed", name="宁德时代", code="300750", stage=None),
    job("job-interrupt", "interrupted", name="中际旭创", code="300308", stage=None),
]

META = {
    "app_version": "0.9.0",
    "server_time": "2026-11-05T09:30:00+08:00",
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

SEARCH = {
    "schema_version": "market-envelope-v1",
    "status": "ok",
    "source": "static",
    "as_of": "2026-11-05T09:00:00+08:00",
    "fetched_at": "2026-11-05T09:00:00+08:00",
    "is_stale": False,
    "stale_reason": None,
    "error_code": None,
    "error_message": None,
    "partial": False,
    "failed_blocks": [],
    "data": {"items": [], "truncated": False},
}


def envelope(data: object) -> dict:
    return {
        "schema_version": "market-envelope-v1",
        "status": "ok",
        "source": "mixed",
        "as_of": "2026-11-05T09:30:00+08:00",
        "fetched_at": "2026-11-05T09:30:01+08:00",
        "is_stale": False,
        "stale_reason": None,
        "error_code": None,
        "error_message": None,
        "partial": False,
        "failed_blocks": [],
        "data": data,
    }


def report(
    report_id: str,
    name: str,
    code: str,
    rating: str,
    analysis_date: str,
    generated_at: str,
) -> dict:
    return {
        "meta": {
            "report_id": report_id,
            "job_id": "job-run",
            "ticker_code": code,
            "ticker_name": name,
            "analysis_date": analysis_date,
            "generated_at": generated_at,
            "generated_at_source": "job_clock",
            "origin": "new",
            "schema_version": "report-v1",
            "content_hash": f"hash-{report_id}",
            "config_digest": "cfg-1",
            "data_quality_status": "ok",
            "chart_snapshot_status": "frozen",
            "retry_of_job_id": None,
            "rating": rating,
            "signal": "Hold",
        },
        "summary_available": True,
    }


RECENT_REPORTS = [
    report("r-vanadium", "钒钛股份", "000629", "Hold", "2026-11-05", "2026-11-05T09:04:00+08:00"),
    report("r-maotai", "贵州茅台", "600519", "Buy", "2026-11-04", "2026-11-04T15:02:00+08:00"),
    report("r-catl", "宁德时代", "300750", "Overweight", "2026-11-03", "2026-11-03T11:41:00+08:00"),
]
REPORT_LIST = {"items": RECENT_REPORTS, "next_cursor": None}

OVERVIEW = envelope(
    {
        "market_session": "closed",
        "indices": [
            {"code": "000001", "name": "上证指数", "price": 4012.34, "change_pct": 0.42, "change_amt": 16.82},
            {"code": "399001", "name": "深证成指", "price": 13210.5, "change_pct": -0.31, "change_amt": -41.2},
            {"code": "399006", "name": "创业板指", "price": 2810.2, "change_pct": 1.12, "change_amt": 31.1},
        ],
        "northbound": None,
    }
)

INDUSTRIES = envelope(
    {
        "top": [
            {"rank": 1, "name": "半导体", "code": "BK0475", "change_pct": 3.21, "up_count": 40, "down_count": 2, "leader": "中芯国际", "leader_change": 8.1},
            {"rank": 2, "name": "算力", "code": "BK1036", "change_pct": 2.84, "up_count": 30, "down_count": 3, "leader": "中际旭创", "leader_change": 7.2},
            {"rank": 3, "name": "稀土", "code": "BK0578", "change_pct": 2.11, "up_count": 20, "down_count": 4, "leader": "北方稀土", "leader_change": 5.4},
        ],
        "bottom": [],
        "total": 30,
    }
)

STRONG = envelope(
    {
        "items": [
            {"ticker_code": "300750", "name": "宁德时代", "reason": "储能", "market": "sz", "change_pct": 6.2, "change_amt": 11.1, "close": 190.2, "turnover_pct": 1.2},
            {"ticker_code": "600519", "name": "贵州茅台", "reason": "白酒", "market": "sh", "change_pct": 4.1, "change_amt": 60.2, "close": 1520.0, "turnover_pct": 0.6},
            {"ticker_code": "300308", "name": "中际旭创", "reason": "算力", "market": "sz", "change_pct": 3.8, "change_amt": 5.4, "close": 148.3, "turnover_pct": 2.1},
        ]
    }
)

NEWS = envelope({"items": []})

ALLOWED_WORKBENCH_GETS = {
    "/api/v1/jobs",
    "/api/v1/meta/options",
    "/api/v1/reports",
    "/api/v1/market/overview",
    "/api/v1/market/industries",
    "/api/v1/market/strong-stocks",
    "/api/v1/market/newsflash",
}


class ApiStub:
    """Read-only jobs, reports and market API; every write is recorded."""

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.requests: list[tuple[str, str]] = []

    def install(self, context: BrowserContext) -> None:
        context.on("request", self._record)
        context.route("**/api/v1/jobs**", self._jobs)
        context.route("**/api/v1/meta/options**", self._json(META))
        context.route("**/api/v1/market/search**", self._json(SEARCH))
        context.route("**/api/v1/reports**", self._json(REPORT_LIST))
        # Registered last so the single-segment detail path wins (P3 pitfall 19).
        context.route("**/api/v1/reports/*", self._report_detail)
        context.route("**/api/v1/market/overview**", self._json(OVERVIEW))
        context.route("**/api/v1/market/industries**", self._json(INDUSTRIES))
        context.route("**/api/v1/market/strong-stocks**", self._json(STRONG))
        context.route("**/api/v1/market/newsflash**", self._json(NEWS))

    def _record(self, request: object) -> None:
        parsed = urllib.parse.urlparse(request.url)  # type: ignore[attr-defined]
        if parsed.path.startswith("/api/"):
            self.requests.append((request.method, parsed.path))  # type: ignore[attr-defined]

    @staticmethod
    def _json(payload: dict):
        def fulfill(route: object, *args: object) -> None:
            route.fulfill(  # type: ignore[attr-defined]
                status=200,
                content_type="application/json",
                body=json.dumps(payload),
            )

        return fulfill

    @staticmethod
    def _report_detail(route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        report_id = urllib.parse.urlparse(request.url).path.rsplit("/", 1)[-1]
        item = next(
            (row for row in RECENT_REPORTS if row["meta"]["report_id"] == report_id),
            None,
        )
        if item is None:
            route.fulfill(  # type: ignore[attr-defined]
                status=404,
                content_type="application/json",
                body=json.dumps({"code": "not_found", "message": "report not found"}),
            )
            return
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps({**item, "sections": {}}),
        )

    def _jobs(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        if request.method != "GET":
            self.writes.append(f"{request.method} {request.url}")
            route.fulfill(  # type: ignore[attr-defined]
                status=201,
                content_type="application/json",
                body="{}",
            )
            return
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.url).query)
        items = ACTIVE if query.get("active") == ["true"] else RECENT
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps({"items": items, "next_cursor": None}),
        )


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


def open_launcher(page: Page) -> None:
    page.get_by_test_id("workbench-primary").click()
    dialog = page.get_by_role("dialog", name="分析启动器")
    dialog.wait_for(state="visible")
    page.wait_for_url(lambda url: "launch=1" in url)


def close_launcher(page: Page) -> None:
    page.get_by_role("dialog", name="分析启动器").get_by_role(
        "button", name="取消"
    ).click()
    page.get_by_role("dialog", name="分析启动器").wait_for(state="detached")
    page.wait_for_url(lambda url: "launch" not in url and "ticker" not in url)


def scroll_content_to_top(page: Page) -> None:
    page.evaluate(
        "document.getElementById('main-content')?.scrollTo({top: 0, left: 0})"
    )
    page.wait_for_timeout(150)


def scroll_content_to_bottom(page: Page) -> None:
    page.evaluate(
        "const el = document.getElementById('main-content');"
        "if (el) el.scrollTo({top: el.scrollHeight, left: 0})"
    )
    page.wait_for_timeout(150)


def mobile_flow(browser: Browser, base: str, stub: ApiStub) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)
    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for(state="visible")

    primary = page.get_by_test_id("workbench-primary").bounding_box()
    check(
        primary is not None
        and primary["height"] >= 44
        and primary["y"] + primary["height"] <= 844,
        f"390 primary action sits in the first screen ({primary})",
    )

    card = page.get_by_test_id("workbench-active-card")
    card.wait_for(state="visible")
    card_text = card.inner_text()
    check(
        "钒钛股份" in card_text and "3/12" in card_text,
        f"390 active card is visible without expanding ({card_text})",
    )

    rows = page.get_by_test_id("recent-job")
    check(rows.count() == 3, f"390 recent jobs shows three rows ({rows.count()})")
    for index in range(rows.count()):
        check(rows.nth(index).is_visible(), f"390 recent row {index} is visible")

    reports = page.get_by_test_id("recent-reports")
    report_rows = reports.get_by_test_id("recent-report")
    check(
        reports.get_by_role("link", name="查看全部").is_visible(),
        "390 recent reports keeps the 查看全部 link",
    )
    check(
        report_rows.count() == 3,
        f"390 recent reports renders three rows ({report_rows.count()})",
    )
    check(
        not report_rows.first.is_visible(),
        "390 report rows are hidden before expanding",
    )
    toggle = reports.get_by_role("button", name="展开")
    check(toggle.is_visible(), "390 展开 toggle is visible")
    toggle_box = toggle.bounding_box()
    check(
        toggle_box is not None and toggle_box["height"] >= 44,
        f"390 展开 toggle is at least 44px ({toggle_box})",
    )
    toggle.click()
    check(report_rows.first.is_visible(), "390 展开 reveals the report rows")
    row_box = report_rows.first.bounding_box()
    check(
        row_box is not None and row_box["height"] >= 44,
        f"390 report row is at least 44px ({row_box})",
    )
    check(
        reports.get_by_test_id("recent-report-ticker").count() == 3,
        "390 recently researched tickers dedupe to three stocks",
    )
    page.screenshot(path=str(SHOTS / "workbench_390_reports.png"), full_page=True)

    market = page.get_by_test_id("market-summary")
    check(
        market.get_by_test_id("summary-index").count() == 3,
        "390 market summary shows three indices",
    )
    check(
        market.get_by_test_id("summary-industry").count() == 3,
        "390 market summary shows three industries",
    )
    strong = market.get_by_test_id("summary-strong-stock")
    check(strong.count() == 3, "390 market summary shows three strong stocks")
    strong_box = strong.first.bounding_box()
    check(
        strong_box is not None and strong_box["height"] >= 44,
        f"390 strong stock link is at least 44px ({strong_box})",
    )
    check(
        market.get_by_role("link", name="查看市场").is_visible(),
        "390 market summary keeps the 查看市场 link",
    )
    scroll_content_to_bottom(page)
    page.screenshot(path=str(SHOTS / "workbench_390_market.png"))

    open_launcher(page)
    page.screenshot(path=str(SHOTS / "workbench_390_launcher.png"))
    close_launcher(page)
    check(stub.writes == [], f"390 open/close launcher never writes ({stub.writes})")
    check(
        rows.count() == 3,
        "390 recent job count is unchanged after the launcher round trip",
    )

    scroll_content_to_top(page)
    page.screenshot(path=str(SHOTS / "workbench_390.png"), full_page=True)
    check(not errors, f"390 console/page errors: {errors}")
    context.close()

def desktop_flow(browser: Browser, base: str, stub: ApiStub) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)
    page.goto(f"{base}/workbench")
    page.get_by_test_id("page-workbench").wait_for(state="visible")
    page.get_by_test_id("recent-job").first.wait_for(state="visible")

    boxes = {
        "activity": page.get_by_test_id("workbench-active-card").bounding_box(),
        "primary": page.get_by_test_id("workbench-primary").bounding_box(),
        "recent": page.get_by_test_id("recent-jobs").bounding_box(),
        "reports": page.get_by_test_id("recent-reports").bounding_box(),
        "market": page.get_by_test_id("market-summary").bounding_box(),
    }
    ordered = [
        boxes[name]["y"]
        for name in ("activity", "primary", "recent", "reports", "market")
        if boxes[name] is not None
    ]
    check(
        len(ordered) == 5 and ordered == sorted(ordered),
        f"1440 content order is activity, start, recent, reports, market ({ordered})",
    )
    reports = page.get_by_test_id("recent-reports")
    rows = reports.get_by_test_id("recent-report")
    check(rows.count() == 3, f"1440 recent reports shows three rows ({rows.count()})")
    first_row = rows.first.inner_text()
    check(
        all(token in first_row for token in ("钒钛股份", "2026-11-05", "中性", "09:04")),
        f"1440 report row shows stock, date, rating and generated time ({first_row})",
    )

    market = page.get_by_test_id("market-summary")
    check(
        market.get_by_test_id("summary-index").count() == 3,
        "1440 market summary shows three indices",
    )
    check(
        market.get_by_test_id("summary-industry").count() == 3,
        "1440 market summary shows three industries",
    )
    check(
        market.get_by_test_id("summary-strong-stock").count() == 3,
        "1440 market summary shows three strong stocks",
    )
    check(
        market.get_by_role("link", name="查看市场").is_visible(),
        "1440 market summary keeps the 查看市场 link",
    )
    check(
        page.get_by_test_id("active-job-bar").count() == 1,
        "1440 keeps exactly one active-job block on the workbench",
    )

    bad_methods = [item for item in stub.requests if item[0] != "GET"]
    check(bad_methods == [], f"WB-04 workbench sends only GETs ({bad_methods})")
    unexpected = [
        item for item in stub.requests if item[1] not in ALLOWED_WORKBENCH_GETS
    ]
    check(
        unexpected == [],
        f"WB-04 workbench only requests its own GET set ({unexpected})",
    )
    paths = {item[1] for item in stub.requests}
    check(
        {
            "/api/v1/reports",
            "/api/v1/market/overview",
            "/api/v1/market/industries",
            "/api/v1/market/strong-stocks",
        }
        <= paths,
        f"WB-04 reads reports and the three market blocks ({sorted(paths)})",
    )
    page.screenshot(path=str(SHOTS / "workbench_1440.png"), full_page=True)

    scroll_content_to_bottom(page)
    page.screenshot(path=str(SHOTS / "workbench_1440_market.png"))
    scroll_content_to_top(page)

    rows.first.click()
    page.wait_for_url("**/reports/r-vanadium")
    page.get_by_test_id("reader-header").wait_for(state="visible")
    page.go_back()
    page.get_by_test_id("page-workbench").wait_for(state="visible")

    market.get_by_test_id("summary-strong-stock").first.click()
    page.wait_for_url("**/stocks/300750")
    page.get_by_test_id("page-stock").wait_for(state="visible")
    page.go_back()
    page.get_by_test_id("page-workbench").wait_for(state="visible")

    page.get_by_role("link", name="查看市场").click()
    page.wait_for_url("**/market")
    page.get_by_test_id("page-market").wait_for(state="visible")
    page.go_back()
    page.get_by_test_id("page-workbench").wait_for(state="visible")

    open_launcher(page)
    close_launcher(page)
    check(stub.writes == [], f"1440 open/close launcher never writes ({stub.writes})")
    scroll_content_to_top(page)
    check(not errors, f"1440 console/page errors: {errors}")
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
            mobile_flow(browser, base, ApiStub())
            desktop_flow(browser, base, ApiStub())
            browser.close()

    result = {
        "ticket": "E2E-03",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
