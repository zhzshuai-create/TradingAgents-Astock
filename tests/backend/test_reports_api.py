"""P3-01 acceptance tests: GET /api/v1/reports (RPT-01 .. RPT-04, 06 .. 08).

Rows are inserted directly so each test controls ``generated_at`` and
``analysis_date``. Every API call in this file is a read; RPT-06 snapshots
report/job/event/stage rows, filesystem mtimes and socket connects around the
four read paths. T14/T15 go through the real terminal write path
(``JobService.finish_success``) so "old report stays readable" is not assumed.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_reports_api.py -q
"""

from __future__ import annotations

import copy
import json
import math
import socket
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobStage, Report  # noqa: E402
from backend.app.services.job_service import (  # noqa: E402
    CST,
    JobService,
    StatsSnapshot,
)
from backend.app.services.report_document import compute_content_hash  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402

BACKEND = ROOT / "backend"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
CLOCK = datetime(2026, 10, 30, 9, 0, tzinfo=CST)
TODAY = "2026-10-30"
BASE_TIME = datetime(2026, 10, 24, 15, 30, tzinfo=CST)
BASE_TIME_TEXT = BASE_TIME.isoformat(timespec="seconds")
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
)


def _golden() -> dict:
    return json.loads((FIXTURES / "final_state_v1.json").read_text(encoding="utf-8"))


GOLDEN = _golden()


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    monkeypatch.setenv("TA_JOB_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("TA_EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    command.upgrade(_alembic_config(), "head")

    now = [CLOCK]
    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    service = JobService(engine, SERVER_CONFIG, clock=lambda: now[0], reports=reports)
    client = TestClient(
        create_app(
            service=service,
            server_config=SERVER_CONFIG,
            report_store=reports,
        )
    )
    try:
        yield SimpleNamespace(
            engine=engine,
            service=service,
            client=client,
            tmp_path=tmp_path,
            now=now,
        )
    finally:
        client.close()
        engine.dispose()


def _report_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


def _row(
    *,
    report_id: str,
    generated_at: str | None,
    ticker: str = "000629",
    analysis_date: str = "2026-10-24",
    rating: str = "Hold",
    origin: str = "new",
) -> Report:
    sections = copy.deepcopy(GOLDEN["sections"])
    meta = copy.deepcopy(GOLDEN["meta"])
    meta.update(
        {
            "report_id": report_id,
            "job_id": None,
            "ticker_code": ticker,
            "ticker_name": None,
            "analysis_date": analysis_date,
            "generated_at": generated_at,
            "generated_at_source": "job_clock" if generated_at else "unknown",
            "origin": origin,
            "origin": origin,
            "rating": rating,
            "signal": {
                "Buy": "Buy",
                "Overweight": "Buy",
                "Hold": "Hold",
                "Underweight": "Sell",
                "Sell": "Sell",
                "unknown": "unknown",
            }[rating],
            "data_quality_status": "ok" if generated_at else "absent",
            "chart_snapshot_status": "frozen" if generated_at else "none",
            "content_hash": compute_content_hash(sections),
        }
    )
    return Report(
        report_id=report_id,
        job_id=None,
        ticker_code=ticker,
        ticker_name=None,
        analysis_date=analysis_date,
        generated_at=generated_at,
        generated_at_source=meta["generated_at_source"],
        origin=origin,
        schema_version="report-v1",
        content_hash=meta["content_hash"],
        config_digest=None,
        data_quality_status="ok" if generated_at else "absent",
        chart_snapshot_status="frozen" if generated_at else "none",
        retry_of_job_id=None,
        rating=rating,
        signal=meta["signal"],
        payload={"meta": meta, "sections": sections},
        created_at=generated_at or "2026-10-24T00:00:00+08:00",
    )


def _insert(env, rows: list[Report]) -> None:
    with Session(env.engine, expire_on_commit=False) as session:
        session.add_all(rows)
        session.commit()


def _seed_mixed(env) -> list[Report]:
    """25 rows: a same-second tie, two tickers, two dates, five null times."""
    rows = []
    for index in range(25):
        if index == 0:
            generated_at = BASE_TIME.isoformat(timespec="seconds")
        elif index == 1:
            generated_at = BASE_TIME.isoformat(timespec="seconds")
        elif index < 20:
            generated_at = (BASE_TIME - timedelta(minutes=index)).isoformat(
                timespec="seconds"
            )
        else:
            generated_at = None
        rows.append(
            _row(
                report_id=_report_id(index),
                generated_at=generated_at,
                ticker="000629" if index % 2 == 0 else "600519",
                analysis_date="2026-10-20" if index < 10 else "2026-10-24",
                rating=("Buy", "Hold", "Sell", "unknown")[index % 4],
            )
        )
    _insert(env, rows)
    return rows


def _expected_ids(rows: list[Report]) -> list[str]:
    timed = [row for row in rows if row.generated_at is not None]
    nulls = [row for row in rows if row.generated_at is None]
    timed.sort(key=lambda row: row.report_id)
    timed.sort(key=lambda row: datetime.fromisoformat(row.generated_at), reverse=True)
    nulls.sort(key=lambda row: row.report_id)
    return [row.report_id for row in timed + nulls]


def _list(env, **params) -> dict:
    response = env.client.get("/api/v1/reports", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_rpt01_default_page_order_matches_contract(env):
    rows = _seed_mixed(env)
    body = _list(env)

    assert len(body["items"]) == 20
    assert body["next_cursor"] is not None
    expected = _expected_ids(rows)
    assert [item["meta"]["report_id"] for item in body["items"]] == expected[:20]

    for item in body["items"]:
        assert set(item) == {"meta", "summary_available"}
        assert item["summary_available"] is True
        assert "sections" not in item

    order = [
        (item["meta"]["generated_at"] is None, item["meta"]["report_id"])
        for item in body["items"]
    ]
    assert order == sorted(order)
    assert all(item["meta"]["generated_at"] is not None for item in body["items"])


def test_rpt02_filters_and_invalid_rating(env):
    rows = _seed_mixed(env)

    ticker_page = _list(env, ticker="000629")
    assert {item["meta"]["ticker_code"] for item in ticker_page["items"]} == {"000629"}
    assert len(ticker_page["items"]) == len(
        [row for row in rows if row.ticker_code == "000629"]
    )

    window = _list(env, date_from="2026-10-21", date_to="2026-10-24")
    assert window["items"]
    assert all(
        "2026-10-21" <= item["meta"]["analysis_date"] <= "2026-10-24"
        for item in window["items"]
    )

    rated = _list(env, rating="Buy,Sell")
    assert {item["meta"]["rating"] for item in rated["items"]} <= {"Buy", "Sell"}
    assert len(rated["items"]) == len(
        [row for row in rows if row.rating in {"Buy", "Sell"}]
    )

    empty = _list(env, date_from="2026-10-25", date_to="2026-10-20")
    assert empty == {"items": [], "next_cursor": None}

    bad_rating = env.client.get("/api/v1/reports", params={"rating": "StrongBuy"})
    assert bad_rating.status_code == 400
    error = bad_rating.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["field"] == "rating"
    assert error["details"]["allowed_values"] == [
        "Buy",
        "Overweight",
        "Hold",
        "Underweight",
        "Sell",
        "unknown",
    ]

    bad_ticker = env.client.get("/api/v1/reports", params={"ticker": "629"})
    assert bad_ticker.status_code == 400
    assert bad_ticker.json()["error"]["details"] == {"field": "ticker"}


def test_rpt03_pagination_covers_each_row_once(env):
    _seed_mixed(env)
    single = _list(env, limit=100)
    assert len(single["items"]) == 25
    assert single["next_cursor"] is None
    expected = [item["meta"]["report_id"] for item in single["items"]]

    collected: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 7}
        if cursor:
            params["cursor"] = cursor
        page = _list(env, **params)
        pages += 1
        collected.extend(item["meta"]["report_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 4
    assert collected == expected
    assert len(set(collected)) == len(collected)

    bad = env.client.get("/api/v1/reports", params={"cursor": "not-a-cursor!!"})
    assert bad.status_code == 400
    assert bad.json()["error"]["details"] == {"field": "cursor"}


def test_rpt04_detail_is_payload_and_missing_is_404(env):
    row = _row(report_id=_report_id(1), generated_at=BASE_TIME_TEXT)
    _insert(env, [row])

    response = env.client.get(f"/api/v1/reports/{row.report_id}")
    assert response.status_code == 200
    assert response.json() == row.payload

    missing = env.client.get("/api/v1/reports/00000000-0000-4000-8000-999999999999")
    assert missing.status_code == 404
    error = missing.json()["error"]
    assert error["code"] == "report_not_found"
    assert error["message"] == "没有找到这份报告"


def test_detail_hash_mismatch_is_500_not_half_a_report(env):
    row = _row(report_id=_report_id(2), generated_at=BASE_TIME_TEXT)
    _insert(env, [row])
    with Session(env.engine) as session:
        stored = session.get(Report, row.report_id)
        payload = copy.deepcopy(stored.payload)
        payload["meta"]["content_hash"] = "0" * 64
        stored.payload = payload
        session.commit()

    response = env.client.get(f"/api/v1/reports/{row.report_id}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


def _counts(engine) -> tuple[int, int, int, int]:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(Report)),
            session.scalar(select(func.count()).select_from(Job)),
            session.scalar(select(func.count()).select_from(JobEvent)),
            session.scalar(select(func.count()).select_from(JobStage)),
        )


def _mtimes(root: Path) -> dict[str, int]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.stat().st_mtime_ns
        for path in root.rglob("*")
        if path.is_file()
    }


def test_rpt06_reads_are_side_effect_free(env, monkeypatch):
    row = _row(report_id=_report_id(3), generated_at=BASE_TIME_TEXT)
    _insert(env, [row])
    reports_dir = env.tmp_path / "reports"
    exports_dir = env.tmp_path / "exports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "sentinel.md").write_text("keep", encoding="utf-8")
    exports_dir.mkdir(parents=True, exist_ok=True)
    (exports_dir / "sentinel.pdf").write_bytes(b"keep")

    connects = {"count": 0}
    real_connect = socket.socket.connect
    loopback = {"127.0.0.1", "::1", "localhost"}

    def counting_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in loopback:
            connects["count"] += 1
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", counting_connect)

    before = (
        _counts(env.engine),
        _mtimes(reports_dir),
        _mtimes(exports_dir),
        copy.deepcopy(row.payload["meta"]),
    )

    assert env.client.get("/api/v1/reports").status_code == 200
    detail = env.client.get(f"/api/v1/reports/{row.report_id}")
    assert detail.status_code == 200
    markdown = env.client.get(f"/api/v1/reports/{row.report_id}/markdown")
    assert markdown.status_code == 200
    cached = env.client.get(
        f"/api/v1/reports/{row.report_id}/markdown",
        headers={"If-None-Match": markdown.headers["ETag"]},
    )
    assert cached.status_code == 304

    after = (
        _counts(env.engine),
        _mtimes(reports_dir),
        _mtimes(exports_dir),
        detail.json()["meta"],
    )
    assert after == before
    assert connects["count"] == 0


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _timed_gets(client: TestClient, url: str, samples: int = 30) -> list[float]:
    for _ in range(3):
        assert client.get(url).status_code == 200
    times = []
    for _ in range(samples):
        started = time.perf_counter()
        response = client.get(url)
        times.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200
    return times


def _bulk_rows(count: int) -> list[dict]:
    sections = copy.deepcopy(GOLDEN["sections"])
    content_hash = compute_content_hash(sections)
    base_meta = copy.deepcopy(GOLDEN["meta"])
    rows = []
    for index in range(count):
        report_id = _report_id(index)
        meta = dict(base_meta)
        meta.update(
            {
                "report_id": report_id,
                "job_id": None,
                "ticker_code": "000629",
                "ticker_name": None,
                "analysis_date": "2026-10-24",
                "generated_at": (BASE_TIME - timedelta(seconds=index)).isoformat(
                    timespec="seconds"
                ),
                "generated_at_source": "job_clock",
                "origin": "new",
                "content_hash": content_hash,
                "rating": "Hold",
                "signal": "Hold",
            }
        )
        rows.append(
            {
                "report_id": report_id,
                "job_id": None,
                "ticker_code": "000629",
                "ticker_name": None,
                "analysis_date": "2026-10-24",
                "generated_at": meta["generated_at"],
                "generated_at_source": "job_clock",
                "origin": "new",
                "schema_version": "report-v1",
                "content_hash": content_hash,
                "config_digest": None,
                "data_quality_status": "ok",
                "chart_snapshot_status": "frozen",
                "retry_of_job_id": None,
                "rating": "Hold",
                "signal": "Hold",
                "payload": {"meta": meta, "sections": sections},
                "created_at": meta["generated_at"],
            }
        )
    return rows


def test_rpt07_rpt08_tenthousand_rows_p95(env):
    rows = _bulk_rows(10_000)
    with Session(env.engine) as session:
        session.execute(insert(Report), rows)
        session.commit()

    list_url = (
        "/api/v1/reports?ticker=000629&date_from=2026-09-01&date_to=2026-10-29&limit=50"
    )
    list_p95 = _p95(_timed_gets(env.client, list_url))
    detail_p95 = _p95(_timed_gets(env.client, f"/api/v1/reports/{_report_id(0)}"))
    assert list_p95 <= 500, list_p95
    assert detail_p95 <= 500, detail_p95


def _create_job(env) -> str:
    response = env.client.post(
        "/api/v1/jobs",
        json={
            "ticker": "000629",
            "analysis_date": TODAY,
            "config": copy.deepcopy(CONFIG),
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def _mark_running(env, job_id: str) -> None:
    with Session(env.engine) as session:
        session.execute(
            update(Job).where(Job.id == job_id).values(status="running")
        )
        session.commit()


def _finish(env, job_id: str, rating: str) -> None:
    _mark_running(env, job_id)
    report = {
        "meta": {
            "rating": rating,
            "data_quality_status": "ok",
            "chart_snapshot_status": "frozen",
        },
        "sections": copy.deepcopy(GOLDEN["sections"]),
    }
    assert env.service.finish_success(
        job_id, detail=None, stats=StatsSnapshot(), report=report
    )


def test_t14_t15_two_successes_keep_both_and_null_last(env):
    first = _create_job(env)
    _finish(env, first, "Overweight")

    env.now[0] = CLOCK + timedelta(hours=2)
    second = _create_job(env)
    _finish(env, second, "Sell")

    body = _list(env, ticker="000629")
    ids = [item["meta"]["report_id"] for item in body["items"]]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    newest_item, older_item = body["items"]
    assert newest_item["meta"]["generated_at"] > older_item["meta"]["generated_at"]

    with Session(env.engine) as session:
        rows = {row.report_id: row for row in session.scalars(select(Report))}
    newest = max(rows.values(), key=lambda row: row.generated_at)
    oldest = min(rows.values(), key=lambda row: row.generated_at)
    old_hash = oldest.content_hash
    old_payload = copy.deepcopy(oldest.payload)

    legacy = _row(
        report_id=_report_id(99),
        generated_at=None,
        origin="legacy_import",
        rating="unknown",
    )
    _insert(env, [legacy])

    body = _list(env, ticker="000629")
    assert [item["meta"]["report_id"] for item in body["items"]][-1] == legacy.report_id
    assert body["items"][-1]["meta"]["generated_at"] is None

    detail = env.client.get(f"/api/v1/reports/{oldest.report_id}")
    assert detail.status_code == 200
    assert detail.json() == old_payload
    with Session(env.engine) as session:
        assert session.get(Report, oldest.report_id).content_hash == old_hash
    assert newest.report_id != oldest.report_id
