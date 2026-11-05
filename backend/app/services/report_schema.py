"""Convert a legacy ``full_states_log`` state dict into a report-v1 DTO.

report-schema-v1 section 5 maps every legacy key to exactly one v1 path. The
rules that matter here:

* Sections are keyed by stable ids, ordered by ``SECTION_TITLES``; render order
  never comes from dict insertion or array position.
* A missing or empty source key drops the whole chapter; nothing is invented.
* ``rating`` is parsed only from the literal ``**Rating**: X`` label and must be
  exactly one of the five tiers — otherwise ``unknown``. ``signal`` derives from
  ``rating`` via ``RATING_TO_SIGNAL``; the old keyword scan is archived as
  ``signal_legacy`` and is not displayed.
* ``risk_debate_state.judge_decision`` usually repeats ``final_trade_decision``;
  it becomes a ``parts_ref`` pointing at ``sec-decision`` instead of a copy.
* ``trader_investment_plan`` is deprecated: it survives only as a
  ``legacy_aliases`` entry, never as body text.
* Legacy imports carry no real generation time, so ``generated_at`` stays null
  and ``generated_at_source`` is ``unknown`` — the file mtime is never used.

This module is pure data transformation: it does not touch the database, the
filesystem or the network, and it does not import ``web`` (GF-06 boundary).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from backend.app.services.report_document import (
    RATING_TO_SIGNAL,
    SCHEMA_VERSION,
    compute_content_hash,
)

# (section id, title) in contract order (report-schema-v1 section 3).
SECTION_TITLES: tuple[tuple[str, str], ...] = (
    ("sec-decision", "最终交易决策"),
    ("sec-market", "技术分析"),
    ("sec-sentiment", "市场情绪"),
    ("sec-news", "新闻舆情"),
    ("sec-fundamentals", "基本面"),
    ("sec-policy", "政策分析"),
    ("sec-hot-money", "游资追踪"),
    ("sec-lockup", "解禁/减持"),
    ("sec-quality", "数据质量"),
    ("sec-debate", "多空辩论"),
    ("sec-trader", "交易员决策"),
    ("sec-plan", "最终投资建议"),
    ("sec-risk", "风控评估"),
)
SECTION_IDS = tuple(section_id for section_id, _ in SECTION_TITLES)
_TITLES = dict(SECTION_TITLES)

LEGACY_KEYS = frozenset(
    {
        "company_of_interest",
        "trade_date",
        "market_report",
        "sentiment_report",
        "news_report",
        "fundamentals_report",
        "policy_report",
        "hot_money_report",
        "lockup_report",
        "data_quality_summary",
        "investment_debate_state",
        "trader_investment_decision",
        "trader_investment_plan",
        "investment_plan",
        "final_trade_decision",
        "risk_debate_state",
    }
)

ANALYST_SECTIONS = (
    ("market_report", "sec-market"),
    ("sentiment_report", "sec-sentiment"),
    ("news_report", "sec-news"),
    ("fundamentals_report", "sec-fundamentals"),
    ("policy_report", "sec-policy"),
    ("hot_money_report", "sec-hot-money"),
    ("lockup_report", "sec-lockup"),
)
DEBATE_PARTS = (
    ("bull_history", "bull"),
    ("bear_history", "bear"),
    ("history", "history"),
    ("current_response", "current"),
    ("judge_decision", "judge"),
)
RISK_PARTS = (
    ("aggressive_history", "aggressive"),
    ("conservative_history", "conservative"),
    ("neutral_history", "neutral"),
    ("history", "history"),
)

_DECISION_KEYS = (
    "final_trade_decision",
    "investment_plan",
    "trader_investment_decision",
)

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE_RE = re.compile(r"^[ \t]*```[^\n]*\n?", re.MULTILINE)
_RATING_RE = re.compile(r"\*\*Rating\*\*\s*[:：]\s*([^\n*]+)")
_PRICE_TARGET_RES = (
    re.compile(r"\*\*Price Target\*\*\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)"),
    re.compile(r"目标价[^0-9{（(]{0,8}([0-9]+(?:\.[0-9]+)?)"),
)
_STOP_RES = (re.compile(r"(?:止损|止损位|硬止损)[^0-9{（(]{0,8}([0-9]+(?:\.[0-9]+)?)"),)
_HORIZON_RES = (
    re.compile(r"\*\*Time Horizon\*\*\s*[:：]\s*([^\n*]+)"),
    re.compile(r"时间(?:范围|周期|跨度)[:：]\s*([^\n，。;；]+)"),
)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def clean_body(value: Any) -> str:
    """Drop think blocks and bare code fences, then trim."""
    text = _strip_think(str(value)) if value is not None else ""
    return _FENCE_RE.sub("", text).strip()


def _legacy_signal(legacy: Mapping[str, Any]) -> str:
    """Mirror of ``web/history.py::extract_signal``; archived, never rendered."""
    for key in ("investment_plan", "trader_investment_decision", "final_trade_decision"):
        text = str(legacy.get(key) or "")
        if not text:
            continue
        cleaned = _strip_think(text).upper()
        for keyword in ("BUY", "SELL", "HOLD"):
            if keyword in cleaned:
                return keyword.capitalize()
    return "N/A"


def _find(patterns: tuple[re.Pattern[str], ...], texts: list[str]) -> str | None:
    for text in texts:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                value = match.group(1).strip().rstrip("*").strip()
                if value:
                    return value
    return None


def _parse_rating(texts: list[str]) -> str:
    for text in texts:
        match = _RATING_RE.search(text)
        if match:
            value = match.group(1).strip()
            return value if value in RATING_TO_SIGNAL else "unknown"
    return "unknown"


def _section(section_id: str, body: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": section_id,
        "title": _TITLES[section_id],
        "body": body,
    }
    payload.update(extra)
    return payload


def _parts(source: Any, mapping: tuple[tuple[str, str], ...]) -> dict[str, str]:
    if not isinstance(source, Mapping):
        return {}
    parts: dict[str, str] = {}
    for old_key, part_key in mapping:
        body = clean_body(source.get(old_key))
        if body:
            parts[part_key] = body
    return parts


def build_legacy_report(
    legacy: Mapping[str, Any], *, report_id: str | None = None
) -> dict[str, Any]:
    """Return a report-v1 DTO for a legacy state dict.

    ``report_id`` is injectable so callers (and tests) can assert that the same
    input yields the same output.
    """
    decision = clean_body(legacy.get("final_trade_decision"))
    plan = clean_body(legacy.get("investment_plan"))
    texts = [clean_body(legacy.get(key)) for key in _DECISION_KEYS]
    texts = [text for text in texts if text]

    sections: dict[str, dict[str, Any]] = {}
    if decision:
        sections["sec-decision"] = _section("sec-decision", decision)
    for old_key, section_id in ANALYST_SECTIONS:
        body = clean_body(legacy.get(old_key))
        if body:
            sections[section_id] = _section(section_id, body)

    quality = clean_body(legacy.get("data_quality_summary"))
    if quality:
        sections["sec-quality"] = _section("sec-quality", quality)

    debate_parts = _parts(legacy.get("investment_debate_state"), DEBATE_PARTS)
    if debate_parts:
        sections["sec-debate"] = _section("sec-debate", "", parts=debate_parts)

    trader = clean_body(legacy.get("trader_investment_decision"))
    if trader:
        sections["sec-trader"] = _section("sec-trader", trader)

    plan_aliases = clean_body(legacy.get("trader_investment_plan"))
    if plan_aliases and plan_aliases == plan:
        plan_aliases = ""
    if plan or plan_aliases:
        extra: dict[str, Any] = {}
        if plan_aliases:
            extra["legacy_aliases"] = {"trader_investment_plan": plan_aliases}
        sections["sec-plan"] = _section("sec-plan", plan, **extra)

    risk_source = legacy.get("risk_debate_state")
    risk_parts = _parts(risk_source, RISK_PARTS)
    risk_judge = clean_body(risk_source.get("judge_decision")) if isinstance(
        risk_source, Mapping
    ) else ""
    risk_ref: dict[str, str] = {}
    if risk_judge:
        if risk_judge == decision:
            risk_ref = {"judge": "sec-decision"}
        else:
            risk_parts["judge"] = risk_judge
    if risk_parts or risk_ref:
        extra = {}
        if risk_ref:
            extra["parts_ref"] = risk_ref
        sections["sec-risk"] = _section("sec-risk", "", **extra)
        if risk_parts:
            sections["sec-risk"]["parts"] = risk_parts

    rating = _parse_rating(texts)
    target = _find(_PRICE_TARGET_RES, texts)
    meta = {
        "report_id": report_id or str(uuid.uuid4()),
        "job_id": None,
        "ticker_code": str(legacy.get("company_of_interest") or "").strip(),
        "ticker_name": None,
        "analysis_date": str(legacy.get("trade_date") or "").strip(),
        "generated_at": None,
        "generated_at_source": "unknown",
        "origin": "legacy_import",
        "schema_version": SCHEMA_VERSION,
        "content_hash": compute_content_hash(sections),
        "config_digest": None,
        "data_quality_status": "absent",
        "chart_snapshot_status": "none",
        "retry_of_job_id": None,
        "rating": rating,
        "signal": RATING_TO_SIGNAL[rating],
        "signal_legacy": _legacy_signal(legacy),
        "price_target": float(target) if target is not None else None,
        "stop_reference": _find(_STOP_RES, texts),
        "time_horizon": _find(_HORIZON_RES, texts),
    }
    return {"meta": meta, "sections": sections}
