"""P3-08 acceptance tests: legacy projection and old-version readability.

CMP-01: same ticker/date projects only the newest generated_at.
CMP-02: a backup exists and os.replace publishes the document; a failed write
        leaves the previous file untouched.
CMP-03: a projection failure keeps the job succeeded and the report readable.
CMP-04 lives in ``e2e/legacy_projection_e2e.py`` (old app renders the file).
CMP-05: ``TA_LEGACY_PROJECTION=0`` writes nothing and creates no directory.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_legacy_projection.py -q
"""

from __future__ import annotations

import copy
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, Report  # noqa: E402
from backend.app.services.job_service import (  # noqa: E402
    CST,
    JobService,
    StatsSnapshot,
)
from backend.app.services import legacy_projection  # noqa: E402
from backend.app.services.legacy_projection import (  # noqa: E402
    FAILED,
    PROJECTED,
    SKIPPED,
    build_legacy_state,
    project_latest,
    project_payload,
)
from backend.app.services.report_document import compute_content_hash  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402

BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
CLOCK = datetime(2026, 11, 6, 10, 0, tzinfo=CST)
SERVER_CONFIG = ServerConfig(
    graph_version="graph-v1",
    llm_profiles=("deepseek-default",),
    parallel_analysts=True,
    stage_toggles={"policy": True, "hot_money": True, "lockup": True},
    write_mode="next",
)
CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}


def _golden() -> dict:
    return json.loads((FIXTURES / "final_state_v1.json").read_text(encoding="utf-8"))


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def projection_on(monkeypatch, _disable_legacy_projection):
    monkeypatch.setenv("TA_LEGACY_PROJECTION", "1")


@pytest.fixture()
def env(tmp_path, monkeypatch, projection_on):
    monkeypatch.setenv("TA_LEGACY_PROJECTION", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv(JOBS_DB_ENV, str(tmp_path / "jobs" / "jobs.db"))
    command.upgrade(_alembic_config(), "head")
    engine = build_engine()
    now = [CLOCK]
    reports = ReportStore(tmp_path / "reports")
    service = JobService(engine, SERVER_CONFIG, clock=lambda: now[0], reports=reports)
    client = TestClient(
        create_app(service=service, server_config=SERVER_CONFIG, report_store=reports)
    )
    try:
        yield SimpleNamespace(
            engine=engine,
            service=service,
            client=client,
            logs=tmp_path / "home" / ".tradingagents" / "logs",
            tmp_path=tmp_path,
            now=now,
        )
    finally:
        engine.dispose()


def _payload(text: str = "正文", *, rating: str = "Overweight") -> dict:
    payload = copy.deepcopy(_golden())
    payload["meta"]["report_id"] = str(uuid.uuid4())
    payload["meta"]["generated_at"] = "2026-10-24T15:30:00+08:00"
    payload["meta"]["rating"] = rating
    payload["meta"]["signal"] = {
        "Buy": "Buy",
        "Overweight": "Buy",
        "Underweight": "Sell",
        "Sell": "Sell",
    }.get(rating, "Hold")
    payload["sections"]["sec-plan"]["body"] = f"## 最终投资建议\n\n{text}"
    payload["sections"]["sec-decision"]["body"] = f"## 最终交易决策\n\n{text}"
    return payload


def _insert(
    engine,
    payload: dict,
    *,
    report_id: str,
    generated_at: str | None,
    created_at: str = "2026-10-24T16:00:00+08:00",
) -> None:
    meta = payload["meta"]
    meta["report_id"] = report_id
    meta["generated_at"] = generated_at
    with Session(engine) as session:
        session.add(
            Report(
                report_id=report_id,
                job_id=None,
                ticker_code=meta["ticker_code"],
                ticker_name=meta.get("ticker_name"),
                analysis_date=meta["analysis_date"],
                generated_at=generated_at,
                generated_at_source="job_clock" if generated_at else "unknown",
                origin="new" if generated_at else "legacy_import",
                schema_version="report-v1",
                content_hash=compute_content_hash(payload["sections"]),
                config_digest=None,
                data_quality_status="ok",
                chart_snapshot_status="none",
                retry_of_job_id=None,
                rating=meta["rating"],
                signal=meta["signal"],
                payload=payload,
                created_at=created_at,
            )
        )
        session.commit()


def _target(logs: Path, ticker: str = "000629", day: str = "2026-10-24") -> Path:
    return (
        logs
        / ticker
        / legacy_projection.STRATEGY_DIR
        / f"full_states_log_{day}.json"
    )


def test_cmp01_only_the_newest_report_for_the_key_is_projected(env):
    older = _payload("旧版正文")
    newer = _payload("新版正文")
    imported = _payload("导入正文")
    _insert(env.engine, older, report_id="r-older", generated_at="2026-10-24T15:30:00+08:00")
    _insert(env.engine, newer, report_id="r-newer", generated_at="2026-10-25T09:00:00+08:00")
    _insert(
        env.engine,
        imported,
        report_id="r-null",
        generated_at=None,
        created_at="2026-10-30T09:00:00+08:00",
    )

    outcome = project_latest(
        env.engine,
        ticker_code="000629",
        analysis_date="2026-10-24",
        logs_root=env.logs,
    )

    assert outcome.status == PROJECTED
    assert outcome.report_id == "r-newer"
    assert outcome.path == _target(env.logs)
    state = json.loads(_target(env.logs).read_text(encoding="utf-8"))
    assert "新版正文" in state["investment_plan"]
    assert "旧版正文" not in state["investment_plan"]
    assert "导入正文" not in state["investment_plan"]


def test_cmp01_null_generated_at_sorts_last_even_when_created_later(env):
    imported = _payload("导入正文")
    new = _payload("新版正文")
    _insert(
        env.engine,
        new,
        report_id="r-new",
        generated_at="2026-10-24T15:30:00+08:00",
    )
    _insert(
        env.engine,
        imported,
        report_id="r-null",
        generated_at=None,
        created_at="2026-10-30T09:00:00+08:00",
    )

    outcome = project_latest(
        env.engine,
        ticker_code="000629",
        analysis_date="2026-10-24",
        logs_root=env.logs,
    )

    assert outcome.report_id == "r-new"
    state = json.loads(_target(env.logs).read_text(encoding="utf-8"))
    assert "新版正文" in state["investment_plan"]


def test_mapping_backfills_legacy_keys_and_lossy_parts(projection_on):
    payload = _payload("决策正文")
    payload["sections"]["sec-debate"]["body"] = "辩论正文"
    payload["sections"]["sec-debate"]["parts"]["extra_note"] = "额外观点"
    decision = payload["sections"]["sec-decision"]["body"]

    state = build_legacy_state(
        payload["meta"],
        payload["sections"],
        ticker_code="000629",
        analysis_date="2026-10-24",
    )

    assert state["company_of_interest"] == "000629"
    assert state["trade_date"] == "2026-10-24"
    assert state["market_report"] == payload["sections"]["sec-market"]["body"]
    assert state["data_quality_summary"] == payload["sections"]["sec-quality"]["body"]
    assert state["investment_plan"].startswith("**Rating**: Overweight")
    assert "**Signal**: Buy" in state["investment_plan"]
    assert "决策正文" in state["investment_plan"]
    assert state["final_trade_decision"] == decision
    assert state["trader_investment_decision"] == payload["sections"]["sec-trader"]["body"]
    assert (
        state["investment_debate_state"]["bull_history"]
        == payload["sections"]["sec-debate"]["parts"]["bull"]
    )
    assert "辩论正文" in state["investment_debate_state"]["judge_decision"]
    assert "**extra_note**" in state["investment_debate_state"]["judge_decision"]
    assert "额外观点" in state["investment_debate_state"]["judge_decision"]
    assert state["risk_debate_state"]["judge_decision"] == decision


def test_plan_falls_back_to_the_decision_body():
    payload = _payload("决策正文")
    payload["sections"]["sec-plan"] = {
        "id": "sec-plan",
        "title": "最终投资建议",
        "body": "",
    }

    state = build_legacy_state(
        payload["meta"],
        payload["sections"],
        ticker_code="000629",
        analysis_date="2026-10-24",
    )

    assert "决策正文" in state["investment_plan"]


def test_deprecated_plan_alias_is_preserved_only_in_its_own_key():
    payload = _payload("决策正文")
    payload["sections"]["sec-plan"] = {
        "id": "sec-plan",
        "title": "最终投资建议",
        "body": "",
        "legacy_aliases": {"trader_investment_plan": "旧交易员计划"},
    }

    state = build_legacy_state(
        payload["meta"],
        payload["sections"],
        ticker_code="000629",
        analysis_date="2026-10-24",
    )

    assert "旧交易员计划" in state["investment_plan"]
    assert "trader_investment_plan" not in state


def test_cmp02_backup_holds_the_previous_document_and_replace_is_atomic(
    tmp_path, monkeypatch, projection_on
):
    logs = tmp_path / "logs"
    first = project_payload(_payload("第一版"), logs_root=logs)
    assert first.status == PROJECTED

    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((Path(src), Path(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(legacy_projection.os, "replace", spy)
    second = project_payload(_payload("第二版"), logs_root=logs)

    assert second.status == PROJECTED
    target = _target(logs)
    backup = target.with_name(target.name + ".bak")
    assert backup.is_file()
    assert "第一版" in backup.read_text(encoding="utf-8")
    assert "第二版" in target.read_text(encoding="utf-8")
    assert len(calls) == 1
    src, dst = calls[0]
    assert src.parent == dst.parent == target.parent
    assert src != target and dst == target
    assert not src.exists()


def test_cmp02_failed_replace_keeps_the_original_file(
    tmp_path, monkeypatch, projection_on
):
    logs = tmp_path / "logs"
    project_payload(_payload("第一版"), logs_root=logs)
    target = _target(logs)
    before = target.read_text(encoding="utf-8")

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(legacy_projection.os, "replace", fail)
    outcome = project_payload(_payload("第二版"), logs_root=logs)

    assert outcome.status == FAILED
    assert target.read_text(encoding="utf-8") == before
    assert not list(target.parent.glob(".*.tmp"))


def test_cmp03_projection_failure_logs_and_reports_readable(env, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr("backend.app.services.job_service.project_latest", boom)
    job_id = env.client.post(
        "/api/v1/jobs",
        json={"ticker": "000629", "analysis_date": "2026-10-30", "config": copy.deepcopy(CONFIG)},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    ).json()["job_id"]
    with Session(env.engine) as session:
        session.execute(update(Job).where(Job.id == job_id).values(status="running"))
        session.commit()

    report = {
        "meta": {"rating": "Buy", "data_quality_status": "ok", "chart_snapshot_status": "none"},
        "sections": copy.deepcopy(_golden()["sections"]),
    }
    with caplog.at_level("ERROR", logger="backend.app.services.job_service"):
        assert env.service.finish_success(job_id, detail=None, stats=StatsSnapshot(), report=report)

    with Session(env.engine) as session:
        job = session.get(Job, job_id)
        row = session.scalar(select(Report).where(Report.job_id == job_id))
    assert job.status == "succeeded"
    assert row is not None
    assert row.payload["sections"]["sec-market"]["body"]
    assert any("legacy projection hook failed" in record.message for record in caplog.records)
    assert not env.logs.exists()


def test_finish_success_projects_the_new_report(env):
    job_id = env.client.post(
        "/api/v1/jobs",
        json={"ticker": "000629", "analysis_date": "2026-10-30", "config": copy.deepcopy(CONFIG)},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    ).json()["job_id"]
    with Session(env.engine) as session:
        session.execute(update(Job).where(Job.id == job_id).values(status="running"))
        session.commit()

    report = {
        "meta": {"rating": "Sell", "data_quality_status": "ok", "chart_snapshot_status": "none"},
        "sections": copy.deepcopy(_golden()["sections"]),
    }
    assert env.service.finish_success(job_id, detail=None, stats=StatsSnapshot(), report=report)

    target = _target(env.logs, day="2026-10-30")
    assert target.is_file()
    state = json.loads(target.read_text(encoding="utf-8"))
    assert "**Rating**: Sell" in state["investment_plan"]
    assert "**Signal**: Sell" in state["investment_plan"]


def test_cmp05_switch_off_writes_nothing(env, monkeypatch):
    monkeypatch.setenv("TA_LEGACY_PROJECTION", "0")
    outcome = project_latest(
        env.engine,
        ticker_code="000629",
        analysis_date="2026-10-24",
        logs_root=env.logs,
    )
    assert outcome.status == SKIPPED
    assert outcome.reason == "disabled"
    assert not env.logs.exists()


def test_cmp05_switch_on_still_skips_a_missing_report(env):
    outcome = project_latest(
        env.engine,
        ticker_code="000629",
        analysis_date="2026-10-24",
        logs_root=env.logs,
    )
    assert outcome.status == SKIPPED
    assert outcome.reason == "no_report"
    assert not env.logs.exists()
