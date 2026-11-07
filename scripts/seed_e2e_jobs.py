"""Test-only seed: one job per status, with readable stage reports.

P2-10. Refuses to run unless ``TA_E2E=1`` and the database lives under the
system temp directory, because it writes jobs without going through the API.
All transitions use the service layer; the only direct write would be a
fixture, and this seed needs none.

    TA_E2E=1 TA_JOBS_DB=<temp>/jobs.db TA_JOB_REPORTS_DIR=<temp>/reports \
        .venv/Scripts/python.exe scripts/seed_e2e_jobs.py

Prints one JSON line: {"jobs": {"<status>": {"job_id": ..., "ticker": ...}}}
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import load_server_config  # noqa: E402
from backend.app.models.stage import STAGE_IDS  # noqa: E402
from backend.app.services.analysis_runner import FakeAnalysisExecutor  # noqa: E402
from backend.app.services.job_service import (  # noqa: E402
    CST,
    JobService,
    StatsSnapshot,
)
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import (  # noqa: E402
    JOB_REPORTS_ENV,
    ReportStore,
)
from backend.app.worker.main import Worker  # noqa: E402

BACKEND = ROOT / "backend"
TOTAL = len(STAGE_IDS)
SEED_OWNER = "seed-e2e"

TICKERS = {
    "queued": "600001",
    "running": "600002",
    "pause_requested": "600003",
    "paused": "600004",
    "cancel_requested": "600005",
    "cancelled": "600006",
    "succeeded": "600007",
    "failed": "600008",
    "interrupted": "600009",
}

STAGE_SUMMARY = {
    "market": "技术面：均线多头排列，量能温和放大。",
    "social": "情绪面：讨论热度回升，分歧仍在。",
    "news": "新闻面：行业政策预期改善。",
    "fundamentals": "基本面：营收与毛利率保持稳定。",
    "policy": "政策面：暂无新增限制性条款。",
    "hot_money": "资金面：龙虎榜出现游资席位。",
    "lockup": "解禁面：未来三个月无大额解禁。",
    "quality_gate": "质量门控：数据完整度满足要求。",
    "debate": "多空辩论：多方论据略占上风。",
    "trader": "交易决策：等待回踩确认后分批建仓。",
    "risk": "风控评估：单笔仓位不超过两成。",
    "pm": "最终决策：谨慎参与，设置止损。",
}


def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _temp_scoped(path: Path) -> bool:
    temp = Path(tempfile.gettempdir()).resolve()
    try:
        Path(path).resolve().relative_to(temp)
    except ValueError:
        return False
    return True


def _require_test_root() -> tuple[Path, Path]:
    if os.environ.get("TA_E2E") != "1":
        raise SystemExit("seed_e2e_jobs refuses to run without TA_E2E=1")
    db_env = os.environ.get(JOBS_DB_ENV)
    reports_env = os.environ.get(JOB_REPORTS_ENV)
    if not db_env or not reports_env:
        raise SystemExit(f"{JOBS_DB_ENV} and {JOB_REPORTS_ENV} must both be set")
    db_path = Path(db_env).expanduser()
    reports_path = Path(reports_env).expanduser()
    if not (_temp_scoped(db_path) and _temp_scoped(reports_path)):
        raise SystemExit("seed_e2e_jobs only writes under the system temp directory")
    return db_path, reports_path


def _report_text(ticker: str, stage_id: str, index: int) -> str:
    lines = [
        f"# {ticker} 阶段 {index}：{stage_id}",
        "",
        STAGE_SUMMARY[stage_id],
        "",
        "## 观察",
        "",
        "- 成交量较五日均值放大 18%",
        "- 北向资金连续两日净流入",
        "- 行业指数跑赢沪深 300",
        "",
        "## 风险",
        "",
        "- 短期涨幅偏大，注意回撤",
        "- 数据来自离线夹具，仅用于界面验收",
        "",
        "参考：[公开行情页](https://example.com/quote)",
        "",
    ]
    lines.extend(
        f"{n}. 第 {n} 条补充说明，用于验证折叠预览、展开全文与移动抽屉内滚动。"
        for n in range(1, 60)
    )
    return "\n".join(lines)


def _stats(step: int) -> StatsSnapshot:
    return StatsSnapshot(
        model_calls=step,
        tokens_in=step * 1200,
        tokens_out=step * 260,
        elapsed_ms=step * 1000,
    )


def _complete_stage(
    jobs: JobService,
    reports: ReportStore,
    job_id: str,
    ticker: str,
    position: int,
    step: int,
) -> None:
    stage_id = STAGE_IDS[position]
    jobs.start_stage(job_id, stage_id, index=position + 1, total=TOTAL)
    path = reports.write_stage_report(
        job_id, stage_id, _report_text(ticker, stage_id, position + 1)
    )
    jobs.finish_stage(
        job_id,
        stage_id,
        index=position + 1,
        total=TOTAL,
        stats=_stats(step),
        report_path=path,
        duration_ms=1000,
    )


def _create(jobs: JobService, ticker: str, analysis_date: str) -> str:
    config = {
        "llm_profile": "deepseek-default",
        "parallel_analysts": True,
        "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
    }
    outcome = jobs.create_job(
        {"ticker": ticker, "analysis_date": analysis_date, "config": config},
        idempotency_key=str(uuid.uuid4()),
    )
    if outcome.status_code != 201:
        raise SystemExit(f"create_job({ticker}) returned {outcome.status_code}")
    return outcome.job.id


def _claim(lease: LeaseService, owner: str) -> str:
    job = lease.claim_next_job(owner)
    if job is None:
        raise SystemExit("expected a queued job to claim")
    return job.id


def _seed_succeeded(
    jobs: JobService, reports: ReportStore, engine, analysis_date: str
) -> str:
    job_id = _create(jobs, TICKERS["succeeded"], analysis_date)
    worker = Worker(
        LeaseService(engine),
        jobs=jobs,
        reports=reports,
        owner="seed-succeeded",
        executor=FakeAnalysisExecutor(),
        reconcile_on_start=False,
    )
    try:
        if not worker.acquire():
            raise SystemExit("seed worker could not take the global lease")
        outcome = worker.run_once()
        if outcome is None or outcome.job.status != "succeeded":
            raise SystemExit("fake graph did not reach succeeded")
    finally:
        worker.shutdown()
    return job_id


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    db_path, reports_path = _require_test_root()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    reports_path.mkdir(parents=True, exist_ok=True)
    os.environ[JOBS_DB_ENV] = str(db_path)
    os.environ[JOB_REPORTS_ENV] = str(reports_path)
    command.upgrade(_alembic_config(), "head")

    config = replace(load_server_config(), write_mode="next")
    engine = build_engine(db_path)
    reports = ReportStore(reports_path)
    jobs = JobService(engine, config, reports=reports)
    analysis_date = datetime.now(CST).date().isoformat()
    seeded: dict[str, dict[str, str]] = {}

    def remember(status: str, job_id: str) -> None:
        seeded[status] = {"job_id": job_id, "ticker": TICKERS[status]}

    try:
        remember("succeeded", _seed_succeeded(jobs, reports, engine, analysis_date))

        lease = LeaseService(engine)
        if not lease.acquire(SEED_OWNER):
            raise SystemExit("seed could not take the global lease")
        try:
            job_id = _create(jobs, TICKERS["running"], analysis_date)
            _claim(lease, SEED_OWNER)
            _complete_stage(jobs, reports, job_id, TICKERS["running"], 0, 1)
            _complete_stage(jobs, reports, job_id, TICKERS["running"], 1, 2)
            jobs.start_stage(job_id, STAGE_IDS[2], index=3, total=TOTAL)
            remember("running", job_id)

            job_id = _create(jobs, TICKERS["pause_requested"], analysis_date)
            _claim(lease, SEED_OWNER)
            _complete_stage(jobs, reports, job_id, TICKERS["pause_requested"], 0, 1)
            _complete_stage(jobs, reports, job_id, TICKERS["pause_requested"], 1, 2)
            jobs.start_stage(job_id, STAGE_IDS[2], index=3, total=TOTAL)
            jobs.request_pause(job_id)
            remember("pause_requested", job_id)

            job_id = _create(jobs, TICKERS["paused"], analysis_date)
            _claim(lease, SEED_OWNER)
            _complete_stage(jobs, reports, job_id, TICKERS["paused"], 0, 1)
            _complete_stage(jobs, reports, job_id, TICKERS["paused"], 1, 2)
            jobs.request_pause(job_id)
            if not jobs.pause_at_boundary(job_id):
                raise SystemExit("pause_at_boundary failed")
            remember("paused", job_id)

            job_id = _create(jobs, TICKERS["cancel_requested"], analysis_date)
            _claim(lease, SEED_OWNER)
            _complete_stage(jobs, reports, job_id, TICKERS["cancel_requested"], 0, 1)
            _complete_stage(jobs, reports, job_id, TICKERS["cancel_requested"], 1, 2)
            jobs.start_stage(job_id, STAGE_IDS[2], index=3, total=TOTAL)
            jobs.request_cancel(job_id)
            remember("cancel_requested", job_id)

            job_id = _create(jobs, TICKERS["failed"], analysis_date)
            _claim(lease, SEED_OWNER)
            for position in range(3):
                _complete_stage(
                    jobs, reports, job_id, TICKERS["failed"], position, position + 1
                )
            jobs.start_stage(job_id, STAGE_IDS[3], index=4, total=TOTAL)
            if not jobs.finish_failure(
                job_id,
                code="source_timeout",
                message="数据源超时，阶段未能完成",
                stats=_stats(4),
            ):
                raise SystemExit("finish_failure failed")
            remember("failed", job_id)

            job_id = _create(jobs, TICKERS["interrupted"], analysis_date)
            _claim(lease, SEED_OWNER)
            for position in range(3):
                _complete_stage(
                    jobs,
                    reports,
                    job_id,
                    TICKERS["interrupted"],
                    position,
                    position + 1,
                )
            if not jobs.mark_interrupted(
                job_id,
                detail="lease_expired",
                resume_from_stage=STAGE_IDS[3],
            ):
                raise SystemExit("mark_interrupted failed")
            remember("interrupted", job_id)

            job_id = _create(jobs, TICKERS["cancelled"], analysis_date)
            jobs.request_cancel(job_id)
            remember("cancelled", job_id)
        finally:
            lease.release(SEED_OWNER)

        remember("queued", _create(jobs, TICKERS["queued"], analysis_date))
    finally:
        engine.dispose()

    print(json.dumps({"jobs": seeded}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
