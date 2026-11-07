"""P1-04 acceptance tests: create job and idempotency.

ID-01 same key + same body returns the original job and writes nothing.
ID-02 same key + different body is 409 idempotency_mismatch.
ID-03 same active fingerprint returns 200 + X-Existing-Job, even with a new key.
ID-04 same ticker/date with a different config is 409 active_conflict.
ID-05 twenty concurrent identical creates produce exactly one active job.
ID-06 GET of a missing job is 404 and writes nothing.

SM-01: creating a job persists status queued plus one `created` audit row
whose seq is NULL, so the replayable SSE sequence stays empty.
"""

from __future__ import annotations

import copy
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
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

from backend.app.core.config import JOBS_DB_ENV  # noqa: E402
from backend.app.core.db import build_engine  # noqa: E402
from backend.app.core.server_config import ServerConfig  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models import Job, JobEvent, JobIdempotencyKey  # noqa: E402
from backend.app.models.job import ACTIVE_STATUSES  # noqa: E402
from backend.app.services.config_snapshot import (  # noqa: E402
    config_hash,
    normalize_config,
)
from backend.app.services.job_service import CST, JobService  # noqa: E402

BACKEND = ROOT / "backend"
CLOCK = datetime(2026, 10, 30, 9, 0, tzinfo=CST)
TODAY = "2026-10-30"
GRAPH_VERSION = "graph-v1"
CONFIG = {
    "llm_profile": "deepseek-default",
    "parallel_analysts": True,
    "stage_toggles": {"policy": True, "hot_money": True, "lockup": True},
}
SERVER_CONFIG = ServerConfig(
    graph_version=GRAPH_VERSION,
    llm_profiles=("deepseek-default", "openai-default"),
    parallel_analysts=True,
    stage_toggles={"policy": True, "hot_money": True, "lockup": True},
    write_mode="next",
)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "jobs" / "jobs.db"
    monkeypatch.setenv(JOBS_DB_ENV, str(path))
    command.upgrade(_alembic_config(), "head")

    engine = build_engine()
    service = JobService(engine, SERVER_CONFIG, clock=lambda: CLOCK)
    app = create_app(service=service, server_config=SERVER_CONFIG)
    client = TestClient(app)
    try:
        yield SimpleNamespace(
            engine=engine, service=service, client=client, db_path=path
        )
    finally:
        client.close()
        engine.dispose()


def _body(**overrides) -> dict:
    body = {
        "ticker": "000629",
        "analysis_date": TODAY,
        "config": copy.deepcopy(CONFIG),
    }
    body.update(overrides)
    return body


def _post(env, body: dict, key: str | None = None):
    headers = {"Idempotency-Key": key or str(uuid.uuid4())}
    return env.client.post("/api/v1/jobs", json=body, headers=headers)


def _counts(engine) -> tuple[int, int, int]:
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(Job)),
            session.scalar(select(func.count()).select_from(JobEvent)),
            session.scalar(select(func.count()).select_from(JobIdempotencyKey)),
        )


def _expected_digest() -> str:
    snapshot = normalize_config(CONFIG, defaults=SERVER_CONFIG.config_defaults())
    return config_hash(snapshot, GRAPH_VERSION)


def test_id01_same_key_same_body_replays_the_original_job(env):
    key = str(uuid.uuid4())
    first = _post(env, _body(), key)

    assert first.status_code == 201
    job = first.json()
    assert job["status"] == "queued"
    assert job["allowed_actions"] == ["cancel"]
    assert job["config_digest"] == _expected_digest()
    assert job["graph_version"] == GRAPH_VERSION
    assert job["links"]["self"] == f"/api/v1/jobs/{job['job_id']}"
    assert len(job["stages"]) == 12
    assert [stage["id"] for stage in job["stages"]][0] == "market"
    assert {stage["status"] for stage in job["stages"]} == {"pending"}
    assert first.headers["X-Request-Id"].startswith("req_")

    before = _counts(env.engine)
    second = _post(env, _body(), key)

    assert second.status_code == 200
    assert second.headers["Idempotency-Replayed"] == "1"
    assert second.json()["job_id"] == job["job_id"]
    assert second.json()["created_at"] == job["created_at"]
    assert _counts(env.engine) == before


def test_id02_same_key_different_body_is_mismatch(env):
    key = str(uuid.uuid4())
    assert _post(env, _body(), key).status_code == 201
    before = _counts(env.engine)

    changed = _body(config={**copy.deepcopy(CONFIG), "llm_profile": "openai-default"})
    response = _post(env, changed, key)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "idempotency_mismatch"
    assert error["message"] == "该请求与之前的提交不一致"
    assert error["request_id"] == response.headers["X-Request-Id"]
    assert _counts(env.engine) == before


def test_id02_key_bound_by_step_three_also_rejects_a_different_body(env):
    first = _post(env, _body())
    assert first.status_code == 201
    existing_key = str(uuid.uuid4())

    reused = _post(env, _body(), existing_key)
    assert reused.status_code == 200
    assert reused.headers["X-Existing-Job"] == first.json()["job_id"]

    changed = _body(config={**copy.deepcopy(CONFIG), "parallel_analysts": False})
    response = _post(env, changed, existing_key)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_mismatch"


def test_id03_new_key_same_fingerprint_returns_existing_job(env):
    first = _post(env, _body())
    assert first.status_code == 201
    job_id = first.json()["job_id"]

    second = _post(env, _body())

    assert second.status_code == 200
    assert second.headers["X-Existing-Job"] == job_id
    assert second.json()["job_id"] == job_id
    assert _counts(env.engine) == (1, 1, 2)

    replay = _post(env, _body(), second.request.headers["Idempotency-Key"])
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "1"
    assert _counts(env.engine) == (1, 1, 2)


def test_id04_same_slot_different_config_is_active_conflict(env):
    first = _post(env, _body())
    assert first.status_code == 201
    job_id = first.json()["job_id"]

    other = _body(config={**copy.deepcopy(CONFIG), "parallel_analysts": False})
    response = _post(env, other)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "active_conflict"
    assert error["details"]["active_job_id"] == job_id
    assert set(error["details"]) <= {"active_job_id", "field", "allowed_values"}


def test_id05_twenty_concurrent_creates_make_one_job(env):
    for round_no in range(10):
        ticker = f"{round_no + 1:06d}"
        body = _body(ticker=ticker)
        keys = [str(uuid.uuid4()) for _ in range(20)]

        with ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(
                pool.map(
                    lambda key: env.service.create_job(
                        body, idempotency_key=key
                    ),
                    keys,
                )
            )

        job_ids = {outcome.job.id for outcome in outcomes}
        assert len(job_ids) == 1, f"round {round_no}: {job_ids}"
        assert all(outcome.status_code in (200, 201) for outcome in outcomes)
        assert sum(outcome.status_code == 201 for outcome in outcomes) == 1

        with Session(env.engine) as session:
            active = session.scalars(
                select(Job).where(
                    Job.ticker_code == ticker,
                    Job.status.in_(ACTIVE_STATUSES),
                )
            ).all()
            assert len(active) == 1
            bound_keys = session.scalar(
                select(func.count())
                .select_from(JobIdempotencyKey)
                .where(JobIdempotencyKey.job_id == active[0].id)
            )
            assert bound_keys == 20


def test_id06_get_missing_job_is_404_and_writes_nothing(env):
    before = _counts(env.engine)
    response = env.client.get(f"/api/v1/jobs/{uuid.uuid4()}")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "job_not_found"
    assert error["request_id"] == response.headers["X-Request-Id"]
    assert _counts(env.engine) == before


def test_get_existing_job_returns_the_same_detail(env):
    created = _post(env, _body()).json()
    response = env.client.get(f"/api/v1/jobs/{created['job_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_sm01_created_job_writes_a_created_audit_without_a_seq(env):
    job_id = _post(env, _body()).json()["job_id"]

    with Session(env.engine) as session:
        job = session.get(Job, job_id)
        assert job.status == "queued"
        assert job.idempotency_key is not None
        events = session.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id)
        ).all()
        assert [event.type for event in events] == ["created"]
        assert events[0].seq is None
        assert events[0].payload == {"status": "queued"}

        sse_events = session.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq.is_not(None))
        )
        assert sse_events == 0


def test_missing_idempotency_key_is_400_and_writes_nothing(env):
    before = _counts(env.engine)
    response = env.client.post("/api/v1/jobs", json=_body())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_required"
    assert _counts(env.engine) == before


def test_request_validation_maps_to_contract_codes(env):
    before = _counts(env.engine)

    unknown_key = _post(
        env, _body(config={**copy.deepcopy(CONFIG), "api_key": "leak"})
    )
    assert unknown_key.status_code == 422
    assert unknown_key.json()["error"]["code"] == "config_unknown_key"
    assert unknown_key.json()["error"]["details"]["field"] == "api_key"

    bad_profile = _post(
        env, _body(config={**copy.deepcopy(CONFIG), "llm_profile": "nope"})
    )
    assert bad_profile.status_code == 422
    assert bad_profile.json()["error"]["code"] == "config_invalid_value"
    assert bad_profile.json()["error"]["details"]["allowed_values"] == [
        "deepseek-default",
        "openai-default",
    ]

    future = _post(env, _body(analysis_date="2026-10-31"))
    assert future.status_code == 422
    assert future.json()["error"]["code"] == "invalid_date"

    bad_format = _post(env, _body(analysis_date="2026/10/30"))
    assert bad_format.status_code == 422
    assert bad_format.json()["error"]["code"] == "invalid_date"

    unknown_field = _post(env, {**_body(), "backend_url": "http://evil"})
    assert unknown_field.status_code == 422
    assert unknown_field.json()["error"]["code"] == "invalid_request"

    assert _counts(env.engine) == before


def test_malformed_json_is_400_invalid_request(env):
    response = env.client.post(
        "/api/v1/jobs",
        content=b"{not json",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
