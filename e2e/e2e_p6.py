"""P6-07: one entry point for the P6 exit walkthrough.

Builds and measures the frontend once, runs the full Python suite once, then the
P2/P3/P4 aggregators with ``--skip-build`` (P4 also with ``--skip-python-full``),
the P5 aggregator with all four skips, the four P6 scenarios, the three
performance lines, the migration head, the legacy smoke and the P0 preflight.
Every gate records its command, exit code and key numbers; the evidence JSON
lands under ``docs/upgrade/reviews/`` and the script exits non-zero on failure.

    "C:/Users/zhzsh/AppData/Local/Programs/Python/Python313/python.exe" \
        e2e/e2e_p6.py

P6 scenarios (temp roots, fake executor, no real model calls):
01 next writer creates a job (201);
02 legacy refuses a new key (409 write_mode_legacy) but replays the key created
   under next (200, same job);
03 ``stack_launch.py`` starts what ``.env.stack`` says and ``stack_mode.py
   status`` agrees (exit 0);
04 the legacy app starts on 8501 with 8600 closed and reads a projected report.

The P2/P3/P4 children build their own frontend unless told not to; passing
``--skip-build`` makes P4's own criterion 4 fail by design, so this aggregate
accepts exactly that one failure for P4 and judges the build through its own
single build gate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
E2E = ROOT / "e2e"
SHOTS = ROOT / "ui_shots_p6" / "P6-07"
LOGS = SHOTS / "logs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SYSTEM = Path(sys.executable)
STACK_FILE = ROOT / ".env.stack"
REVIEWS = ROOT / "docs" / "upgrade" / "reviews"
EVIDENCE = REVIEWS / "2026-11-08_P6出口证据.json"
DRILL_EVIDENCE = REVIEWS / "2026-11-08_P6-07回滚演练.json"
CANARY_EVIDENCE = REVIEWS / "2026-11-07_P6-04aCanary结果.json"
OBSERVATION_EVIDENCE = REVIEWS / "2026-11-08_P6-04b观察结论.json"

ENTRY_BUDGET_KB = 202.45
ROUTE_CHUNK_LIMIT_KB = 60.0
EXPECTED_ROUTE_CHUNKS = 11
UNIT_FILES_FLOOR = 38
UNIT_TESTS_FLOOR = 527
PYTHON_FULL_FLOOR = 832
PYTHON_SKIPPED = 4
MIGRATION_HEAD = "0007"
PREFLIGHT_ITEMS = 10
PERF_SAMPLES = 20

# The floors are the check counts each child reports with ``--skip-build``:
# P3 drops its 4 build/preview checks (19 -> 15), P4 drops its 5 (26 -> 21);
# the aggregate's own build gate judges the bundle once for all of them.
REGRESSION = (
    ("p2", "e2e_p2.py", ["--skip-build"], 102),
    ("p3", "e2e_p3.py", ["--skip-build"], 15),
    ("p4", "e2e_p4.py", ["--skip-build", "--skip-python-full"], 21),
)
P5_ARGS = ("--skip-build", "--skip-python", "--skip-regression", "--skip-preflight")

LEGACY_PORT = 8501
BACKEND_PORT = 8600
PREVIEW_PORT = 5173
SMOKE_PORT = 8599

# Child suites refresh these tracked files; the preflight's clean-worktree check
# only means something if they are back at HEAD before it runs.
GENERATED_BY_CHILDREN = (
    "docs/upgrade/reviews/2026-11-06_P3-09性能结果.json",
    "docs/upgrade/reviews/2026-11-07_P5-08可访问性与移动结果.json",
    "docs/upgrade/reviews/2026-11-07_P5出口证据.json",
)

gates: list[dict[str, Any]] = []
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return ANSI.sub("", text or "")


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
    print(f"{'PASS' if passed else 'FAIL'} {name}: {value} (expected {expected})", flush=True)
    return bool(passed)


def node() -> str:
    found = shutil.which("node")
    if found is None:
        raise SystemExit("node executable not found on PATH")
    return found


def run(
    label: str,
    command: list[str],
    cwd: Path = ROOT,
    timeout: int = 2400,
    env: dict[str, str] | None = None,
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
        env=env,
    )
    seconds = round(time.monotonic() - started, 1)
    (LOGS / f"{label}.log").write_text(
        f"$ {' '.join(command)}\n\n{proc.stdout or ''}\n--- stderr ---\n{proc.stderr or ''}",
        encoding="utf-8",
    )
    return proc, seconds


def run_node(label: str, script: str, *args: str) -> tuple[subprocess.CompletedProcess[str], float]:
    return run(label, [node(), script, *args], cwd=FRONTEND)


def parse_last_json(stdout: str) -> dict[str, Any]:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def stage(name: str, fn: Any, default: Any) -> Any:
    """One crashed stage must still leave the evidence file and a non-zero exit."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - recorded as a failed gate
        gate(name, name, f"{type(exc).__name__}: {exc}", "no exception", False)
        return default


# --- single frontend build -------------------------------------------------


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
    text = plain((unit.stdout or "") + (unit.stderr or ""))
    files = re.search(r"Test Files\s+(\d+)\s+passed", text)
    tests = re.search(r"Tests\s+(\d+)\s+passed", text)
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
    gate(
        "build",
        "cd frontend && node node_modules/vite/bin/vite.js build",
        "exit",
        0,
        build.returncode == 0,
        build.returncode,
        seconds,
    )

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


# --- python and the P2..P5 children ---------------------------------------


def python_full() -> dict[str, Any]:
    full, seconds = run("pytest_full", [str(PYTHON), "-m", "pytest", "-q"])
    text = plain(full.stdout or "")
    passed_match = re.search(r"(\d+) passed", text)
    skipped_match = re.search(r"(\d+) skipped", text)
    passed = int(passed_match.group(1)) if passed_match else 0
    skipped = int(skipped_match.group(1)) if skipped_match else 0
    ok = (
        full.returncode == 0
        and passed >= PYTHON_FULL_FLOOR
        and skipped == PYTHON_SKIPPED
    )
    gate(
        "python full",
        ".venv/Scripts/python.exe -m pytest -q",
        f"{passed} passed / {skipped} skipped",
        f">= {PYTHON_FULL_FLOOR} passed / {PYTHON_SKIPPED} skipped",
        ok,
        full.returncode,
        seconds,
    )
    return {"passed": passed, "skipped": skipped, "ok": ok}


def p4_passed(returncode: int, payload: dict[str, Any], floor: int) -> bool:
    """--skip-build empties P4's bundle block, so its own criterion 4 fails by
    design; the aggregate judges the build once in ``frontend_chain`` and only
    tolerates exactly that one failure."""
    failures = payload.get("failures") or []
    criteria = payload.get("criteria") or {}
    tolerated = set(failures) == {"exit criterion 4"} and not payload.get("bundle")
    return (
        (returncode == 0 or tolerated)
        and (payload.get("checks") or 0) >= floor
        and all(criteria.get(key) for key in ("1", "2", "3"))
        and bool((payload.get("route_switch") or {}).get("passed"))
        and bool((payload.get("perf") or {}).get("passed"))
    )


def regression() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, script, args, floor in REGRESSION:
        proc, seconds = run(name, [str(SYSTEM), str(E2E / script), *args])
        payload = parse_last_json(proc.stdout or "")
        failures = payload.get("failures") or []
        checks = payload.get("checks") or 0
        criteria = payload.get("criteria") or {}

        if name == "p4":
            ok = p4_passed(proc.returncode, payload, floor)
            value = (
                f"{checks} checks, {len(failures)} failures, "
                f"criteria {criteria}, route_switch "
                f"{payload.get('route_switch', {}).get('passed')}"
            )
            expected = (
                f">= {floor} checks; criteria 1-3 true; only 'exit criterion 4' "
                "may fail (build gate is the aggregate's)"
            )
        elif name == "p3":
            ok = (
                proc.returncode == 0
                and checks >= floor
                and not failures
                and all(criteria.values())
            )
            value = f"{checks} checks, {len(failures)} failures, criteria {criteria}"
            expected = f">= {floor} checks, 0 failures, all criteria true"
        else:
            ok = proc.returncode == 0 and checks >= floor and not failures
            value = f"{checks} checks, {len(failures)} failures"
            expected = f">= {floor} checks, 0 failures"

        gate(
            f"regression {name}",
            f"python e2e/{script} {' '.join(args)}".strip(),
            value,
            expected,
            ok,
            proc.returncode,
            seconds,
        )
        if failures:
            print(f"  {name} failures: {failures[:3]}", flush=True)
        out[name] = {
            "script": f"e2e/{script}",
            "args": args,
            "checks": checks,
            "failures": failures,
            "criteria": criteria,
            "passed": ok,
        }
    return out


def p5_aggregate() -> dict[str, Any]:
    # The child's printed summary omits the gates array; only the evidence file
    # it rewrites has it, so trust the file only when this run actually wrote it.
    p5_file = REVIEWS / "2026-11-07_P5出口证据.json"
    before = p5_file.stat().st_mtime_ns if p5_file.exists() else 0
    proc, seconds = run("p5", [str(SYSTEM), str(E2E / "e2e_p5.py"), *P5_ARGS])
    payload = parse_last_json(proc.stdout or "")
    doc: dict[str, Any] = {}
    if p5_file.exists() and p5_file.stat().st_mtime_ns != before:
        doc = json.loads(p5_file.read_text(encoding="utf-8"))
    gate_entries = doc.get("gates") or []
    failed_gates = doc.get("failed_gates") or payload.get("failed_gates") or []
    criteria = doc.get("criteria") or payload.get("criteria") or []
    failed_criteria = set(
        doc.get("failed_criteria", payload.get("failed_criteria") or [])
    )
    # P5's criterion 1 also cites the P2 regression, which the four skips omit
    # here; this aggregate runs P2 itself, so criterion 1 may stay false.
    tolerated = failed_criteria <= {"1"}
    suite_gates_ok = (
        len(gate_entries) >= 8
        and not failed_gates
        and all(entry.get("passed") for entry in gate_entries)
    )
    ok = suite_gates_ok and tolerated and proc.returncode in (0, 1)
    gate(
        "p5 aggregate",
        f"python e2e/e2e_p5.py {' '.join(P5_ARGS)}",
        f"exit {proc.returncode}, passed={doc.get('passed', payload.get('passed'))}, "
        f"gates={len(gate_entries)}, failed={failed_gates}, "
        f"failed criteria={sorted(failed_criteria)}",
        "8 suite gates green, no failed gate; only criterion 1 (P2 half skipped)",
        ok,
        proc.returncode,
        seconds,
    )
    return {
        "checks": sum(
            (entry.get("checks") or 0)
            for entry in ((doc.get("suites") or payload.get("suites") or {}).values())
        ),
        "gates": len(gate_entries),
        "criteria": sum(1 for item in criteria if item.get("passed")),
        "failed_gates": failed_gates,
        "passed": ok,
    }


# --- P6 scenarios ----------------------------------------------------------


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(port: int, want: bool = True, timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port) == want:
            return True
        time.sleep(0.3)
    return port_open(port) == want


def fetch_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_job(key: str, ticker: str = "000629") -> tuple[int, dict[str, Any]]:
    import urllib.error

    body = {
        "ticker": ticker,
        "analysis_date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
        "config": {
            "llm_profile": "deepseek-default",
            "parallel_analysts": True,
            "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
        },
    }
    request = urllib.request.Request(
        f"http://127.0.0.1:{BACKEND_PORT}/api/v1/jobs",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Idempotency-Key", key)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        return exc.code, json.loads(raw) if raw else {}


def isolated_env(root: Path, home: Path, *, mode: str | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ACTIVE_ANALYSIS_UI", None)
    env.pop("TA_ENABLE_REAL_RUNNER", None)
    env["TA_DATA_ROOT"] = str(root)
    env["TRADINGAGENTS_RESULTS_DIR"] = str(root / "logs")
    env["TRADINGAGENTS_CACHE_DIR"] = str(root / "cache")
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    # The legacy app is started and stopped inside the scenarios; never pop a tab.
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["BROWSER"] = "none"
    # Offline determinism: RPT-01 chart capture would time out without a network.
    env["TA_CHART_SNAPSHOT"] = "0"
    if mode:
        env["ACTIVE_ANALYSIS_UI"] = mode
    return env


def start_process(label: str, command: list[str], env: dict[str, str]) -> subprocess.Popen:
    LOGS.mkdir(parents=True, exist_ok=True)
    handle = open(LOGS / f"{label}.log", "wb")
    return subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )


def stop_process(proc: subprocess.Popen, ports: tuple[int, ...]) -> None:
    if proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    for port in ports:
        wait_port(port, False, 20)


def stack_mode_value() -> str:
    if not STACK_FILE.exists():
        return "legacy"
    for line in STACK_FILE.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == "ACTIVE_ANALYSIS_UI":
            return value.strip() or "legacy"
    return "legacy"


def scenario_01(temp: Path) -> dict[str, Any]:
    root, home = temp / "data", temp / "home"
    (home / ".streamlit").mkdir(parents=True, exist_ok=True)
    (home / ".streamlit" / "credentials.toml").write_text(
        "[general]\nemail = \"\"\n", encoding="utf-8"
    )
    proc = start_process(
        "e2e01-backend",
        [str(PYTHON), "scripts/run_backend.py", "--port", str(BACKEND_PORT)],
        isolated_env(root, home, mode="next"),
    )
    try:
        if not wait_port(BACKEND_PORT):
            raise RuntimeError("8600 did not start")
        meta = fetch_json(f"http://127.0.0.1:{BACKEND_PORT}/api/v1/meta/options")
        key = str(uuid.uuid4())
        status, body = post_job(key)
        return {
            "write_mode": meta.get("write_mode"),
            "contract_version": meta.get("contract_version"),
            "status": status,
            "job_id": body.get("job_id"),
            "key": key,
            "passed": (
                meta.get("write_mode") == "next"
                and meta.get("contract_version") == "api-v1"
                and status == 201
                and bool(body.get("job_id"))
            ),
        }
    finally:
        stop_process(proc, (BACKEND_PORT,))


def scenario_02(temp: Path, first: dict[str, Any]) -> dict[str, Any]:
    root, home = temp / "data", temp / "home"
    proc = start_process(
        "e2e02-backend",
        [str(PYTHON), "scripts/run_backend.py", "--port", str(BACKEND_PORT)],
        isolated_env(root, home, mode="legacy"),
    )
    try:
        if not wait_port(BACKEND_PORT):
            raise RuntimeError("8600 did not start")
        meta = fetch_json(f"http://127.0.0.1:{BACKEND_PORT}/api/v1/meta/options")
        # A different ticker keeps the new key clear of the same-config active
        # job that scenario 01 left behind; only the replay carries key 01.
        new_status, refused = post_job(str(uuid.uuid4()), ticker="600519")
        replay_status, replayed = post_job(first["key"])
        return {
            "write_mode": meta.get("write_mode"),
            "new_key": {
                "status": new_status,
                "code": (refused.get("error") or {}).get("code"),
            },
            "replay": {
                "status": replay_status,
                "job_id": replayed.get("job_id"),
                "same_job": replayed.get("job_id") == first.get("job_id"),
            },
            "passed": (
                meta.get("write_mode") == "legacy"
                and new_status == 409
                and (refused.get("error") or {}).get("code") == "write_mode_legacy"
                and replay_status == 200
                and replayed.get("job_id") == first.get("job_id")
            ),
        }
    finally:
        stop_process(proc, (BACKEND_PORT,))


def scenario_03(temp: Path) -> dict[str, Any]:
    root, home = temp / "data", temp / "home"
    (home / ".streamlit").mkdir(parents=True, exist_ok=True)
    (home / ".streamlit" / "credentials.toml").write_text(
        "[general]\nemail = \"\"\n", encoding="utf-8"
    )
    mode = stack_mode_value()
    proc = start_process(
        "e2e03-stack",
        [str(SYSTEM), "scripts/stack_launch.py", "--no-ui", "--no-journal"],
        isolated_env(root, home),
    )
    try:
        entry_port = BACKEND_PORT if mode == "next" else LEGACY_PORT
        up = wait_port(entry_port, True, 150)
        meta: dict[str, Any] = {}
        if mode == "next":
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if port_open(BACKEND_PORT):
                    try:
                        meta = fetch_json(
                            f"http://127.0.0.1:{BACKEND_PORT}/api/v1/meta/options", 3
                        )
                    except Exception:  # noqa: BLE001 - poll
                        meta = {}
                    if meta.get("write_mode") == mode:
                        break
                time.sleep(0.5)
        status_proc, _seconds = run(
            "e2e03-status", [str(PYTHON), "scripts/stack_mode.py", "status", "--json"]
        )
        payload = parse_last_json(status_proc.stdout or "")
        if mode == "next":
            entry_ok = (
                meta.get("write_mode") == "next"
                and payload.get("backend_listening") is True
            )
        else:
            entry_ok = (
                payload.get("backend_listening") is False
                and payload.get("legacy_listening") is True
            )
        return {
            "env_stack_mode": mode,
            "entry_port": entry_port,
            "entry_up": up,
            "meta_mode": meta.get("write_mode"),
            "status_exit": status_proc.returncode,
            "status": payload,
            "passed": (
                up
                and status_proc.returncode == 0
                and payload.get("mode") == mode
                and payload.get("consistent") is True
                and entry_ok
            ),
        }
    finally:
        # The next plan may have started the preview in older builds; tolerate
        # 5173 being cold as well as occupied by this run.
        stop_process(proc, (BACKEND_PORT, LEGACY_PORT, PREVIEW_PORT))


def scenario_04(temp: Path) -> dict[str, Any]:
    root, home = temp / "data", temp / "home"
    (home / ".streamlit").mkdir(parents=True, exist_ok=True)
    (home / ".streamlit" / "credentials.toml").write_text(
        "[general]\nemail = \"\"\n", encoding="utf-8"
    )
    proc = start_process(
        "e2e04-legacy",
        [str(PYTHON), "web/launch.py"],
        isolated_env(root, home),
    )
    try:
        if not wait_port(LEGACY_PORT, True, 150):
            raise RuntimeError("8501 did not start")
        healthy = False
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{LEGACY_PORT}/_stcore/health", timeout=2
                ) as response:
                    healthy = response.read().strip() == b"ok"
                    if healthy:
                        break
            except Exception:  # noqa: BLE001 - poll
                time.sleep(0.5)
        projection, seconds = run("e2e04-projection", [str(SYSTEM), "e2e/legacy_projection_e2e.py"])
        text = plain(projection.stdout or "")
        match = re.search(r"(\d+) checks?, (\d+) failures?", text)
        checks = int(match.group(1)) if match else 0
        failures = int(match.group(2)) if match else 99
        return {
            "health": healthy,
            "8600": port_open(BACKEND_PORT),
            "projection": {
                "exit": projection.returncode,
                "checks": checks,
                "failures": failures,
                "seconds": seconds,
            },
            "passed": (
                healthy
                and not port_open(BACKEND_PORT)
                and projection.returncode == 0
                and failures == 0
                and checks > 0
            ),
        }
    finally:
        stop_process(proc, (LEGACY_PORT,))


def p6_scenarios() -> dict[str, Any]:
    outcomes: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="astock-e2e-p6-") as raw:
        temp = Path(raw)
        first: dict[str, Any] = {}

        for label, runner in (
            ("p6 e2e 01", lambda: scenario_01(temp)),
        ):
            started = time.monotonic()
            outcome = runner()
            first = outcome
            gate(
                label,
                "run_backend.py (ACTIVE_ANALYSIS_UI=next) + POST /api/v1/jobs",
                f"write_mode={outcome.get('write_mode')}, POST {outcome.get('status')}, "
                f"job={outcome.get('job_id')}",
                "write_mode=next, 201 with job_id",
                outcome["passed"],
                0,
                round(time.monotonic() - started, 1),
            )
            outcomes["01"] = outcome

        started = time.monotonic()
        outcome = scenario_02(temp, first)
        gate(
            "p6 e2e 02",
            "run_backend.py (legacy) + new key then replay",
            f"mode={outcome.get('write_mode')}, new={outcome.get('new_key')}, "
            f"replay={outcome.get('replay')}",
            "409 write_mode_legacy on a new key; 200 same job on replay",
            outcome["passed"],
            0,
            round(time.monotonic() - started, 1),
        )
        outcomes["02"] = outcome

    for label, runner in (
        ("p6 e2e 03", scenario_03),
        ("p6 e2e 04", scenario_04),
    ):
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="astock-e2e-p6-") as raw:
            outcome = runner(Path(raw))
        if label.endswith("03"):
            value = (
                f"mode={outcome.get('env_stack_mode')}, meta={outcome.get('meta_mode')}, "
                f"status exit {outcome.get('status_exit')}, "
                f"consistent={outcome.get('status', {}).get('consistent')}"
            )
            expected = "stack_launch follows .env.stack; status exit 0 and consistent"
        else:
            value = (
                f"8501 health={outcome.get('health')}, 8600={outcome.get('8600')}, "
                f"projection {outcome.get('projection')}"
            )
            expected = "8501 health ok, 8600 closed, projection suite green"
        gate(
            label,
            "stack_launch.py + stack_mode.py status" if label.endswith("03") else "web/launch.py + legacy_projection_e2e.py",
            value,
            expected,
            outcome["passed"],
            0,
            round(time.monotonic() - started, 1),
        )
        outcomes[label[-2:]] = outcome
    return outcomes


# --- performance, migrations, smoke, preflight -----------------------------


def performance(temp: Path) -> dict[str, Any]:
    out = temp / "perf.json"
    # Playwright only lives in the system Python 3.13 (P6-05 ticket).
    proc, seconds = run(
        "perf_core",
        [str(SYSTEM), "scripts/perf_core.py", "--no-build", "--samples", str(PERF_SAMPLES), "--out", str(out)],
        timeout=1800,
    )
    doc: dict[str, Any] = {}
    if out.exists():
        doc = json.loads(out.read_text(encoding="utf-8"))
    # perf_core appends one record per run; --out is a fresh file each time.
    run_doc = (doc.get("runs") or [{}])[-1]
    metrics = run_doc.get("metrics") or {}
    summary = {
        viewport: {
            key: (entry or {}).get("p75")
            for key, entry in (metrics.get(viewport) or {}).items()
        }
        for viewport in ("mobile", "desktop")
    }
    conclusion = run_doc.get("conclusion")
    ok = proc.returncode == 0 and conclusion == "pass"
    gate(
        "perf lcp/cls/inp",
        f"python scripts/perf_core.py --no-build --samples {PERF_SAMPLES}",
        f"conclusion={conclusion}, p75 {summary}",
        "conclusion pass (all p75 below the regression lines)",
        ok,
        proc.returncode,
        seconds,
    )
    return {"conclusion": conclusion, "p75": summary, "passed": ok}


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


def legacy_smoke() -> dict[str, Any]:
    started = time.monotonic()
    LOGS.mkdir(parents=True, exist_ok=True)
    log = (LOGS / "legacy_smoke.log").open("wb")
    proc = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "streamlit",
            "run",
            str(ROOT / "web" / "app.py"),
            "--server.headless",
            "true",
            "--server.port",
            str(SMOKE_PORT),
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    healthy = False
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{SMOKE_PORT}/_stcore/health", timeout=2
                ) as response:
                    if response.read().strip() == b"ok":
                        healthy = True
                        break
            except Exception:  # noqa: BLE001 - poll
                time.sleep(1)
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False
        )
        log.close()
    seconds = round(time.monotonic() - started, 1)
    gate(
        "legacy smoke",
        f".venv/Scripts/python.exe -m streamlit run web/app.py --server.port {SMOKE_PORT}",
        f"health {'ok' if healthy else 'missing'}",
        "Streamlit health ok on 8599",
        healthy,
        0,
        seconds,
    )
    return {"healthy": healthy, "seconds": seconds}


def restore_generated() -> list[str]:
    restored: list[str] = []
    for path in GENERATED_BY_CHILDREN:
        changed = (
            subprocess.run(
                ["git", "diff", "--quiet", "--", path], cwd=ROOT, capture_output=True
            ).returncode
            != 0
        )
        if changed:
            subprocess.run(["git", "checkout", "--", path], cwd=ROOT, check=True)
            restored.append(path)
    gate(
        "restore child evidence",
        "git checkout -- <P3-09 / P5-08 / P5 exit evidence>",
        f"restored {restored}" if restored else "nothing modified",
        "tracked evidence back to HEAD",
        True,
    )
    return restored


def preflight() -> dict[str, Any]:
    proc, seconds = run(
        "preflight", [str(PYTHON), "scripts/p0_preflight.py", "--full", "--smoke"]
    )
    text = plain(proc.stdout or "")
    counts = re.search(r"通过 (\d+)，失败 (\d+)", text)
    passed = int(counts.group(1)) if counts else 0
    failed = int(counts.group(2)) if counts else 99
    ok = proc.returncode == 0 and passed == PREFLIGHT_ITEMS and failed == 0
    smoke = "健康检查 ok" in text
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


# --- committed exit evidence ----------------------------------------------


def rollback_evidence() -> dict[str, Any]:
    doc: dict[str, Any] = {}
    if DRILL_EVIDENCE.exists():
        doc = json.loads(DRILL_EVIDENCE.read_text(encoding="utf-8"))
    steps = doc.get("steps") or []
    rollback = doc.get("rollback") or []
    swap_ok = len(steps) >= 16 and all(item.get("pass") for item in steps)
    rollback_ok = len(rollback) >= 9 and all(item.get("pass") for item in rollback)
    ok = doc.get("conclusion") == "pass" and swap_ok and rollback_ok
    value = (
        f"conclusion={doc.get('conclusion')}, swap {sum(1 for s in steps if s.get('pass'))}/{len(steps)}, "
        f"rollback {sum(1 for s in rollback if s.get('pass'))}/{len(rollback)}, "
        f"head={doc.get('repo_head', '')[:8]}"
    )
    gate(
        "rollback drill",
        f"python {DRILL_EVIDENCE.name} (D0..D15 + R0..R8)",
        value,
        "conclusion pass; every swap and rollback step green",
        ok,
    )
    return {
        "file": str(DRILL_EVIDENCE.relative_to(ROOT)).replace("\\", "/"),
        "conclusion": doc.get("conclusion"),
        "swap_steps": len(steps),
        "rollback_steps": len(rollback),
        "drilled_at": doc.get("drilled_at"),
        "repo_head": doc.get("repo_head"),
        "passed": ok,
    }


def canary_evidence() -> dict[str, Any]:
    doc = json.loads(CANARY_EVIDENCE.read_text(encoding="utf-8"))
    acceptance = doc.get("acceptance") or {}
    ok = (
        doc.get("verdict") == "pass"
        and acceptance.get("single_run") is True
        and acceptance.get("replay_same_job") is True
        and acceptance.get("replay_stats_unchanged") is True
        and acceptance.get("replay_jobs_unchanged") is True
        and acceptance.get("replay_llm_calls") == 0
        and bool(doc.get("report", {}).get("content_hash"))
    )
    gate(
        "canary evidence",
        f"read {CANARY_EVIDENCE.name}",
        f"verdict={doc.get('verdict')}, replay_llm_calls={acceptance.get('replay_llm_calls')}, "
        f"job={doc.get('job_id')}",
        "verdict pass; replay makes no model call and keeps stats/job rows",
        ok,
    )
    return {
        "file": str(CANARY_EVIDENCE.relative_to(ROOT)).replace("\\", "/"),
        "job_id": doc.get("job_id"),
        "model_calls": (doc.get("stats") or {}).get("model_calls"),
        "replay_llm_calls": acceptance.get("replay_llm_calls"),
        "passed": ok,
    }


def observation_evidence() -> dict[str, Any]:
    doc = json.loads(OBSERVATION_EVIDENCE.read_text(encoding="utf-8"))
    ok = (
        (doc.get("anomalies") or 0) == 0
        and doc.get("report_hash_stable") is True
        and doc.get("no_auto_rerun") is True
        and (doc.get("days") or 0) >= 7
    )
    gate(
        "observation evidence",
        f"read {OBSERVATION_EVIDENCE.name}",
        f"days={doc.get('days')}, runs={len(doc.get('jobs') or [])}, "
        f"anomalies={doc.get('anomalies')}, deviation={bool(doc.get('deviation'))}",
        ">=7 runs; 0 anomalies; report hash stable; no auto rerun",
        ok,
    )
    return {
        "file": str(OBSERVATION_EVIDENCE.relative_to(ROOT)).replace("\\", "/"),
        "days": doc.get("days"),
        "runs": len(doc.get("jobs") or []),
        "same_day_runs": doc.get("same_day_runs"),
        "deviation": doc.get("deviation"),
        "anomalies": doc.get("anomalies"),
        "pending_checks": doc.get("pending_checks"),
        "passed": ok,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P6-07 P6 exit acceptance")
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
        print("running the frontend build chain once...", flush=True)
        front = stage("frontend chain", lambda: frontend_chain(temp), {})

    print("running the full python suite once...", flush=True)
    python = stage("python full", python_full, {})

    print("running the P2/P3/P4 aggregators...", flush=True)
    regressions = stage("regression", regression, {})

    print("running the P5 aggregate with the four skips...", flush=True)
    p5 = stage("p5 aggregate", p5_aggregate, {})

    print("running the P6 scenarios...", flush=True)
    busy = [port for port in (LEGACY_PORT, BACKEND_PORT, 8610) if port_open(port)]
    if busy:
        gate("ports free", "netstat 8501/8600/8610", busy, "no listeners", False)
        scenarios: dict[str, Any] = {}
    else:
        scenarios = stage("p6 scenarios", p6_scenarios, {})

    print("running the performance gate...", flush=True)
    with tempfile.TemporaryDirectory() as raw:
        perf = stage("perf", lambda: performance(Path(raw)), {})

    head = stage("migration head", migrations, None)
    smoke = stage("legacy smoke", legacy_smoke, {})

    rollback = stage("rollback evidence", rollback_evidence, {})
    canary = stage("canary evidence", canary_evidence, {})
    observation = stage("observation evidence", observation_evidence, {})

    print("restoring the evidence the child suites refreshed...", flush=True)
    stage("restore child evidence", restore_generated, [])
    print("running the preflight...", flush=True)
    pf = stage("preflight", preflight, {})

    by_name = {entry["name"]: entry for entry in gates}

    def ok(name: str) -> bool:
        return bool(by_name.get(name, {}).get("passed"))

    criteria = [
        {
            "id": "1",
            "statement": "回滚演练通过（八步在副本上走通，真实目录未替换）",
            "evidence": "D0..D15 + R0..R8（含 R2b：等无在跑任务后补证 409）全绿；真实根前后 manifest 一致；R7 只在副本还原",
            "passed": (
                ok("rollback drill")
                and ok("p6 e2e 02")
                and ok("migration head")
            ),
        },
        {
            "id": "2",
            "statement": "Canary 无重复调用",
            "evidence": "P6-04a：单次真实分析 27 次调用；同键重放 0 次调用、stats 与 job 行不变",
            "passed": ok("canary evidence") and ok("p6 e2e 02"),
        },
        {
            "id": "3",
            "statement": "连续主用观察通过",
            "evidence": "P6-04b：7 次真实运行、0 异常、报告哈希稳定、无自动重跑（6 次同日为已记录偏离）",
            "passed": ok("observation evidence"),
        },
        {
            "id": "4",
            "statement": "旧版可独立启动",
            "evidence": "P6-06 D3 与 P6-07 D3/R3 均在 8600 关闭时起 8501；E2E-04 读投影报告",
            "passed": ok("p6 e2e 04") and ok("rollback drill"),
        },
    ]

    evidence = {
        "ticket": "P6-07",
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "head": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "criteria": criteria,
        "gates": gates,
        "numbers": {
            "python": python,
            "unit": front.get("unit"),
            "bundle": front.get("bundle"),
            "regression": regressions,
            "p5": p5,
            "perf": perf,
            "migration_head": head,
            "legacy_smoke": smoke,
            "preflight": pf,
        },
        "scenarios": scenarios,
        "rollback_evidence": rollback,
        "canary_evidence": canary,
        "observation_evidence": observation,
        "leftovers": [
            "R1 百度 403 风控与负缓存：真实供应商暖加载 p95 未达标，独立后续票",
            "C4 旧版日志桥 postMessage('*') 与外部 trade-journal 来源校验：外部仓库 + 旧版解冻",
        ],
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
    print(
        json.dumps(
            {
                key: evidence[key]
                for key in (
                    "ticket",
                    "passed",
                    "criteria",
                    "failed_gates",
                    "failed_criteria",
                    "numbers",
                    "seconds",
                )
            },
            ensure_ascii=True,
        )
    )
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
