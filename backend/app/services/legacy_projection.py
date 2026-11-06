"""Project the newest report for one ticker/date back into the legacy log tree.

``web/history.py`` lists ``<HOME>/.tradingagents/logs/<ticker>/
TradingAgentsStrategy_logs/full_states_log_<date>.json`` and renders the state
dict directly. This module writes that file from a report-v1 DTO so the old
Streamlit entry keeps opening reports produced by the new worker (P3-08).

Only the newest report for the key is projected. The old format has no slot for
several v1 structures, so those parts are concatenated into the rendered judge
tabs instead of being dropped; the mapping is one-way and never imports
``web`` (GF-06).

Writes are best effort: a backup is copied next to the target, the new document
goes through a same-directory temp file and ``os.replace``, and any failure is
logged without touching the report row or the job status.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.models.report import Report

LEGACY_PROJECTION_ENV = "TA_LEGACY_PROJECTION"
STRATEGY_DIR = "TradingAgentsStrategy_logs"
LOGS_DIR = (".tradingagents", "logs")

_TICKER_RE = re.compile(r"^[0-9]{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ANALYST_KEYS: tuple[tuple[str, str], ...] = (
    ("market_report", "sec-market"),
    ("sentiment_report", "sec-sentiment"),
    ("news_report", "sec-news"),
    ("fundamentals_report", "sec-fundamentals"),
    ("policy_report", "sec-policy"),
    ("hot_money_report", "sec-hot-money"),
    ("lockup_report", "sec-lockup"),
)
DEBATE_PARTS: tuple[tuple[str, str], ...] = (
    ("bull_history", "bull"),
    ("bear_history", "bear"),
    ("history", "history"),
    ("current_response", "current"),
)
RISK_PARTS: tuple[tuple[str, str], ...] = (
    ("aggressive_history", "aggressive"),
    ("conservative_history", "conservative"),
    ("neutral_history", "neutral"),
    ("history", "history"),
)

PROJECTED = "projected"
SKIPPED = "skipped"
FAILED = "failed"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectionOutcome:
    status: str
    report_id: str | None = None
    path: Path | None = None
    backup_path: Path | None = None
    reason: str | None = None


def projection_enabled(environ: Mapping[str, str] | None = None) -> bool:
    value = (os.environ if environ is None else environ).get(LEGACY_PROJECTION_ENV)
    return str(value if value is not None else "1").strip() != "0"


def default_logs_root() -> Path:
    return Path.home().joinpath(*LOGS_DIR)


def latest_for_key(engine: Engine, ticker_code: str, analysis_date: str) -> dict[str, Any] | None:
    """Newest report for the key; a null generated_at sorts last."""
    with Session(engine) as session:
        row = session.scalars(
            select(Report)
            .where(
                Report.ticker_code == ticker_code,
                Report.analysis_date == analysis_date,
            )
            .order_by(
                Report.generated_at.is_(None),
                Report.generated_at.desc(),
                Report.created_at.desc(),
                Report.report_id.asc(),
            )
            .limit(1)
        ).first()
        return dict(row.payload) if row is not None else None


def project_latest(
    engine: Engine,
    *,
    ticker_code: str,
    analysis_date: str,
    logs_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProjectionOutcome:
    if not projection_enabled(environ):
        return ProjectionOutcome(SKIPPED, reason="disabled")
    if not _TICKER_RE.fullmatch(ticker_code or "") or not _DATE_RE.fullmatch(
        analysis_date or ""
    ):
        return ProjectionOutcome(SKIPPED, reason="invalid_identity")
    payload = latest_for_key(engine, ticker_code, analysis_date)
    if payload is None:
        return ProjectionOutcome(SKIPPED, reason="no_report")
    return project_payload(
        payload,
        ticker_code=ticker_code,
        analysis_date=analysis_date,
        logs_root=logs_root,
        environ=environ,
    )


def project_payload(
    payload: Mapping[str, Any],
    *,
    ticker_code: str | None = None,
    analysis_date: str | None = None,
    logs_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProjectionOutcome:
    if not projection_enabled(environ):
        return ProjectionOutcome(SKIPPED, reason="disabled")
    meta = payload.get("meta")
    if not isinstance(meta, Mapping):
        return ProjectionOutcome(SKIPPED, reason="invalid_payload")
    ticker = str(ticker_code or meta.get("ticker_code") or "").strip()
    day = str(analysis_date or meta.get("analysis_date") or "").strip()
    if not _TICKER_RE.fullmatch(ticker) or not _DATE_RE.fullmatch(day):
        return ProjectionOutcome(SKIPPED, reason="invalid_identity")

    sections = payload.get("sections")
    state = build_legacy_state(
        meta,
        sections if isinstance(sections, Mapping) else {},
        ticker_code=ticker,
        analysis_date=day,
    )
    target = (
        Path(logs_root).expanduser() if logs_root is not None else default_logs_root()
    ) / ticker / STRATEGY_DIR / f"full_states_log_{day}.json"
    report_id = str(meta.get("report_id") or "") or None
    try:
        backup = _write_atomic(target, state)
    except Exception:  # noqa: BLE001 - projection must never break the report
        logger.exception(
            "legacy projection failed: report=%s ticker=%s date=%s target=%s",
            report_id,
            ticker,
            day,
            target,
        )
        return ProjectionOutcome(
            FAILED, report_id=report_id, path=target, reason="write_failed"
        )
    logger.info(
        "legacy projection wrote report=%s ticker=%s date=%s target=%s",
        report_id,
        ticker,
        day,
        target,
    )
    return ProjectionOutcome(PROJECTED, report_id=report_id, path=target, backup_path=backup)


def build_legacy_state(
    meta: Mapping[str, Any],
    sections: Mapping[str, Any],
    *,
    ticker_code: str,
    analysis_date: str,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "company_of_interest": ticker_code,
        "trade_date": analysis_date,
    }
    for key, section_id in ANALYST_KEYS:
        state[key] = _body(sections, section_id)
    state["data_quality_summary"] = _body(sections, "sec-quality")

    decision = _body(sections, "sec-decision")
    plan = _body(sections, "sec-plan")
    aliases = _mapping(_section(sections, "sec-plan").get("legacy_aliases"))
    alias_plan = _text(aliases.get("trader_investment_plan"))
    if not plan and alias_plan:
        plan, alias_plan = alias_plan, ""
    if not plan and decision:
        plan = decision
    state["investment_plan"] = _decorate(plan, meta)
    if alias_plan:
        state["trader_investment_plan"] = alias_plan
    state["trader_investment_decision"] = _body(sections, "sec-trader")
    state["final_trade_decision"] = decision

    debate = _debate_state(sections)
    if debate:
        state["investment_debate_state"] = debate
    risk = _risk_state(sections)
    if risk:
        state["risk_debate_state"] = risk
    return state


def _debate_state(sections: Mapping[str, Any]) -> dict[str, str]:
    section = _section(sections, "sec-debate")
    if not section:
        return {}
    parts = _parts(section)
    state = {key: parts.get(part, "") for key, part in DEBATE_PARTS}
    judge = parts.get("judge") or _ref_text(sections, section, "judge")
    state["judge_decision"] = _join_texts(
        judge,
        _body(sections, "sec-debate"),
        _extras(parts, {part for _, part in DEBATE_PARTS} | {"judge"}),
    )
    return state if any(state.values()) else {}


def _risk_state(sections: Mapping[str, Any]) -> dict[str, str]:
    section = _section(sections, "sec-risk")
    if not section:
        return {}
    parts = _parts(section)
    state = {key: parts.get(part, "") for key, part in RISK_PARTS}
    judge = parts.get("judge") or _ref_text(sections, section, "judge")
    state["judge_decision"] = _join_texts(
        judge,
        _body(sections, "sec-risk"),
        _extras(parts, {part for _, part in RISK_PARTS} | {"judge"}),
    )
    return state if any(state.values()) else {}


def _decorate(text: str, meta: Mapping[str, Any]) -> str:
    """Put the frozen rating/signal ahead of the first text the old reader scans."""
    lines = []
    rating = _text(meta.get("rating"))
    signal = _text(meta.get("signal"))
    if rating:
        lines.append(f"**Rating**: {rating}")
    if signal in {"Buy", "Sell", "Hold"}:
        lines.append(f"**Signal**: {signal}")
    if not lines:
        return text
    header = "\n\n".join(lines)
    return f"{header}\n\n{text}" if text else header


def _extras(parts: Mapping[str, str], known: set[str]) -> str:
    return _join_texts(
        *(
            f"**{key}**\n\n{parts[key]}"
            for key in sorted(parts)
            if key not in known and parts[key]
        )
    )


def _join_texts(*values: str) -> str:
    return "\n\n".join(value for value in values if value)


def _section(sections: Mapping[str, Any], section_id: str) -> Mapping[str, Any]:
    value = sections.get(section_id)
    return value if isinstance(value, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _body(sections: Mapping[str, Any], section_id: str) -> str:
    return _text(_section(sections, section_id).get("body"))


def _parts(section: Mapping[str, Any]) -> dict[str, str]:
    raw = _mapping(section.get("parts"))
    return {str(key): _text(value) for key, value in raw.items() if _text(value)}


def _ref_text(
    sections: Mapping[str, Any], section: Mapping[str, Any], key: str
) -> str:
    target_id = _text(_mapping(section.get("parts_ref")).get(key))
    if not target_id:
        return ""
    target = _section(sections, target_id)
    body = _text(target.get("body"))
    if body:
        return body
    return _join_texts(
        *(f"**{part}**\n\n{text}" for part, text in sorted(_parts(target).items()))
    )


def _write_atomic(target: Path, state: Mapping[str, Any]) -> Path | None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    backup: Path | None = None
    try:
        with temp.open("w", encoding="utf-8", newline="") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        if target.exists():
            backup = target.with_name(f"{target.name}.bak")
            shutil.copy2(target, backup)
        os.replace(temp, target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return backup
