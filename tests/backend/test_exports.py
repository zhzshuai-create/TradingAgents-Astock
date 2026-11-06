"""P3-03 acceptance tests: PDF export queue, cache, status and file.

EXP-01 first POST queues and settles; EXP-02 a second POST is a cache hit with
no extra render; EXP-03 non-ready downloads and missing ids; EXP-04 a render
failure is safe and leaves report/Markdown readable; EXP-05 the startup sweep
closes abandoned rows; EXP-06/07 are the p95 and cache-hit latency lines;
EXP-08 marks a legacy export without changing the report row.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_exports.py -q
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import EXPORTS_DIR_ENV, JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Report, ReportExport  # noqa: E402
from backend.app.services.export_service import ExportService  # noqa: E402
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.pdf_renderer import (  # noqa: E402
    EXPORTER_VERSION,
    RenderedPdf,
    render_pdf,
)
from backend.app.services.report_document import compute_content_hash  # noqa: E402
from backend.app.services.report_schema import build_legacy_report  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402

BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
CLOCK = datetime(2026, 11, 6, 10, 0, tzinfo=CST)
CLOCK_TEXT = CLOCK.isoformat(timespec="seconds")
RID = "00000000-0000-4000-8000-000000000001"
LEGACY_RID = "00000000-0000-4000-8000-000000000002"
FAKE_PDF = b"%PDF-1.4\n% fake export\n%%EOF\n"
SERVER_CONFIG = ServerConfig()


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs" / "jobs.db"
    exports_dir = tmp_path / "exports"
    monkeypatch.setenv(JOBS_DB_ENV, str(db_path))
    monkeypatch.setenv(EXPORTS_DIR_ENV, str(exports_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    command.upgrade(_alembic_config(), "head")

    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    jobs = JobService(engine, SERVER_CONFIG, clock=lambda: CLOCK, reports=reports)
    state = SimpleNamespace(calls=0, fail=False, real=False, rendered=[])

    def renderer(payload, *, exported_at=None):
        state.calls += 1
        if state.fail:
            raise RuntimeError("boom C:/private/renderer/path")
        if state.real:
            rendered = render_pdf(payload, exported_at=exported_at)
            state.rendered.append(rendered)
            return rendered
        return RenderedPdf(data=FAKE_PDF, bookmarks=(), text_blocks=())

    service = ExportService(
        engine,
        exports_dir=exports_dir,
        clock=lambda: CLOCK,
        renderer=renderer,
    )
    client = TestClient(
        create_app(
            service=jobs,
            server_config=SERVER_CONFIG,
            report_store=reports,
            export_service=service,
        )
    )
    _insert(engine, _report_row())
    try:
        yield SimpleNamespace(
            engine=engine,
            client=client,
            service=service,
            state=state,
            exports_dir=exports_dir,
            tmp_path=tmp_path,
        )
    finally:
        client.close()
        service.shutdown()
        engine.dispose()


def _golden() -> dict:
    return json.loads((FIXTURES / "final_state_v1.json").read_text(encoding="utf-8"))


def _report_row(
    *,
    report_id: str = RID,
    origin: str = "new",
    payload: dict | None = None,
) -> Report:
    dto = copy.deepcopy(payload or _golden())
    dto["meta"]["report_id"] = report_id
    dto["meta"]["origin"] = origin
    dto["meta"]["content_hash"] = compute_content_hash(dto["sections"])
    meta = dto["meta"]
    return Report(
        report_id=report_id,
        job_id=None,
        ticker_code=meta["ticker_code"],
        ticker_name=meta.get("ticker_name"),
        analysis_date=meta["analysis_date"],
        generated_at=meta.get("generated_at"),
        generated_at_source=meta.get("generated_at_source") or "unknown",
        origin=origin,
        schema_version="report-v1",
        content_hash=meta["content_hash"],
        config_digest=None,
        data_quality_status=meta.get("data_quality_status") or "absent",
        chart_snapshot_status=meta.get("chart_snapshot_status") or "none",
        retry_of_job_id=None,
        rating=meta["rating"],
        signal=meta["signal"],
        payload=dto,
        created_at="2026-11-06T10:00:00+08:00",
    )


def _legacy_payload() -> dict:
    legacy = json.loads(
        (FIXTURES / "legacy_report_v1.json").read_text(encoding="utf-8")
    )
    return build_legacy_report(legacy)


def _insert(engine, *rows) -> None:
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(rows)
        session.commit()


def _insert_export(env, *, export_id: str, status: str, report_id: str = RID):
    row = ReportExport(
        export_id=export_id,
        report_id=report_id,
        content_hash=hashlib.sha256(export_id.encode()).hexdigest(),
        exporter_version=EXPORTER_VERSION,
        template="default",
        status=status,
        created_at=CLOCK_TEXT,
    )
    _insert(env.engine, row)
    return row


def _post(env, report_id: str = RID, body=None):
    return env.client.post(
        f"/api/v1/reports/{report_id}/exports/pdf",
        json=body if body is not None else None,
    )


def _wait(env, export_id: str, *, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = env.client.get(f"/api/v1/exports/{export_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in ("ready", "failed"):
            return last
        time.sleep(0.01)
    raise AssertionError(f"export never settled: {last}")


def test_exp01_queue_poll_and_download(env):
    response = _post(env)
    assert response.status_code == 202
    queued = response.json()
    assert set(queued) == {"export_id", "status", "poll_url"}
    assert queued["status"] == "queued"
    assert queued["poll_url"] == f"/api/v1/exports/{queued['export_id']}"
    assert response.headers["Location"] == queued["poll_url"]
    assert "X-Export-Cached" not in response.headers

    status = _wait(env, queued["export_id"])
    assert status == {
        "export_id": queued["export_id"],
        "report_id": RID,
        "status": "ready",
        "download_url": f"/api/v1/exports/{queued['export_id']}/file",
        "error": None,
        "created_at": CLOCK_TEXT,
        "ready_at": CLOCK_TEXT,
        "exporter_version": "pdf-v1",
    }

    download = env.client.get(status["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content == FAKE_PDF
    assert str(env.exports_dir).encode() not in download.content

    with Session(env.engine) as session:
        row = session.get(ReportExport, queued["export_id"])
        assert row is not None and row.file_path is not None
        assert (env.exports_dir / row.file_path).read_bytes() == FAKE_PDF


def test_exp02_second_request_hits_cache_without_rendering(env):
    first = _post(env)
    assert first.status_code == 202
    export_id = first.json()["export_id"]
    _wait(env, export_id)
    calls = env.state.calls

    second = _post(env)
    assert second.status_code == 200
    assert second.headers["X-Export-Cached"] == "1"
    assert second.json()["export_id"] == export_id
    assert second.json()["status"] == "ready"
    assert env.state.calls == calls
    with Session(env.engine) as session:
        assert session.scalar(select(func.count()).select_from(ReportExport)) == 1


def test_exp03_not_ready_missing_and_template_errors(env):
    _insert_export(env, export_id="queued-export", status="queued")
    _insert_export(env, export_id="rendering-export", status="rendering")

    for export_id in ("queued-export", "rendering-export"):
        response = env.client.get(f"/api/v1/exports/{export_id}/file")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "export_not_ready"

    missing = env.client.get("/api/v1/exports/no-such-export")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "export_not_found"
    missing_file = env.client.get("/api/v1/exports/no-such-export/file")
    assert missing_file.status_code == 404
    assert missing_file.json()["error"]["code"] == "export_not_found"

    no_report = _post(env, "no-such-report")
    assert no_report.status_code == 404
    assert no_report.json()["error"]["code"] == "report_not_found"

    unknown = _post(env, body={"template": "latex"})
    assert unknown.status_code == 400
    error = unknown.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"] == {
        "field": "template",
        "allowed_values": ["default"],
    }

    extra = _post(env, body={"template": "default", "foo": 1})
    assert extra.status_code == 422
    assert extra.json()["error"]["code"] == "invalid_request"
    assert extra.json()["error"]["details"]["field"] == "foo"


def test_exp04_render_failure_is_safe_and_retryable(env):
    with Session(env.engine) as session:
        before = session.get(Report, RID)
        before_chart = before.chart_snapshot_status
        before_hash = before.content_hash

    env.state.fail = True
    response = _post(env)
    assert response.status_code == 202
    status = _wait(env, response.json()["export_id"])
    assert status["status"] == "failed"
    assert status["download_url"] is None
    assert status["ready_at"] is None
    assert status["error"] == {"code": "render_failed", "message": "导出失败，请重试"}
    assert "boom" not in json.dumps(status)
    assert "private" not in json.dumps(status)

    detail = env.client.get(f"/api/v1/reports/{RID}")
    assert detail.status_code == 200
    markdown = env.client.get(f"/api/v1/reports/{RID}/markdown")
    assert markdown.status_code == 200

    with Session(env.engine) as session:
        after = session.get(Report, RID)
        assert after.chart_snapshot_status == before_chart
        assert after.content_hash == before_hash
        assert after.payload["meta"]["chart_snapshot_status"] == before_chart
    produced = list(env.exports_dir.rglob("*.pdf")) if env.exports_dir.exists() else []
    assert produced == []

    env.state.fail = False
    retry = _post(env)
    assert retry.status_code == 202
    assert retry.json()["export_id"] == status["export_id"]
    assert "X-Export-Cached" not in retry.headers
    assert _wait(env, status["export_id"])["status"] == "ready"


def test_exp05_startup_sweep_closes_abandoned_rows(env):
    _insert_export(env, export_id="stale-queued", status="queued")
    _insert_export(env, export_id="stale-rendering", status="rendering")

    assert env.service.sweep_stale() == 2

    with Session(env.engine) as session:
        for export_id in ("stale-queued", "stale-rendering"):
            row = session.get(ReportExport, export_id)
            assert row.status == "failed"
            assert row.error_code == "render_failed"
            assert row.error_message == "导出中断，请重试"
            assert row.ready_at is None


def test_exp06_long_report_first_pdf_p95_under_15s():
    payload = json.loads(
        (FIXTURES / "long_report.json").read_text(encoding="utf-8")
    )
    for _ in range(3):
        render_pdf(payload)
    samples = []
    for _ in range(30):
        started = time.perf_counter()
        rendered = render_pdf(payload)
        samples.append((time.perf_counter() - started) * 1000)
        assert rendered.data.startswith(b"%PDF-")
    samples.sort()
    p95 = samples[math.ceil(0.95 * len(samples)) - 1]
    assert p95 <= 15000, f"long_report p95 {p95:.0f} ms"


def test_exp07_cache_hit_preparation_under_500ms(env):
    first = _post(env)
    export_id = first.json()["export_id"]
    _wait(env, export_id)

    started = time.perf_counter()
    cached = _post(env)
    cached_ms = (time.perf_counter() - started) * 1000
    assert cached.status_code == 200
    assert cached.headers["X-Export-Cached"] == "1"

    started = time.perf_counter()
    download = env.client.get(cached.json()["poll_url"] + "/file")
    download_ms = (time.perf_counter() - started) * 1000
    assert download.status_code == 200
    assert cached_ms <= 500, f"cache hit POST {cached_ms:.0f} ms"
    assert download_ms <= 500, f"cache hit download {download_ms:.0f} ms"


def test_exp08_legacy_export_marks_supplement_without_touching_report(env):
    dto = _legacy_payload()
    _insert(
        env.engine,
        _report_row(report_id=LEGACY_RID, origin="legacy_import", payload=dto),
    )
    env.state.real = True

    response = _post(env, LEGACY_RID)
    assert response.status_code == 202
    status = _wait(env, response.json()["export_id"])
    assert status["status"] == "ready"
    assert env.state.rendered

    note = f"导出时补充数据；补充时间：{CLOCK_TEXT}。"
    assert note in env.state.rendered[-1].text_blocks

    with Session(env.engine) as session:
        row = session.get(Report, LEGACY_RID)
        assert row.origin == "legacy_import"
        assert row.chart_snapshot_status == "none"
        assert row.generated_at is None
        assert row.payload["meta"]["chart_snapshot_status"] == "none"
    detail = env.client.get(f"/api/v1/reports/{LEGACY_RID}")
    assert detail.status_code == 200
    assert detail.json()["meta"]["chart_snapshot_status"] == "none"
