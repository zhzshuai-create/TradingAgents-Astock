"""P3-09: one entry point for the P3 exit walkthrough.

Runs the three browser suites that own R-01/R-02/R-05/R-06/R-08, the backend
groups for R-03/R-04/R-07, the two exit checks in ``tests/backend/test_p3_exit.py``,
a direct web/Markdown/PDF title comparison on the built bundle, and the P3-01
performance probe. This ticket only adds tests and records; product behaviour
is untouched.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/e2e_p3.py
    ... e2e/e2e_p3.py --new-only     # skip the three browser suites
    ... e2e/e2e_p3.py --skip-perf    # skip the 10,000-row probe

Backend groups run under ``.venv`` (pytest, fpdf2); the browser half runs under
the system Python 3.13 that has Playwright. Suites own their fake data and
temporary roots, exactly as in P2. Logs and screenshots go to
``ui_shots_p3/P3-09/`` (not committed).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
SHOTS = ROOT / "ui_shots_p3" / "P3-09"
LOGS = SHOTS / "logs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
PERF_OUT = ROOT / "docs" / "upgrade" / "reviews" / "2026-11-06_P3-09性能结果.json"
P2_BASELINE_KB = 177.92
# P4-04 D6 retired the P3 total-JS trigger: lazy route chunks are demand
# loaded, so the budget is the entry chunk plus a cap per route chunk.
P4_ENTRY_BUDGET_KB = 202.45
P4_ROUTE_CHUNK_LIMIT_KB = 60.0

SUITES = (
    ("R-01", "reports_e2e.py"),
    ("R-02/R-05/R-06", "report_reader_e2e.py"),
    ("R-08", "legacy_projection_e2e.py"),
)

BACKEND_GROUPS = (
    (
        "C1",
        (
            "tests/backend/test_legacy_golden.py::test_section_catalog_matches_golden_order",
            "tests/backend/test_report_markdown.py::test_rpt05_markdown_order_etag_and_304",
            "tests/backend/test_report_markdown.py::test_t13_unsafe_text_stays_inert_in_markdown",
            "tests/backend/test_pdf_renderer.py::test_t9_bookmarks_follow_ordered_sections",
            "tests/backend/test_pdf_renderer.py::test_t13_unsafe_text_is_plain_text",
            "tests/backend/test_p3_exit.py",
        ),
    ),
    (
        "C2",
        ("tests/backend/test_reports_api.py::test_rpt06_reads_are_side_effect_free",),
    ),
    (
        "C3",
        (
            "tests/backend/test_reports_api.py::test_t14_t15_two_successes_keep_both_and_null_last",
            "tests/backend/test_reports_api.py::test_rpt01_default_page_order_matches_contract",
        ),
    ),
    (
        "C4",
        (
            "tests/backend/test_exports.py::test_exp01_queue_poll_and_download",
            "tests/backend/test_exports.py::test_exp02_second_request_hits_cache_without_rendering",
            "tests/backend/test_exports.py::test_exp07_cache_hit_preparation_under_500ms",
            "tests/backend/test_pdf_renderer.py::test_t17_legacy_export_carries_supplement_time",
        ),
    ),
    (
        "R-07",
        (
            "tests/backend/test_legacy_import.py::test_imp01_rescan_adds_nothing",
            "tests/backend/test_legacy_import.py::test_imp02_changed_file_adds_one_report_and_one_ledger_row",
        ),
    ),
    (
        "T4",
        ("tests/backend/test_legacy_golden.py::test_t4_golden_samples_have_no_secrets_or_private_data",),
    ),
)

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
groups: dict[str, bool] = {}
suite_results: list[dict[str, Any]] = []


def check(condition: bool, message: str) -> bool:
    global checks
    checks += 1
    if condition:
        print(f"PASS {message}")
    else:
        failures.append(message)
        print(f"FAIL {message}")
    return bool(condition)


def run_node(script: str, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node executable not found on PATH")
    env = dict(os.environ, NO_COLOR="1", FORCE_COLOR="0")
    return subprocess.run(
        [node, script, *args],
        cwd=FRONTEND,
        check=True,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def build_frontend() -> str:
    run_node("node_modules/typescript/bin/tsc", "--noEmit")
    proc = run_node("node_modules/vite/bin/vite.js", "build", capture=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    print(output)
    return output


def bundle_size(build_output: str) -> dict[str, Any]:
    assets = FRONTEND / "dist" / "assets"
    js = sorted(assets.glob("*.js"))
    css = sorted(assets.glob("*.css"))
    if not js:
        raise RuntimeError("no JS bundle under frontend/dist/assets")
    # Vite's own gzip number is the P2 baseline's unit; keep the Python
    # measurement as a cross-check instead of mixing the two. Vite colours the
    # path and size, so strip ANSI before parsing.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", build_output)
    reported = re.findall(
        r"dist/assets/(\S+\.js)\s+.*?gzip:\s+([\d.]+)\s+kB", plain
    )
    js_kb = round(sum(float(value) for _name, value in reported), 2) if reported else None
    measured = round(
        sum(len(gzip.compress(path.read_bytes(), 9)) for path in js) / 1000, 2
    )
    if js_kb is None:
        js_kb = measured
    reported_by_name = {name: float(value) for name, value in reported}
    manifest = json.loads(
        (FRONTEND / "dist" / ".vite" / "manifest.json").read_text(encoding="utf-8")
    )
    entry = next(chunk for chunk in manifest.values() if chunk.get("isEntry"))
    entry_name = Path(entry["file"]).name
    entry_kb = reported_by_name.get(
        entry_name,
        round(len(gzip.compress((FRONTEND / "dist" / entry["file"]).read_bytes(), 9)) / 1000, 2),
    )
    route_kb = {
        Path(chunk["file"]).name: reported_by_name.get(
            Path(chunk["file"]).name,
            round(
                len(gzip.compress((FRONTEND / "dist" / chunk["file"]).read_bytes(), 9))
                / 1000,
                2,
            ),
        )
        for source, chunk in manifest.items()
        if chunk.get("isDynamicEntry") and source != "index.html"
    }
    oversized = {
        name: value for name, value in route_kb.items() if value > P4_ROUTE_CHUNK_LIMIT_KB
    }
    return {
        "js_files": [path.name for path in js],
        "js_gzip_kb": js_kb,
        "js_gzip_kb_python": measured,
        "css_gzip_kb": round(
            sum(len(gzip.compress(path.read_bytes(), 9)) for path in css) / 1000, 2
        ),
        "p2_baseline_kb": P2_BASELINE_KB,
        "total_delta_kb": round(js_kb - P2_BASELINE_KB, 2),
        "entry_file": entry_name,
        "entry_gzip_kb": entry_kb,
        "entry_budget_kb": P4_ENTRY_BUDGET_KB,
        "route_chunks": route_kb,
        "route_chunk_limit_kb": P4_ROUTE_CHUNK_LIMIT_KB,
        "oversized_route_chunks": oversized,
        "triggered": entry_kb > P4_ENTRY_BUDGET_KB or bool(oversized),
    }


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def preview_ready(url: str, proc: subprocess.Popen[str], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("vite preview exited early")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(0.1)
    raise RuntimeError("timed out waiting for vite preview")


class Preview:
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    def __enter__(self) -> str:
        preview_ready(f"{self.base}/reports", self.proc)
        return self.base

    def __exit__(self, *_exc: object) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def run_suites() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    for ticket, name in SUITES:
        log = LOGS / f"{name[:-3]}.log"
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(ROOT / "e2e" / name)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
        log.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
        result: dict[str, Any] = {}
        for line in reversed(proc.stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    continue
                break
        if not result:
            # legacy_projection_e2e.py prints "N checks, M failures" instead
            # of a JSON line; accept both shapes.
            match = re.search(r"(\d+) checks, (\d+) failures", proc.stdout)
            if match:
                count = int(match.group(1))
                failed = int(match.group(2))
                result = {
                    "checks": count,
                    "failures": ["see log"] if failed else [],
                }
        seconds = round(time.monotonic() - started, 1)
        passed = (
            proc.returncode == 0
            and not result.get("failures")
            and (result.get("checks") or 0) > 0
        )
        check(
            passed,
            f"{ticket} ({name}): {result.get('checks', '?')} checks, "
            f"{len(result.get('failures', []))} failures, {seconds}s",
        )
        if not passed:
            failures.extend(
                f"{name}: {item}" for item in result.get("failures", ["see log"])
            )
        suite_results.append(
            {
                "ticket": ticket,
                "script": f"e2e/{name}",
                "checks": result.get("checks"),
                "failures": result.get("failures", []),
                "exit_code": proc.returncode,
                "seconds": seconds,
                "log": str(log.relative_to(ROOT)).replace("\\", "/"),
            }
        )


def run_backend_group(name: str, nodes: tuple[str, ...]) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        [str(PYTHON), "-m", "pytest", *nodes, "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    seconds = round(time.monotonic() - started, 1)
    tail = [line for line in proc.stdout.splitlines() if line.strip()][-1:]
    ok = proc.returncode == 0
    groups[name] = groups.get(name, True) and ok
    check(ok, f"{name} backend: {tail[0] if tail else 'no output'} ({seconds}s)")
    if not ok:
        failures.append(f"{name} backend failed: {proc.stdout[-600:]}")
    return {
        "group": name,
        "nodes": list(nodes),
        "exit_code": proc.returncode,
        "summary": tail[0] if tail else "",
        "seconds": seconds,
    }


def web_titles(base: str) -> list[str]:
    payload = json.loads((FIXTURES / "final_state_v1.json").read_text(encoding="utf-8"))
    payload = json.loads(json.dumps(payload))
    payload["meta"]["report_id"] = "r-golden"
    payload["meta"]["job_id"] = None
    expected = [section["title"] for section in payload["sections"].values()]
    writes: list[str] = []
    errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                errors.append(message.text) if message.type == "error" else None
            ),
        )

        def handle(route) -> None:
            request = route.request
            if request.method != "GET":
                writes.append(f"{request.method} {request.url}")
            if "/api/v1/reports/r-golden" in request.url:
                route.fulfill(json=payload)
            elif "/api/v1/meta" in request.url:
                route.fulfill(json=META)
            else:
                route.fulfill(
                    status=404,
                    json={"error": {"code": "not_found", "message": "stub"}},
                )

        page.route("**/api/v1/**", handle)
        page.goto(f"{base}/reports/r-golden")
        page.get_by_test_id("report-section").first.wait_for(
            state="visible", timeout=30_000
        )
        titles = page.locator(
            '[data-testid="report-section"] > h2'
        ).all_inner_texts()
        page.screenshot(path=str(SHOTS / "web_titles.png"), full_page=True)
        context.close()
        browser.close()

    check(writes == [], f"C1 web title flow makes no non-GET request ({writes})")
    unexpected = [error for error in errors if "Failed to load resource" not in error]
    check(not unexpected, f"C1 web title flow console/page errors: {unexpected}")
    check(titles == expected, f"C1 web titles match the golden sequence ({titles})")
    return titles


def run_perf() -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(PYTHON),
            "scripts/p3_reports_perf.py",
            "--reports",
            "10000",
            "--samples",
            "30",
            "--out",
            str(PERF_OUT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    (LOGS / "p3_reports_perf.log").write_text(
        proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8"
    )
    if proc.returncode != 0:
        check(False, f"performance probe exited {proc.returncode}")
        return {}
    result = json.loads(PERF_OUT.read_text(encoding="utf-8"))
    check(
        result.get("conclusion") == "pass",
        f"performance list p95 {result['list_filtered']['p95_ms']} ms, "
        f"detail p95 {result['detail']['p95_ms']} ms, hard line "
        f"{result['hard_line_ms']} ms",
    )
    result["ticket"] = "P3-09"
    result["pdf_first_render"] = {
        "hard_line_ms": 15000,
        "status": "pass" if groups.get("C4") and groups.get("PERF-PDF") else "fail",
        "source": "tests/backend/test_exports.py::test_exp06_long_report_first_pdf_p95_under_15s",
    }
    result["pdf_cache_hit"] = {
        "hard_line_ms": 500,
        "status": "pass" if groups.get("C4") else "fail",
        "source": "tests/backend/test_exports.py::test_exp07_cache_hit_preparation_under_500ms",
    }
    result["external_network_calls"] = {
        "hard_line": 0,
        "value": 0 if groups.get("C2") else None,
        "source": "tests/backend/test_reports_api.py::test_rpt06_reads_are_side_effect_free",
    }
    PERF_OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def run_perf_pdf() -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pytest",
            "tests/backend/test_exports.py::test_exp06_long_report_first_pdf_p95_under_15s",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    seconds = round(time.monotonic() - started, 1)
    ok = proc.returncode == 0
    groups["PERF-PDF"] = ok
    check(ok, f"PDF first render p95 <= 15000 ms ({seconds}s)")
    return {"exit_code": proc.returncode, "seconds": seconds}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P3-09 P3 exit acceptance")
    parser.add_argument("--new-only", action="store_true", help="skip the three suites")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-perf", action="store_true")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "Python313" not in sys.executable and "Python31" not in sys.executable:
        print(f"warning: run with the system Python 3.13 (current: {sys.executable})")
    SHOTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    if not args.new_only:
        print("running the three P3 browser suites...")
        run_suites()

    if args.skip_build:
        print("skipping build")
        bundle = {}
    else:
        print("building frontend...")
        build_output = build_frontend()
        bundle = bundle_size(build_output)
        check(
            not bundle["triggered"],
            f"R-09 entry gzip {bundle['entry_gzip_kb']} kB "
            f"(budget {bundle['entry_budget_kb']} kB), "
            f"route chunks {bundle['route_chunks']} "
            f"(limit {bundle['route_chunk_limit_kb']} kB), "
            f"total {bundle['js_gzip_kb']} kB",
        )
        with Preview() as base:
            print(f"preview at {base}")
            web_titles(base)

    backend: list[dict[str, Any]] = []
    for name, nodes in BACKEND_GROUPS:
        print(f"running backend group {name}...")
        backend.append(run_backend_group(name, nodes))

    perf_pdf: dict[str, Any] = {}
    if not args.skip_perf:
        print("running the long-report PDF probe...")
        perf_pdf = run_perf_pdf()
        print("running the 10,000-row probe...")
        perf = run_perf()
    else:
        perf = {}

    suite_ok = len(suite_results) == len(SUITES) and all(
        item["exit_code"] == 0 and not item["failures"] and item["checks"]
        for item in suite_results
    )
    perf_ok = args.skip_perf or groups.get("PERF-PDF", False)
    criteria = {
        "1": groups.get("C1", False) and suite_ok,
        "2": groups.get("C2", False) and suite_ok,
        "3": groups.get("C3", False) and suite_ok,
        "4": groups.get("C4", False) and perf_ok and suite_ok,
    }
    for number, passed in criteria.items():
        check(passed, f"exit criterion {number}")

    result = {
        "ticket": "P3-09",
        "checks": checks,
        "failures": failures,
        "criteria": criteria,
        "suites": suite_results,
        "backend": backend,
        "bundle": bundle,
        "perf": {
            "list_filtered_p95_ms": (perf.get("list_filtered") or {}).get("p95_ms"),
            "detail_p95_ms": (perf.get("detail") or {}).get("p95_ms"),
            "pdf_first_render": (perf.get("pdf_first_render") or {}).get("status"),
            "pdf_cache_hit": (perf.get("pdf_cache_hit") or {}).get("status"),
            "external_network_calls": (perf.get("external_network_calls") or {}).get("value"),
            "file": str(PERF_OUT.relative_to(ROOT)).replace("\\", "/"),
            "pdf_probe_seconds": perf_pdf.get("seconds"),
        },
        "screenshots": str(SHOTS.relative_to(ROOT)).replace("\\", "/"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
