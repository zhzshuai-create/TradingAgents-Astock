"""P3-05 / A11 / A12 / T9 / T11-T13: desktop report reader at 1440px.

Serves the frozen upgrade fixtures (long, missing_fields, unsafe_text) plus a
legacy copy and a link sample through a read-only reports API. Every write and
every non-reports API call is recorded and must stay empty.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/report_reader_e2e.py

Prints one JSON line and writes screenshots to ui_shots_p3/P3-05/.
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
from typing import Callable

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
SHOTS = ROOT / "ui_shots_p3" / "P3-05"

CONTRACT_ORDER = [
    "sec-decision",
    "sec-market",
    "sec-sentiment",
    "sec-news",
    "sec-fundamentals",
    "sec-policy",
    "sec-hot-money",
    "sec-lockup",
    "sec-quality",
    "sec-debate",
    "sec-trader",
    "sec-plan",
    "sec-risk",
]

META = {
    "app_version": "0.9.0",
    "server_time": "2026-11-06T09:30:00+08:00",
    "default_analysis_date": "2026-11-06",
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
                with urllib.request.urlopen(
                    f"{self.base}/reports", timeout=1
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


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def build_details() -> dict[str, dict]:
    long_report = load_fixture("long_report.json")
    # Reverse the JSON insertion order: the reader must follow the contract.
    long_report["sections"] = dict(
        reversed(list(long_report["sections"].items()))
    )
    long_report["meta"]["report_id"] = "r-long"

    missing = load_fixture("missing_fields_report.json")
    missing["meta"]["report_id"] = "r-missing"

    unsafe = load_fixture("unsafe_text_report.json")
    unsafe["meta"]["report_id"] = "r-unsafe"

    legacy = load_fixture("missing_fields_report.json")
    legacy["meta"] = {
        **legacy["meta"],
        "report_id": "r-legacy",
        "job_id": None,
        "origin": "legacy_import",
        "generated_at": None,
        "generated_at_source": "unknown",
        "data_quality_status": "absent",
        "chart_snapshot_status": "none",
    }

    links = load_fixture("missing_fields_report.json")
    links["meta"]["report_id"] = "r-links"
    links["sections"] = {
        "sec-news": {
            "id": "sec-news",
            "title": "新闻舆情",
            "body": (
                "## 外链样本\n\n"
                "[官网](https://example.com/doc) 与 [内链](/reports) "
                "与 [脚本](javascript:alert(1))"
            ),
        }
    }

    return {
        "r-long": long_report,
        "r-missing": missing,
        "r-unsafe": unsafe,
        "r-legacy": legacy,
        "r-links": links,
    }


def summary(detail: dict) -> dict:
    return {"meta": detail["meta"], "summary_available": True}


def filter_reports(items: list[dict], params: dict[str, str]) -> list[dict]:
    ratings = [value for value in params.get("rating", "").split(",") if value]
    if ratings:
        items = [item for item in items if item["meta"]["rating"] in ratings]
    ticker = params.get("ticker")
    if ticker:
        items = [item for item in items if item["meta"]["ticker_code"] == ticker]
    date_from = params.get("date_from")
    if date_from:
        items = [item for item in items if item["meta"]["analysis_date"] >= date_from]
    date_to = params.get("date_to")
    if date_to:
        items = [item for item in items if item["meta"]["analysis_date"] <= date_to]
    return items


class ApiStub:
    """Read-only reports API; writes and unrelated APIs are failures."""

    def __init__(self, details: dict[str, dict]) -> None:
        self.details = details
        self.list_params: list[dict[str, str]] = []
        self.detail_paths: list[str] = []
        self.missing: list[str] = []
        self.writes: list[str] = []
        self.unexpected: list[str] = []

    def install(self, context: BrowserContext) -> None:
        # LIFO: the reports handler registered last wins over the catch-all.
        context.route("**/api/**", self._other)
        context.route("**/api/v1/jobs**", self._jobs)
        context.route("**/api/v1/meta/options**", self._json(META))
        context.route("**/api/v1/reports**", self._reports)

    @staticmethod
    def _json(payload: dict):
        def fulfill(route: object, *args: object) -> None:
            route.fulfill(  # type: ignore[attr-defined]
                status=200,
                content_type="application/json",
                body=json.dumps(payload, ensure_ascii=False),
            )

        return fulfill

    def _other(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        self.unexpected.append(f"{request.method} {request.url}")
        route.fulfill(  # type: ignore[attr-defined]
            status=404,
            content_type="application/json",
            body=json.dumps(
                {"error": {"code": "not_found", "message": "not found"}}
            ),
        )

    def _jobs(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        if request.method != "GET":
            self.writes.append(f"{request.method} {request.url}")
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps({"items": [], "next_cursor": None}),
        )

    def _reports(self, route: object) -> None:
        request = route.request  # type: ignore[attr-defined]
        parsed = urllib.parse.urlparse(request.url)
        path = parsed.path.rstrip("/")
        if request.method != "GET":
            self.writes.append(f"{request.method} {request.url}")
            route.fulfill(  # type: ignore[attr-defined]
                status=202,
                content_type="application/json",
                body="{}",
            )
            return
        if path == "/api/v1/reports":
            raw = urllib.parse.parse_qs(parsed.query)
            params = {key: values[0] for key, values in raw.items()}
            self.list_params.append(params)
            items = [
                summary(detail) for detail in self.details.values()
            ]
            items = filter_reports(items, params)
            route.fulfill(  # type: ignore[attr-defined]
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {"items": items, "next_cursor": None}, ensure_ascii=False
                ),
            )
            return
        report_id = path.rsplit("/", 1)[-1]
        self.detail_paths.append(path)
        detail = self.details.get(report_id)
        if detail is None:
            self.missing.append(report_id)
            route.fulfill(  # type: ignore[attr-defined]
                status=404,
                content_type="application/json",
                body=json.dumps(
                    {
                        "error": {
                            "code": "report_not_found",
                            "message": "报告不存在",
                        }
                    },
                    ensure_ascii=False,
                ),
            )
            return
        route.fulfill(  # type: ignore[attr-defined]
            status=200,
            content_type="application/json",
            body=json.dumps(detail, ensure_ascii=False),
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


def wait_until(
    page: Page,
    predicate: Callable[[], bool],
    message: str,
    timeout_ms: int = 5000,
) -> None:
    end = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < end:
        if predicate():
            return
        page.wait_for_timeout(50)
    raise AssertionError(message)


def toc_ids(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        '[data-testid="toc-link"]',
        "links => links.map((link) => link.dataset.sectionId)",
    )


def section_ids(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        '[data-testid="report-section"]', "nodes => nodes.map((node) => node.id)"
    )


def toc_numbers(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        '[data-testid="toc-link"]',
        "links => links.map((link) => link.firstElementChild.textContent.trim())",
    )


def active_toc_id(page: Page) -> str | None:
    return page.evaluate(
        "() => {"
        "  const node = document.querySelector("
        "    '[data-testid=\"toc-link\"][aria-current=\"location\"]'"
        "  );"
        "  return node ? node.dataset.sectionId : null;"
        "}"
    )


def scroll_top(page: Page) -> float:
    return page.evaluate(
        "() => document.getElementById('main-content')?.scrollTop ?? 0"
    )


def section_gap(page: Page, section_id: str) -> float:
    return page.evaluate(
        "([id]) => {"
        "  const main = document.getElementById('main-content');"
        "  const target = document.getElementById(id);"
        "  return target.getBoundingClientRect().top"
        "    - main.getBoundingClientRect().top;"
        "}",
        [section_id],
    )


def scroll_content_to_top(page: Page) -> None:
    page.evaluate(
        "document.getElementById('main-content')?.scrollTo({top: 0, left: 0})"
    )
    page.wait_for_timeout(200)


def wait_reader(page: Page) -> None:
    page.get_by_test_id("page-report-detail").wait_for(state="visible")
    page.get_by_test_id("report-article").wait_for(state="visible")
    page.wait_for_timeout(250)


def long_report_flow(browser: Browser, base: str) -> None:
    stub = ApiStub(build_details())
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/reports?rating=Overweight")
    page.get_by_test_id("page-reports").wait_for(state="visible")
    page.get_by_test_id("report-table").wait_for(state="visible")
    wait_until(
        page,
        lambda: page.get_by_test_id("report-row").count() == 2,
        "expected two Overweight rows",
    )
    check(
        any(params.get("rating") == "Overweight" for params in stub.list_params),
        f"list sends the rating filter ({stub.list_params})",
    )

    page.get_by_test_id("report-row").locator('a[href="/reports/r-long"]').click()
    wait_reader(page)
    check(
        urllib.parse.urlparse(page.url).path == "/reports/r-long",
        f"opening a row lands on the reader ({page.url})",
    )
    check(
        stub.detail_paths == ["/api/v1/reports/r-long"],
        f"opening the reader sends exactly one detail GET ({stub.detail_paths})",
    )

    # RDR-01 / T9: DOM order follows the contract, not the JSON key order.
    check(
        toc_ids(page) == CONTRACT_ORDER,
        f"TOC lists all 13 sections in contract order ({toc_ids(page)})",
    )
    check(
        section_ids(page) == CONTRACT_ORDER,
        f"article follows the same order ({section_ids(page)})",
    )
    check(
        toc_numbers(page) == [str(index) for index in range(1, 14)],
        f"TOC numbers the contract chapters ({toc_numbers(page)})",
    )

    # RDR-07 / T12: the long section renders through its tail.
    market_text = page.locator("#sec-market").inner_text()
    check(
        "第 01799 行" in market_text and "第 00000 行" in market_text,
        "long section renders from head to tail",
    )

    decision = page.get_by_test_id("decision-card").inner_text()
    check(
        all(
            token in decision
            for token in ["增持", "Buy", "3.2", "2.55", "3-6个月"]
        ),
        f"decision card mirrors the DTO ({decision!r})",
    )
    check(
        page.get_by_test_id("meta-generated-at").inner_text() == "10-24 15:30",
        "meta shows the DTO generation time",
    )
    check(
        page.get_by_test_id("meta-origin").inner_text() == "AI 分析",
        "meta shows the DTO origin",
    )
    check(
        page.get_by_test_id("meta-data-quality").inner_text() == "正常",
        "meta shows the DTO data quality",
    )
    check(
        page.get_by_test_id("meta-job").get_attribute("href") == "/jobs/job-0001",
        "meta links to the source job",
    )

    debate = page.locator("#sec-debate").inner_text()
    check(
        all(
            label in debate
            for label in ["多方论点", "空方论点", "辩论记录", "当前回应", "研究经理结论"]
        ),
        "debate renders its five labelled parts in order",
    )
    check(
        "见「最终交易决策」（内容相同）" in page.locator("#sec-risk").inner_text(),
        "risk parts_ref points at the decision section",
    )
    check(
        page.evaluate(
            "() => {"
            "  const table = document.querySelector('#sec-decision table');"
            "  return table !== null"
            "    && table.innerText.includes('样本行');"
            "}"
        ),
        "GFM tables render as real tables inside the article",
    )
    check(
        page.evaluate(
            "document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth"
        ),
        "reader has no page-level horizontal scroll",
    )
    page.screenshot(path=str(SHOTS / "reader_long.png"), full_page=False)

    # RDR-02: TOC click scrolls, keeps the active mark and syncs the hash
    # without another detail request.
    page.locator(
        '[data-testid="toc-link"][data-section-id="sec-debate"]'
    ).click()
    wait_until(
        page,
        lambda: page.evaluate("location.hash") == "#sec-debate",
        "clicking the TOC does not set the hash",
    )
    wait_until(
        page,
        lambda: active_toc_id(page) == "sec-debate",
        "clicking the TOC does not mark the link",
    )
    gap = section_gap(page, "sec-debate")
    check(
        0 <= gap <= 48,
        f"clicking the TOC brings the section to the top (gap={gap})",
    )
    check(
        stub.detail_paths == ["/api/v1/reports/r-long"],
        f"TOC clicks add no detail request ({stub.detail_paths})",
    )

    # Sticky TOC while scrolling a long body; it must not cover the article.
    page.evaluate(
        "() => {"
        "  const main = document.getElementById('main-content');"
        "  const target = document.getElementById('sec-quality');"
        "  const offset = target.getBoundingClientRect().top"
        "    - main.getBoundingClientRect().top + main.scrollTop - 20;"
        "  main.scrollTo({top: offset});"
        "}"
    )
    wait_until(
        page,
        lambda: active_toc_id(page) == "sec-quality",
        "scrolling does not highlight the section in view",
        timeout_ms=4000,
    )
    check(
        active_toc_id(page) == "sec-quality",
        "scrolling highlights the section in view",
    )
    sticky = page.evaluate(
        "() => {"
        "  const main = document.getElementById('main-content');"
        "  const toc = document.querySelector('[data-testid=\"report-toc\"]');"
        "  const article = document.querySelector"
        "    ('[data-testid=\"report-article\"]');"
        "  const m = main.getBoundingClientRect();"
        "  const t = toc.getBoundingClientRect();"
        "  const a = article.getBoundingClientRect();"
        "  return {mainTop: m.top, tocTop: t.top, tocBottom: t.bottom,"
        "    tocRight: t.right, articleLeft: a.left, viewport: innerHeight};"
        "}"
    )
    check(
        -2 <= sticky["tocTop"] - sticky["mainTop"] <= 40,
        f"TOC stays sticky at the top of the scroll container ({sticky})",
    )
    check(
        sticky["tocRight"] <= sticky["articleLeft"] + 1,
        f"TOC does not overlap the article ({sticky})",
    )
    check(
        0 < sticky["tocBottom"] < sticky["viewport"],
        f"sticky TOC stays inside the viewport ({sticky})",
    )
    page.screenshot(path=str(SHOTS / "reader_sticky.png"), full_page=False)

    check(
        abs(scroll_top(page)) > 0,
        "the page is scrolled before leaving",
    )
    page.get_by_role("button", name="返回").click()
    page.get_by_test_id("page-reports").wait_for(state="visible")
    check(
        "rating=Overweight" in page.url,
        f"返回 keeps the list filter ({page.url})",
    )
    wait_until(
        page,
        lambda: page.get_by_test_id("report-row").count() == 2,
        "returning to the list does not restore its rows",
    )
    page.get_by_test_id("report-row").locator('a[href="/reports/r-long"]').click()
    wait_reader(page)
    check(
        stub.detail_paths == ["/api/v1/reports/r-long"],
        f"reopening inside the cache adds no detail GET ({stub.detail_paths})",
    )

    check(stub.writes == [], f"reader never writes ({stub.writes})")
    check(
        stub.unexpected == [],
        f"reader only calls the reports API ({stub.unexpected})",
    )
    scroll_content_to_top(page)
    check(not errors, f"long flow console/page errors: {errors}")
    context.close()


def deep_link_flow(browser: Browser, base: str) -> None:
    stub = ApiStub(build_details())
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    # RDR-03: direct #sec-debate link scrolls once the body exists.
    page.goto(f"{base}/reports/r-long#sec-debate")
    wait_reader(page)
    wait_until(
        page,
        lambda: section_gap(page, "sec-debate") <= 48 and scroll_top(page) > 0,
        "the #sec-debate deep link does not scroll",
    )
    check(
        urllib.parse.urlparse(page.url).fragment == "sec-debate",
        f"deep link keeps the hash ({page.url})",
    )
    check(
        active_toc_id(page) == "sec-debate",
        "deep link marks the target chapter",
    )
    check(
        stub.detail_paths == ["/api/v1/reports/r-long"],
        f"deep link sends one detail GET ({stub.detail_paths})",
    )

    # Refresh stays on the same anchor and refetches once.
    page.reload()
    wait_reader(page)
    wait_until(
        page,
        lambda: section_gap(page, "sec-debate") <= 48 and scroll_top(page) > 0,
        "reloading loses the #sec-debate anchor",
    )
    check(
        urllib.parse.urlparse(page.url).fragment == "sec-debate",
        f"refresh keeps the hash ({page.url})",
    )
    check(
        active_toc_id(page) == "sec-debate",
        "refresh marks the deep-linked chapter",
    )
    check(
        stub.detail_paths == ["/api/v1/reports/r-long"] * 2,
        f"refresh fetches once per load ({stub.detail_paths})",
    )

    # Missing anchor: top of the page, first chapter active, no error.
    # A hash-only goto is a same-document navigation, so force a fresh load.
    page.goto("about:blank")
    page.goto(f"{base}/reports/r-long#sec-missing")
    wait_reader(page)
    page.wait_for_timeout(400)
    check(
        scroll_top(page) == 0,
        f"#sec-missing stays at the top (scrollTop={scroll_top(page)})",
    )
    check(
        page.locator('[role="alert"]').count() == 0,
        "#sec-missing shows no error alert",
    )
    check(
        active_toc_id(page) == "sec-decision",
        f"#sec-missing marks the first chapter ({active_toc_id(page)})",
    )
    check(
        stub.detail_paths == ["/api/v1/reports/r-long"] * 3,
        f"missing anchor still fetches once ({stub.detail_paths})",
    )

    check(stub.writes == [], f"deep links never write ({stub.writes})")
    check(
        stub.unexpected == [],
        f"deep links only call the reports API ({stub.unexpected})",
    )
    check(not errors, f"deep link console/page errors: {errors}")
    context.close()


def missing_fields_flow(browser: Browser, base: str) -> None:
    stub = ApiStub(build_details())
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    page.goto(f"{base}/reports/r-missing")
    wait_reader(page)
    check(
        page.get_by_test_id("reader-header").get_by_role("heading").inner_text()
        == "000629",
        "a null ticker name falls back to the code",
    )
    check(
        toc_ids(page) == ["sec-decision", "sec-market"],
        f"TOC lists only present chapters ({toc_ids(page)})",
    )
    check(
        toc_numbers(page) == ["1", "2"],
        f"chapter numbers keep contract gaps ({toc_numbers(page)})",
    )
    check(
        page.locator('[data-section-id="sec-sentiment"]').count() == 0
        and page.locator('[data-testid="report-section"]').count() == 2,
        "absent chapters are not rendered",
    )
    check(
        page.get_by_test_id("decision-rating").inner_text() == "未知",
        "unknown rating reads 未知",
    )
    for test_id in [
        "decision-signal",
        "decision-price-target",
        "decision-stop",
        "decision-horizon",
    ]:
        check(
            page.get_by_test_id(test_id).inner_text() == "—",
            f"missing {test_id} shows an em dash",
        )
    check(
        page.get_by_test_id("meta-data-quality").inner_text() == "缺失",
        "meta reports the absent data quality",
    )
    check(
        page.get_by_test_id("meta-job").count() == 0,
        "meta hides the job link when job_id is null",
    )
    page.screenshot(path=str(SHOTS / "reader_missing.png"), full_page=False)

    # RDR-05: a legacy import is honest about its unknown time.
    page.goto(f"{base}/reports/r-legacy")
    wait_reader(page)
    check(
        page.get_by_test_id("meta-generated-at").inner_text() == "生成时间未知",
        "legacy meta shows 生成时间未知",
    )
    check(
        page.get_by_test_id("meta-origin").inner_text() == "历史导入",
        "legacy meta shows 历史导入",
    )
    check(
        "历史导入" in page.get_by_test_id("reader-header").inner_text(),
        "legacy header carries the import badge",
    )
    check(
        page.get_by_test_id("meta-job").count() == 0,
        "legacy meta has no job link",
    )

    # Unknown ids get the not-found state, never a stack trace.
    page.goto(f"{base}/reports/r-gone")
    page.get_by_test_id("reader-not-found").wait_for(state="visible")
    check(
        "没有找到这份报告" in page.get_by_test_id("reader-not-found").inner_text(),
        "unknown report shows the not-found state",
    )
    check(
        page.get_by_role("link", name="返回报告库").get_attribute("href")
        == "/reports",
        "not-found state links back to the library",
    )
    check(
        stub.missing == ["r-gone"],
        f"the missing id was asked for once ({stub.missing})",
    )

    check(stub.writes == [], f"missing flow never writes ({stub.writes})")
    check(
        stub.unexpected == [],
        f"missing flow only calls the reports API ({stub.unexpected})",
    )
    # The deliberate 404 for r-gone is the only expected browser log.
    unexpected_errors = [
        error for error in errors if "Failed to load resource" not in error
    ]
    check(
        not unexpected_errors,
        f"missing flow console/page errors: {unexpected_errors}",
    )
    context.close()


def unsafe_flow(browser: Browser, base: str) -> None:
    stub = ApiStub(build_details())
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    stub.install(context)
    page = context.new_page()
    errors = watch_errors(page)

    # RDR-06 / T13: the unsafe fixture renders as inert text.
    page.goto(f"{base}/reports/r-unsafe")
    wait_reader(page)
    probe = page.evaluate(
        "() => {"
        "  const article = document.querySelector"
        "    ('[data-testid=\"report-article\"]');"
        "  const html = article.innerHTML.toLowerCase();"
        "  return {"
        "    scripts: article.querySelectorAll('script').length,"
        "    images: article.querySelectorAll('img').length,"
        "    handlers: article.querySelectorAll('[onerror],[onclick],[onload]')"
        "      .length,"
        "    javascript: html.includes('javascript:'),"
        "    dataUrl: html.includes('data:text/html'),"
        "    onerror: html.includes('onerror'),"
        "    text: article.innerText,"
        "  };"
        "}"
    )
    check(probe["scripts"] == 0, "no script element survives")
    check(probe["images"] == 0, "no image element survives")
    check(probe["handlers"] == 0, "no inline event handler survives")
    check(not probe["javascript"], "no javascript: URL survives")
    check(not probe["dataUrl"], "no data:text/html URL survives")
    check(not probe["onerror"], "no onerror payload is written to the DOM")
    check(
        "注入样本" in probe["text"] and "伪装链接" in probe["text"],
        "unsafe text is kept as inert text",
    )
    page.locator(
        '[data-testid="toc-link"][data-section-id="sec-news"]'
    ).click()
    page.wait_for_timeout(300)
    page.screenshot(path=str(SHOTS / "reader_unsafe.png"), full_page=False)

    # D5: external links open a new window with a safe rel; internal and
    # javascript: links stay inert.
    page.goto(f"{base}/reports/r-links")
    wait_reader(page)
    external = page.evaluate(
        "() => {"
        "  const link = document.querySelector("
        "    '[data-testid=\"report-article\"] a[href=\"https://example.com/doc\"]'"
        "  );"
        "  return link ? {target: link.target, rel: link.rel} : null;"
        "}"
    )
    check(
        external is not None,
        "external link renders as a link",
    )
    check(
        external is not None
        and external["target"] == "_blank"
        and external["rel"] == "noopener noreferrer",
        f"external link opens safely ({external})",
    )
    internal = page.evaluate(
        "() => {"
        "  const link = document.querySelector("
        "    '[data-testid=\"report-article\"] a[href=\"/reports\"]'"
        "  );"
        "  return link ? {target: link.target} : null;"
        "}"
    )
    check(
        internal is not None and internal["target"] == "",
        f"internal link stays in place ({internal})",
    )
    check(
        page.evaluate(
            "() => document.querySelector("
            "'[data-testid=\"report-article\"]')"
            ".innerHTML.toLowerCase().includes('javascript:')"
        )
        is False,
        "javascript: link is neutralised",
    )
    page.screenshot(path=str(SHOTS / "reader_links.png"), full_page=False)

    check(
        stub.detail_paths
        == ["/api/v1/reports/r-unsafe", "/api/v1/reports/r-links"],
        f"unsafe flow sends one GET per report ({stub.detail_paths})",
    )
    check(stub.writes == [], f"unsafe flow never writes ({stub.writes})")
    check(
        stub.unexpected == [],
        f"unsafe flow only calls the reports API ({stub.unexpected})",
    )
    check(not errors, f"unsafe flow console/page errors: {errors}")
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
            long_report_flow(browser, base)
            deep_link_flow(browser, base)
            missing_fields_flow(browser, base)
            unsafe_flow(browser, base)
            browser.close()

    result = {
        "ticket": "P3-05 + A11 + A12 + T9 + T11 + T12 + T13",
        "checks": checks,
        "failures": failures,
        "screenshots": str(SHOTS.relative_to(ROOT)),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
