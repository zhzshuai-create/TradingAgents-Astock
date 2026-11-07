"""P2-01 acceptance: the dev entry runs API and worker on one temp store.

DEV-01: a temporary database; POST /api/v1/jobs reaches succeeded with all 12
        stage files; SIGINT (CTRL_BREAK on Windows) exits cleanly.
DEV-02: the entry never creates or modifies ~/.tradingagents.
DEV-03: --no-worker leaves the job queued; a later worker run finishes it.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.models.stage import STAGE_IDS  # noqa: E402

SCRIPT = ROOT / "scripts" / "dev_backend.py"
TERMINAL_TIMEOUT = 60
CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DevServer:
    def __init__(self, proc: subprocess.Popen, port: int, root: Path) -> None:
        self.proc = proc
        self.port = port
        self.root = root
        self.base = f"http://127.0.0.1:{port}"
        self._result: tuple[int, str] | None = None
        self.session = requests.Session()
        self.session.trust_env = False

    def wait_ready(self, timeout: float = 60) -> None:
        url = f"{self.base}/api/v1/jobs/not-ready-probe"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"dev entry exited early:\n{self._drain()}")
            try:
                response = self.session.get(url, timeout=1)
            except requests.RequestException:
                time.sleep(0.1)
                continue
            if response.status_code == 404:
                return
            time.sleep(0.1)
        raise AssertionError(f"dev entry did not become ready:\n{self._drain()}")

    def create_job(self) -> str:
        response = self.session.post(
            f"{self.base}/api/v1/jobs",
            json={
                "ticker": "000629",
                "analysis_date": "2026-10-30",
                "config": dict(CONFIG),
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
            timeout=10,
        )
        assert response.status_code == 201, response.text
        return response.json()["job_id"]

    def job(self, job_id: str) -> dict:
        response = self.session.get(f"{self.base}/api/v1/jobs/{job_id}", timeout=10)
        assert response.status_code == 200, response.text
        return response.json()

    def wait_status(self, job_id: str, status: str) -> dict:
        deadline = time.monotonic() + TERMINAL_TIMEOUT
        latest: dict = {}
        while time.monotonic() < deadline:
            latest = self.job(job_id)
            if latest["status"] == status:
                return latest
            time.sleep(0.1)
        raise AssertionError(
            f"job {job_id} did not reach {status}; last={latest.get('status')}"
        )

    def stop(self) -> tuple[int, str]:
        if self._result is not None:
            return self._result
        if self.proc.poll() is not None:
            self._result = (int(self.proc.returncode), self._drain())
            return self._result
        if os.name == "nt":
            self.proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            self.proc.send_signal(signal.SIGINT)
        try:
            output, _ = self.proc.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            output, _ = self.proc.communicate(timeout=10)
            raise AssertionError(
                f"dev entry ignored the stop signal:\n{output.decode('utf-8', 'replace')}"
            ) from None
        self._result = (
            int(self.proc.returncode),
            output.decode("utf-8", "replace"),
        )
        return self._result

    def _drain(self) -> str:
        if self.proc.stdout is None:
            return ""
        try:
            return self.proc.communicate(timeout=5)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            return "<process still running>"


def _start(tmp_path: Path, *args: str, home: Path | None = None) -> DevServer:
    root = tmp_path / "devroot"
    home = home or (tmp_path / "home")
    home.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "TA_DEV_ROOT": str(root),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "ACTIVE_ANALYSIS_UI": "next",
        }
    )
    for key in (
        "TA_JOBS_DB",
        "TA_JOB_REPORTS_DIR",
        "TA_ENABLE_REAL_RUNNER",
        "TA_STARTUP_RECONCILE",
    ):
        env.pop(key, None)

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--port", str(port), *args],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    server = DevServer(proc, port, root)
    server.wait_ready()
    return server


@pytest.fixture()
def launcher(tmp_path):
    started: list[DevServer] = []

    def start(*args: str, home: Path | None = None) -> DevServer:
        server = _start(tmp_path, *args, home=home)
        started.append(server)
        return server

    yield start
    for server in reversed(started):
        server.stop()
        server.session.close()


def test_dev01_temp_run_reaches_succeeded_with_all_stage_files(launcher):
    server = launcher()
    job_id = server.create_job()
    detail = server.wait_status(job_id, "succeeded")

    assert [stage["status"] for stage in detail["stages"]] == ["done"] * len(STAGE_IDS)
    report_root = server.root / "reports" / job_id
    files = sorted(
        path.relative_to(report_root).as_posix()
        for path in report_root.glob("*/attempt-1.md")
    )
    assert set(files) == {f"{stage_id}/attempt-1.md" for stage_id in STAGE_IDS}
    assert (report_root / "report.json").is_file()
    assert (server.root / "jobs.db").is_file()

    code, output = server.stop()
    assert code == 0, output
    assert "Traceback" not in output


def test_dev02_only_the_temp_root_is_written(launcher, tmp_path):
    home = tmp_path / "home"
    tradingagents = home / ".tradingagents"
    tradingagents.mkdir(parents=True)
    sentinel = tradingagents / "jobs.db"
    sentinel.write_bytes(b"sentinel-from-before")

    server = launcher(home=home)
    job_id = server.create_job()
    server.wait_status(job_id, "succeeded")
    code, output = server.stop()
    assert code == 0, output

    assert sentinel.read_bytes() == b"sentinel-from-before"
    assert not (tradingagents / "job_reports").exists()
    assert sorted(path.name for path in tradingagents.iterdir()) == ["jobs.db"]
    assert (server.root / "jobs.db").is_file()


def test_dev03_no_worker_keeps_job_queued_until_worker_returns(launcher):
    idle = launcher("--no-worker")
    job_id = idle.create_job()
    time.sleep(1.0)
    assert idle.job(job_id)["status"] == "queued"
    assert not (idle.root / "reports" / job_id).exists()
    code, output = idle.stop()
    assert code == 0, output

    server = launcher()
    server.wait_status(job_id, "succeeded")
    code, output = server.stop()
    assert code == 0, output
