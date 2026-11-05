"""P1-12 acceptance tests: legacy report -> report-v1 DTO.

T1: the four golden DTO fixtures validate against report-schema-v1.json.
T2: the schema rejects six classes of violation.
T3: legacy_report_v1 keys stay inside the legacy key set.
T5: rating -> signal mapping is the five-tier table.
T6: rating is parsed only from the literal ``**Rating**:`` label; keywords in
    body text never leak into ``meta.rating``.
T7: ``signal_legacy`` is archived and no product module other than
    ``report_schema`` reads it.
T8: ``trader_investment_plan`` survives only in ``legacy_aliases``; no time
    field is invented.
T10: ``content_hash`` is stable per DTO and changes with any section body.
T11: missing data stays missing: no ``sec-quality`` without a summary, decision
    facts are null, nothing is filled in.
RC-01: legacy keys do not exceed the documented set.
RC-02: rendering-facing ``signal`` comes from ``rating``, not the legacy scan.
RC-03: ``content_hash`` recomputes from the converted sections.

T9/T12/T13 rendering assertions (web outline, markdown headings, PDF bookmarks,
DOM escaping) need the P3 renderers and are not part of this ticket.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_legacy_golden.py -q
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.report_document import (  # noqa: E402
    RATING_TO_SIGNAL,
    compute_content_hash,
)
from backend.app.services.report_schema import (  # noqa: E402
    LEGACY_KEYS,
    SECTION_IDS,
    SECTION_TITLES,
    build_legacy_report,
    clean_body,
)

FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
SCHEMA_PATH = ROOT / "docs" / "upgrade" / "contracts" / "report-schema-v1.json"
GOLDEN_DTOS = (
    "final_state_v1",
    "missing_fields_report",
    "long_report",
    "unsafe_text_report",
)
FIXED_REPORT_ID = "11111111-4b5a-6978-8765-4321fedcba98"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema):
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def legacy() -> dict:
    return _load("legacy_report_v1")


@pytest.fixture()
def converted(legacy) -> dict:
    return build_legacy_report(legacy, report_id=FIXED_REPORT_ID)


def _minimal_legacy(**overrides) -> dict:
    data = {
        "company_of_interest": "000629",
        "trade_date": "2026-10-24",
        "final_trade_decision": "**Rating**: Hold\n\n正文。",
    }
    data.update(overrides)
    return data


def test_section_catalog_matches_golden_order(converted):
    golden = _load("final_state_v1")
    assert tuple(golden["sections"]) == SECTION_IDS
    assert tuple(converted["sections"]) == tuple(
        section_id for section_id in SECTION_IDS if section_id in converted["sections"]
    )
    assert dict(SECTION_TITLES)["sec-quality"] == "数据质量"


def test_t1_golden_dtos_validate(validator):
    for name in GOLDEN_DTOS:
        validator.validate(_load(name))


def _violate_signal(dto):
    dto["meta"]["signal"] = "Sell"
    return dto


def _violate_legacy_generated_at(dto):
    dto["meta"]["origin"] = "legacy_import"
    dto["meta"]["generated_at"] = "2026-10-24T15:30:00+08:00"
    return dto


def _violate_section_id(dto):
    dto["sections"]["sec-bogus"] = {
        "id": "sec-bogus",
        "title": "伪造章节",
        "body": "x",
    }
    return dto


def _violate_rating(dto):
    dto["meta"]["rating"] = "StrongBuy"
    return dto


def _violate_ticker(dto):
    dto["meta"]["ticker_code"] = "629"
    return dto


def _violate_extra_meta(dto):
    dto["meta"]["invented"] = True
    return dto


def _violate_extra_top(dto):
    dto["extra"] = []
    return dto


@pytest.mark.parametrize(
    "mutate",
    [
        _violate_signal,
        _violate_legacy_generated_at,
        _violate_section_id,
        _violate_rating,
        _violate_ticker,
        _violate_extra_meta,
        _violate_extra_top,
    ],
    ids=[
        "signal-contradicts-rating",
        "legacy-with-generated-at",
        "unknown-section-id",
        "rating-out-of-enum",
        "ticker-not-six-digits",
        "extra-meta-field",
        "extra-top-level-field",
    ],
)
def test_t2_schema_rejects_violations(validator, mutate):
    dto = mutate(copy.deepcopy(_load("final_state_v1")))
    with pytest.raises(ValidationError):
        validator.validate(dto)


def test_t3_legacy_keys_within_documented_set(legacy):
    assert set(legacy) <= LEGACY_KEYS
    assert len(legacy) == 14


@pytest.mark.parametrize(
    ("label", "rating", "signal"),
    [
        ("Buy", "Buy", "Buy"),
        ("Overweight", "Overweight", "Buy"),
        ("Hold", "Hold", "Hold"),
        ("Underweight", "Underweight", "Sell"),
        ("Sell", "Sell", "Sell"),
    ],
)
def test_t5_rating_to_signal_table(label, rating, signal):
    dto = build_legacy_report(
        _minimal_legacy(final_trade_decision=f"**Rating**: {label}"), report_id=FIXED_REPORT_ID
    )
    assert dto["meta"]["rating"] == rating
    assert dto["meta"]["signal"] == signal == RATING_TO_SIGNAL[label]


def test_t6_rating_is_parsed_not_guessed(legacy):
    dto = build_legacy_report(legacy, report_id=FIXED_REPORT_ID)
    assert dto["meta"]["rating"] == "Underweight"
    assert dto["meta"]["signal"] == "Sell"

    contradictory = _minimal_legacy(
        investment_plan="BUY on the dip",
        trader_investment_decision="FINAL TRANSACTION PROPOSAL: **HOLD**",
        final_trade_decision="**Rating**: Sell\n\n正文。",
    )
    dto = build_legacy_report(contradictory, report_id=FIXED_REPORT_ID)
    assert dto["meta"]["signal_legacy"] == "Buy"
    assert dto["meta"]["rating"] == "Sell"
    assert dto["meta"]["signal"] == "Sell"

    unlabelled = _minimal_legacy(final_trade_decision="BUY now, strong momentum")
    assert build_legacy_report(unlabelled)["meta"]["rating"] == "unknown"

    off_table = _minimal_legacy(final_trade_decision="**Rating**: Strong Buy")
    assert build_legacy_report(off_table)["meta"]["rating"] == "unknown"


def test_t7_signal_legacy_is_archived_only():
    sources = [
        path
        for path in (ROOT / "backend").rglob("*.py")
        if "signal_legacy" in path.read_text(encoding="utf-8")
    ]
    assert [path.name for path in sources] == ["report_schema.py"]


def test_t8_trader_investment_plan_is_alias_only(legacy, converted):
    assert "legacy_aliases" not in converted["sections"]["sec-plan"]

    variant = copy.deepcopy(legacy)
    variant["trader_investment_plan"] = "旧的交易员计划：分批减仓。"
    dto = build_legacy_report(variant, report_id=FIXED_REPORT_ID)
    plan = dto["sections"]["sec-plan"]
    assert plan["legacy_aliases"] == {
        "trader_investment_plan": "旧的交易员计划：分批减仓。"
    }
    assert "分批减仓" not in plan["body"]
    bodies = [
        body
        for section in dto["sections"].values()
        for body in [section["body"], *section.get("parts", {}).values()]
    ]
    assert all("旧的交易员计划" not in body for body in bodies)

    same = copy.deepcopy(legacy)
    same["trader_investment_plan"] = same["investment_plan"]
    assert "legacy_aliases" not in build_legacy_report(same)["sections"]["sec-plan"]

    assert dto["meta"]["generated_at"] is None
    assert dto["meta"]["generated_at_source"] == "unknown"


def test_t10_content_hash_is_stable_and_body_sensitive(legacy, converted):
    again = build_legacy_report(legacy, report_id=FIXED_REPORT_ID)
    assert again["meta"]["content_hash"] == converted["meta"]["content_hash"]

    changed = copy.deepcopy(converted)
    changed["sections"]["sec-market"]["body"] += " "
    assert compute_content_hash(changed["sections"]) != converted["meta"]["content_hash"]


def test_t11_missing_data_stays_missing(converted):
    assert "sec-quality" not in converted["sections"]
    assert converted["meta"]["data_quality_status"] == "absent"

    minimal = build_legacy_report(
        {"company_of_interest": "000629", "trade_date": "2026-10-24"}
    )
    assert minimal["meta"]["rating"] == "unknown"
    assert minimal["meta"]["signal"] == "unknown"
    assert minimal["meta"]["price_target"] is None
    assert minimal["meta"]["stop_reference"] is None
    assert minimal["meta"]["time_horizon"] is None
    assert minimal["meta"]["signal_legacy"] == "N/A"
    assert "sec-decision" not in minimal["sections"]


def test_cleaning_strips_think_blocks_and_bare_fences():
    assert clean_body("<think>隐藏</think>\n正文") == "正文"
    assert clean_body("```markdown\n正文\n```") == "正文"
    assert clean_body(None) == ""


def test_rc01_legacy_conversion_uses_documented_keys(legacy, converted):
    assert set(legacy) <= LEGACY_KEYS
    assert re.fullmatch(r"[0-9a-f]{64}", converted["meta"]["content_hash"])
    assert converted["sections"]["sec-risk"]["parts_ref"] == {"judge": "sec-decision"}
    assert "judge" not in converted["sections"]["sec-risk"]["parts"]
    assert list(converted["sections"]["sec-debate"]["parts"]) == [
        "bull",
        "bear",
        "history",
        "current",
        "judge",
    ]


def test_rc02_rendered_signal_ignores_legacy_scan():
    legacy = _minimal_legacy(
        investment_plan="SELL everything",
        final_trade_decision="**Rating**: Buy\n\n正文。",
    )
    dto = build_legacy_report(legacy, report_id=FIXED_REPORT_ID)
    assert dto["meta"]["signal_legacy"] == "Sell"
    assert dto["meta"]["signal"] == "Buy"
    assert dto["meta"]["signal"] == RATING_TO_SIGNAL[dto["meta"]["rating"]]


def test_rc03_content_hash_recomputes(converted):
    assert compute_content_hash(converted["sections"]) == converted["meta"]["content_hash"]
