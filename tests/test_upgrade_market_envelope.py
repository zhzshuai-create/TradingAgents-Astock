"""P0 Day 4：市场数据信封、错误码与接口契约的机器校验。

只读 docs/ 与 tests/fixtures/，不启动服务、不联网。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs" / "upgrade" / "contracts"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"

SCHEMA = json.loads((CONTRACTS / "market-data-envelope-v1.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

ENVELOPE_FILES = [
    "market_ok.json",
    "market_empty.json",
    "market_error.json",
    "market_stale.json",
    "market_partial.json",
]

MINIMUM_FIELDS = [
    "status",
    "source",
    "as_of",
    "fetched_at",
    "is_stale",
    "error_code",
    "data",
]

LEAK_PATTERNS = [
    "Traceback (most recent call last)",
    'File "',
    "sk-",
    "api_key",
    "Authorization",
    "token=",
    "C:\\",
    "/home/",
    "/Users/",
]

SSE_EVENT_TYPES = [
    "snapshot",
    "stage_changed",
    "stats",
    "status_changed",
    "report_ready",
    "error",
]

JOB_ENDPOINTS = [
    "POST /api/v1/jobs",
    "GET /api/v1/jobs",
    "GET /api/v1/jobs/{jobId}",
    "POST /api/v1/jobs/{jobId}/actions",
    "POST /api/v1/jobs/{jobId}/retry",
    "GET /api/v1/jobs/{jobId}/events",
    "GET /api/v1/jobs/{jobId}/stages/{stageId}",
]

REPORT_ENDPOINTS = [
    "GET /api/v1/reports",
    "GET /api/v1/reports/{reportId}",
    "GET /api/v1/reports/{reportId}/markdown",
    "POST /api/v1/reports/{reportId}/exports/pdf",
]


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def errors_for(doc: dict) -> list[str]:
    return [
        f"{list(err.absolute_path)}: {err.message}"
        for err in VALIDATOR.iter_errors(doc)
    ]


@pytest.mark.parametrize("name", ENVELOPE_FILES)
def test_fixture_matches_schema(name: str) -> None:
    assert errors_for(load(name)) == []


@pytest.mark.parametrize("name", ENVELOPE_FILES)
def test_fixture_has_minimum_fields(name: str) -> None:
    doc = load(name)
    missing = [f for f in MINIMUM_FIELDS if f not in doc]
    assert missing == []


def test_four_states_all_covered() -> None:
    statuses = {load(n)["status"] for n in ENVELOPE_FILES}
    assert statuses == {"ok", "empty", "error", "stale"}


@pytest.mark.parametrize("name", ENVELOPE_FILES)
def test_is_stale_matches_status(name: str) -> None:
    doc = load(name)
    assert doc["is_stale"] is (doc["status"] == "stale")


def test_empty_is_not_error() -> None:
    doc = load("market_empty.json")
    assert doc["status"] == "empty"
    assert doc["data"] is None
    assert doc["error_code"] is None
    assert doc["as_of"] is None


def test_error_carries_code_and_no_data() -> None:
    doc = load("market_error.json")
    assert doc["status"] == "error"
    assert doc["data"] is None
    assert doc["as_of"] is None
    assert isinstance(doc["error_code"], str) and doc["error_code"]


def test_stale_keeps_data_and_says_why() -> None:
    doc = load("market_stale.json")
    assert doc["status"] == "stale"
    assert doc["data"] is not None
    assert doc["as_of"] is not None
    assert doc["stale_reason"] == "trading_day_mismatch"


def test_partial_success_is_block_level() -> None:
    doc = load("market_partial.json")
    assert doc["status"] == "ok"
    assert doc["partial"] is True
    assert doc["failed_blocks"] == ["northbound"]
    blocks = doc["blocks"]
    assert blocks["indices"]["status"] == "ok"
    assert blocks["northbound"]["status"] == "error"
    assert blocks["northbound"]["error_code"]
    assert doc["error_code"] is None
    assert doc["data"]["northbound"] is None
    assert doc["data"]["indices"]


def test_blocks_are_state_only() -> None:
    for name in ("market_ok.json", "market_stale.json", "market_partial.json"):
        doc = load(name)
        for block_name, block in doc["blocks"].items():
            assert "data" not in block, f"{name}:{block_name} 不应携带数据"
            for field in ("status", "source", "as_of", "fetched_at", "is_stale", "error_code"):
                assert field in block, f"{name}:{block_name} 缺 {field}"


def test_schema_rejects_confused_states() -> None:
    base = load("market_ok.json")

    error_with_data = copy.deepcopy(base)
    error_with_data["status"] = "error"
    error_with_data["error_code"] = "upstream_error"
    error_with_data["error_message"] = "数据服务暂时不可用"
    assert errors_for(error_with_data), "error 态不应允许携带 data"

    ok_with_code = copy.deepcopy(base)
    ok_with_code["error_code"] = "upstream_error"
    assert errors_for(ok_with_code), "ok 态不应允许 error_code"

    stale_not_marked = copy.deepcopy(load("market_stale.json"))
    stale_not_marked["is_stale"] = False
    assert errors_for(stale_not_marked), "stale 态必须 is_stale = true"

    empty_with_code = copy.deepcopy(load("market_empty.json"))
    empty_with_code["error_code"] = "upstream_timeout"
    assert errors_for(empty_with_code), "empty 不应携带错误码"

    partial_without_failed = copy.deepcopy(load("market_partial.json"))
    partial_without_failed["failed_blocks"] = []
    assert errors_for(partial_without_failed), "partial = true 时 failed_blocks 必须非空"

    unknown_status = copy.deepcopy(base)
    unknown_status["status"] = "partial"
    assert errors_for(unknown_status), "status 只有四个值，不接受第五种"


def test_fixtures_do_not_leak_internals() -> None:
    for name in ENVELOPE_FILES:
        text = (FIXTURES / name).read_text(encoding="utf-8")
        hits = [p for p in LEAK_PATTERNS if p in text]
        assert hits == [], f"{name} 含敏感片段: {hits}"


def test_error_codes_exist_in_dictionary() -> None:
    dictionary = (CONTRACTS / "error-codes-v1.md").read_text(encoding="utf-8-sig")
    known = set(re.findall(r"^\|\s*`([a-z][a-z0-9_]*)`\s*\|", dictionary, flags=re.M))
    used = set()
    for name in ENVELOPE_FILES:
        doc = load(name)
        if doc["error_code"]:
            used.add(doc["error_code"])
        for block in (doc.get("blocks") or {}).values():
            if block["error_code"]:
                used.add(block["error_code"])
    assert used, "样本里至少要出现一个数据源码"
    assert used <= known, f"字典缺少: {sorted(used - known)}"


def test_sse_contract_lists_six_events() -> None:
    text = (CONTRACTS / "sse-events-v1.md").read_text(encoding="utf-8-sig")
    for event_type in SSE_EVENT_TYPES:
        assert f"`{event_type}`" in text, f"缺少事件类型 {event_type}"
    for rule in ("Last-Event-ID", "sse_cursor_expired", "text/event-stream"):
        assert rule in text, f"缺少 {rule}"


def test_api_contract_freezes_paths() -> None:
    text = (CONTRACTS / "api-v1.md").read_text(encoding="utf-8-sig")
    for path in JOB_ENDPOINTS + REPORT_ENDPOINTS:
        assert path in text, f"缺少接口 {path}"
    assert "Idempotency-Key" in text
    assert "已受理，不等于生效" in text or "受理不等于生效" in text


def test_wireframe_gaps_written_back() -> None:
    api = (CONTRACTS / "api-v1.md").read_text(encoding="utf-8-sig")
    errors = (CONTRACTS / "error-codes-v1.md").read_text(encoding="utf-8-sig")
    for needle in ("stage_not_found", "default_analysis_date", "journal.reason", "active=true", "rating="):
        assert needle in api, f"api-v1 缺少线框回写字段 {needle}"
    assert "`stage_not_found`" in errors
