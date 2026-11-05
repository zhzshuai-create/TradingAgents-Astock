"""P1-11 acceptance tests: SSE snapshot, replay and reconnect.

SSE-01: the first frame is a snapshot carrying the full JobDetail and the
        current max seq; the response carries the frozen SSE headers.
SSE-02: the five persisted event shapes plus snapshot; event line equals
        data.type; ids are 1..N with no holes; no ``error`` frame is invented.
SSE-03: a terminal subscription ends with stats, status_changed, report_ready
        and then EOF, without heartbeats.
SSE-04: an idle connection gets ``: ping`` without consuming a seq.
SSE-05: a cursor outside the 24h/2000-event window, or past the maximum,
        is 410 sse_cursor_expired; count retention is injectable.
SSE-06: ``created`` / ``transition_rejected`` audit rows keep seq NULL and
        never appear as frames.
Handshake: POST is 405 method_not_allowed, wrong Accept and bad cursors are
        400 invalid_request, unknown job is 404 job_not_found.
GF-19: two subscriptions see identical frames and change no row counts.
GF-20: reconnecting with Last-Event-ID replays exactly seq > N, contiguous;
        reconnecting at the maximum replays nothing.
CB-05: a report_ready appended by B5 is delivered through replay.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_sse.py -q
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, Report  # noqa: E402
from backend.app.services.event_stream import (  # noqa: E402
    CursorExpired,
    EventStream,
)
from backend.app.services.job_service import CST, JobService  # noqa: E402
from backend.app.services.lease import LeaseService  # noqa: E402
from backend.app.services.report_store import ReportStore  # noqa: E402
from backend.app.worker.main import Worker  # noqa: E402

BACKEND = ROOT / "backend"
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
)
MEDIA = {"Accept": "text/event-stream"}
TOTAL_EVENTS = 40
STAGE_PAYLOAD_KEYS = {
    "stage_id",
    "stage_name",
    "stage_status",
    "index",
    "total",
    "started_at",
    "finished_at",
    "duration_ms",
}
STATUS_PAYLOAD_KEYS = {
    "from",
    "to",
    "reason",
    "detail",
    "pending_action",
    "error",
}
REPORT_PAYLOAD_KEYS = {"report_id", "content_hash", "rating", "signal", "url"}
FRAME_KEYS = {"seq", "job_id", "type", "at", "payload"}


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    command.upgrade(_alembic_config(), "head")

    clock = _Clock(datetime(2026, 10, 30, 9, 0, tzinfo=CST))
    engine = build_engine()
    reports = ReportStore(tmp_path / "reports")
    jobs = JobService(engine, SERVER_CONFIG, clock=clock, reports=reports)
    stream = EventStream(jobs, poll_interval=0.005, heartbeat_interval=0.05)
    app = create_app(
        service=jobs,
        server_config=SERVER_CONFIG,
        report_store=reports,
        event_stream=stream,
    )
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            engine=engine,
            jobs=jobs,
            reports=reports,
            clock=clock,
            stream=stream,
            app=app,
            client=client,
            lease=lambda **kwargs: LeaseService(engine, clock=clock, **kwargs),
        )
    finally:
        client.close()
        engine.dispose()


def _create(env, ticker: str = "000629") -> str:
    outcome = env.jobs.create_job(
        {"ticker": ticker, "analysis_date": TODAY, "config": dict(CONFIG)},
        idempotency_key=str(uuid.uuid4()),
    )
    assert outcome.status_code == 201
    return outcome.job.id


def _run(env, executor=None):
    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner="worker-test",
        executor=executor,
        reconcile_on_start=False,
    )
    assert worker.acquire() is True
    try:
        outcome = worker.run_once()
        assert outcome is not None
        return outcome
    finally:
        worker.shutdown()


def _detail(env, job_id: str) -> dict:
    response = env.client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    return response.json()


def _events(env, job_id: str) -> list[JobEvent]:
    with Session(env.engine) as session:
        return list(
            session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.id)
            )
        )


def _broadcast(env, job_id: str) -> list[JobEvent]:
    return [event for event in _events(env, job_id) if event.seq is not None]


def _counts(env) -> dict[str, int]:
    with Session(env.engine) as session:
        return {
            "jobs": session.scalar(select(func.count()).select_from(Job)),
            "events": session.scalar(select(func.count()).select_from(JobEvent)),
            "reports": session.scalar(select(func.count()).select_from(Report)),
        }


def _get(env, job_id: str, cursor: int | None = None, headers=None):
    merged = dict(MEDIA)
    if headers is not None:
        merged.update(headers)
    if cursor is not None:
        merged["Last-Event-ID"] = str(cursor)
    return env.client.get(f"/api/v1/jobs/{job_id}/events", headers=merged)


def _frames(text: str) -> list[dict]:
    parsed = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        frame = {
            "retry": None,
            "comment": None,
            "id": None,
            "event": None,
            "data": None,
        }
        data_lines = []
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            elif line.startswith("retry: "):
                frame["retry"] = int(line[7:])
            elif line.startswith("id: "):
                frame["id"] = int(line[4:])
            elif line.startswith("event: "):
                frame["event"] = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
        if data_lines:
            frame["data"] = json.loads("\n".join(data_lines))
        parsed.append(frame)
    return parsed


def _data_frames(text: str) -> list[dict]:
    return [frame for frame in _frames(text) if frame["data"] is not None]


# -- SSE-01 --------------------------------------------------------------


def test_sse01_snapshot_first_and_matches_job_detail(env):
    job_id = _create(env)
    _run(env)

    response = _get(env, job_id)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    frames = _frames(response.text)
    assert frames[0]["retry"] == 3000
    snapshot = frames[1]
    assert snapshot["event"] == "snapshot"
    assert snapshot["id"] == TOTAL_EVENTS
    assert snapshot["data"]["seq"] == TOTAL_EVENTS
    assert snapshot["data"]["job_id"] == job_id
    assert snapshot["data"]["type"] == "snapshot"
    assert snapshot["data"]["payload"]["last_seq"] == TOTAL_EVENTS
    assert snapshot["data"]["payload"]["job"] == _detail(env, job_id)


# -- SSE-02 --------------------------------------------------------------


def test_sse02_event_shapes_and_contiguous_ids(env):
    job_id = _create(env)
    _run(env)
    events = _data_frames(_get(env, job_id, cursor=0).text)

    assert events[0]["event"] == "snapshot"
    persisted = [frame for frame in events if frame["event"] != "snapshot"]
    assert {frame["event"] for frame in persisted} == {
        "stage_changed",
        "stats",
        "status_changed",
        "report_ready",
    }
    assert [frame["id"] for frame in persisted] == list(
        range(1, TOTAL_EVENTS + 1)
    )
    for frame in events:
        data = frame["data"]
        assert set(data) == FRAME_KEYS
        assert frame["event"] == data["type"]
        assert frame["id"] == data["seq"]
        assert data["job_id"] == job_id

    for frame in persisted:
        payload = frame["data"]["payload"]
        if frame["event"] == "stage_changed":
            assert set(payload) == STAGE_PAYLOAD_KEYS
            assert payload["stage_status"] in ("started", "done", "failed", "skipped")
        elif frame["event"] == "stats":
            assert set(payload) == {
                "model_calls",
                "tokens_in",
                "tokens_out",
                "elapsed_ms",
            }
        elif frame["event"] == "status_changed":
            assert set(payload) == STATUS_PAYLOAD_KEYS
            assert payload["reason"] in ("user", "worker", "reconcile")
        else:
            assert set(payload) == REPORT_PAYLOAD_KEYS

    final_stats = [f for f in persisted if f["event"] == "stats"][-1]["data"]
    assert final_stats["payload"] == {
        "model_calls": 14,
        "tokens_in": 182430,
        "tokens_out": 41208,
        "elapsed_ms": 21600000,
    }


# -- SSE-03 --------------------------------------------------------------


def test_sse03_terminal_close_order_and_no_ping(env):
    job_id = _create(env)
    _run(env)
    text = _get(env, job_id, cursor=0).text

    persisted = [f for f in _data_frames(text) if f["event"] != "snapshot"]
    assert [frame["event"] for frame in persisted[-3:]] == [
        "stats",
        "status_changed",
        "report_ready",
    ]
    assert persisted[-2]["data"]["payload"]["to"] == "succeeded"
    assert persisted[-2]["data"]["payload"]["detail"] is None
    assert ": ping" not in text
    assert "event: report_ready" in text


# -- SSE-04 --------------------------------------------------------------


def test_sse04_idle_stream_pings_without_consuming_seq(env):
    job_id = _create(env)
    url = f"/api/v1/jobs/{job_id}/events"
    lines: list[str] = []
    with env.client.stream("GET", url, headers=MEDIA) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            lines.append(line)
            if lines.count(": ping") >= 2:
                break

    assert "retry: 3000" in lines
    assert "event: snapshot" in lines
    assert "id: 0" in lines
    assert _broadcast(env, job_id) == []


# -- SSE-05 --------------------------------------------------------------


def test_sse05_cursor_outside_window_is_gone(env):
    job_id = _create(env)
    _run(env)

    beyond = _get(env, job_id, cursor=TOTAL_EVENTS + 5)
    assert beyond.status_code == 410
    assert beyond.json()["error"]["code"] == "sse_cursor_expired"

    job = env.jobs.get_job(job_id)
    assert job is not None
    short = EventStream(env.jobs, retention_count=2)
    with pytest.raises(CursorExpired):
        short.subscribe(job, 1)
    frames = list(short.subscribe(job, TOTAL_EVENTS - 1))
    assert "event: report_ready" in frames[-1]

    env.clock.advance(hours=25)
    expired = _get(env, job_id, cursor=1)
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "sse_cursor_expired"


def test_sse05_cursor_at_maximum_replays_nothing(env):
    job_id = _create(env)
    _run(env)
    response = _get(env, job_id, cursor=TOTAL_EVENTS)
    assert response.status_code == 200
    frames = _data_frames(response.text)
    assert [frame["event"] for frame in frames] == ["snapshot"]


# -- SSE-06 --------------------------------------------------------------


def test_sse06_audit_rows_stay_out_of_the_stream(env):
    job_id = _create(env)
    _run(env)

    rejected = env.client.post(
        f"/api/v1/jobs/{job_id}/actions", json={"action": "pause"}
    )
    assert rejected.status_code == 409

    audit = [event for event in _events(env, job_id) if event.seq is None]
    assert {event.type for event in audit} == {
        "created",
        "transition_rejected",
    }
    assert all(event.seq is None for event in audit)

    frames = _data_frames(_get(env, job_id, cursor=0).text)
    assert frames[0]["event"] == "snapshot"
    ids = [frame["id"] for frame in frames[1:]]
    assert ids == list(range(1, TOTAL_EVENTS + 1))
    assert all(frame["event"] != "transition_rejected" for frame in frames)


# -- handshake -----------------------------------------------------------


def test_handshake_errors_use_contract_codes(env):
    job_id = _create(env)

    wrong_method = env.client.post(
        f"/api/v1/jobs/{job_id}/events", headers=MEDIA
    )
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"

    wrong_accept = env.client.get(
        f"/api/v1/jobs/{job_id}/events", headers={"Accept": "application/json"}
    )
    assert wrong_accept.status_code == 400
    assert wrong_accept.json()["error"]["code"] == "invalid_request"

    for cursor in ("abc", "-1"):
        bad = env.client.get(
            f"/api/v1/jobs/{job_id}/events",
            headers={**MEDIA, "Last-Event-ID": cursor},
        )
        assert bad.status_code == 400
        assert bad.json()["error"]["code"] == "invalid_request"

    missing = _get(env, "job-does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "job_not_found"


# -- GF-19 ---------------------------------------------------------------


def test_gf19_two_subscriptions_are_identical_and_read_only(env):
    job_id = _create(env)
    _run(env)
    before = _counts(env)

    first = _get(env, job_id)
    second = _get(env, job_id)
    assert first.text == second.text
    assert _counts(env) == before

    snapshot_a = _data_frames(first.text)[0]["data"]["payload"]
    snapshot_b = _data_frames(second.text)[0]["data"]["payload"]
    assert snapshot_a == snapshot_b


# -- GF-20 ---------------------------------------------------------------


def test_gf20_reconnect_replays_only_after_the_cursor(env):
    job_id = _create(env)
    _run(env)
    events = _broadcast(env, job_id)
    assert [event.seq for event in events] == list(
        range(1, TOTAL_EVENTS + 1)
    )

    cursor = 5
    frames = _data_frames(_get(env, job_id, cursor=cursor).text)
    assert frames[0]["event"] == "snapshot"
    replayed = frames[1:]
    assert [frame["id"] for frame in replayed] == list(
        range(cursor + 1, TOTAL_EVENTS + 1)
    )
    assert [f["data"] for f in replayed] == [
        {
            "seq": event.seq,
            "job_id": job_id,
            "type": event.type,
            "at": event.created_at,
            "payload": event.payload,
        }
        for event in events[cursor:]
    ]


# -- CB-05 ---------------------------------------------------------------


def test_cb05_b5_report_ready_arrives_through_replay(env):
    job_id = _create(env)
    _run(env)
    with Session(env.engine) as session:
        session.execute(
            delete(JobEvent).where(
                JobEvent.job_id == job_id, JobEvent.type == "report_ready"
            )
        )
        session.commit()
    assert len(_broadcast(env, job_id)) == TOTAL_EVENTS - 1

    worker = Worker(
        env.lease(),
        jobs=env.jobs,
        reports=env.reports,
        owner="worker-startup",
        reconcile_on_start=True,
    )
    assert worker.acquire() is True
    worker.shutdown()

    frames = _data_frames(_get(env, job_id, cursor=TOTAL_EVENTS - 1).text)
    assert [frame["event"] for frame in frames] == ["snapshot", "report_ready"]
    assert frames[1]["id"] == TOTAL_EVENTS
    assert frames[1]["data"]["payload"]["report_id"] == _detail(env, job_id)[
        "report_id"
    ]
