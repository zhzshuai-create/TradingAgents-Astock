"""Generate PDF reports from analysis results using fpdf2."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fpdf import FPDF

logger = logging.getLogger(__name__)

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _find_cjk_font() -> str | None:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


# ── Text cleaning pipeline ────────────────────────────────────────────────────


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from DeepSeek/LLM output."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _strip_pre_header_monologue(text: str) -> str:
    """Remove LLM inner monologue that appears before the first Markdown header.

    DeepSeek and similar models often output verbose reasoning/calculations
    before writing the actual report (which starts with a # header).
    """
    header_match = re.search(r"^#+\s+", text, re.MULTILINE)
    if header_match and header_match.start() > 50:
        return text[header_match.start():]
    return text


def _remove_emojis(text: str) -> str:
    """Strip emoji and non-renderable symbols, keep CJK/ASCII/punctuation."""
    keep: list[str] = []
    for ch in text:
        cp = ord(ch)
        # U+20D0-U+20FF: Combining Diacritical Marks for Symbols (keycap, etc.)
        if 0x20D0 <= cp <= 0x20FF:
            continue
        if cp < 0x80:
            keep.append(ch)
        elif 0xA0 <= cp <= 0x24CF:
            keep.append(ch)
        elif 0x2E80 <= cp <= 0x33BF:
            keep.append(ch)
        elif 0x3400 <= cp <= 0x9FFF:
            keep.append(ch)
        elif 0xF900 <= cp <= 0xFAFF:
            keep.append(ch)
        elif 0xFE10 <= cp <= 0xFE4F:
            keep.append(ch)
        elif 0xFF00 <= cp <= 0xFFEF:
            keep.append(ch)
        elif 0x2000 <= cp <= 0x206F:
            keep.append(ch)
        elif 0x20A0 <= cp <= 0x20CF:
            keep.append(ch)
        elif cp in (0x2018, 0x2019, 0x201C, 0x201D, 0x2013, 0x2014):
            keep.append(ch)
    return "".join(keep)


def _clean_markdown(text: str) -> str:
    """Convert Markdown formatting to clean plain text suitable for PDF."""

    # 1. Remove horizontal rules (standalone --- or ***)
    text = re.sub(r"^\s*[-*]{3,}\s*$", "", text, flags=re.MULTILINE)

    # 2. Remove blockquote markers
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)

    # 3. Remove bold markers: **text** -> text
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)

    # 4. Remove italic markers: *text* -> text (but not bullet points)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"\1", text)

    # 5. Remove heading markers: ### Heading -> Heading
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # 6. Convert markdown tables to readable lists
    text = _flatten_tables(text)

    # 7. Remove inline code markers
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # 8. Clean bullet markers (keep indentation structure)
    text = re.sub(r"^[\s]*[-*+]\s+", "  - ", text, flags=re.MULTILINE)

    # 9. Replace fancy quotes and dashes with ASCII equivalents
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("—", "--").replace("–", "-")

    return text


def _flatten_tables(text: str) -> str:
    """Convert Markdown pipe tables into readable indented text.

    A table like:
        | Key | Value |
        |-----|-------|
        | PE  | 128x  |

    Becomes:
        Key: Value
        PE: 128x
    """
    lines = text.split("\n")
    result: list[str] = []
    in_table = False
    table_rows: list[list[str]] = []

    for line in lines:
        stripped = line.strip()
        is_table_line = stripped.startswith("|") and stripped.endswith("|")
        is_separator = bool(re.match(r"^\|[\s\-:|]+\|$", stripped))

        if is_separator:
            # Always skip table separators, regardless of table state
            if not in_table:
                result.append("")
            continue
        elif is_table_line:
            if not in_table:
                in_table = True
                table_rows = []
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            table_rows.append(cells)
            continue
        elif in_table:
            # Non-table line after a table block – flush
            result.append(_render_table_rows(table_rows))
            table_rows = []
            in_table = False

        result.append(line)

    if in_table and table_rows:
        result.append(_render_table_rows(table_rows))

    return "\n".join(result)


def _render_table_rows(rows: list[list[str]]) -> str:
    """Render table rows as key-value pairs or simple indented text."""
    if not rows:
        return ""

    out: list[str] = []
    if len(rows[0]) == 2:
        # Two-column table: render as "Key: Value"
        max_key_len = max(len(r[0]) for r in rows if len(r) >= 2)
        for row in rows:
            if len(row) >= 2:
                key = row[0].ljust(max_key_len)
                out.append(f"  {key}: {row[1]}")
            elif len(row) == 1 and row[0]:
                out.append(f"  {row[0]}")
    else:
        # Multi-column: space-separated indented rows
        for row in rows:
            out.append("  " + "  ".join(row))

    return "\n".join(out)


def _normalize_whitespace(text: str) -> str:
    """Collapse excessive blank lines and trim."""
    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove trailing whitespace on each line
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    # Remove leading blank lines
    text = text.lstrip("\n")
    return text


def clean_for_pdf(text: str) -> str:
    """Full cleaning pipeline: raw LLM output -> readable PDF text."""
    if not text:
        return ""
    text = str(text)

    text = _strip_thinking_tags(text)
    text = _strip_pre_header_monologue(text)
    text = _clean_markdown(text)
    text = _remove_emojis(text)
    text = _normalize_whitespace(text)
    return text.strip()


# ── PDF generation ────────────────────────────────────────────────────────────


def _signal_color(signal: str) -> tuple[int, int, int]:
    s = signal.upper()
    if "BUY" in s:
        return (34, 197, 94)
    if "SELL" in s:
        return (239, 68, 68)
    return (251, 191, 36)


def _signal_label(signal: str) -> str:
    s = signal.upper()
    if "BUY" in s:
        return "BUY 买入"
    if "SELL" in s:
        return "SELL 卖出"
    if "HOLD" in s or "UNDERWEIGHT" in s or "OVERWEIGHT" in s:
        return f"{s} 持有/观望"
    return s


_REPORT_SECTIONS = [
    ("market_report", "技术分析报告"),
    ("sentiment_report", "市场情绪报告"),
    ("news_report", "新闻舆情报告"),
    ("fundamentals_report", "基本面报告"),
    ("policy_report", "政策分析报告"),
    ("hot_money_report", "游资追踪报告"),
    ("lockup_report", "解禁/减持报告"),
]


class _ReportPDF(FPDF):
    def __init__(self, ticker: str, trade_date: str, signal: str) -> None:
        super().__init__()
        self.ticker = ticker
        self.trade_date = trade_date
        self.signal = signal
        self._has_cjk = False

        font_path = _find_cjk_font()
        if font_path:
            self.add_font("CJK", "", font_path, uni=True)
            self.add_font("CJK", "B", font_path, uni=True)
            self._has_cjk = True

    def _use_font(self, style: str = "", size: int = 10) -> None:
        if self._has_cjk:
            self.set_font("CJK", style, size)
        else:
            self.set_font("Helvetica", style, size)

    def header(self) -> None:
        self._use_font("", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, f"A股多Agent投研分析  |  {self.ticker}  |  {self.trade_date}", align="C")
        self.ln(8)
        self.set_draw_color(60, 60, 60)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self._use_font("", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def add_cover(self) -> None:
        self.add_page()
        self.ln(60)

        self._use_font("B", 24)
        self.set_text_color(255, 90, 31)
        self.cell(0, 12, "A股多Agent投研分析报告", align="C")
        self.ln(20)

        self._use_font("B", 36)
        self.set_text_color(30, 30, 30)
        self.cell(0, 18, self.ticker, align="C")
        self.ln(16)

        self._use_font("", 14)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f"分析日期: {self.trade_date}", align="C")
        self.ln(8)
        self.cell(0, 10, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")
        self.ln(20)

        r, g, b = _signal_color(self.signal)
        self._use_font("B", 40)
        self.set_text_color(r, g, b)
        self.cell(0, 20, _signal_label(self.signal), align="C")
        self.ln(20)

        self._use_font("", 9)
        self.set_text_color(120, 120, 120)
        self.multi_cell(
            0, 5,
            "免责声明: 本报告由 AI 多 Agent 系统自动生成, 仅供学习研究与技术演示, "
            "不构成任何投资建议。投资决策请咨询持牌专业机构。"
            "使用本报告所产生的任何损失由使用者自行承担。",
            align="C",
        )

    def add_chart_image(self, png_bytes: bytes, caption: str = "") -> None:
        """Embed a PNG chart image centred on the page."""
        if not png_bytes:
            return
        self.ln(4)
        if caption:
            self._use_font("B", 11)
            self.set_text_color(255, 90, 31)
            self.cell(0, 8, caption, align="C")
            self.ln(6)
        buf = BytesIO(png_bytes)
        self.image(buf, x=12, w=self.w - 24)
        self.ln(4)

    def add_section(self, title: str, content: str, first: bool = False) -> None:
        cleaned = clean_for_pdf(content)
        if not cleaned:
            return

        if not first:
            # Visual separator instead of forced page break
            self.ln(4)
            self.set_draw_color(80, 80, 80)
            self.set_line_width(0.3)
            y = self.get_y()
            self.line(30, y, self.w - 30, y)
            self.ln(6)

        self._use_font("B", 16)
        self.set_text_color(255, 90, 31)
        self.cell(0, 10, title)
        self.ln(10)

        self._use_font("", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, cleaned)


def _embed_charts(pdf: _ReportPDF, ticker: str, trade_date: str) -> None:
    """Generate and embed technical charts into the PDF."""
    from web.chart_utils import generate_kline_chart, generate_macd_chart, generate_rsi_chart

    charts: list[tuple[str, object]] = [
        ("K线蜡烛图  |  K-line with MA", generate_kline_chart),
        ("MACD 指标  |  MACD Indicator", generate_macd_chart),
        ("RSI 指标  |  RSI (14)", generate_rsi_chart),
    ]
    for caption, fn in charts:
        try:
            png = fn(ticker, trade_date)
            if png:
                pdf.add_chart_image(png, caption)
            else:
                logger.info("Chart %s returned no data for %s", caption, ticker)
        except Exception:
            logger.warning("Chart %s failed for %s", caption, ticker, exc_info=True)


def generate_pdf(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> bytes:
    """Generate a PDF report and return it as bytes."""
    pdf = _ReportPDF(ticker, trade_date, signal)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.add_cover()

    first = True
    for key, title in _REPORT_SECTIONS:
        content = final_state.get(key, "")
        if content:
            pdf.add_section(title, str(content), first=first)
            first = False
        # Inject charts after market analysis report
        if key == "market_report" and content:
            _embed_charts(pdf, ticker, trade_date)

    debate = final_state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        parts = []
        if debate.get("bull_history"):
            parts.append(f"=== 多方论点 ===\n{debate['bull_history']}")
        if debate.get("bear_history"):
            parts.append(f"\n=== 空方论点 ===\n{debate['bear_history']}")
        if debate.get("judge_decision"):
            parts.append(f"\n=== 研究经理决策 ===\n{debate['judge_decision']}")
        if parts:
            pdf.add_section("多空辩论", "\n".join(parts))

    trader_decision = final_state.get("trader_investment_decision", "")
    if trader_decision:
        pdf.add_section("交易员决策", clean_for_pdf(str(trader_decision)))

    inv_plan = final_state.get("investment_plan", "")
    if inv_plan:
        pdf.add_section("最终投资建议", clean_for_pdf(str(inv_plan)))

    risk = final_state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        parts = []
        for key_name, label in [("aggressive_history", "激进观点"),
                                 ("conservative_history", "保守观点"),
                                 ("neutral_history", "中性观点")]:
            if risk.get(key_name):
                parts.append(f"=== {label} ===\n{risk[key_name]}")
        if risk.get("judge_decision"):
            parts.append(f"\n=== 风控决策 ===\n{risk['judge_decision']}")
        if parts:
            pdf.add_section("风控评估", "\n".join(parts))

    final_decision = final_state.get("final_trade_decision", "")
    if final_decision:
        pdf.add_section("最终决策", clean_for_pdf(str(final_decision)))

    return bytes(pdf.output())
