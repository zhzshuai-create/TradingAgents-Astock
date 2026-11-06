"""P3-03 renderer acceptance tests: T9, T12, T13, T17 and font failure.

The renderer returns both the PDF bytes and the exact bookmark/text sequence it
wrote, so a test does not need a second PDF parser. When ``pdftotext`` is on
PATH the extraction is checked against the real artifact as well.

Commands: .venv/Scripts/python.exe -m pytest tests/backend/test_pdf_renderer.py -q
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.job_service import CST  # noqa: E402
from backend.app.services.pdf_renderer import (  # noqa: E402
    PdfFontMissing,
    render_pdf,
)
from backend.app.services.report_render import ordered_sections  # noqa: E402
from backend.app.services.report_schema import build_legacy_report  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
CLOCK = datetime(2026, 11, 6, 10, 0, tzinfo=CST)
PDFTOTEXT = shutil.which("pdftotext")


def _dto(name: str) -> dict:
    path = FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


def _extract(data: bytes, tmp_path: Path) -> str | None:
    if PDFTOTEXT is None:
        return None
    path = tmp_path / "rendered.pdf"
    path.write_bytes(data)
    completed = subprocess.run(
        [PDFTOTEXT, "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.decode("utf-8", "replace")


def _titles(payload: dict) -> list[str]:
    return [
        str(section.get("title") or section.get("id"))
        for section in ordered_sections(payload)
    ]


def test_t9_bookmarks_follow_ordered_sections(tmp_path):
    payload = _dto("final_state_v1.json")
    rendered = render_pdf(payload)

    assert rendered.data.startswith(b"%PDF-")
    assert list(rendered.bookmarks) == _titles(payload)
    assert len(rendered.bookmarks) == 13
    blocks = rendered.text_blocks
    assert "多方论点" in blocks
    assert "研究经理结论" in blocks
    assert "见「最终交易决策」（内容相同）。" in blocks

    extracted = _extract(rendered.data, tmp_path)
    if extracted is not None:
        for title in rendered.bookmarks:
            assert title in extracted


def test_t12_long_report_keeps_every_character(tmp_path):
    payload = _dto("long_report.json")
    body = payload["sections"]["sec-market"]["body"]
    assert len(body) == 59399

    rendered = render_pdf(payload)

    assert body in rendered.text_blocks
    extracted = _extract(rendered.data, tmp_path)
    if extracted is not None:
        assert "第 00000 行" in extracted
        assert "第 01799 行" in extracted
        assert extracted.count("行：") == 1800


def test_t13_unsafe_text_is_plain_text(tmp_path):
    payload = _dto("unsafe_text_report.json")
    body = payload["sections"]["sec-news"]["body"]

    rendered = render_pdf(payload)

    assert body in rendered.text_blocks
    lowered = rendered.data.lower()
    # fpdf2 writes "/OpenAction [page /FitH null]" to open the first page; that
    # is navigation, not code. Executable/embedded markers must be absent.
    for marker in (
        b"/javascript",
        b"/launch",
        b"/embeddedfile",
        b"/richmedia",
    ):
        assert marker not in lowered

    extracted = _extract(rendered.data, tmp_path)
    if extracted is not None:
        assert '<script>alert("xss")</script>' in extracted
        assert "javascript:alert(1)" in extracted


def test_t17_legacy_export_carries_supplement_time():
    legacy = json.loads(
        (FIXTURES / "legacy_report_v1.json").read_text(encoding="utf-8")
    )
    payload = build_legacy_report(legacy)
    assert payload["meta"]["chart_snapshot_status"] == "none"

    rendered = render_pdf(payload, exported_at=CLOCK)

    stamp = CLOCK.isoformat(timespec="seconds")
    note = f"导出时补充数据；补充时间：{stamp}。"
    assert note in rendered.text_blocks
    assert payload["meta"]["chart_snapshot_status"] == "none"


def test_missing_font_fails_loudly(tmp_path, monkeypatch):
    missing = tmp_path / "no-such-font.ttf"
    monkeypatch.setenv("TA_PDF_FONT", str(missing))
    with pytest.raises(PdfFontMissing):
        render_pdf(_dto("final_state_v1.json"))
