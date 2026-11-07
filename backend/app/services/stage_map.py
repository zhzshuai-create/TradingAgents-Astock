"""Contract stage catalog and legacy state-dict mapping for the real runner.

The legacy UI detects stage completion from the streamed state chunk
(``web/runner._detect_completed_stages``). The backend may not import ``web``,
so the mapping is restated here and kept honest by a sync test that compares
both sides (tests/backend/test_real_runner.py RR-06).

Only ``<think>`` blocks are stripped from stage bodies. The legacy stock-name
normalization lives in ``web/stock_display.py`` and is deliberately not
reproduced; see P6-04pre 交接卡 第五节.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from backend.app.models.stage import STAGE_IDS, STAGE_NAMES

THINK_TAG_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

ANALYST_SOURCES: tuple[tuple[str, str], ...] = (
    ("market", "market_report"),
    ("social", "sentiment_report"),
    ("news", "news_report"),
    ("fundamentals", "fundamentals_report"),
    ("policy", "policy_report"),
    ("hot_money", "hot_money_report"),
    ("lockup", "lockup_report"),
)

FLAT_SOURCES: tuple[tuple[str, str], ...] = (
    ("quality_gate", "data_quality_summary"),
    ("trader", "trader_investment_plan"),
    ("pm", "final_trade_decision"),
)

NESTED_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("debate", "investment_debate_state", "judge_decision"),
    ("risk", "risk_debate_state", "judge_decision"),
)

# Legacy ``PIPELINE_STAGES`` display metadata. debate/risk report the whole
# debate state key even though completion is detected from judge_decision.
REPORT_KEYS: dict[str, str] = {
    **dict(ANALYST_SOURCES),
    "quality_gate": "data_quality_summary",
    "debate": "investment_plan",
    "trader": "trader_investment_plan",
    "risk": "risk_debate_state",
    "pm": "final_trade_decision",
}

ANALYST_ORDER: tuple[str, ...] = (
    "market",
    "social",
    "news",
    "fundamentals",
    "policy",
    "hot_money",
    "lockup",
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return THINK_TAG_RE.sub("", text).strip()


def stage_name(stage_id: str) -> str:
    return STAGE_NAMES[stage_id]


def selected_analysts(toggles: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Four fixed analysts plus the toggled A-share specialists, in graph order."""
    if toggles is None:
        return ANALYST_ORDER
    chosen = ["market", "social", "news", "fundamentals"]
    for stage_id in ("policy", "hot_money", "lockup"):
        if toggles.get(stage_id, True):
            chosen.append(stage_id)
    return tuple(chosen)


def expected_stages(analysts: tuple[str, ...]) -> tuple[str, ...]:
    """Stage ids a run can produce, in contract order."""
    enabled = set(analysts) | {"quality_gate", "debate", "trader", "risk", "pm"}
    return tuple(stage_id for stage_id in STAGE_IDS if stage_id in enabled)


def detected_stages(state: Mapping[str, Any]) -> dict[str, str]:
    """Stage id -> non-empty body for every stage this chunk has completed."""
    bodies: dict[str, str] = {}
    for stage_id, key in ANALYST_SOURCES:
        text = clean_text(state.get(key))
        if text:
            bodies[stage_id] = text
    for stage_id, key in FLAT_SOURCES:
        text = clean_text(state.get(key))
        if text:
            bodies[stage_id] = text
    for stage_id, key, nested in NESTED_SOURCES:
        source = state.get(key)
        if not isinstance(source, Mapping):
            continue
        text = clean_text(source.get(nested))
        if text:
            bodies[stage_id] = text
    return {stage_id: bodies[stage_id] for stage_id in STAGE_IDS if stage_id in bodies}
