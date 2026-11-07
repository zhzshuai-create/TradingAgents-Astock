"""P4-12: one entry point for the P4 exit walkthrough.

Runs the browser suites that own R-10 to R-16, the backend groups behind the
market/stock envelopes, the bundle manifest check, the P4 performance fixture,
the cached route-switch probe and the E1-E18 equivalence checklist. This ticket
only adds scripts and records; product behaviour is untouched.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/e2e_p4.py
    ... e2e/e2e_p4.py --skip-suites      # bundle, route switch, backend, perf
    ... e2e/e2e_p4.py --skip-build       # reuse the existing dist
    ... e2e/e2e_p4.py --skip-python-full # targeted backend groups only

Everything runs under the system Python 3.13 (Playwright); the backend groups
and the perf fixture run under ``.venv``. Logs and screenshots go to
``ui_shots_p4/P4-12/`` (not committed). The script writes no evidence into the
repository: the perf JSON is produced by the standalone ``p4_market_perf.py``
command and cited by the exit review.

Exit criteria (backlog section 6):
1. equivalence: the checklist covers E1-E18 with only the written exceptions;
2. states: both suites plus the envelope backend groups pass;
3. context: the market/stock suites pass (R-11, R-12, R-13);
4. mobile and performance: both suites (R-14), bundle, fixture perf and the
   cached route switch stay inside their lines.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
E2E = ROOT / "e2e"
SHOTS = ROOT / "ui_shots_p4" / "P4-12"
LOGS = SHOTS / "logs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
REVIEWS = ROOT / "docs" / "upgrade" / "reviews"
EQUIVALENCE = REVIEWS / "2026-11-07_P4等价清单.md"

ENTRY_BUDGET_KB = 202.45
ROUTE_CHUNK_LIMIT_KB = 60.0
ROUTE_SWITCH_LINE_MS = 300.0
WARM_LINE_MS = 1500.0
COLD_LINE_MS = 4000.0

MARKET_MIN_CHECKS = 103
STOCK_MIN_CHECKS = 99
PYTHON_FULL_FLOOR = 789
MIGRATION_HEAD = "0007"
MIGRATION_COUNT = 7

STRONG_TICKER = "000001"
ROUTE_SWITCH_TARGET = "stock-price"

sys.path.insert(0, str(E2E))
try:
    import market_e2e  # noqa: E402
    import stock_e2e  # noqa: E402
except ModuleNotFoundError as error:  # Playwright only lives in the system Python
    raise SystemExit(
        "run e2e/e2e_p4.py with the system Python 3.13 that has Playwright "
        f"({error})"
    ) from error

BACKEND_GROUPS = (
    (
        "ENV",
        (
            "tests/backend/test_market_envelope.py",
            "tests/backend/test_market_cache.py",
            "tests/backend/test_market_providers.py",
            "tests/backend/test_market_service.py",
        ),
    ),
    (
        "MKT",
        (
            "tests/backend/test_market_api.py",
            "tests/backend/test_market_search.py",
        ),
    ),
    (
        "STK",
        (
            "tests/backend/test_stock_snapshot.py",
            "tests/backend/test_stock_kline.py",
            "tests/backend/test_stocks_api.py",
        ),
    ),
)

SUITES = (
    (
        "R-10/R-11/R-14/R-15/R-16 (market)",
        "market_e2e.py",
        MARKET_MIN_CHECKS,
        ("W08M-01", "W08M-04"),
    ),
    (
        "R-12/R-13/R-14/R-15/R-16 (stock)",
        "stock_e2e.py",
        STOCK_MIN_CHECKS,
        ("W07M-01", "W07M-04"),
    ),
)

failures: list[str] = []
checks = 0
groups: dict[str, bool] = {}

ROUTE_SWITCH_JS = """async ({link, target}) => {
  const anchor = document.querySelector(link);
  if (anchor === null) throw new Error(`missing link ${link}`);
  const started = performance.now();
  anchor.click();
  await new Promise((resolve, reject) => {
    const deadline = started + 5000;
    const tick = () => {
      const node = document.querySelector(`[data-testid="${target}"]`);
      if (node !== null && node.getBoundingClientRect().height > 0) {
        resolve();
        return;
      }
      if (performance.now() > deadline) {
        reject(new Error(`timeout waiting for ${target}`));
        return;
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
  return performance.now() - started;
}"""


def check(condition: bool, message: str) -> bool:
    global checks
    checks += 1
    if condition:
        print(f"PASS {message}")
    else:
        failures.append(message)
        print(f"FAIL {message}")
    return bool(condition)


def nearest_rank(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    rank = max(1, -(-percentile * len(ordered) // 100))
    return ordered[rank - 1]


def run_node(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node executable not found on PATH")
    return subprocess.run(
        [node, script, *args],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def build_frontend() -> None:
    print("building frontend...", flush=True)
    typecheck = run_node("node_modules/typescript/bin/tsc", "--noEmit")
    check(typecheck.returncode == 0, "tsc --noEmit")
    build = run_node("node_modules/vite/bin/vite.js", "build")
    check(build.returncode == 0, "vite build")
    if build.returncode != 0:
        raise RuntimeError("vite build failed:\n" + (build.stderr or build.stdout or ""))


def run_bundle(temp: Path) -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    out = temp / "bundle.json"
    proc = run_node("scripts/check_bundle.mjs", "--out", str(out))
    (LOGS / "check_bundle.log").write_text(
        (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""),
        encoding="utf-8",
    )
    if not out.exists():
        check(False, "bundle manifest check produced no JSON")
        return {}
    evidence = json.loads(out.read_text(encoding="utf-8"))
    entry = evidence.get("entry", {})
    routes = evidence.get("route_chunks", [])
    check(
        proc.returncode == 0 and bool(evidence.get("passed")),
        f"bundle entry {entry.get('gzip_kb')} kB gzip "
        f"(budget {ENTRY_BUDGET_KB}), {len(routes)} route chunks "
        f"(limit {ROUTE_CHUNK_LIMIT_KB} kB)",
    )
    check(
        bool(evidence.get("passed"))
        and all(
            chunk.get("dynamic_import")
            and chunk.get("separate_from_entry")
            and chunk.get("gzip_kb", 999) <= ROUTE_CHUNK_LIMIT_KB
            for chunk in routes
        ),
        "every route chunk stays lazy, separate and under the per-chunk limit",
    )
    return {
        "entry_gzip_kb": entry.get("gzip_kb"),
        "entry_budget_gzip_kb": ENTRY_BUDGET_KB,
        "route_chunks": len(routes),
        "route_chunk_limit_gzip_kb": ROUTE_CHUNK_LIMIT_KB,
        "largest_route_chunk": max(
            routes, key=lambda chunk: chunk.get("gzip_kb", 0), default={}
        ),
        "shared_chunks": evidence.get("shared_chunks", []),
        "passed": bool(evidence.get("passed")),
    }


def run_route_switch(base: str, samples: int) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    warmups = 3
    values: list[float] = []
    errors: list[str] = []
    requests: list[tuple[str, str]] = []
    snapshot_needle = f"/api/v1/stocks/{STRONG_TICKER}/snapshot"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            timezone_id="Asia/Shanghai",
        )
        market_e2e.stub_api(context)
        # The market's strong-stock rows link at 000001; retarget the stock stub
        # to that ticker for this in-process probe only (suites are subprocesses).
        stock_e2e.TICKER = STRONG_TICKER
        stock_e2e.stub_api(context)

        page = context.new_page()
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

        page.goto(f"{base}/market")
        page.get_by_test_id("page-market").wait_for(state="visible", timeout=30_000)
        page.get_by_test_id("strong-row").first.wait_for(
            state="visible", timeout=30_000
        )
        link = f'[data-testid="strong-row"] a[href^="/stocks/{STRONG_TICKER}"]'

        def switch_once() -> float:
            return page.evaluate(
                ROUTE_SWITCH_JS, {"link": link, "target": ROUTE_SWITCH_TARGET}
            )

        def go_back_to_market() -> None:
            page.go_back()
            page.get_by_test_id("page-market").wait_for(
                state="visible", timeout=15_000
            )
            page.get_by_test_id("strong-row").first.wait_for(
                state="visible", timeout=15_000
            )

        try:
            for _ in range(warmups):
                switch_once()
                go_back_to_market()
            before = sum(1 for _method, url in requests if snapshot_needle in url)
            for _ in range(samples):
                values.append(switch_once())
                go_back_to_market()
            after = sum(1 for _method, url in requests if snapshot_needle in url)
            page.get_by_test_id("strong-row").first.wait_for(
                state="visible", timeout=15_000
            )
            page.screenshot(path=str(SHOTS / "route_switch.png"), full_page=True)
        except Exception as error:  # noqa: BLE001 - reported as a failed check
            errors.append(f"route switch failed: {error}")
            before = after = 0
        finally:
            context.close()
            browser.close()

    unexpected = [error for error in errors if "Failed to load resource" not in error]
    non_get = [f"{method} {url}" for method, url in requests if method != "GET"]
    if not values:
        check(False, "route switch collected no samples")
        return {"samples": 0, "passed": False, "errors": unexpected}

    p95 = nearest_rank(values, 95)
    median = sorted(values)[len(values) // 2]
    cached = before >= 1 and after - before == 0
    check(
        p95 <= ROUTE_SWITCH_LINE_MS,
        f"cached route switch p95 {p95:.1f} ms (line {ROUTE_SWITCH_LINE_MS} ms, "
        f"{len(values)} samples)",
    )
    check(
        cached,
        f"route switch reads the cached snapshot (before {before}, after {after})",
    )
    check(not non_get, f"route switch reads are all GET ({non_get[:3]})")
    check(not unexpected, f"route switch console/page errors: {unexpected[:3]}")
    return {
        "samples": len(values),
        "warmups": warmups,
        "median_ms": round(median, 2),
        "p95_ms": round(p95, 2),
        "line_ms": ROUTE_SWITCH_LINE_MS,
        "samples_ms": [round(value, 2) for value in values],
        "snapshot_requests": {"before": before, "after": after, "cached": cached},
        "passed": p95 <= ROUTE_SWITCH_LINE_MS and cached and not non_get and not unexpected,
    }


def parse_last_json(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def run_suite(
    label: str, script: str, min_checks: int, required_tags: tuple[str, ...]
) -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{script[:-3]}.log"
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(E2E / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    stdout = proc.stdout or ""
    log.write_text(
        stdout + "\n--- stderr ---\n" + (proc.stderr or ""), encoding="utf-8"
    )
    result = parse_last_json(stdout)
    seconds = round(time.monotonic() - started, 1)
    found = set(re.findall(r"\b(W08M-\d{2}|W07M-\d{2})\b", stdout))
    missing_tags = sorted(set(required_tags) - found)
    passed = (
        proc.returncode == 0
        and not result.get("failures")
        and (result.get("checks") or 0) >= min_checks
        and "R-15" in stdout
        and not missing_tags
    )
    check(
        passed,
        f"{label}: {result.get('checks', '?')} checks, "
        f"{len(result.get('failures', []))} failures, {seconds}s"
        + (f", missing {missing_tags}" if missing_tags else ""),
    )
    if not passed:
        failures.extend(
            f"{script}: {item}" for item in result.get("failures", ["see log"])
        )
    return {
        "label": label,
        "script": f"e2e/{script}",
        "checks": result.get("checks"),
        "min_checks": min_checks,
        "failures": result.get("failures", []),
        "exit_code": proc.returncode,
        "seconds": seconds,
        "mobile_tags": sorted(found),
        "log": str(log.relative_to(ROOT)).replace("\\", "/"),
        "passed": passed,
    }


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
    tail = [line for line in (proc.stdout or "").splitlines() if line.strip()][-1:]
    ok = proc.returncode == 0
    groups[name] = ok
    check(ok, f"{name} backend: {tail[0] if tail else 'no output'} ({seconds}s)")
    if not ok:
        failures.append(f"{name} backend failed: {(proc.stdout or '')[-600:]}")
    return {
        "group": name,
        "nodes": list(nodes),
        "exit_code": proc.returncode,
        "summary": tail[0] if tail else "",
        "seconds": seconds,
        "passed": ok,
    }


def run_python_full() -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        [str(PYTHON), "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    seconds = round(time.monotonic() - started, 1)
    plain = proc.stdout or ""
    match = re.search(r"(\d+) passed", plain)
    passed = int(match.group(1)) if match else 0
    ok = proc.returncode == 0 and passed >= PYTHON_FULL_FLOOR
    check(ok, f"python full suite: {passed} passed ({seconds}s, floor {PYTHON_FULL_FLOOR})")
    if not ok:
        failures.append(f"python full suite regressed: {plain[-600:]}")
    return {
        "passed": passed,
        "floor": PYTHON_FULL_FLOOR,
        "exit_code": proc.returncode,
        "seconds": seconds,
        "passed_check": ok,
    }


def run_perf(temp: Path, samples: int) -> dict[str, Any]:
    LOGS.mkdir(parents=True, exist_ok=True)
    out = temp / "p4_perf.json"
    proc = subprocess.run(
        [
            str(PYTHON),
            "scripts/p4_market_perf.py",
            "--fixture",
            "--samples",
            str(samples),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    (LOGS / "p4_market_perf.log").write_text(
        (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or ""),
        encoding="utf-8",
    )
    if not out.exists():
        check(False, f"performance fixture exited {proc.returncode} without JSON")
        return {}
    result = json.loads(out.read_text(encoding="utf-8"))
    warm = result.get("snapshot_warm", {})
    cold = result.get("snapshot_cold", {})
    calls = result.get("provider_calls", {})
    blocks = result.get("dataset", {}).get("blocks", [])
    check(
        result.get("conclusion") == "pass"
        and warm.get("p95_ms", 1e9) <= WARM_LINE_MS
        and cold.get("p95_ms", 1e9) <= COLD_LINE_MS,
        f"snapshot warm p95 {warm.get('p95_ms')} ms (line {WARM_LINE_MS}), "
        f"cold p95 {cold.get('p95_ms')} ms (line {COLD_LINE_MS})",
    )
    check(
        result.get("external_network_calls") == 0,
        f"performance fixture makes no external call "
        f"({result.get('external_network_calls')})",
    )
    check(
        bool(blocks) and all(calls.get(block, 0) >= samples for block in blocks),
        f"every cold sample reaches all blocks ({ {block: calls.get(block) for block in blocks} })",
    )
    return {
        "mode": result.get("mode"),
        "warm_p95_ms": warm.get("p95_ms"),
        "cold_p95_ms": cold.get("p95_ms"),
        "warm_line_ms": WARM_LINE_MS,
        "cold_line_ms": COLD_LINE_MS,
        "provider_calls": calls,
        "external_network_calls": result.get("external_network_calls"),
        "conclusion": result.get("conclusion"),
        "command": result.get("command"),
        "evidence_file": "docs/upgrade/reviews/2026-11-07_P4-12性能结果.json",
        "passed": result.get("conclusion") == "pass",
    }


EQUIVALENCE_EXCEPTIONS = {"E5", "E6", "E17"}
EQUIVALENCE_CONCLUSIONS = {"等价", "部分等价", "例外", "行为差异", "新版增强"}
ROW_PATTERN = re.compile(r"^\|\s*(E\d{1,2})\s*\|")


def check_equivalence(path: Path) -> dict[str, Any]:
    if not path.exists():
        check(False, f"equivalence checklist missing: {path.relative_to(ROOT)}")
        return {"file": str(path.relative_to(ROOT)), "rows": 0, "passed": False}
    text = path.read_text(encoding="utf-8-sig")
    rows: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        match = ROW_PATTERN.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        rows[match.group(1)] = {"conclusion": cells[4], "note": cells[5]}
    expected = {f"E{number}" for number in range(1, 19)}
    missing = sorted(expected - set(rows), key=lambda item: int(item[1:]))
    unexpected = sorted(set(rows) - expected)
    bad_conclusion = {
        key: value["conclusion"]
        for key, value in rows.items()
        if value["conclusion"] not in EQUIVALENCE_CONCLUSIONS
    }
    wrong_exception = {
        key: value["conclusion"]
        for key, value in rows.items()
        if value["conclusion"] != "等价"
        and key not in EQUIVALENCE_EXCEPTIONS
        and key != "E18"
    }
    check(
        not missing and not unexpected,
        f"equivalence checklist covers E1-E18 (missing {missing}, extra {unexpected})",
    )
    check(
        not bad_conclusion and not wrong_exception,
        f"equivalence conclusions stay in the written exceptions "
        f"({bad_conclusion or wrong_exception})",
    )
    check(
        "C6" in rows.get("E5", {}).get("note", "")
        and "C4" in rows.get("E6", {}).get("note", "")
        and "C5" in rows.get("E14", {}).get("note", ""),
        "E5/E6/E14 name their conflicts C6/C4/C5",
    )
    check(
        "C9" in text and "P5" in text,
        "the known C9 market-copy defect is recorded for P5",
    )
    passed = (
        not missing
        and not unexpected
        and not bad_conclusion
        and not wrong_exception
        and "C9" in text
        and "P5" in text
    )
    return {
        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
        "rows": len(rows),
        "exceptions": sorted(EQUIVALENCE_EXCEPTIONS),
        "known_defect": "C9",
        "passed": passed,
    }


def check_migrations() -> dict[str, Any]:
    versions = sorted(
        path
        for path in (ROOT / "backend" / "alembic" / "versions").glob("*.py")
        if path.name != "__init__.py"
    )
    names = [path.name for path in versions]
    head = names[-1].split("_")[0] if names else None
    ok = len(names) == MIGRATION_COUNT and head == MIGRATION_HEAD
    check(
        ok,
        f"alembic head {head} with {len(names)} version files "
        f"(expected {MIGRATION_HEAD}, {MIGRATION_COUNT})",
    )
    return {"head": head, "count": len(names), "passed": ok}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P4-12 P4 exit acceptance")
    parser.add_argument("--skip-suites", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-route-perf", action="store_true")
    parser.add_argument("--skip-python-full", action="store_true")
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args(argv)
    if args.samples < 30:
        parser.error("--samples must be at least 30")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "Python313" not in sys.executable and "Python31" not in sys.executable:
        print(f"warning: run with the system Python 3.13 (current: {sys.executable})")
    if not PYTHON.exists():
        raise SystemExit(f"backend interpreter missing: {PYTHON}")
    SHOTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)

        if args.skip_build:
            print("skipping build", flush=True)
            bundle: dict[str, Any] = {}
        else:
            build_frontend()
            bundle = run_bundle(temp)

        route_switch: dict[str, Any] = {}
        if not args.skip_route_perf:
            print("measuring the cached route switch...", flush=True)
            with market_e2e.Server() as base:
                print(f"preview at {base}", flush=True)
                route_switch = run_route_switch(base, args.samples)

        suite_results: list[dict[str, Any]] = []
        if not args.skip_suites:
            for label, script, min_checks, tags in SUITES:
                print(f"running {script}...", flush=True)
                suite_results.append(run_suite(label, script, min_checks, tags))

        backend: list[dict[str, Any]] = []
        for name, nodes in BACKEND_GROUPS:
            print(f"running backend group {name}...", flush=True)
            backend.append(run_backend_group(name, nodes))

        python_full: dict[str, Any] = {}
        if not args.skip_python_full:
            print("running the full python suite...", flush=True)
            python_full = run_python_full()

        print("running the performance fixture...", flush=True)
        perf = run_perf(temp, args.samples)

    equivalence = check_equivalence(EQUIVALENCE)
    migrations = check_migrations()

    suites_ok = (
        len(suite_results) == len(SUITES)
        and all(result["passed"] for result in suite_results)
    )
    backend_ok = all(groups.get(name, False) for name, _nodes in BACKEND_GROUPS)
    bundle_ok = bool(bundle) and bool(bundle.get("passed"))
    perf_ok = bool(perf) and bool(perf.get("passed"))
    route_ok = bool(route_switch) and bool(route_switch.get("passed"))
    criteria = {
        "1": bool(equivalence.get("passed")),
        "2": backend_ok and suites_ok,
        "3": suites_ok,
        "4": suites_ok and bundle_ok and perf_ok and route_ok,
    }
    for number, passed in criteria.items():
        check(passed, f"exit criterion {number}")

    result = {
        "ticket": "P4-12",
        "checks": checks,
        "failures": failures,
        "criteria": criteria,
        "suites": suite_results,
        "backend": backend,
        "bundle": bundle,
        "perf": perf,
        "route_switch": route_switch,
        "equivalence": equivalence,
        "migrations": migrations,
        "python_full": python_full,
        "screenshots": str(SHOTS.relative_to(ROOT)).replace("\\", "/"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
