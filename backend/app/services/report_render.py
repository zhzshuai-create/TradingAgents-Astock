"""Render one ReportDTO as ordered sections and Markdown (P3-01).

The section order is the frozen report-schema-v1 section 3 order, never dict
insertion order. A section is present when it has a non-empty body, at least
one non-empty part, or a ``parts_ref``; an empty section never produces a bare
heading. P3-03 (PDF) and P3-05 (reader) reuse :func:`ordered_sections` so all
three outputs share one sequence.

Markdown is plain text: the body is emitted as stored. Raw HTML is disabled by
the reader, not by rewriting the document here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.app.services.report_schema import SECTION_TITLES

SECTION_ORDER = tuple(section_id for section_id, _ in SECTION_TITLES)
SECTION_TITLE = dict(SECTION_TITLES)

PART_ORDER: dict[str, tuple[str, ...]] = {
    "sec-debate": ("bull", "bear", "history", "current", "judge"),
    "sec-risk": ("aggressive", "conservative", "neutral", "history", "judge"),
}

PART_LABELS: dict[str, dict[str, str]] = {
    "sec-debate": {
        "bull": "多方论点",
        "bear": "空方论点",
        "history": "辩论记录",
        "current": "当前回应",
        "judge": "研究经理结论",
    },
    "sec-risk": {
        "aggressive": "激进观点",
        "conservative": "保守观点",
        "neutral": "中性观点",
        "history": "风控记录",
        "judge": "风控结论",
    },
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has_content(section: Mapping[str, Any]) -> bool:
    if _text(section.get("body")):
        return True
    parts = section.get("parts")
    if isinstance(parts, Mapping) and any(_text(value) for value in parts.values()):
        return True
    refs = section.get("parts_ref")
    return isinstance(refs, Mapping) and bool(refs)


def ordered_sections(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Present sections in contract order; empty or unknown ids are dropped."""
    raw = payload.get("sections")
    if not isinstance(raw, Mapping):
        return []
    return [
        raw[section_id]
        for section_id in SECTION_ORDER
        if isinstance(raw.get(section_id), Mapping) and _has_content(raw[section_id])
    ]


def _ordered_part_keys(section_id: str, parts: Mapping[str, Any]) -> list[str]:
    preferred = PART_ORDER.get(section_id, ())
    keys = [key for key in preferred if _text(parts.get(key))]
    keys.extend(
        sorted(key for key in parts if key not in preferred and _text(parts[key]))
    )
    return keys


def _part_label(section_id: str, key: str) -> str:
    return PART_LABELS.get(section_id, {}).get(key, key)


def render_markdown(payload: Mapping[str, Any]) -> str:
    """One ``# title`` per present section, chapters separated by a blank line."""
    blocks: list[str] = []
    for section in ordered_sections(payload):
        section_id = str(section.get("id") or "")
        title = str(section.get("title") or SECTION_TITLE.get(section_id, section_id))
        lines = [f"# {title}"]
        body = _text(section.get("body"))
        if body:
            lines.extend(("", body))

        parts = section.get("parts")
        if isinstance(parts, Mapping):
            for key in _ordered_part_keys(section_id, parts):
                lines.extend(
                    ("", f"**{_part_label(section_id, key)}**", "", _text(parts[key]))
                )

        refs = section.get("parts_ref")
        if isinstance(refs, Mapping):
            for key in sorted(refs):
                target_id = str(refs[key])
                target = SECTION_TITLE.get(target_id, target_id)
                lines.extend(
                    (
                        "",
                        f"**{_part_label(section_id, key)}**",
                        "",
                        f"见「{target}」（内容相同）。",
                    )
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
