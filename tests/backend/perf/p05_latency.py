"""P05 measurement for the P1 job kernel (server side only).

``perf-template.md`` defines P05 as "event written to the UI is visible within
500ms" plus "the gap between a stage's done and the next stage's started stays
within 5% of the stage's real duration". P1 has no UI, so this module measures
the server-side proxy of the first part (commit -> SSE frame readable) and
measures the second part in-process at the executor hook boundary, because job
timestamps are second-precision and cannot resolve sub-second gaps.

The fake graph reports virtual 30-minute stage durations; they are never used
here (perf-template section 4 forbids it). ``PacedExecutor`` sleeps for real and
reports the measured duration instead.

Usage (writes a perf-result-v1 copy, leaving unmeasured metrics null):
    .venv/Scripts/python.exe tests/backend/perf/p05_latency.py \
        --template docs/upgrade/fake-graph/perf-result-template.json \
        --out docs/upgrade/reviews/2026-11-05_P1-13性能结果.json

Scope: a temp database and temp report root under the system temp dir; nothing
under ``~/.tradingagents`` is read or written.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.models.stage import STAGE_IDS  # noqa: E402
from backend.app.services.analysis_runner import (  # noqa: E402
    RunResult,
    RunStats,
    StageProgress,
)
from backend.app.services.event_log import append_event  # noqa: E402
from backend.app.services.event_stream import EventStream  # noqa: E402
from backend.app.services.job_service import JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402

TODAY = "2026-10-30"
CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}
SERVER_CONFIG = ServerConfig(
    graph_version="graph-v1",
    llm_profiles=("deepseek-default",),
    parallel_analysts=True,
    stage_toggles={"policy": True, "hot_money": True, "lockup": True},
    write_mode="next",
)
LATENCY_BUDGET_MS = 500.0
STAGE_GAP_BUDGET_PERCENT = 5.0


def alembic_config() -> Config:
    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    return cfg


def build_env(directory: Path) -> SimpleNamespace:
    """Temp DB + temp report root + a real-clock service; no HTTP layer."""
    db_path = directory / "jobs" / "jobs.db"
    os.environ[JOBS_DB_ENV] = str(db_path)
    command.upgrade(alembic_config(), "head")
    engine = build_engine(db_path)
    reports = ReportStore(directory / "reports")
    jobs = JobService(engine, SERVER_CONFIG, reports=reports)
    stream = EventStream(jobs, poll_interval=0.005, heartbeat_interval=60.0)
    return SimpleNamespace(
        db_path=db_path,
        engine=engine,
        jobs=jobs,
        reports=reports,
        stream=stream,
        lease=lambda **kwargs: LeaseService(engine, **kwargs),
        dispose=lambda: engine.dispose(),
    )


def create_job(env, ticker: str = "000629") -> str:
    outcome = env.jobs.create_job(
        {"ticker": ticker, "analysis_date": TODAY, "config": dict(CONFIG)},
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def run_job(env, executor) -> None:
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner="perf-worker",
        executor=executor,
        reconcile_on_start=False,
    )
    assert worker.acquire() is True
    try:
        assert worker.run_once() is not None
    finally:
        worker.shutdown()


class PacedExecutor:
    """Sleeps for real and records gaps around the worker's stage writes.

    ``gaps_ms`` is the full server-side inter-stage latency: from the moment a
    stage's work ends (just before its ``done`` hook) until the next stage's
    ``started`` hook has returned. That interval contains both stage writes,
    the stats event and the boundary check, so it is what the template means by
    "previous done -> next started" without relying on second-precision job
    timestamps.
    """

    name = "paced"

    def __init__(self, per_stage_ms: float = 500.0) -> None:
        self._per_stage_s = per_stage_ms / 1000
        self.durations_ms: list[float] = []
        self.gaps_ms: list[float] = []

    def run(self, request, *, on_stage=None, on_chunk=None) -> RunResult:
        total = len(STAGE_IDS)
        start = 0
        if request.resume_from_stage is not None:
            start = STAGE_IDS.index(request.resume_from_stage)
        previous_done: float | None = None
        for index, stage_id in enumerate(STAGE_IDS, 1):
            if index <= start:
                continue
            if on_stage is not None:
                on_stage(
                    StageProgress(
                        stage_id=stage_id,
                        stage_name=stage_id,
                        phase="started",
                        index=index,
                        total=total,
                    )
                )
            if previous_done is not None:
                self.gaps_ms.append((time.perf_counter() - previous_done) * 1000)
            began = time.perf_counter()
            time.sleep(self._per_stage_s)
            duration_ms = (time.perf_counter() - began) * 1000
            self.durations_ms.append(duration_ms)
            previous_done = time.perf_counter()
            if on_stage is not None:
                on_stage(
                    StageProgress(
                        stage_id=stage_id,
                        stage_name=stage_id,
                        phase="done",
                        index=index,
                        total=total,
                        report_text=f"# {stage_id}\n",
                        duration_ms=int(duration_ms),
                    )
                )
        return RunResult(
            signal="Hold",
            stats=RunStats(),
            stages_completed=STAGE_IDS[start:],
            last_chunk={},
        )


def measure_event_latency(env, *, samples: int = 5) -> dict[str, object]:
    """Commit -> frame readable by an already-following reader, in ms.

    The reader thread is already blocked in the stream's poll loop when the
    writer commits, so the interval includes the rest of the 5ms poll sleep
    plus the query/decode; it excludes HTTP write and any UI rendering.
    """
    job_id = create_job(env)
    job = env.jobs.get_job(job_id)
    assert job is not None
    frames = env.stream.subscribe(job)
    next(frames)  # retry
    next(frames)  # snapshot

    latencies: list[float] = []
    write_ms: list[float] = []
    for probe in range(samples):
        box: dict[str, object] = {}

        def _read() -> None:
            box["frame"] = next(frames)

        reader = threading.Thread(target=_read, daemon=True)
        reader.start()
        time.sleep(0.001)  # let the reader enter the poll loop
        began = time.perf_counter()
        with Session(env.engine) as session:
            append_event(
                session,
                job_id=job_id,
                event_type="stage_changed",
                payload={"probe": probe},
                created_at=env.jobs.now().isoformat(timespec="seconds"),
            )
            session.commit()
        committed = time.perf_counter()
        reader.join(timeout=2)
        received = time.perf_counter()
        assert not reader.is_alive(), "SSE reader did not see the event"
        assert "event: stage_changed" in box["frame"]
        write_ms.append((committed - began) * 1000)
        latencies.append((received - committed) * 1000)
    frames.close()
    return {
        "job_id": job_id,
        "latency_samples_ms": latencies,
        "write_samples_ms": write_ms,
    }


def measure_stage_gaps(env, *, per_stage_ms: float = 500.0) -> dict[str, object]:
    """Gap between a stage's done write and the next started write."""
    job_id = create_job(env, ticker="600519")
    executor = PacedExecutor(per_stage_ms)
    run_job(env, executor)
    deviations = [
        gap / duration * 100
        for gap, duration in zip(executor.gaps_ms, executor.durations_ms)
        if duration > 0
    ]
    return {
        "job_id": job_id,
        "gap_samples_ms": executor.gaps_ms,
        "duration_samples_ms": executor.durations_ms,
        "deviation_samples_percent": deviations,
    }


def measure(per_stage_ms: float = 500.0) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="p1-13-p05-") as tmp:
        env = build_env(Path(tmp))
        try:
            latency = measure_event_latency(env)
            gaps = measure_stage_gaps(env, per_stage_ms=per_stage_ms)
        finally:
            env.dispose()
    return {"latency": latency, "gaps": gaps}


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_result(template: dict, measurement: dict, *, commit: str) -> dict:
    result = json.loads(json.dumps(template))
    latency = measurement["latency"]
    gaps = measurement["gaps"]
    latency_median = statistics.median(latency["latency_samples_ms"])
    deviation_median = statistics.median(gaps["deviation_samples_percent"])

    result["run"].update(
        {
            "run_id": f"perf-{datetime.now():%Y%m%d}-01",
            "date": f"{datetime.now():%Y-%m-%d}",
            "commit": commit,
            "operator": "qoder-agent",
            "notes": (
                "P1 只有服务端，没有界面，本文件按 P1-13 交接卡的口径填 P05："
                "P05-a 测 append_event 提交到已订阅 SSE 帧可读的延迟（不含网络、"
                "前端渲染，以及服务端 5ms 轮询上界）；P05-b 在执行器钩子边界测"
                "前一阶段结束到下一阶段 started 写入返回的间隔（任务时间戳只有"
                "秒级精度，测不了亚秒间隔）。P01-P04、P06-P08 需要网页与 PDF "
                "导出器，P1 未实现，按模板第 4 节填 null；P05 未达标时 verdict "
                "记 fail，否则记 baseline_only。假图的虚拟 30 分钟时长未用于任何指标；"
                "P05-b 的 500ms 阶段用真实 sleep 计时。"
            ),
        }
    )
    result["method"] = {
        "script": "tests/backend/perf/p05_latency.py",
        "measurement": "server-side proxy; P1 has no DOM, so no silence window",
        "dom_silence_ms": None,
        "rerun_buffer_ms": None,
        "first_screen_silence_ms": None,
        "samples_per_metric": 5,
        "statistic": "median",
        "stage_length_ms": 500,
    }
    result["environment"].update(
        {
            "python": platform.python_version(),
            "streamlit": None,
            "browser": None,
            "os": platform.platform(),
            "port": None,
        }
    )
    cases = result["metrics"]["P05"]["cases"]
    cases[0].update(
        {
            "name": "事件产生到 SSE 帧可读（P1 无界面，服务端代理）",
            "samples": [int(round(value)) for value in latency["latency_samples_ms"]],
            "median": int(round(latency_median)),
            "pass": latency_median <= LATENCY_BUDGET_MS,
        }
    )
    cases[1].update(
        {
            "samples": [
                round(value, 3) for value in gaps["deviation_samples_percent"]
            ],
            "median": round(deviation_median, 3),
            "pass": deviation_median <= STAGE_GAP_BUDGET_PERCENT,
        }
    )
    for metric_id in result["metrics"]:
        if metric_id != "P05":
            result["metrics"][metric_id] = None

    regressions = [
        case["id"]
        for metric in result["metrics"].values()
        if metric is not None
        for case in metric.get("cases", [])
        if case.get("pass") is False
    ]
    result["regressions"] = regressions
    result["verdict"] = "fail" if regressions else "baseline_only"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template",
        type=Path,
        default=ROOT / "docs" / "upgrade" / "fake-graph" / "perf-result-template.json",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-stage-ms", type=float, default=500.0)
    args = parser.parse_args(argv)

    measurement = measure(per_stage_ms=args.per_stage_ms)
    template = json.loads(args.template.read_text(encoding="utf-8"))
    result = build_result(template, measurement, commit=_git_commit())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "P05-a median %.1f ms, P05-b median %.2f%%, wrote %s"
        % (
            statistics.median(measurement["latency"]["latency_samples_ms"]),
            statistics.median(measurement["gaps"]["deviation_samples_percent"]),
            args.out,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
