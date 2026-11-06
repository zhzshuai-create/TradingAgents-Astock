"""P3-09 exit checks that the per-ticket suites do not state directly.

Criterion 1 has two halves. The round trip below projects the new golden DTO
into the legacy state and converts it back; the section set and order must be
identical and every body byte-identical after removing the two compatibility
lines the old reader needs for its rating and signal badge. The second check
pins Markdown headings and PDF bookmarks to ``ordered_sections()``; the web
half (DOM order) lives in ``e2e/report_reader_e2e.py`` (RDR-01).

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_p3_exit.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.legacy_projection import build_legacy_state  # noqa: E402
from backend.app.services.pdf_renderer import render_pdf  # noqa: E402
from backend.app.services.report_render import ordered_sections, render_markdown  # noqa: E402
from backend.app.services.report_schema import build_legacy_report  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
REPORT_ID = "00000000-0000-4000-8000-0000000000e9"
HEADER = "**Rating**: Overweight\n\n**Signal**: Buy\n\n"
SECTIONS = (
    "sec-decision",
    "sec-market",
    "sec-sentiment",
    "sec-news",
    "sec-fundamentals",
    "sec-policy",
    "sec-hot-money",
    "sec-lockup",
    "sec-quality",
    "sec-debate",
    "sec-trader",
    "sec-plan",
    "sec-risk",
)


def _golden() -> dict:
    return json.loads((FIXTURES / "final_state_v1.json").read_text(encoding="utf-8"))


def test_exit1_round_trip_keeps_sections_order_and_bodies():
    payload = _golden()
    state = build_legacy_state(
        payload["meta"],
        payload["sections"],
        ticker_code="000629",
        analysis_date="2026-10-24",
    )
    converted = build_legacy_report(state, report_id=REPORT_ID)

    assert tuple(converted["sections"]) == SECTIONS
    assert tuple(payload["sections"]) == SECTIONS
    assert converted["meta"]["report_id"] == REPORT_ID

    for section_id in SECTIONS:
        original = payload["sections"][section_id]
        again = converted["sections"][section_id]
        assert again["title"] == original["title"], section_id
        assert again.get("parts") == original.get("parts"), section_id
        assert again.get("parts_ref") == original.get("parts_ref"), section_id
        body = again["body"]
        if section_id == "sec-plan":
            # The old reader scans this field for its rating badge; those two
            # lines are the only intentional difference in the whole round trip.
            assert body.startswith(HEADER)
            body = body[len(HEADER):]
        assert body == original["body"], section_id


def test_exit1_markdown_and_pdf_titles_follow_the_contract():
    payload = _golden()
    expected = [section["title"] for section in ordered_sections(payload)]

    markdown = [
        line[2:]
        for line in render_markdown(payload).splitlines()
        if line.startswith("# ")
    ]
    bookmarks = list(render_pdf(payload).bookmarks)

    assert len(expected) == 13
    assert markdown == expected
    assert bookmarks == expected
