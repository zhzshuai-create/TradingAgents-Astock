"""P5-09: one entry point for the P5 exit walkthrough.

Runs the frontend build chain, the backend groups and the full Python suite, the
P2/P3/P4 exit aggregators, the five P5 browser suites plus the market/stock
regressions, the alembic head check and the P0 preflight. Every step is recorded
with its command, exit code and key numbers; the script writes the evidence JSON
under ``docs/upgrade/reviews/`` and exits non-zero on any failed gate.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/e2e_p5.py
    ... e2e/e2e_p5.py --skip-build        # reuse dist, skip tsc/vitest/build/bundle
    ... e2e/e2e_p5.py --skip-regression   # skip the P2/P3/P4 aggregators
    ... e2e/e2e_p5.py --skip-preflight    # skip the trailing P0 preflight

Only runs existing commands: this ticket adds no product behaviour and no new
assertions. Before the preflight it restores the two review files the child
suites refresh, so the run leaves the worktree as it found it. Logs go to
``ui_shots_p5/P5-09/logs/`` (not committed).

Exit criteria (backlog section 5):
1. a journal outage never takes the rest of the site down;
2. settings never expose or accept secrets;
3. the nine core pages stay free of critical/serious axe findings;
4. the whole main flow works from the keyboard alone.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
E2E = ROOT / "e2e"
SHOTS = ROOT / "ui_shots_p5" / "P5-09"
LOGS = SHOTS / "logs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
EVIDENCE = ROOT / "docs" / "upgrade" / "reviews" / "2026-11-07_P5出口证据.json"

ENTRY_BUDGET_KB = 202.45
ROUTE_CHUNK_LIMIT_KB = 60.0
EXPECTED_ROUTE_CHUNKS = 11
UNIT_FILES_FLOOR = 38
UNIT_TESTS_FLOOR = 527
PYTHON_FULL_FLOOR = 789
PYTHON_SKIPPED = 4
MIGRATION_HEAD = "0007"
AXE_PAGE_STATES = 29
MOBILE_PAGES = 24
MOBILE_SHOTS = 26
PREFLIGHT_ITEMS = 10

P5_SUITES = (
    ("keyboard", "keyboard_e2e.py", 59),
    ("settings", "settings_e2e.py", 73),
    ("journal", "journal_e2e.py", 80),
    ("a11y", "a11y_e2e.py", 0),
    ("mobile", "mobile_e2e.py", 0),
    ("market", "market_e2e.py", 103),
    ("stock", "stock_e2e.py", 99),
)

REGRESSION = (
    ("p2", "e2e_p2.py", []),
    ("p3", "e2e_p3.py", []),
    ("p4", "e2e_p4.py", []),
)

# The P3 and P5-08 suites refresh their own review evidence while running.
# Restoring those tracked files keeps the preflight's clean-worktree check
# meaningful and leaves the tree exactly as it was before this script ran.
GENERATED_BY_CHILDREN = (
    "docs/upgrade/reviews/2026-11-06_P3-09性能结果.json",
    "docs/upgrade/reviews/2026-11-07_P5-08可访问性与移动结果.json",
)

gates: list[dict[str, Any]] = []
results: dict[str, dict[str, Any]] = {}


def gate(
    name: str,
    command: str,
    value: Any,
    expected: Any,
    passed: bool,
    exit_code: int | None = None,
    seconds: float | None = None,
) -> bool:
    entry = {
        "name": name,
        "command": command,
        "exit_code": exit_code,
        "value": value,
        "expected": expected,
        "passed": bool(passed),
    }
    if seconds is not None:
        entry["seconds"] = seconds
    gates.append(entry)
    print(
        f"{'PASS' if passed else 'FAIL'} {name}: {value} "
        f"(expected {expected})",
        flush=True,
    )
    return bool(passed)


def node() -> str:
    found = shutil.which("node")
    if found is None:
        raise SystemExit("node executable not found on PATH")
    return found


def run(
    label: str, command: list[str], cwd: Path = ROOT, timeout: int = 1800
) -> tuple[subprocess.CompletedProcess[str], float]:
    LOGS.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    seconds = round(time.monotonic() - started, 1)
    (LOGS / f"{label}.log").write_text(
        f"$ {' '.join(command)}\n\n{proc.stdout or ''}\n--- stderr ---\n{proc.stderr or ''}",
        encoding="utf-8",
    )
    return proc, seconds


def parse_last_json(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def run_node(label: str, script: str, *args: str) -> tuple[subprocess.CompletedProcess[str], float]:
    return run(label, [node(), script, *args], cwd=FRONTEND)


def frontend_chain(temp: Path) -> dict[str, Any]:
    typecheck, seconds = run_node("tsc", "node_modules/typescript/bin/tsc", "--noEmit")
    gate(
        "typecheck",
        "cd frontend && node node_modules/typescript/bin/tsc --noEmit",
        f"exit {typecheck.returncode}",
        "exit 0",
        typecheck.returncode == 0,
        typecheck.returncode,
        seconds,
    )

    unit, seconds = run_node("vitest", "node_modules/vitest/vitest.mjs", "run")
    plain = (unit.stdout or "") + (unit.stderr or "")
    files = re.search(r"Test Files\s+(\d+)\s+passed", plain)
    tests = re.search(r"Tests\s+(\d+)\s+passed", plain)
    file_count = int(files.group(1)) if files else 0
    test_count = int(tests.group(1)) if tests else 0
    unit_ok = (
        unit.returncode == 0
        and file_count >= UNIT_FILES_FLOOR
        and test_count >= UNIT_TESTS_FLOOR
    )
    gate(
        "unit",
        "cd frontend && node node_modules/vitest/vitest.mjs run",
        f"{test_count} tests / {file_count} files",
        f">= {UNIT_TESTS_FLOOR} tests / >= {UNIT_FILES_FLOOR} files",
        unit_ok,
        unit.returncode,
        seconds,
    )

    build, seconds = run_node("build", "node_modules/vite/bin/vite.js", "build")
    gate("build", "cd frontend && node node_modules/vite/bin/vite.js build", "exit", 0, build.returncode == 0, build.returncode, seconds)

    out = temp / "bundle.json"
    manifest, seconds = run_node("check_bundle", "scripts/check_bundle.mjs", "--out", str(out))
    bundle: dict[str, Any] = {}
    if out.exists():
        bundle = json.loads(out.read_text(encoding="utf-8"))
    entry = bundle.get("entry", {})
    chunks = bundle.get("route_chunks", [])
    entry_kb = entry.get("gzip_kb")
    largest = max(chunks, key=lambda item: item.get("gzip_kb", 0), default={})
    bundle_ok = (
        manifest.returncode == 0
        and bool(bundle.get("passed"))
        and entry_kb is not None
        and entry_kb <= ENTRY_BUDGET_KB
        and len(chunks) == EXPECTED_ROUTE_CHUNKS
        and all(
            chunk.get("dynamic_import")
            and chunk.get("separate_from_entry")
            and chunk.get("gzip_kb", 999) <= ROUTE_CHUNK_LIMIT_KB
            for chunk in chunks
        )
    )
    gate(
        "bundle",
        "cd frontend && node scripts/check_bundle.mjs --out <temp>",
        f"entry {entry_kb} kB gzip, {len(chunks)} route chunks, "
        f"largest {largest.get('file')} {largest.get('gzip_kb')} kB",
        f"entry <= {ENTRY_BUDGET_KB} kB, {EXPECTED_ROUTE_CHUNKS} lazy chunks, "
        f"each <= {ROUTE_CHUNK_LIMIT_KB} kB",
        bundle_ok,
        manifest.returncode,
        seconds,
    )

    return {
        "unit": {"tests": test_count, "files": file_count, "passed": unit_ok},
        "bundle": {
            "entry_gzip_kb": entry_kb,
            "entry_budget_gzip_kb": ENTRY_BUDGET_KB,
            "route_chunks": len(chunks),
            "route_chunk_limit_gzip_kb": ROUTE_CHUNK_LIMIT_KB,
            "largest_route_chunk": {
                "file": largest.get("file"),
                "gzip_kb": largest.get("gzip_kb"),
            },
            "passed": bundle_ok,
        },
    }


def python_groups() -> dict[str, Any]:
    backend, seconds = run(
        "pytest_backend", [str(PYTHON), "-m", "pytest", "tests/backend", "-q"]
    )
    tail = [line for line in (backend.stdout or "").splitlines() if line.strip()][-1:]
    gate(
        "backend group",
        ".venv/Scripts/python.exe -m pytest tests/backend -q",
        tail[0] if tail else "no output",
        "exit 0",
        backend.returncode == 0,
        backend.returncode,
        seconds,
    )

    full, seconds = run("pytest_full", [str(PYTHON), "-m", "pytest", "-q"])
    plain = full.stdout or ""
    passed_match = re.search(r"(\d+) passed", plain)
    skipped_match = re.search(r"(\d+) skipped", plain)
    passed = int(passed_match.group(1)) if passed_match else 0
    skipped = int(skipped_match.group(1)) if skipped_match else 0
    full_ok = (
        full.returncode == 0
        and passed >= PYTHON_FULL_FLOOR
        and skipped == PYTHON_SKIPPED
    )
    gate(
        "python full",
        ".venv/Scripts/python.exe -m pytest -q",
        f"{passed} passed / {skipped} skipped",
        f">= {PYTHON_FULL_FLOOR} passed / {PYTHON_SKIPPED} skipped",
        full_ok,
        full.returncode,
        seconds,
    )
    return {"passed": passed, "skipped": skipped, "ok": full_ok}


def regression() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, script, args in REGRESSION:
        proc, seconds = run(name, [sys.executable, str(E2E / script), *args])
        payload = parse_last_json(proc.stdout or "")
        failed = payload.get("failures") or []
        ok = proc.returncode == 0 and not failed
        gate(
            f"regression {name}",
            f"python e2e/{script} {' '.join(args)}".strip(),
            f"{payload.get('checks', '?')} checks, {len(failed)} failures",
            "exit 0, 0 failures",
            ok,
            proc.returncode,
            seconds,
        )
        out[name] = {
            "script": f"e2e/{script}",
            "checks": payload.get("checks"),
            "failures": failed,
            "passed": ok,
        }
    return out


def suites() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, script, min_checks in P5_SUITES:
        proc, seconds = run(label, [sys.executable, str(E2E / script)])
        payload = parse_last_json(proc.stdout or "")
        failed = payload.get("failures") or []
        checks = payload.get("checks") or 0
        ok = proc.returncode == 0 and not failed and checks >= min_checks

        if label == "a11y":
            critical = payload.get("critical")
            serious = payload.get("serious")
            states = payload.get("pages_scanned")
            ok = (
                ok
                and critical == 0
                and serious == 0
                and states == AXE_PAGE_STATES
            )
            value = f"{states} page states, {critical} critical, {serious} serious"
            expected = f"{AXE_PAGE_STATES} states, 0 critical, 0 serious"
        elif label == "mobile":
            pages = payload.get("pages_measured")
            undersized = payload.get("undersized")
            shots = payload.get("screenshots")
            ok = ok and pages == MOBILE_PAGES and undersized == 0 and shots >= MOBILE_SHOTS
            value = f"{pages} pages, {undersized} undersized, {shots} screenshots"
            expected = f"{MOBILE_PAGES} pages, 0 undersized, >= {MOBILE_SHOTS} screenshots"
        else:
            value = f"{checks} checks, {len(failed)} failures"
            expected = f">= {min_checks} checks, 0 failures"

        gate(
            f"suite {label}",
            f"python e2e/{script}",
            value,
            expected,
            ok,
            proc.returncode,
            seconds,
        )
        if failed:
            print(f"  {label} failures: {failed[:3]}", flush=True)
        out[label] = {
            "script": f"e2e/{script}",
            "checks": checks,
            "failures": failed,
            "axe_version": payload.get("axe_version"),
            "critical": payload.get("critical"),
            "serious": payload.get("serious"),
            "pages_scanned": payload.get("pages_scanned"),
            "pages_measured": payload.get("pages_measured"),
            "undersized": payload.get("undersized"),
            "exceptions": payload.get("exceptions"),
            "screenshots": payload.get("screenshots"),
            "passed": ok,
        }
    return out


def migrations() -> str | None:
    proc, seconds = run(
        "alembic_heads", [str(PYTHON), "-m", "alembic", "-c", "backend/alembic.ini", "heads"]
    )
    heads = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    head = heads[0].split(" ")[0] if heads else None
    single = len(heads) == 1 and head == MIGRATION_HEAD
    gate(
        "migration head",
        ".venv/Scripts/python.exe -m alembic -c backend/alembic.ini heads",
        heads[0] if heads else "no head",
        f"{MIGRATION_HEAD} (single head)",
        proc.returncode == 0 and single,
        proc.returncode,
        seconds,
    )
    return head if single else None


def restore_generated() -> list[str]:
    restored: list[str] = []
    for path in GENERATED_BY_CHILDREN:
        changed = (
            subprocess.run(
                ["git", "diff", "--quiet", "--", path],
                cwd=ROOT,
                capture_output=True,
            ).returncode
            != 0
        )
        if changed:
            subprocess.run(["git", "checkout", "--", path], cwd=ROOT, check=True)
            restored.append(path)
    gate(
        "restore child evidence",
        "git checkout -- <P3-09 / P5-08 evidence>",
        f"restored {restored}" if restored else "nothing modified",
        "tracked evidence back to HEAD",
        True,
    )
    return restored


def preflight() -> dict[str, Any]:
    proc, seconds = run(
        "preflight", [str(PYTHON), "scripts/p0_preflight.py", "--full", "--smoke"]
    )
    plain = proc.stdout or ""
    counts = re.search(r"通过 (\d+)，失败 (\d+)", plain)
    passed = int(counts.group(1)) if counts else 0
    failed = int(counts.group(2)) if counts else 99
    ok = proc.returncode == 0 and passed == PREFLIGHT_ITEMS and failed == 0
    smoke = "健康检查 ok" in plain
    gate(
        "preflight",
        ".venv/Scripts/python.exe scripts/p0_preflight.py --full --smoke",
        f"{passed} PASS / {failed} FAIL, legacy smoke {'ok' if smoke else 'missing'}",
        f"{PREFLIGHT_ITEMS} PASS / 0 FAIL",
        ok,
        proc.returncode,
        seconds,
    )
    return {"passed": passed, "failed": failed, "smoke": smoke, "ok": ok}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P5-09 P5 exit acceptance")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-regression", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "Python313" not in sys.executable and "Python31" not in sys.executable:
        print(f"warning: run with the system Python 3.13 (current: {sys.executable})")
    if not PYTHON.exists():
        raise SystemExit(f"backend interpreter missing: {PYTHON}")
    LOGS.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    front: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        if args.skip_build:
            print("skipping the frontend build chain", flush=True)
        else:
            print("running the frontend build chain...", flush=True)
            front = frontend_chain(temp)

    print("running the python groups...", flush=True)
    python = python_groups()

    regressions: dict[str, Any] = {}
    if args.skip_regression:
        print("skipping the P2/P3/P4 aggregators", flush=True)
    else:
        print("running the P2/P3/P4 aggregators...", flush=True)
        regressions = regression()

    print("running the P5 suites...", flush=True)
    suite_results = suites()

    head = migrations()

    pf = {"passed": 0, "failed": 0, "smoke": False, "ok": True}
    if args.skip_preflight:
        print("skipping the preflight", flush=True)
    else:
        print("restoring the evidence the child suites refreshed...", flush=True)
        restore_generated()
        print("running the preflight...", flush=True)
        pf = preflight()

    by_name = {entry["name"]: entry for entry in gates}

    def ok(name: str) -> bool:
        return bool(by_name.get(name, {}).get("passed"))

    criteria = [
        {
            "id": "1",
            "statement": "日志故障不拖垮主站",
            "evidence": "journal_e2e.py 三原因与超时仍绿；market/stock 与 P2 任务回归在日志不可用下全绿",
            "passed": ok("suite journal") and ok("suite market") and ok("regression p2"),
        },
        {
            "id": "2",
            "statement": "设置不泄露密钥",
            "evidence": "settings_e2e.py 无密钥输入、DOM/localStorage 无密钥模式、已有任务快照不变",
            "passed": ok("suite settings"),
        },
        {
            "id": "3",
            "statement": "核心页面无严重 axe 问题",
            "evidence": "a11y_e2e.py 29 个页面状态 critical/serious 全 0",
            "passed": ok("suite a11y"),
        },
        {
            "id": "4",
            "statement": "全键盘主流程通过",
            "evidence": "keyboard_e2e.py 纯键盘完成导航、搜索、发起分析、任务、报告、设置分组与日志重试",
            "passed": ok("suite keyboard"),
        },
    ]

    total_checks = sum(item["checks"] or 0 for item in suite_results.values())
    evidence = {
        "ticket": "P5-09",
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "head": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "criteria": criteria,
        "gates": gates,
        "axe": {
            "version": suite_results.get("a11y", {}).get("axe_version"),
            "pages_scanned": suite_results.get("a11y", {}).get("pages_scanned"),
            "critical": suite_results.get("a11y", {}).get("critical"),
            "serious": suite_results.get("a11y", {}).get("serious"),
        },
        "mobile": {
            "pages_measured": suite_results.get("mobile", {}).get("pages_measured"),
            "undersized": suite_results.get("mobile", {}).get("undersized"),
            "exceptions": suite_results.get("mobile", {}).get("exceptions"),
            "screenshots": suite_results.get("mobile", {}).get("screenshots"),
        },
        "legacy": {
            "python_passed": python.get("passed"),
            "python_skipped": python.get("skipped"),
            "unit_tests": front.get("unit", {}).get("tests"),
            "e2e_checks": total_checks,
            "migration_head": head,
        },
        "leftovers": [
            "R1 百度 403 风控与负缓存：独立后续票",
            "C4 旧版日志桥与外部 trade-journal 的来源校验：外部仓库 + 旧版解冻",
            "C9 市场文案位置与契约指向不一致：长期书面例外",
            "控件边框 1.52/1.79 与禁用文字 3.70/3.78 的非文本对比：P5-07 记录，axe 未报",
        ],
        "suites": suite_results,
        "regression": regressions,
        "preflight": pf,
        "seconds": round(time.monotonic() - started, 1),
    }

    failed_gates = [entry["name"] for entry in gates if not entry["passed"]]
    failed_criteria = [item["id"] for item in criteria if not item["passed"]]
    evidence["failed_gates"] = failed_gates
    evidence["failed_criteria"] = failed_criteria
    evidence["passed"] = not failed_gates and not failed_criteria

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print(
        f"{len(gates) - len(failed_gates)}/{len(gates)} gates passed, "
        f"criteria {sum(1 for item in criteria if item['passed'])}/4 true, "
        f"evidence {EVIDENCE.relative_to(ROOT)}",
        flush=True,
    )
    print(json.dumps({key: evidence[key] for key in (
        "ticket", "passed", "criteria", "failed_gates", "failed_criteria",
        "axe", "mobile", "legacy", "seconds",
    )}, ensure_ascii=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
