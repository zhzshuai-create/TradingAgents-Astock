"""P4-01 acceptance: envelope builder, merge table and frozen samples.

ENV-01, ENV-02, ENV-07 and ENV-08 live here. The JSON Schema is read from the
frozen contract directory; fixtures are rebuilt through the builder instead of
being compared by hand.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.market_clock import (  # noqa: E402
    CST,
    format_cst,
    latest_trading_day,
    market_session,
    trading_day_mismatch,
)
from backend.app.services.market_envelope import (  # noqa: E402
    BlockResult,
    EnvelopeError,
    build_blocks_envelope,
    build_envelope,
    validate_envelope,
)

CONTRACT = ROOT / "docs" / "upgrade" / "contracts" / "market-data-envelope-v1.json"
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
FETCHED = "2026-10-29T10:15:04+08:00"
AS_OF = "2026-10-29T10:15:03+08:00"


@pytest.fixture(scope="module")
def schema_validator() -> Draft202012Validator:
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def ok_block(_name: str = "quote", **overrides) -> BlockResult:
    values = {
        "status": "ok",
        "source": "tencent",
        "as_of": AS_OF,
        "fetched_at": FETCHED,
        "data": {"value": 1},
    }
    values.update(overrides)
    return BlockResult(**values)


def _single(status: str, **overrides) -> dict:
    values = {
        "status": status,
        "source": "tencent",
        "as_of": AS_OF,
        "fetched_at": FETCHED,
        "data": {"items": []},
    }
    if status == "error":
        values["error_code"] = "upstream_timeout"
    if status == "stale":
        values["stale_reason"] = "ttl_exceeded"
    if status in ("empty", "error"):
        values["as_of"] = None
        values["data"] = None
    values.update(overrides)
    return values


# -- ENV-01 ------------------------------------------------------------------


@pytest.mark.parametrize("status", ["ok", "empty", "error", "stale"])
def test_env01_each_state_passes_schema(status, schema_validator):
    doc = build_envelope(**_single(status))
    validate_envelope(doc)
    schema_validator.validate(doc)
    assert doc["is_stale"] is (status == "stale")
    if status in ("empty", "error"):
        assert doc["data"] is None and doc["as_of"] is None
    if status == "error":
        assert doc["error_code"] == "upstream_timeout"
        assert doc["error_message"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"error_code": None},
        {"as_of": AS_OF},
        {"data": {"x": 1}},
        {"stale_reason": "ttl_exceeded"},
    ],
)
def test_env01_error_state_rejects_bad_fields(overrides):
    with pytest.raises(EnvelopeError):
        build_envelope(**_single("error", **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"data": {"x": 1}},
        {"as_of": AS_OF},
        {"error_code": "upstream_error"},
        {"error_message": "boom"},
        {"stale_reason": "ttl_exceeded"},
    ],
)
def test_env01_empty_state_rejects_bad_fields(overrides):
    with pytest.raises(EnvelopeError):
        build_envelope(**_single("empty", **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"data": None},
        {"as_of": None},
        {"stale_reason": "ttl_exceeded"},
        {"error_code": "upstream_error"},
        {"error_message": "boom"},
    ],
)
def test_env01_ok_state_rejects_bad_fields(overrides):
    with pytest.raises(EnvelopeError):
        build_envelope(**_single("ok", **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"data": None},
        {"as_of": None},
        {"stale_reason": None},
        {"stale_reason": "expired"},
        {"error_code": "upstream_error"},
        {"error_message": "boom"},
    ],
)
def test_env01_stale_state_rejects_bad_fields(overrides):
    with pytest.raises(EnvelopeError):
        build_envelope(**_single("stale", **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "unknown"},
        {"source": "sina"},
        {"partial": True},
        {"partial": False, "failed_blocks": ["quote"]},
    ],
)
def test_env01_envelope_level_constraints(overrides):
    values = _single("ok")
    values.update(overrides)
    with pytest.raises(EnvelopeError):
        build_envelope(**values)


# -- ENV-02 ------------------------------------------------------------------


def test_env02_all_ok():
    doc = build_blocks_envelope(
        {
            "quote": ok_block("quote"),
            "valuation": ok_block("valuation", source="ths"),
        }
    )
    assert doc["status"] == "ok"
    assert doc["partial"] is False
    assert doc["failed_blocks"] == []
    assert doc["source"] == "mixed"
    assert doc["data"]["quote"] == {"value": 1}


def test_env02_all_empty():
    doc = build_blocks_envelope(
        {
            "indices": BlockResult("empty", "tencent", None, FETCHED),
            "northbound": BlockResult("empty", "hexin", None, FETCHED),
        }
    )
    assert doc["status"] == "empty"
    assert doc["partial"] is False
    assert doc["data"] is None
    assert doc["as_of"] is None


def test_env02_all_error():
    doc = build_blocks_envelope(
        {
            "indices": BlockResult(
                "error",
                "tencent",
                None,
                FETCHED,
                error_code="upstream_timeout",
                error_message="超时",
            ),
            "northbound": BlockResult(
                "error",
                "hexin",
                None,
                FETCHED,
                error_code="upstream_error",
                error_message="失败",
            ),
        }
    )
    assert doc["status"] == "error"
    assert doc["error_code"] == "upstream_timeout"
    assert doc["partial"] is False
    assert doc["data"] is None


def test_env02_mixed_usable_and_failed_is_partial():
    doc = build_blocks_envelope(
        {
            "indices": ok_block("indices"),
            "northbound": BlockResult(
                "error",
                "hexin",
                None,
                FETCHED,
                error_code="upstream_error",
                error_message="失败",
            ),
        }
    )
    assert doc["status"] == "ok"
    assert doc["partial"] is True
    assert doc["failed_blocks"] == ["northbound"]
    assert doc["data"]["northbound"] is None
    assert doc["data"]["indices"] == {"value": 1}


def test_env02_ok_and_stale_mix_is_stale():
    doc = build_blocks_envelope(
        {
            "quote": ok_block("quote"),
            "valuation": ok_block(
                "valuation", status="stale", stale_reason="trading_day_mismatch"
            ),
        }
    )
    assert doc["status"] == "stale"
    assert doc["stale_reason"] == "trading_day_mismatch"
    assert doc["as_of"] == AS_OF


def test_env02_primary_as_of_falls_back_to_first_usable():
    old = "2026-10-28T15:00:00+08:00"
    doc = build_blocks_envelope(
        {
            "quote": BlockResult(
                "error", "tencent", None, FETCHED, error_code="upstream_error",
                error_message="失败",
            ),
            "valuation": ok_block("valuation", as_of=old),
        }
    )
    assert doc["as_of"] == old
    assert doc["partial"] is True


# -- clock / ENV-07 ----------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (9, 29, "pre_open"),
        (9, 30, "trading"),
        (11, 29, "trading"),
        (11, 30, "lunch_break"),
        (12, 59, "lunch_break"),
        (13, 0, "trading"),
        (14, 59, "trading"),
        (15, 0, "closed"),
        (15, 1, "closed"),
    ],
)
def test_session_boundaries(hour, minute, expected):
    now = datetime(2026, 11, 5, hour, minute, tzinfo=CST)
    assert market_session(now) == expected


def test_weekend_is_closed_and_trading_day_is_last_weekday():
    sunday = datetime(2026, 11, 8, 10, 0, tzinfo=CST)
    assert market_session(sunday) == "closed"
    assert latest_trading_day(sunday).isoformat() == "2026-11-06"


def test_trading_day_mismatch_compares_against_latest_trading_day():
    friday = datetime(2026, 11, 6, 10, 0, tzinfo=CST)
    assert trading_day_mismatch("2026-11-05", friday) is True
    assert trading_day_mismatch("2026-11-06", friday) is False
    sunday = datetime(2026, 11, 8, 10, 0, tzinfo=CST)
    assert trading_day_mismatch("2026-11-06", sunday) is False


def test_fetched_at_uses_cst_offset():
    text = format_cst(datetime(2026, 10, 29, 10, 15, 4, tzinfo=CST))
    assert text == "2026-10-29T10:15:04+08:00"
    assert text.endswith("+08:00")


@pytest.mark.parametrize("as_of", ["2026-10-29", "2026-10-29T10:15:03+08:00"])
def test_env07_both_as_of_shapes_pass_schema(as_of, schema_validator):
    doc = build_envelope(**_single("ok", as_of=as_of))
    schema_validator.validate(doc)


# -- ENV-08 ------------------------------------------------------------------


def _rebuild(sample: str) -> dict:
    doc = json.loads((FIXTURES / sample).read_text(encoding="utf-8"))
    if "blocks" not in doc:
        return build_envelope(
            status=doc["status"],
            source=doc["source"],
            as_of=doc["as_of"],
            fetched_at=doc["fetched_at"],
            data=doc["data"],
            stale_reason=doc["stale_reason"],
            error_code=doc["error_code"],
            error_message=doc["error_message"],
        )
    data = doc["data"] or {}
    blocks = {
        name: BlockResult(
            status=block["status"],
            source=block["source"],
            as_of=block["as_of"],
            fetched_at=block["fetched_at"],
            data=data.get(name),
            stale_reason=block["stale_reason"],
            error_code=block["error_code"],
            error_message=block["error_message"],
        )
        for name, block in doc["blocks"].items()
    }
    extra = {key: value for key, value in data.items() if key not in blocks}
    return build_blocks_envelope(blocks, extra_data=extra, fetched_at=doc["fetched_at"])


@pytest.mark.parametrize(
    "sample",
    [
        "market_ok.json",
        "market_empty.json",
        "market_error.json",
        "market_stale.json",
        "market_partial.json",
    ],
)
def test_env08_frozen_samples_rebuild_identically(sample, schema_validator):
    expected = json.loads((FIXTURES / sample).read_text(encoding="utf-8"))
    rebuilt = _rebuild(sample)
    assert rebuilt == expected
    schema_validator.validate(rebuilt)
