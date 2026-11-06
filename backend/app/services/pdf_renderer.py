"""Render one ReportDTO as a PDF (P3-03, D4).

The section sequence and titles come from :func:`ordered_sections`, the same
source as Markdown and the reader, so the PDF bookmark sequence is the frozen
report-schema order. Text is written as plain text: fpdf2 never interprets
HTML, scripts or markdown, so unsafe fixture strings stay inert.

``RenderedPdf`` also returns the bookmark titles and the exact text blocks the
renderer wrote; tests use them without a second PDF parser. Font discovery
follows D4 and fails loudly instead of silently emitting a Latin-only PDF.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF

from backend.app.services.job_service import CST
from backend.app.services.report_render import (
    SECTION_TITLE,
    ordered_part_keys,
    ordered_sections,
    part_label,
)

EXPORTER_VERSION = "pdf-v1"
FONT_ENV = "TA_PDF_FONT"

FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

SUPPLEMENT_NOTE = "导出时补充数据"


class PdfFontMissing(RuntimeError):
    """No CJK font is available; the export must fail, not degrade."""


@dataclass(frozen=True)
class RenderedPdf:
    data: bytes
    bookmarks: tuple[str, ...]
    text_blocks: tuple[str, ...]


def find_pdf_font() -> Path:
    override = os.environ.get(FONT_ENV)
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
        raise PdfFontMissing(f"{FONT_ENV} does not point at a file")
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    raise PdfFontMissing("no CJK font found")


def render_pdf(
    payload: Mapping[str, Any], *, exported_at: datetime | None = None
) -> RenderedPdf:
    font = find_pdf_font()
    meta = payload.get("meta")
    meta = meta if isinstance(meta, Mapping) else {}

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("body", "", str(font), collection_font_number=0)
    pdf.set_author("AStock Pro")
    pdf.set_creator("AStock Pro")
    pdf.add_page()

    blocks: list[str] = []

    def emit(text: str, *, size: float, gap: float = 2.0) -> None:
        text = str(text or "")
        if not text.strip():
            return
        pdf.set_font("body", size=size)
        pdf.multi_cell(0, max(size * 0.55, 3.5), text, wrapmode="CHAR")
        pdf.ln(gap)
        blocks.append(text)

    ticker = str(meta.get("ticker_name") or meta.get("ticker_code") or "分析报告")
    day = str(meta.get("analysis_date") or "")
    title = f"{ticker} {day} 分析报告".replace("  ", " ").strip()
    pdf.set_title(title)
    emit(title, size=18, gap=3)
    emit(
        f"评级：{meta.get('rating') or '—'}"
        f"　信号：{meta.get('signal') or '—'}"
        f"　生成时间：{meta.get('generated_at') or '未知'}",
        size=9.5,
        gap=2,
    )
    if meta.get("origin") == "legacy_import":
        stamp = (exported_at or datetime.now(CST)).isoformat(timespec="seconds")
        emit(f"{SUPPLEMENT_NOTE}；补充时间：{stamp}。", size=9.5, gap=3)

    bookmarks: list[str] = []
    for section in ordered_sections(payload):
        section_id = str(section.get("id") or "")
        section_title = str(
            section.get("title") or SECTION_TITLE.get(section_id, section_id)
        )
        pdf.start_section(section_title, level=0)
        bookmarks.append(section_title)
        emit(section_title, size=15, gap=2)

        body = str(section.get("body") or "").strip()
        if body:
            emit(body, size=10.5)

        parts = section.get("parts")
        if isinstance(parts, Mapping):
            for key in ordered_part_keys(section_id, parts):
                emit(part_label(section_id, key), size=11, gap=1)
                emit(str(parts[key]).strip(), size=10.5)

        refs = section.get("parts_ref")
        if isinstance(refs, Mapping):
            for key in sorted(refs):
                target_id = str(refs[key])
                target = SECTION_TITLE.get(target_id, target_id)
                emit(part_label(section_id, key), size=11, gap=1)
                emit(f"见「{target}」（内容相同）。", size=10.5)

    return RenderedPdf(
        data=bytes(pdf.output()),
        bookmarks=tuple(bookmarks),
        text_blocks=tuple(blocks),
    )
